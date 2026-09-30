package rpcgate

import (
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/rpcgate/gatetest"
)

func streamTestPipe(t *testing.T) (*os.File, *os.File) {
	t.Helper()
	r, w, err := gatetest.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { r.Close(); w.Close() })
	return r, w
}

func fillStreamTestPipe(t *testing.T, w *os.File) {
	t.Helper()
	written, err := gatetest.Saturate(w)
	if err != nil || written <= 0 {
		t.Fatal("full-pipe precondition not established", written, err)
	}
}

func TestReadinessAndFailureRecordsUseOwnedPipes(t *testing.T) {
	for _, failure := range []bool{false, true} {
		r, w := streamTestPipe(t)
		out, err := OpenOutput(w)
		if err != nil {
			t.Fatal(err)
		}
		want := ReadyRecord
		if failure {
			want = FailureRecord
			err = WriteFailure(context.Background(), out)
		} else {
			err = WriteReady(context.Background(), out)
		}
		if err != nil {
			t.Fatal(err)
		}
		out.Close()
		raw, err := io.ReadAll(r)
		if err != nil || string(raw) != want {
			t.Fatal("fixed record", err)
		}
	}
}

func TestStreamOwnersRejectUnsupportedOrClosedOutput(t *testing.T) {
	if _, err := OpenOutput(nil); err == nil {
		t.Fatal("nil output")
	}
	if _, err := OpenInput(nil); err == nil {
		t.Fatal("nil input")
	}
	if WriteReady(context.Background(), nil) != ErrReady || WriteFailure(context.Background(), &Output{}) != ErrService {
		t.Fatal("missing capability")
	}
	p := filepath.Join(t.TempDir(), "unsupported")
	f, err := os.Create(p)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := OpenOutput(f); err == nil {
		t.Fatal("regular file acquired capability")
	}
	if raw, err := os.ReadFile(p); err != nil || len(raw) != 0 {
		t.Fatal("unsupported file written")
	}
	r, w := streamTestPipe(t)
	out, err := OpenOutput(w)
	if err != nil {
		t.Fatal(err)
	}
	defer out.Close()
	if WriteReady(nil, out) != ErrReady {
		t.Fatal("nil context")
	}
	r.Close()
	if WriteReady(context.Background(), out) != ErrReady {
		t.Fatal("broken pipe succeeded")
	}
}

func TestInputEOFAndCancellationWithoutClose(t *testing.T) {
	r, w := streamTestPipe(t)
	in, err := OpenInput(r)
	if err != nil {
		t.Fatal(err)
	}
	defer in.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	started := time.Now()
	if err := in.UntilEOF(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatal("input cancellation", err)
	}
	if time.Since(started) > time.Second {
		t.Fatal("input needed Close to cancel")
	}
	// The writer has remained open until AFTER the cancellation result.
	w.Close()
	if err := in.UntilEOF(context.Background()); err != nil {
		t.Fatal("EOF", err)
	}
}

func TestCanceledOutputDoesNotWrite(t *testing.T) {
	r, w := streamTestPipe(t)
	out, err := OpenOutput(w)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if WriteReady(ctx, out) != ErrReady {
		t.Fatal("canceled output")
	}
	out.Close()
	raw, err := io.ReadAll(r)
	if err != nil || len(raw) != 0 {
		t.Fatal("canceled write produced bytes")
	}
}

// This child is only a standard-stream MECHANISM regression in the test binary.
// The native operator_e2e suite separately invokes the actual gateway command.
func TestInheritedStreamChild(t *testing.T) {
	mode := os.Getenv("ZEVUNE_STREAM_TEST_CHILD")
	if mode == "" {
		return
	}
	if mode == "input" {
		in, err := OpenInput(os.Stdin)
		if err != nil {
			os.Exit(11)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
		err = in.UntilEOF(ctx)
		cancel()
		in.Close()
		if !errors.Is(err, context.DeadlineExceeded) {
			os.Exit(12)
		}
		os.Exit(0)
	}
	file := os.Stdout
	if mode == "failure" {
		file = os.Stderr
	}
	out, err := OpenOutput(file)
	if err != nil {
		os.Exit(13)
	}
	started := time.Now()
	if mode == "ready" {
		err = WriteReady(context.Background(), out)
		if err != ErrReady || time.Since(started) < 1800*time.Millisecond {
			os.Exit(14)
		}
	} else if mode == "failure" {
		err = WriteFailure(context.Background(), out)
		if err != ErrService || time.Since(started) < 800*time.Millisecond {
			os.Exit(15)
		}
	} else if mode == "cancel" {
		ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
		err = WriteReady(ctx, out)
		cancel()
		if err != ErrReady || time.Since(started) > time.Second {
			os.Exit(16)
		}
	} else {
		os.Exit(17)
	}
	out.Close()
	os.Exit(0)
}

func TestInheritedPipesExitBeforeParentClosesOrDrains(t *testing.T) {
	for _, mode := range []string{"input", "ready", "failure", "cancel"} {
		t.Run(mode, func(t *testing.T) {
			in, keepOpen := streamTestPipe(t)
			outReader, output := streamTestPipe(t)
			errReader, stderr := streamTestPipe(t)
			if mode == "ready" || mode == "cancel" {
				fillStreamTestPipe(t, output)
			}
			if mode == "failure" {
				fillStreamTestPipe(t, stderr)
			}
			cmd := exec.Command(os.Args[0], "-test.run=^TestInheritedStreamChild$")
			cmd.Env = append(os.Environ(), "ZEVUNE_STREAM_TEST_CHILD="+mode)
			cmd.Stdin, cmd.Stdout, cmd.Stderr = in, output, stderr
			if err := cmd.Start(); err != nil {
				t.Fatal(err)
			}
			done := make(chan error, 1)
			go func() { done <- cmd.Wait() }()
			select {
			case err := <-done:
				if err != nil {
					t.Fatal("inherited child", mode, err)
				}
			case <-time.After(6 * time.Second):
				cmd.Process.Kill()
				<-done
				t.Fatal("child needed parent pipe intervention", mode)
			}
			// Only after Wait succeeds may the parent close/read any peer endpoint.
			keepOpen.Close()
			output.Close()
			stderr.Close()
			io.Copy(io.Discard, outReader)
			io.Copy(io.Discard, errReader)
		})
	}
}
