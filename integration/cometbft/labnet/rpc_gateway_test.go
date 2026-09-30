package labnet

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/p2p"
	ctypes "github.com/cometbft/cometbft/rpc/core/types"
	"github.com/cometbft/cometbft/types"
	"github.com/youq616/Zevune/internal/poolbridge"
	"github.com/youq616/Zevune/internal/rpcgate"
	"github.com/youq616/Zevune/internal/rpcgate/gatetest"
)

func gatewayTestAddress(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := l.Addr().String()
	l.Close()
	return address
}

// This regular test verifies wire compatibility over real HTTP sockets using
// the original typed client. It is not a consensus/proof acceptance fixture;
// genuine signatures/payments are covered separately by operator_e2e.
func gatewayTestPeer(t *testing.T, upstreamURL string) (*peer, *rpcgate.Service) {
	t.Helper()
	upstream, err := newPeer(upstreamURL)
	if err != nil {
		t.Fatal(err)
	}
	address := gatewayTestAddress(t)
	s, err := rpcgate.Start(context.Background(), rpcgate.Config{Listen: address, Host: strings.TrimPrefix(privateTestEndpoint, "http://"), MaxHeight: 1000000}, &gatewayBackend{source: upstream, chain: "gateway-test-chain"})
	if err != nil {
		upstream.close()
		t.Fatal(err)
	}
	downstream, err := newRPCPeer(privateTestEndpoint, func(ctx context.Context, network, target string) (net.Conn, error) {
		if target != strings.TrimPrefix(privateTestEndpoint, "http://") {
			return nil, ErrEndpoint
		}
		return (&net.Dialer{}).DialContext(ctx, "tcp4", address)
	})
	if err != nil {
		s.Stop()
		s.Wait()
		upstream.close()
		t.Fatal(err)
	}
	t.Cleanup(func() {
		downstream.close()
		s.Stop()
		if err := s.Wait(); err != nil {
			t.Error(err)
		}
		upstream.close()
	})
	return downstream, s
}

type gatewayWireRequest struct {
	JSONRPC string                     `json:"jsonrpc"`
	ID      json.RawMessage            `json:"id"`
	Method  string                     `json:"method"`
	Params  map[string]json.RawMessage `json:"params"`
}

