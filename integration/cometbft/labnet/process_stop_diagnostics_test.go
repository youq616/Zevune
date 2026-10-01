package labnet

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"testing"
	"time"
)

const stopDiagnosticSecret = "private-stop-fixture-password-path-and-receipt"

func TestProcessStopObservationIsBoundedAndRedacted(t *testing.T) {
	valid := `{"status":"local_node_failed","stage":"running","code":"other"}`
	unknown := `{"private":"` + stopDiagnosticSecret + `"}`
	for _, tc := range []struct {
		name, input, class string
		retained, observed int
		truncated, capped  bool
	}{
		{"empty", "", "empty", 0, 0, false, false},
		{"text", stopDiagnosticSecret, "invalid_json", len(stopDiagnosticSecret), len(stopDiagnosticSecret), false, false},
		{"unknown", unknown, "unrecognized_record", len(unknown), len(unknown), false, false},
		{"known", valid, "fixed_record", len(valid), len(valid), false, false},
		{"boundary", strings.Repeat("x", 512), "invalid_json", 512, 512, false, false},
		{"truncated", strings.Repeat("x", 513), "truncated", 512, 513, true, false},
		{"count-cap", strings.Repeat("x", 70000), "truncated", 512, 65535, true, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			b := &boundedProcessOutput{}
			if n, err := b.Write([]byte(tc.input)); n != len(tc.input) || err != nil {
				t.Fatal("capture did not drain the whole write")
			}
			p := &process{diagnostic: b, done: make(chan struct{})}
			got := p.stopObservation(false, errors.New(stopDiagnosticSecret))
			want := processStderrObservation{tc.class, tc.observed, tc.capped, tc.retained, tc.truncated}
			if got.Stderr != want || got.StdinClose != "other" || got.ExitObservedMS != -1 {
				t.Fatalf("bounded observation mismatch: %+v", got)
			}
			if strings.Contains(fmt.Sprint(got), stopDiagnosticSecret) {
				t.Fatal("private stderr or close error escaped")
			}
		})
	}
	p := &process{done: make(chan struct{}), exitObservedMS: 123}
	if got := p.stopObservation(false, io.ErrClosedPipe); got.Stderr.Class != "not_captured" || got.StdinClose != "closed" || got.ExitObservedMS != -1 {
		t.Fatal("uncaptured/running state was invented")
	}
	close(p.done)
	if got := p.stopObservation(true, os.ErrClosed); !got.ExitObservedBeforeClose || got.ExitObservedMS != 123 || got.StdinClose != "closed" {
		t.Fatal("Wait completion or close category was lost")
	}
}

func TestProcessStopObservationCounterBoundaryAndRace(t *testing.T) {
	b := &boundedProcessOutput{}
	_, _ = b.Write([]byte(strings.Repeat("x", 65535)))
	p := &process{diagnostic: b, done: make(chan struct{})}
	if got := p.stopObservation(false, nil); got.Stderr.ObservedBytes != 65535 || got.Stderr.BytesCapped {
		t.Fatal("exact counter boundary was mislabeled as saturated")
	}
	var group sync.WaitGroup
	for i := 0; i < 8; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for j := 0; j < 100; j++ {
				_, _ = b.Write([]byte(stopDiagnosticSecret))
				got := p.stopObservation(false, nil)
				if got.Stderr.RetainedBytes > 512 || got.Stderr.ObservedBytes != 65535 || !got.Stderr.BytesCapped {
					t.Error("capture or counter exceeded its bound")
				}
			}
		}()
	}
	group.Wait()
}

func TestProcessStopDiagnosticSubprocess(t *testing.T) {
	if len(os.Args) < 3 || os.Args[len(os.Args)-2] != "--" {
		return
	}
	mode := os.Args[len(os.Args)-1]
	if strings.HasPrefix(mode, "leaf-") {
		if mode != "leaf-early" {
			_, _ = fmt.Fprintln(os.Stdout, "ready")
			_, _ = io.Copy(io.Discard, os.Stdin)
		}
		_, _ = fmt.Fprint(os.Stderr, stopDiagnosticSecret)
		if mode == "leaf-success" {
			os.Exit(0)
		}
		os.Exit(2)
	}
	leaf := "leaf-" + mode
	p, err := startTestProcess(os.Args[0], []string{"-test.run=^TestProcessStopDiagnosticSubprocess$", "--", leaf}, &boundedProcessOutput{})
	if err != nil {
		t.Fatal("fixture process did not start")
	}
	p.nodeIndex = 2
	t.Cleanup(func() { p.stop(t) })
	if mode == "early" {
		waitProcessFixture(t, p)
	} else {
		line, err := bufio.NewReader(p.out).ReadString('\n')
		if err != nil || line != "ready\n" {
			t.Fatal("fixture handshake missing")
		}
	}
	p.stop(t) // The original failure assertion must still fail the child test.
	p.stop(t) // Repeated cleanup must remain idempotent.
}

func TestProcessStopFailureReportsRealBeforeAndAfterEOFWithoutRawOutput(t *testing.T) {
	for _, mode := range []string{"early", "after", "success"} {
		t.Run(mode, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestProcessStopDiagnosticSubprocess$", "--", mode)
			out, err := cmd.CombinedOutput()
			if ctx.Err() != nil || len(out) > 4096 || strings.Contains(string(out), stopDiagnosticSecret) {
				t.Fatal("fixture exceeded budget/output bound or leaked private output")
			}
			if mode == "success" {
				if err != nil || strings.Contains(string(out), "stop_observation") {
					t.Fatal("successful child produced a stop failure")
				}
				return
			}
			var exit *exec.ExitError
			if !errors.As(err, &exit) || exit.ExitCode() != 1 {
				t.Fatal("real nonzero child no longer fails the supervising test")
			}
			want := "ExitObservedBeforeClose:false"
			if mode == "early" {
				want = "ExitObservedBeforeClose:true"
			}
			if strings.Count(string(out), "child exited unsuccessfully:") != 1 ||
				!strings.Contains(string(out), "node=2 exit_code=2 diagnostic={Stage:unknown Code:unknown}") ||
				!strings.Contains(string(out), want) || !strings.Contains(string(out), "Class:invalid_json") ||
				strings.Contains(string(out), "child did not stop:") {
				t.Fatal("stop observation lost phase/exit distinction or repeated cleanup failure")
			}
		})
	}
}
