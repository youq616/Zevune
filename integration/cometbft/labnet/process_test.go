package labnet

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sync"
	"testing"
	"time"

	ctypes "github.com/cometbft/cometbft/rpc/core/types"
)

var (
	errNodeReadiness = errors.New("invalid node readiness record")
	errNodeExited    = errors.New("supervised child exited unexpectedly")
	errNodeIdentity  = errors.New("status response has the wrong node identity")
)

type process struct {
	cmd            *exec.Cmd
	in             io.WriteCloser
	out            io.ReadCloser
	done           chan struct{}
	exitErr        error // Written before done closes; read only after observing done.
	exitObservedMS int64 // When Wait returned, not the kernel's exact exit time.
	stopped        bool
	started        time.Time
	nodeIndex      int
	nodeID         string
	readyDone      chan struct{}
	readyErr       error // Written before readyDone closes.
	diagnostic     *boundedProcessOutput
}

// Owned stdout pipes keep unread bytes available after Wait. StdoutPipe would
// let Wait close the read descriptor while a scenario or ready reader uses it.
func startTestProcess(exe string, args []string, diagnostic *boundedProcessOutput) (*process, error) {
	p := &process{cmd: exec.Command(exe, args...), done: make(chan struct{}), nodeIndex: -1, diagnostic: diagnostic}
	p.cmd.Stderr = io.Discard
	if diagnostic != nil {
		p.cmd.Stderr = diagnostic
	}
	var err error
	p.in, err = p.cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	reader, writer, err := os.Pipe()
	if err != nil {
		_ = p.in.Close()
		return nil, err
	}
	p.out, p.cmd.Stdout = reader, writer
	p.started = time.Now()
	if err = p.cmd.Start(); err != nil {
		_ = p.in.Close()
		_ = reader.Close()
		_ = writer.Close()
		return nil, err
	}
	_ = writer.Close()
	go func() {
		p.exitErr = p.cmd.Wait()
		p.exitObservedMS = time.Since(p.started).Milliseconds()
		close(p.done)
	}()
	return p, nil
}

func launch(t *testing.T, exe string, args ...string) *process {
	t.Helper()
	p, err := startTestProcess(exe, args, nil)
	if err != nil {
		t.Fatal("child start failed:", nodeFailureCode(err))
	}
	t.Cleanup(func() { p.stop(t) })
	return p
}

func launchNode(t *testing.T, exe string, index int, id string, args ...string) *process {
	t.Helper()
	p, err := startTestProcess(exe, args, &boundedProcessOutput{})
	if err != nil {
		t.Fatal("node process start failed:", nodeFailureCode(err))
	}
	p.nodeIndex, p.nodeID, p.readyDone = index, id, make(chan struct{})
	go func() {
		p.readyErr = readNodeReady(p.out, index)
		close(p.readyDone)
	}()
	t.Cleanup(func() { p.stop(t) })
	return p
}

func (p *process) stop(t *testing.T) {
	t.Helper()
	if p.stopped {
		return
	}
	p.stopped = true
	_ = p.in.Close()
	select {
	case <-p.done:
		if p.exitErr != nil {
			t.Errorf("child exited unsuccessfully: node=%d exit_code=%d diagnostic=%+v", p.nodeIndex, p.exitCode(), p.failure())
		}
	case <-time.After(45 * time.Second):
		_ = p.cmd.Process.Kill()
		<-p.done
		t.Errorf("child did not stop: node=%d exit_code=%d diagnostic=%+v", p.nodeIndex, p.exitCode(), p.failure())
	}
	_ = p.out.Close()
}

func (p *process) exitCode() int {
	select {
	case <-p.done:
		if p.exitErr == nil {
			return 0
		}
		var exit *exec.ExitError
		if errors.As(p.exitErr, &exit) {
			return exit.ExitCode()
		}
		return -1
	default:
		return -2 // Still running; no exit code has been observed.
	}
}

func readNodeReady(r io.Reader, index int) error {
	line, err := bufio.NewReader(io.LimitReader(r, 257)).ReadBytes('\n')
	if err != nil || len(line) > 256 {
		return errNodeReadiness
	}
	// The actual CLI encoder sorts these map keys. This validates the first ready
	// record, including false/zero fields and duplicate/trailing fields on its
	// line. It does not claim to validate any subsequent stdout records.
	want := fmt.Sprintf("{\"node\":%d,\"real_funds_allowed\":false,\"status\":\"local_node_started\"}\n", index)
	if index < 0 || index >= 4 || !bytes.Equal(line, []byte(want)) {
		return errNodeReadiness
	}
	return nil
}

// Drain all stderr without blocking a child; retain at most 512 bytes. Only a
// validated fixed-label failure record is ever returned for diagnostic output.
type boundedProcessOutput struct {
	mu        sync.Mutex
	data      []byte
	truncated bool
}

func (b *boundedProcessOutput) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	n := len(p)
	remaining := 512 - len(b.data)
	if n > remaining {
		b.truncated = true
		p = p[:remaining]
	}
	b.data = append(b.data, p...)
	return n, nil
}