func readGatewayTestRequest(t *testing.T, r *http.Request) gatewayWireRequest {
	t.Helper()
	var q gatewayWireRequest
	raw, err := io.ReadAll(io.LimitReader(r.Body, rpcgate.MaxRequestBytes+1))
	if err != nil || json.Unmarshal(raw, &q) != nil || q.JSONRPC != "2.0" {
		t.Error("invalid upstream request")
	}
	if r.Header.Get("Cookie") != "" || r.Header.Get("Authorization") != "" {
		t.Error("forwarded private headers")
	}
	return q
}
func gatewayTestResponse(t *testing.T, w http.ResponseWriter, q gatewayWireRequest, result any) {
	t.Helper()
	raw, err := cmtjson.Marshal(result)
	if err != nil {
		t.Error(err)
		w.WriteHeader(500)
		return
	}
	response, err := json.Marshal(struct {
		JSONRPC string          `json:"jsonrpc"`
		ID      json.RawMessage `json:"id"`
		Result  json.RawMessage `json:"result"`
	}{"2.0", q.ID, raw})
	if err != nil {
		t.Error(err)
		w.WriteHeader(500)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Set-Cookie", "must-not-propagate")
	_, _ = w.Write(response)
}
func gatewayStatus() *ctypes.ResultStatus {
	return &ctypes.ResultStatus{NodeInfo: p2p.DefaultNodeInfo{Network: "gateway-test-chain", Moniker: "must-not-propagate", ListenAddr: "tcp://127.0.0.1:1234"}, SyncInfo: ctypes.SyncInfo{LatestBlockHeight: 7}}
}

func TestGatewayOriginalClientDecodesEveryField(t *testing.T) {
	tx := types.Tx{0, 1, 255}
	hash := bytes.Repeat([]byte{0xab}, 32)
	header := types.Header{ChainID: "gateway-test-chain", Height: 7, Time: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), AppHash: hash}
	block := &ctypes.ResultBlock{BlockID: types.BlockID{Hash: hash}, Block: &types.Block{Header: header, Data: types.Data{Txs: types.Txs{tx}}}}
	commit := ctypes.NewResultCommit(&header, &types.Commit{Height: 7, Round: 2, BlockID: types.BlockID{Hash: hash}}, true)
	var calls atomic.Int64
	var code atomic.Uint32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := readGatewayTestRequest(t, r)
		calls.Add(1)
		switch q.Method {
		case "status":
			if len(q.Params) != 0 {
				t.Error("status parameters")
			}
			gatewayTestResponse(t, w, q, gatewayStatus())
		case "block", "commit":
			if len(q.Params) != 1 || string(q.Params["height"]) != `"7"` {
				t.Error("height was not a decimal string")
			}
			if q.Method == "block" {
				gatewayTestResponse(t, w, q, block)
			} else {
				gatewayTestResponse(t, w, q, commit)
			}
		case "broadcast_tx_sync":
			if len(q.Params) != 1 || string(q.Params["tx"]) != `"`+base64.StdEncoding.EncodeToString(tx)+`"` {
				t.Error("tx parameters")
			}
			gatewayTestResponse(t, w, q, &ctypes.ResultBroadcastTx{Code: code.Load(), Hash: hash, Log: "must-not-propagate"})
		default:
			t.Error("unexpected upstream method")
			w.WriteHeader(400)
		}
	}))
	defer upstream.Close()
	p, _ := gatewayTestPeer(t, upstream.URL)
	status, err := p.Status(context.Background())
	if err != nil || status == nil || status.NodeInfo.Network != "gateway-test-chain" || status.SyncInfo.LatestBlockHeight != 7 || status.NodeInfo.Moniker != "" || status.NodeInfo.ListenAddr != "" {
		t.Fatal("status compatibility", err)
	}
	height := int64(7)
	gotBlock, err := p.Block(context.Background(), &height)
	if err != nil || gotBlock == nil || gotBlock.Block == nil || gotBlock.Block.Height != 7 || len(gotBlock.Block.Data.Txs) != 1 || !bytes.Equal(gotBlock.Block.Data.Txs[0], tx) || !bytes.Equal(gotBlock.BlockID.Hash, hash) {
		t.Fatal("block compatibility", err)
	}
	gotCommit, err := p.Commit(context.Background(), &height)
	if err != nil || gotCommit == nil || gotCommit.Header == nil || gotCommit.Commit == nil || gotCommit.Header.Height != 7 || gotCommit.Commit.Round != 2 || !gotCommit.CanonicalCommit || !bytes.Equal(gotCommit.Header.AppHash, hash) {
		t.Fatal("commit compatibility", err)
	}
	for _, value := range []uint32{0, 7} {
		code.Store(value)
		got, err := p.BroadcastTxSync(context.Background(), tx)
		if err != nil || got == nil || got.Code != value || !bytes.Equal(got.Hash, hash) || got.Log != "" {
			t.Fatal("broadcast compatibility", err)
		}
	}
	if calls.Load() != 5 {
		t.Fatal("unexpected request count")
	}
}

func TestGatewayBroadcastReceivedThenDisconnectedIsNotRetried(t *testing.T) {
	var broadcasts atomic.Int64
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := readGatewayTestRequest(t, r)
		if q.Method == "status" {
			gatewayTestResponse(t, w, q, gatewayStatus())
			return
		}
		if q.Method != "broadcast_tx_sync" {
			t.Error("unexpected method")
		}
		broadcasts.Add(1)
		conn, _, err := w.(http.Hijacker).Hijack()
		if err != nil {
			t.Error(err)
			return
		}
		conn.Close()
	}))
	defer upstream.Close()
	p, _ := gatewayTestPeer(t, upstream.URL)
	// Warm the upstream keep-alive connection, exercising the transport's reuse
	// path, then close it AFTER the complete broadcast reached that upstream.
	if _, err := p.Status(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := p.BroadcastTxSync(context.Background(), types.Tx{1}); err == nil {
		t.Fatal("unknown broadcast made successful")
	}
	if broadcasts.Load() != 1 {
		t.Fatal("broadcast retried after receipt")
	}
	if _, err := p.Status(context.Background()); err != nil {
		t.Fatal("error stopped service", err)
	}
}

func TestGatewayEarlyUpstreamHeadersLateBodyAreBounded(t *testing.T) {
	entered := make(chan struct{}, 1)
	exited := make(chan struct{}, 1)
	var broadcasts atomic.Int64
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := readGatewayTestRequest(t, r)
		if q.Method == "status" {
			gatewayTestResponse(t, w, q, gatewayStatus())
			return
		}
		broadcasts.Add(1)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		w.(http.Flusher).Flush()
		entered <- struct{}{}
		<-r.Context().Done()
		exited <- struct{}{}
	}))
	defer upstream.Close()
	p, _ := gatewayTestPeer(t, upstream.URL)
	started := time.Now()
	done := make(chan error, 1)
	go func() { _, err := p.BroadcastTxSync(context.Background(), types.Tx{1}); done <- err }()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("no upstream call")
	}
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("late body succeeded")
		}
	case <-time.After(6 * time.Second):
		t.Fatal("unbounded body")
	}
	if elapsed := time.Since(started); elapsed > 6*time.Second {
		t.Fatal("budget", elapsed)
	}
	select {
	case <-exited:
	case <-time.After(time.Second):
		t.Fatal("upstream body not canceled")
	}
	if broadcasts.Load() != 1 {
		t.Fatal("retried late broadcast")
	}
	if _, err := p.Status(context.Background()); err != nil {
		t.Fatal("timeout stopped service", err)
	}
}

