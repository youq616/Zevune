//go:build pool_e2e

package poolapp

// Failure evidence for the synthetic four-process fixture only. This does not
// change admission, finality, polling, retries, or any production logger/API.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	rpc "github.com/cometbft/cometbft/rpc/client/http"
	ctypes "github.com/cometbft/cometbft/rpc/core/types"
)

const fixtureOutputLimit = 4096
const fixtureEventPrefix = "POOL_FIXTURE_EVENT "

// Keep only a bounded tail. Snapshot can race with a live child's pipe writer.
// Arbitrary child bytes, RPC error strings, raw transactions and node keys are
// NEVER emitted by the evidence encoder, even if the captured tail contains them.
type fixtureOutput struct {
	mu    sync.Mutex
	tail  []byte
	total int64
}

func (b *fixtureOutput) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	n := len(p)
	b.total += int64(n)
	if n >= fixtureOutputLimit {
		b.tail = append(b.tail[:0], p[n-fixtureOutputLimit:]...)
	} else {
		overflow := len(b.tail) + n - fixtureOutputLimit
		if overflow > 0 {
			b.tail = append(b.tail[:0], b.tail[overflow:]...)
		}
		b.tail = append(b.tail, p...)
	}
	return n, nil
}
func (b *fixtureOutput) snapshot() (int64, []byte) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.total, bytes.Clone(b.tail)
}

func fixtureError(err error) string {
	switch {
	case err == nil:
		return "none"
	case errors.Is(err, context.DeadlineExceeded):
		return "deadline"
	case errors.Is(err, context.Canceled):
		return "canceled"
	case errors.Is(err, syscall.EADDRINUSE):
		return "address_in_use"
	case errors.Is(err, syscall.ECONNREFUSED):
		return "connection_refused"
	case errors.Is(err, io.EOF):
		return "eof"
	}
	var timeout net.Error
	if errors.As(err, &timeout) && timeout.Timeout() {
		return "network_timeout"
	}
	// A type name is not the peer-supplied error text or a local secret path.
	return fmt.Sprintf("%T", err)
}

type fixtureLifecycle struct {
	Stage   string `json:"stage"`
	Node    int    `json:"node"`
	RPCPort int    `json:"rpc_port"`
	P2PPort int    `json:"p2p_port"`
	Error   string `json:"error"`
}

func fixtureNodeEvent(stage string, index, base int, err error) {
	raw, _ := json.Marshal(fixtureLifecycle{stage, index, base + 2*index, base + 2*index + 1, fixtureError(err)})
	fmt.Fprintln(os.Stderr, fixtureEventPrefix+string(raw))
}
func fixtureLifecycleEvents(raw []byte) []fixtureLifecycle {
	var events []fixtureLifecycle
	for _, line := range bytes.Split(raw, []byte{'\n'}) {
		if !bytes.HasPrefix(line, []byte(fixtureEventPrefix)) || len(line) > 512 {
			continue
		}
		var event fixtureLifecycle
		if json.Unmarshal(line[len(fixtureEventPrefix):], &event) != nil {
			continue
		}
		switch event.Stage {
		case "construct_failed", "start_failed", "started", "stopped", "close_failed":
		default:
			continue
		}
		if event.Node < 0 || event.Node > 3 || event.RPCPort < 1 || event.RPCPort > 65534 || event.P2PPort != event.RPCPort+1 {
			continue
		}
		// Never trust a child's arbitrary string, even inside a matching frame.
		switch event.Error {
		case "none", "deadline", "canceled", "address_in_use", "connection_refused", "eof", "network_timeout":
		default:
			event.Error = "other_error"
		}
		events = append(events, event)
		if len(events) == 8 {
			break
		}
	}
	return events
}
func fixtureProcessEvidence(c *child, err error) any {
	total, tail := c.output.snapshot()
	digest := sha256.Sum256(tail)
	code := 0
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		code = exit.ExitCode()
	} else if err != nil {
		code = -1
	}
	return struct {
		Node        int                `json:"node"`
		RPCPort     int                `json:"rpc_port"`
		P2PPort     int                `json:"p2p_port"`
		ExitCode    int                `json:"exit_code"`
		Error       string             `json:"error"`
		OutputBytes int64              `json:"output_bytes"`
		TailBytes   int                `json:"tail_bytes"`
		Truncated   bool               `json:"truncated"`
		TailSHA256  string             `json:"tail_sha256"`
		Lifecycle   []fixtureLifecycle `json:"lifecycle"`
	}{c.index, c.base + 2*c.index, c.base + 2*c.index + 1, code, fixtureError(err), total, len(tail), total > int64(len(tail)), hex.EncodeToString(digest[:]), fixtureLifecycleEvents(tail)}
}
func fixtureLog(t *testing.T, kind string, value any) {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil || len(raw) > 16384 {
		t.Logf("POOL_FIXTURE_%s evidence_encoding_or_size_failure", kind)
		return
	}
	t.Logf("POOL_FIXTURE_%s %s", kind, raw)
}

