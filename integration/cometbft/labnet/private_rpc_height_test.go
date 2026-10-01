package labnet

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/cometbft/cometbft/p2p"
	ctypes "github.com/cometbft/cometbft/rpc/core/types"
	"github.com/cometbft/cometbft/types"
)

// A finite, public observation only: no RPC text, endpoints, paths or hashes.
type privateRPCHeaderObservation struct {
	Target int64
	Peer   int
	Height int64
	Class  string
}

func privateRPCCheckClass(err error) string {
	switch {
	case err == nil:
		return "ok"
	case errors.Is(err, ErrResponse):
		return "response"
	case errors.Is(err, ErrCertificate):
		return "certificate"
	case errors.Is(err, errNodeReadiness):
		return "readiness"
	case errors.Is(err, errNodeIdentity):
		return "identity"
	case errors.Is(err, errNodeExited):
		return "process_exit"
	default:
		return nodeFailureCode(err)
	}
}

// The caller owns the post-inclusion deadline. Height availability is only a
// prerequisite: keep the real certificate and AppHash checks, once per peer.
func checkPrivateRPCHeaders(ctx context.Context, network *Network, nodes []*process, peers []rpcSource, needed int64, appHash Hash) ([]nodeObservation, privateRPCHeaderObservation) {
	sources := make([]nodeStatusSource, len(peers))
	for i, p := range peers {
		sources[i] = p
	}
	observed, err := waitNodeHeights(ctx, nodes, sources, needed)
	failure := privateRPCHeaderObservation{Target: needed, Peer: -1, Height: -1, Class: privateRPCCheckClass(err)}
	if err != nil {
		return observed, failure
	}
	for i, p := range peers {
		failure.Peer, failure.Height = i, observed[i].Height
		header, err := network.header(ctx, p, needed)
		if err != nil {
			failure.Class = privateRPCCheckClass(err)
			return observed, failure
		}
		if !bytes.Equal(header.Header.AppHash, appHash[:]) {
			failure.Class = "app_hash"
			return observed, failure
		}
	}
	return observed, failure
}

// These status/Commit doubles exist only in tests. Signed headers below still
// pass through the real fixed-validator certificate verifier.
type privateHeightPeer struct {
	rpcSource
	id          string
	heights     []int64
	statusCalls int
	commitCalls int
	signed      *types.SignedHeader
	commitErr   error
	onStatus    func(context.Context)
	onCommit    func(context.Context, *int64)
}

func (p *privateHeightPeer) Status(ctx context.Context) (*ctypes.ResultStatus, error) {
	if p.onStatus != nil {
		p.onStatus(ctx)
	}
	i := p.statusCalls
	p.statusCalls++
	if i >= len(p.heights) {
		i = len(p.heights) - 1
	}
	return &ctypes.ResultStatus{NodeInfo: p2p.DefaultNodeInfo{DefaultNodeID: p2p.ID(p.id)}, SyncInfo: ctypes.SyncInfo{LatestBlockHeight: p.heights[i]}}, nil
}

func (p *privateHeightPeer) Commit(ctx context.Context, height *int64) (*ctypes.ResultCommit, error) {
	p.commitCalls++
	if p.onCommit != nil {
		p.onCommit(ctx, height)
	}
	if p.commitErr != nil || p.signed == nil {
		return nil, p.commitErr
	}
	return &ctypes.ResultCommit{SignedHeader: *p.signed}, nil
}

func privateHeightNode(index int) *process {
	p := &process{done: make(chan struct{}), readyDone: make(chan struct{}), nodeIndex: index, nodeID: fmt.Sprint(index), started: time.Now()}
	close(p.readyDone)
	return p
}