func TestGatewayMissingOrWrongUpstreamResultsNeverSucceed(t *testing.T) {
	for _, body := range []string{`{}`, `null`, `{"node_info":{"network":"wrong"},"sync_info":{"latest_block_height":"7"}}`} {
		upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			q := readGatewayTestRequest(t, r)
			fmt.Fprintf(w, `{"jsonrpc":"2.0","id":%s,"result":%s}`, q.ID, body)
		}))
		p, _ := gatewayTestPeer(t, upstream.URL)
		if _, err := p.Status(context.Background()); err == nil {
			t.Error("empty or wrong status accepted")
		}
		h := int64(1)
		if _, err := p.Block(context.Background(), &h); err == nil {
			t.Error("empty block accepted")
		}
		if _, err := p.Commit(context.Background(), &h); err == nil {
			t.Error("empty commit accepted")
		}
		if _, err := p.BroadcastTxSync(context.Background(), types.Tx{1}); err == nil {
			t.Error("empty broadcast accepted")
		}
		upstream.Close()
	}
}

func TestGatewayConfigurationAndReadyFailureCloseListener(t *testing.T) {
	// Private fields are constructed ONLY in this test; production obtains them
	// via Load and the independently supplied digest. No verifier is replaced.
	n := &Network{configPin: Hash{1}, assetPin: Hash{2}, profile: poolbridge.LegacyJournal}
	var calls atomic.Int64
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls.Add(1); w.WriteHeader(500) }))
	defer upstream.Close()
	good := GatewayOptions{NoRealFunds: true, Listen: gatewayTestAddress(t), Upstream: upstream.URL, OnionEndpoint: privateTestEndpoint}
	if _, err := n.gatewayConfig(good); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 6; i++ {
		bad := good
		switch i {
		case 0:
			bad.NoRealFunds = false
		case 1:
			bad.Listen = "0.0.0.0:8080"
		case 2:
			bad.Upstream = "http://example.org:8080"
		case 3:
			bad.Upstream = "http://" + bad.Listen
		case 4:
			bad.OnionEndpoint += "/"
		case 5:
			bad.OnionEndpoint = "http://" + strings.Repeat("a", 56) + ".onion:80"
		}
		if _, err := n.gatewayConfig(bad); err == nil {
			t.Fatal("invalid config")
		}
	}
	assertClosed := func() {
		t.Helper()
		c, err := net.DialTimeout("tcp4", good.Listen, 200*time.Millisecond)
		if err == nil {
			c.Close()
			t.Fatal("listener retained after failed ready")
		}
	}
	if err := n.RunGateway(context.Background(), good, nil); err != rpcgate.ErrConfiguration {
		t.Fatal("unvalidated output accepted")
	}
	assertClosed()
	for _, blocked := range []bool{false, true} {
		r, w, err := gatetest.Pipe()
		if err != nil {
			t.Fatal(err)
		}
		if blocked {
			if err := w.SetWriteDeadline(time.Now().Add(100 * time.Millisecond)); err != nil {
				t.Fatal(err)
			}
			_, err := w.Write(make([]byte, 4*1024*1024))
			if !errors.Is(err, os.ErrDeadlineExceeded) {
				t.Fatal("pipe not blocked", err)
			}
			w.SetWriteDeadline(time.Time{})
		} else {
			r.Close() // a real broken pipe, not a cooperative mock writer
		}
		out, err := rpcgate.OpenOutput(w)
		if err != nil {
			r.Close()
			t.Fatal(err)
		}
		budget := 2 * time.Second
		if blocked {
			budget = 200 * time.Millisecond
		}
		ctx, cancel := context.WithTimeout(context.Background(), budget)
		err = n.RunGateway(ctx, good, out)
		cancel()
		// Assert return and socket cleanup BEFORE closing/draining the pipe peer.
		if err != rpcgate.ErrReady {
			t.Error("readiness failure", err)
		}
		assertClosed()
		out.Close()
		r.Close()
	}
	if calls.Load() != 0 {
		t.Fatal("readiness generated upstream request")
	}
}
