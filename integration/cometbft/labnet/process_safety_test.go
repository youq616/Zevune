package labnet

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/cometbft/cometbft/p2p"
	ctypes "github.com/cometbft/cometbft/rpc/core/types"
)

func TestSupervisedProcessFixture(t *testing.T) {
	if len(os.Args) < 3 || os.Args[len(os.Args)-2] != "--" {
		return
	}
	mode := os.Args[len(os.Args)-1]
	if mode == "buffer-then-exit" {
		_, _ = os.Stdout.Write([]byte{0, 0, 0, 4, 0, 255, 1, 128})
		os.Exit(0)
	}
	if strings.HasPrefix(mode, "ready-") {
		_, _ = fmt.Fprintln(os.Stdout, `{"node":0,"real_funds_allowed":false,"status":"local_node_started"}`)
	}
	if strings.HasSuffix(mode, "exit7") {
		os.Exit(7)
	}
	if strings.HasSuffix(mode, "exit0") {
		os.Exit(0)
	}
	os.Exit(9)
}

func processFixtureArgs(mode string) []string {
	return []string{"-test.run=^TestSupervisedProcessFixture$", "--", mode}
}

func waitProcessFixture(t *testing.T, p *process) {
	t.Helper()
	select {
	case <-p.done:
	case <-time.After(10 * time.Second):
		t.Fatal("subprocess fixture did not exit")
	}
}

func TestOwnedStdoutSurvivesWaitAndExitIsNotConsumed(t *testing.T) {
	p := launch(t, os.Args[0], processFixtureArgs("buffer-then-exit")...)
	waitProcessFixture(t, p)
	for i := 0; i < 3; i++ {
		if p.exitCode() != 0 {
			t.Fatal("exit observation consumed or lost the result")
		}
	}
	raw, err := io.ReadAll(p.out)
	if err != nil || !bytes.Equal(raw, []byte{0, 0, 0, 4, 0, 255, 1, 128}) {
		t.Fatal("Wait closed stdout before its reader drained the final binary frame")
	}
	p.stop(t) // Observing done above must not make cleanup wait a second time.
}

type fixedNodeStatus struct{ id string }

func (s fixedNodeStatus) Status(context.Context) (*ctypes.ResultStatus, error) {
	return &ctypes.ResultStatus{NodeInfo: p2p.DefaultNodeInfo{DefaultNodeID: p2p.ID(s.id)}, SyncInfo: ctypes.SyncInfo{LatestBlockHeight: 3}}, nil
}

func TestSupervisionRejectsZeroAndNonzeroExitBeforeAndAfterReady(t *testing.T) {
	for _, mode := range []string{"exit0", "exit7", "ready-exit0", "ready-exit7"} {
		t.Run(mode, func(t *testing.T) {
			p := launchNode(t, os.Args[0], 0, "expected", processFixtureArgs(mode)...)
			waitProcessFixture(t, p)
			// The helper exits deliberately. Own cleanup without treating this
			// expected fixture exit as a second test failure.
			p.stopped = true
			_ = p.in.Close()
			defer p.out.Close()
			select {
			case <-p.readyDone:
			case <-time.After(10 * time.Second):
				t.Fatal("ready reader did not finish after subprocess exit")
			}
			if (p.readyErr == nil) != strings.HasPrefix(mode, "ready-") {
				t.Fatal("subprocess readiness was lost or invented")
			}
			p.stopped = false
			ctx, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			unobserved := &process{done: make(chan struct{}), readyDone: make(chan struct{}), nodeIndex: 1, nodeID: "next", started: time.Now()}
			observed, err := waitNodeHeights(ctx, []*process{p, unobserved}, []nodeStatusSource{fixedNodeStatus{"expected"}, fixedNodeStatus{"next"}}, 3)
			p.stopped = true
			if !errors.Is(err, errNodeExited) {
				t.Fatal("successful status concealed a child exit", err)
			}
			want := 0
			if strings.HasSuffix(mode, "exit7") {
				want = 7
			}
			if observed[0].ExitCode != want || p.exitCode() != want {
				t.Fatal("supervision discarded the actual exit code")
			}
			if observed[0].ExitObservedMS < 0 || observed[0].ExitObservedMS > observed[0].SampleElapsedMS ||
				observed[1].Index != 1 || observed[1].Height != -1 || observed[1].ExitCode != -2 || observed[1].ExitObservedMS != -1 {
				t.Fatal("early return invented an exit/height or lost the observed exit timing")
			}
		})
	}
}

func TestReadinessIsBoundedAndRequiresEverySafetyField(t *testing.T) {
	valid := "{\"node\":0,\"real_funds_allowed\":false,\"status\":\"local_node_started\"}\n"
	if readNodeReady(strings.NewReader(valid), 0) != nil {
		t.Fatal("actual CLI ready record rejected")
	}
	for _, input := range []string{
		"", strings.TrimSuffix(valid, "\n"), strings.Replace(valid, `"node":0`, `"node":1`, 1),
		strings.Replace(valid, `"real_funds_allowed":false,`, "", 1),
		strings.Replace(valid, `"node":0`, `"node":0,"node":0`, 1),
		strings.Replace(valid, `false`, `true`, 1), strings.Repeat("x", 257) + "\n",
	} {
		if !errors.Is(readNodeReady(strings.NewReader(input), 0), errNodeReadiness) {
			t.Fatal("malformed or oversized ready output accepted")
		}
	}
}

func TestHeightWaitSharesReadinessDeadlineAndPinsNodeIdentity(t *testing.T) {
	p := &process{done: make(chan struct{}), readyDone: make(chan struct{}), nodeIndex: 0, nodeID: "expected", started: time.Now()}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if _, err := waitNodeHeights(ctx, []*process{p}, []nodeStatusSource{fixedNodeStatus{"expected"}}, 3); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatal("height success bypassed unfinished readiness or its deadline", err)
	}
	close(p.readyDone)
	if _, err := waitNodeHeights(context.Background(), []*process{p}, []nodeStatusSource{fixedNodeStatus{"different"}}, 3); !errors.Is(err, errNodeIdentity) {
		t.Fatal("another node at the same endpoint satisfied height readiness", err)
	}
}

func TestChildDiagnosticsDrainBoundedlyAndNeverEchoUnknownText(t *testing.T) {
	for _, input := range []string{
		strings.Repeat("private-fixture", 1000),
		`{"status":"local_node_failed","stage":"private-fixture","code":"address_in_use"}`,
		`{"status":"local_node_failed","stage":"consensus_start","code":"private-fixture"}`,
	} {
		out := &boundedProcessOutput{}
		if n, err := out.Write([]byte(input)); err != nil || n != len(input) || len(out.data) > 512 {
			t.Fatal("stderr capture blocked output or exceeded its bound")
		}
		if got := (&process{diagnostic: out}).failure(); got != (NodeFailure{Stage: "unknown", Code: "unknown"}) {
			t.Fatal("unknown child text entered diagnostics")
		}
	}
	out := &boundedProcessOutput{}
	_, _ = out.Write([]byte(`{"status":"local_node_failed","stage":"consensus_start","code":"address_in_use"}`))
	if got := (&process{diagnostic: out}).failure(); got != (NodeFailure{Stage: "consensus_start", Code: "address_in_use"}) {
		t.Fatal("known bounded failure was lost")
	}
}