// Do not renew the original Status timeout or change its -1 behavior for callers.
func fixtureHeight(c *rpc.HTTP) (int64, string) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	r, err := c.Status(ctx)
	if err != nil {
		return -1, fixtureError(err)
	}
	if r == nil {
		return -1, "nil_status"
	}
	return r.SyncInfo.LatestBlockHeight, "none"
}

type fixturePoll struct {
	ElapsedMillis int64  `json:"elapsed_millis"`
	Attempt       int    `json:"attempt"`
	Height        int64  `json:"height"`
	StatusError   string `json:"status_error"`
	BlocksRead    int    `json:"blocks_read"`
	BlockError    string `json:"block_error"`
}

// Read-only interface deliberately contains no broadcast or application calls.
type fixtureRPC interface {
	Status(context.Context) (*ctypes.ResultStatus, error)
	NetInfo(context.Context) (*ctypes.ResultNetInfo, error)
	UnconfirmedTxs(context.Context, *int) (*ctypes.ResultUnconfirmedTxs, error)
	ConsensusState(context.Context) (*ctypes.ResultConsensusState, error)
}
type fixtureNodeSnapshot struct {
	NodeID                string   `json:"node_id"`
	PeerIDs               []string `json:"peer_ids"`
	ChainMatches          bool     `json:"chain_matches"`
	Node                  int      `json:"node"`
	RPCPort               int      `json:"rpc_port"`
	P2PPort               int      `json:"p2p_port"`
	Height                int64    `json:"height"`
	CatchingUp            bool     `json:"catching_up"`
	StatusError           string   `json:"status_error"`
	Peers                 int      `json:"peers"`
	Listening             bool     `json:"listening"`
	PeerError             string   `json:"peer_error"`
	MempoolCount          int      `json:"mempool_count"`
	MempoolBytes          int64    `json:"mempool_bytes"`
	SampledTxs            int      `json:"sampled_txs"`
	WantedInSample        bool     `json:"wanted_in_sample"`
	MempoolSampleComplete bool     `json:"mempool_sample_complete"`
	MempoolError          string   `json:"mempool_error"`
	HeightRoundStep       string   `json:"height_round_step"`
	ConsensusError        string   `json:"consensus_error"`
}