func TestPrivateRPCFinalHeightWaitsForEveryPeerAtExactTarget(t *testing.T) {
	network, keys := signingNetwork(t)
	const needed = int64(8) // Final sync advanced beyond inclusion height 3.
	signed := signHeader(t, network, keys, headerTemplate(network, needed), types.PartSetHeader{Total: 1, Hash: bytes.Repeat([]byte{3}, 32)}, 4)
	var appHash Hash
	copy(appHash[:], signed.Header.AppHash)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	deadline, _ := ctx.Deadline()
	nodes := make([]*process, 4)
	peers := make([]rpcSource, 4)
	statuses := make([]nodeStatusSource, 4)
	for i := range nodes {
		nodes[i] = privateHeightNode(i)
		p := &privateHeightPeer{id: nodes[i].nodeID, heights: []int64{4, needed}, signed: signed}
		if i == 3 {
			p.heights = []int64{4, needed - 1, needed}
		}
		p.onStatus = func(request context.Context) {
			if got, ok := request.Deadline(); !ok || !got.Equal(deadline) {
				t.Fatal("height request reset the caller deadline")
			}
		}
		p.onCommit = func(request context.Context, height *int64) {
			if request != ctx || height == nil || *height != needed {
				t.Fatal("final header reset the context or requested an extra height")
			}
			for _, node := range peers {
				if node.(*privateHeightPeer).statusCalls < 3 {
					t.Fatal("read a header before every peer reached the final target")
				}
			}
		}
		peers[i], statuses[i] = p, p
	}
	if _, err := waitNodeHeights(ctx, nodes, statuses, 4); err != nil {
		t.Fatal("original inclusion wait failed", err)
	}
	observed, failure := checkPrivateRPCHeaders(ctx, network, nodes, peers, needed, appHash)
	if failure.Class != "ok" {
		t.Fatalf("late peer did not reach exact target: %+v", failure)
	}
	for i, peer := range peers {
		if peer.(*privateHeightPeer).commitCalls != 1 || observed[i].Height != needed {
			t.Fatal("header verification was skipped/retried or required another block")
		}
	}
}

func TestPrivateRPCFinalHeightKeepsCallerDeadlineAndSupervision(t *testing.T) {
	for _, mode := range []string{"deadline", "expired_after_inclusion", "readiness", "identity", "process_exit"} {
		t.Run(mode, func(t *testing.T) {
			p := privateHeightNode(0)
			peer := &privateHeightPeer{id: p.nodeID, heights: []int64{4}}
			ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
			defer cancel()
			want := mode
			switch mode {
			case "expired_after_inclusion":
				if _, err := waitNodeHeights(ctx, []*process{p}, []nodeStatusSource{peer}, 4); err != nil {
					t.Fatal("inclusion wait failed", err)
				}
				<-ctx.Done() // Simulate sync/replay consuming the remaining budget.
				peer.heights, want = []int64{8}, "deadline"
			case "readiness":
				p.readyErr = errNodeReadiness
			case "identity":
				peer.id = "other"
			case "process_exit":
				close(p.done)
			}
			observed, failure := checkPrivateRPCHeaders(ctx, nil, []*process{p}, []rpcSource{peer}, 8, Hash{})
			if failure.Class != want || failure.Target != 8 || len(observed) != 1 || peer.commitCalls != 0 {
				t.Fatalf("unready network reached header verification: %+v", failure)
			}
		})
	}
}

func TestPrivateRPCFinalHeaderRejectsWithoutRetryAndRedacts(t *testing.T) {
	const secret = "private-rpc-path-password-and-payment"
	for _, mode := range []string{"response", "nil_response", "certificate", "app_hash"} {
		t.Run(mode, func(t *testing.T) {
			network, keys := signingNetwork(t)
			signed := signHeader(t, network, keys, headerTemplate(network, 8), types.PartSetHeader{Total: 1, Hash: bytes.Repeat([]byte{3}, 32)}, 4)
			var appHash Hash
			copy(appHash[:], signed.Header.AppHash)
			peer := &privateHeightPeer{id: "0", heights: []int64{8}, signed: signed}
			want := mode
			switch mode {
			case "response":
				peer.commitErr = errors.New(secret)
			case "nil_response":
				peer.signed, want = nil, "response"
			case "certificate":
				signed.Commit.Signatures[0].Signature[0] ^= 1
			case "app_hash":
				appHash[0] ^= 1
			}
			ctx, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			observed, failure := checkPrivateRPCHeaders(ctx, network, []*process{privateHeightNode(0)}, []rpcSource{peer}, 8, appHash)
			if failure != (privateRPCHeaderObservation{8, 0, 8, want}) || peer.commitCalls != 1 || peer.statusCalls != 1 {
				t.Fatalf("failed verification was hidden or retried: %+v", failure)
			}
			report := fmt.Sprintf("%+v nodes=%+v", failure, observed)
			if strings.Contains(report, secret) || len(report) > 512 || privateRPCCheckClass(errors.New(secret)) != "other" {
				t.Fatal("private RPC error escaped the finite diagnostic")
			}
		})
	}
}
