//go:build pool_e2e

package poolapp

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	ctypes "github.com/cometbft/cometbft/rpc/core/types"
	"github.com/cometbft/cometbft/types"
)

func TestPoolFixtureDiagnosticOutputBoundAndRace(t *testing.T) {
	var output fixtureOutput
	var joined sync.WaitGroup
	for i := 0; i < 8; i++ {
		joined.Add(1)
		go func() {
			defer joined.Done()
			for k := 0; k < 100; k++ {
				if n, e := output.Write(bytes.Repeat([]byte{'x'}, 100)); e != nil || n != 100 {
					panic("writer contract")
				}
				output.snapshot()
			}
		}()
	}
	joined.Wait()
	total, tail := output.snapshot()
	if total != 80000 || len(tail) != fixtureOutputLimit {
		t.Fatal("unbounded or incomplete output accounting")
	}
	replacement := bytes.Repeat([]byte{'y'}, fixtureOutputLimit*2)
	_, _ = output.Write(replacement)
	_, tail = output.snapshot()
	if !bytes.Equal(tail, replacement[len(replacement)-fixtureOutputLimit:]) {
		t.Fatal("latest tail not retained")
	}
	tail[0] = 'z'
	_, again := output.snapshot()
	if again[0] != 'y' {
		t.Fatal("snapshot aliases live writer")
	}
}

func TestPoolFixtureDiagnosticRedactionAndClassification(t *testing.T) {
	for _, tc := range []struct {
		err  error
		want string
	}{
		{nil, "none"}, {context.DeadlineExceeded, "deadline"}, {context.Canceled, "canceled"},
		{fmt.Errorf("private path: %w", syscall.EADDRINUSE), "address_in_use"},
		{fmt.Errorf("private target: %w", syscall.ECONNREFUSED), "connection_refused"}, {io.EOF, "eof"},
	} {
		if got := fixtureError(tc.err); got != tc.want {
			t.Fatalf("got %q want %q", got, tc.want)
		}
	}
	sentinel := "PRIVATE_SENTINEL_DO_NOT_PUBLISH"
	if strings.Contains(fixtureError(errors.New(sentinel)), sentinel) {
		t.Fatal("raw error text leaked")
	}
	c := &child{index: 0, base: 31000}
	for _, stage := range []string{"started", "stopped", "PRIVATE_SENTINEL_DO_NOT_PUBLISH"} {
		raw, _ := json.Marshal(fixtureLifecycle{stage, 0, 31000, 31001, sentinel})
		_, _ = c.output.Write(append(append([]byte(fixtureEventPrefix), raw...), '\n'))
	}
	_, _ = c.output.Write([]byte(sentinel + "\n"))
	raw, _ := json.Marshal(fixtureProcessEvidence(c, nil))
	if bytes.Contains(raw, []byte(sentinel)) || !bytes.Contains(raw, []byte(`"other_error"`)) || !bytes.Contains(raw, []byte(`"exit_code":0`)) {
		t.Fatalf("bad sanitized evidence: %s", raw)
	}
	var malformed = []byte(fixtureEventPrefix + `{"stage":"started","node":4,"rpc_port":1,"p2p_port":2,"error":"none"}` + "\n")
	if len(fixtureLifecycleEvents(malformed)) != 0 {
		t.Fatal("foreign node evidence admitted")
	}
}

func TestPoolFixtureDiagnosticRoundStateIsNotRawJSON(t *testing.T) {
	good := []byte(`{"height/round/step":"4/2/3","PRIVATE_SENTINEL":"not output"}`)
	if s, e := fixtureRoundStep(good); s != "4/2/3" || e != "none" {
		t.Fatal(s, e)
	}
	for _, bad := range []string{`{}`, `null`, `{"height/round/step":"4/2/secret"}`, `{"height/round/step":"04/2/3"}`, `{"height/round/step":"4/-1/3"}`, strings.Repeat("x", 16385)} {
		if s, e := fixtureRoundStep([]byte(bad)); s != "" || e == "none" {
			t.Fatal("unbounded or unvalidated consensus evidence")
		}
	}
}

// Inert RPC data fixtures, never a proof/admission substitute or runtime route.
type diagnosticRPCFixture struct {
	wait   bool
	calls  atomic.Int32
	limits atomic.Int32
	raw    types.Tx
}