func fixturePublicID(raw string) string {
	if len(raw) != 40 {
		return "invalid_id"
	}
	data, err := hex.DecodeString(raw)
	if err != nil {
		return "invalid_id"
	}
	return hex.EncodeToString(data)
}
func fixtureRoundStep(raw []byte) (string, string) {
	if len(raw) > 16384 {
		return "", "round_state_oversize"
	}
	var value struct {
		HRS string `json:"height/round/step"`
	}
	if json.Unmarshal(raw, &value) != nil {
		return "", "invalid_round_state"
	}
	parts := strings.Split(value.HRS, "/")
	if len(parts) != 3 {
		return "", "invalid_round_step"
	}
	for _, p := range parts {
		n, err := strconv.ParseInt(p, 10, 64)
		if err != nil || n < 0 || strconv.FormatInt(n, 10) != p {
			return "", "invalid_round_step"
		}
	}
	return value.HRS, "none"
}
func fixtureSnapshot(ctx context.Context, c fixtureRPC, index, base int, wanted [32]byte) fixtureNodeSnapshot {
	out := fixtureNodeSnapshot{Node: index, RPCPort: base + 2*index, P2PPort: base + 2*index + 1, Height: -1}
	status, err := c.Status(ctx)
	out.StatusError = fixtureError(err)
	if err == nil && status != nil {
		out.Height = status.SyncInfo.LatestBlockHeight
		out.NodeID = fixturePublicID(string(status.NodeInfo.ID()))
		out.ChainMatches = status.NodeInfo.Network == ChainID
		out.CatchingUp = status.SyncInfo.CatchingUp
	} else if status == nil && err == nil {
		out.StatusError = "nil_status"
	}
	peers, err := c.NetInfo(ctx)
	out.PeerError = fixtureError(err)
	if err == nil && peers != nil {
		out.Peers = peers.NPeers
		out.Listening = peers.Listening
		for i, p := range peers.Peers {
			if i == 4 {
				break
			}
			out.PeerIDs = append(out.PeerIDs, fixturePublicID(string(p.NodeInfo.ID())))
		}
	} else if peers == nil && err == nil {
		out.PeerError = "nil_peers"
	}
	limit := 4
	pending, err := c.UnconfirmedTxs(ctx, &limit)
	out.MempoolError = fixtureError(err)
	if err == nil && pending != nil {
		out.MempoolCount = pending.Total
		out.MempoolBytes = pending.TotalBytes
		for i, tx := range pending.Txs {
			if i == limit {
				break
			}
			out.SampledTxs++
			if len(tx) <= 28134 && sha256.Sum256(tx) == wanted {
				out.WantedInSample = true
			}
		}
		out.MempoolSampleComplete = len(pending.Txs) <= limit && out.SampledTxs == pending.Total
	} else if pending == nil && err == nil {
		out.MempoolError = "nil_mempool"
	}
	state, err := c.ConsensusState(ctx)
	out.ConsensusError = fixtureError(err)
	if err == nil && state != nil {
		out.HeightRoundStep, out.ConsensusError = fixtureRoundStep(state.RoundState)
	} else if state == nil && err == nil {
		out.ConsensusError = "nil_consensus"
	}
	return out
}
func fixtureFailureSnapshots(parent context.Context, clients []fixtureRPC, base int, wanted [32]byte) []fixtureNodeSnapshot {
	// A single shared two-second ceiling INSIDE the original 120-second parent.
	// No new retry, per-peer budget, renewed parent, or extra polling iteration.
	ctx, cancel := context.WithTimeout(parent, 2*time.Second)
	defer cancel()
	count := len(clients)
	if count > 4 {
		count = 4
	}
	result := make([]fixtureNodeSnapshot, count)
	var joined sync.WaitGroup
	for i, c := range clients[:count] {
		joined.Add(1)
		go func(i int, c fixtureRPC) { defer joined.Done(); result[i] = fixtureSnapshot(ctx, c, i, base, wanted) }(i, c)
	}
	joined.Wait()
	return result
}
func fixtureInclusionFailure(t *testing.T, ctx context.Context, clients []*rpc.HTTP, base int, tx []byte, accepted *ctypes.ResultBroadcastTx, polls []fixturePoll) {
	t.Helper()
	wanted := sha256.Sum256(tx)
	peers := make([]fixtureRPC, len(clients))
	for i, c := range clients {
		peers[i] = c
	}
	// Public fixture hashes/counters only. No raw accepted.Log/Data or tx bytes.
	receiptHash := "invalid_length"
	var code uint32
	if accepted != nil {
		code = accepted.Code
		if len(accepted.Hash) == 32 {
			receiptHash = hex.EncodeToString(accepted.Hash)
		}
	}
	fixtureLog(t, "INCLUSION_FAILURE", struct {
		Scope        string                `json:"scope"`
		TxSHA256     string                `json:"tx_sha256"`
		AcceptedHash string                `json:"accepted_hash"`
		AcceptedCode uint32                `json:"accepted_code"`
		ParentError  string                `json:"parent_error"`
		Polls        []fixturePoll         `json:"polls"`
		Nodes        []fixtureNodeSnapshot `json:"nodes"`
	}{"synthetic_zero_value_only_not_finality", hex.EncodeToString(wanted[:]), receiptHash, code, fixtureError(ctx.Err()), polls, fixtureFailureSnapshots(ctx, peers, base, wanted)})
}