func (p *process) failure() NodeFailure {
	unknown := NodeFailure{Stage: "unknown", Code: "unknown"}
	if p.diagnostic == nil {
		return unknown
	}
	b := p.diagnostic
	b.mu.Lock()
	defer b.mu.Unlock()
	var report struct {
		Status string `json:"status"`
		Stage  string `json:"stage"`
		Code   string `json:"code"`
	}
	if b.truncated || json.Unmarshal(b.data, &report) != nil || report.Status != "local_node_failed" {
		return unknown
	}
	switch report.Stage {
	case "validation", "configuration", "worker_start", "signer_load", "consensus_configuration", "consensus_construct", "consensus_start", "running":
	default:
		return unknown
	}
	switch report.Code {
	case "deadline", "canceled", "address_in_use", "connection_refused", "consensus_stopped", "worker_unavailable", "worker_protocol", "worker_rejected", "configuration", "storage", "bounds", "other":
	default:
		return unknown
	}
	return NodeFailure{Stage: report.Stage, Code: report.Code}
}

type nodeStatusSource interface {
	Status(context.Context) (*ctypes.ResultStatus, error)
}

type nodeObservation struct {
	Index           int
	Ready           bool
	Height          int64
	RPC             string
	ExitCode        int
	SampleElapsedMS int64
	ExitObservedMS  int64
	Failure         NodeFailure
}

func snapshotNodeProcesses(nodes []*process, observed []nodeObservation) {
	for i, p := range nodes {
		if p == nil {
			continue
		}
		o := &observed[i]
		o.Index, o.ExitCode, o.SampleElapsedMS, o.Failure = p.nodeIndex, p.exitCode(), time.Since(p.started).Milliseconds(), p.failure()
		if o.ExitCode != -2 {
			o.ExitObservedMS = p.exitObservedMS
		}
		select {
		case <-p.readyDone:
			o.Ready = p.readyErr == nil
		default:
		}
	}
}

func waitNodeHeights(ctx context.Context, nodes []*process, peers []nodeStatusSource, want int64) (observed []nodeObservation, err error) {
	observed = make([]nodeObservation, len(nodes))
	for i := range observed {
		observed[i] = nodeObservation{Index: i, Height: -1, RPC: "not_observed", ExitCode: -2, ExitObservedMS: -1, Failure: NodeFailure{Stage: "unknown", Code: "unknown"}}
	}
	defer func() { snapshotNodeProcesses(nodes, observed) }()
	if ctx == nil || len(nodes) == 0 || len(nodes) != len(peers) || want < 1 {
		return observed, ErrBounds
	}
	tick := time.NewTicker(100 * time.Millisecond)
	defer tick.Stop()
	for {
		snapshotNodeProcesses(nodes, observed)
		complete, active := true, 0
		for i, p := range nodes {
			if p == nil || peers[i] == nil {
				return observed, ErrBounds
			}
			o := &observed[i]
			if p.stopped {
				o.RPC = "requested_stop"
				continue
			}
			active++
			if o.ExitCode != -2 {
				return observed, errNodeExited
			}
			select {
			case <-p.readyDone:
				if p.readyErr != nil {
					o.RPC = "invalid_ready"
					return observed, errNodeReadiness
				}
				o.Ready = true
			default:
				o.RPC = "awaiting_ready"
				complete = false
				continue
			}
			request, cancel := context.WithTimeout(ctx, 2*time.Second)
			status, err := peers[i].Status(request)
			cancel()
			if err != nil {
				o.RPC = nodeFailureCode(err)
				complete = false
				continue
			}
			if status == nil {
				o.RPC = "empty_status"
				complete = false
				continue
			}
			if string(status.NodeInfo.ID()) != p.nodeID {
				o.RPC = "wrong_identity"
				return observed, errNodeIdentity
			}
			o.Height, o.RPC = status.SyncInfo.LatestBlockHeight, "observed"
			if o.Height < want {
				complete = false
			}
		}
		if active == 0 {
			return observed, ErrBounds
		}
		if err := ctx.Err(); err != nil {
			return observed, err
		}
		if complete {
			// An RPC success cannot conceal another child's unexpected exit.
			for _, p := range nodes {
				if !p.stopped && p.exitCode() != -2 {
					return observed, errNodeExited
				}
			}
			return observed, nil
		}
		select {
		case <-ctx.Done():
			return observed, ctx.Err()
		case <-tick.C:
		}
	}
}

func awaitNetworkHeight(t *testing.T, nodes []*process, peers []*peer, want int64) {
	t.Helper()
	// Readiness and every node's height share this one original 90-second budget.
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	sources := make([]nodeStatusSource, len(peers))
	for i, p := range peers {
		sources[i] = p
	}
	observed, err := waitNodeHeights(ctx, nodes, sources, want)
	if err != nil {
		for _, node := range observed {
			t.Logf("node observation: %+v", node)
		}
		t.Fatalf("network did not reach height %d: %v", want, err)
	}
}