func (f *diagnosticRPCFixture) observe(ctx context.Context) error {
	f.calls.Add(1)
	if f.wait {
		<-ctx.Done()
		return ctx.Err()
	}
	return nil
}
func (f *diagnosticRPCFixture) Status(ctx context.Context) (*ctypes.ResultStatus, error) {
	if e := f.observe(ctx); e != nil {
		return nil, e
	}
	r := &ctypes.ResultStatus{}
	r.SyncInfo.LatestBlockHeight = 7
	return r, nil
}
func (f *diagnosticRPCFixture) NetInfo(ctx context.Context) (*ctypes.ResultNetInfo, error) {
	if e := f.observe(ctx); e != nil {
		return nil, e
	}
	return &ctypes.ResultNetInfo{Listening: true, NPeers: 3}, nil
}
func (f *diagnosticRPCFixture) UnconfirmedTxs(ctx context.Context, limit *int) (*ctypes.ResultUnconfirmedTxs, error) {
	if e := f.observe(ctx); e != nil {
		return nil, e
	}
	f.limits.Store(int32(*limit))
	return &ctypes.ResultUnconfirmedTxs{Count: 1, Total: 1, TotalBytes: int64(len(f.raw)), Txs: []types.Tx{f.raw}}, nil
}
func (f *diagnosticRPCFixture) ConsensusState(ctx context.Context) (*ctypes.ResultConsensusState, error) {
	if e := f.observe(ctx); e != nil {
		return nil, e
	}
	return &ctypes.ResultConsensusState{RoundState: []byte(`{"height/round/step":"8/1/2","secret":"never log raw"}`)}, nil
}

func TestPoolFixtureDiagnosticSnapshotReadOnlyAndBounded(t *testing.T) {
	f := &diagnosticRPCFixture{raw: types.Tx("synthetic data, not a payment")}
	want := sha256.Sum256(f.raw)
	got := fixtureFailureSnapshots(context.Background(), []fixtureRPC{f}, 30000, want)
	if len(got) != 1 || f.calls.Load() != 4 || f.limits.Load() != 4 {
		t.Fatal("observation retried or expanded")
	}
	s := got[0]
	if s.Height != 7 || s.Peers != 3 || !s.Listening || !s.WantedInSample || !s.MempoolSampleComplete || s.HeightRoundStep != "8/1/2" || s.RPCPort != 30000 || s.P2PPort != 30001 {
		t.Fatal("public diagnostic fields lost")
	}
	raw, _ := json.Marshal(s)
	if bytes.Contains(raw, f.raw) || bytes.Contains(raw, []byte("never log raw")) {
		t.Fatal("raw response/transaction emitted")
	}
	f = &diagnosticRPCFixture{wait: true}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	start := time.Now()
	got = fixtureFailureSnapshots(ctx, []fixtureRPC{f, f, f, f, f}, 30000, want)
	if time.Since(start) > time.Second || len(got) != 4 || f.calls.Load() != 16 {
		t.Fatal("parent deadline, four-peer cap, or no-retry boundary changed")
	}
	for _, s := range got {
		if s.StatusError != "deadline" || s.PeerError != "deadline" || s.MempoolError != "deadline" || s.ConsensusError != "deadline" {
			t.Fatal("deadline errors swallowed")
		}
	}
}

func TestPoolFixtureOutputHelper(t *testing.T) {
	if os.Getenv("ZEVUNE_DIAGNOSTIC_OUTPUT_HELPER") != "1" {
		return
	}
	fmt.Fprintln(os.Stderr, "PRIVATE_SENTINEL_DO_NOT_PUBLISH")
	fixtureNodeEvent("started", 0, 30000, nil)
	fixtureNodeEvent("stopped", 0, 30000, nil)
	os.Exit(0)
}
func TestPoolFixtureCleanupFailureEvidence(t *testing.T) {
	if os.Getenv("ZEVUNE_DIAGNOSTIC_CLEANUP_PROBE") == "1" {
		c := &child{done: make(chan error, 1), index: 0, base: 30000}
		c.cmd = exec.Command(os.Args[0], "-test.run=^TestPoolFixtureOutputHelper$")
		c.cmd.Env = append(os.Environ(), "ZEVUNE_DIAGNOSTIC_OUTPUT_HELPER=1")
		c.cmd.Stdout = &c.output
		c.cmd.Stderr = &c.output
		var err error
		c.in, err = c.cmd.StdinPipe()
		if err != nil {
			t.Fatal(err)
		}
		if err = c.cmd.Start(); err != nil {
			t.Fatal(err)
		}
		go func() { c.done <- c.cmd.Wait() }()
		t.Error("intentional synthetic failed-parent probe")
		stop(t, c) // A successful child exit must still produce sanitized evidence.
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestPoolFixtureCleanupFailureEvidence$", "-test.v")
	cmd.Env = append(os.Environ(), "ZEVUNE_DIAGNOSTIC_CLEANUP_PROBE=1")
	raw, err := cmd.CombinedOutput()
	if err == nil || ctx.Err() != nil {
		t.Fatal("expected isolated failure probe did not terminate")
	}
	if !bytes.Contains(raw, []byte("POOL_FIXTURE_CHILD_EXIT")) || !bytes.Contains(raw, []byte(`"exit_code":0`)) || !bytes.Contains(raw, []byte(`"stage":"stopped"`)) || bytes.Contains(raw, []byte("PRIVATE_SENTINEL_DO_NOT_PUBLISH")) {
		t.Fatalf("successful cleanup lost evidence or leaked raw bytes: %s", raw)
	}
}
