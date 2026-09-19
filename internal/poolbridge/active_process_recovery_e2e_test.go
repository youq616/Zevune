//go:build payment_resource_e2e

package poolbridge

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

// These wrappers only record, withhold or discard bytes from a genuine worker.
// They never construct a successful response or change the production transport.
type processRequestRecorder struct {
	io.WriteCloser
	mu       sync.Mutex
	recorded []byte
	overflow bool
}

func (r *processRequestRecorder) Write(b []byte) (int, error) {
	n, err := r.WriteCloser.Write(b)
	r.mu.Lock()
	defer r.mu.Unlock()
	if n < 0 || n > len(b) || len(r.recorded)+n > 512 {
		r.overflow = true
	} else {
		r.recorded = append(r.recorded, b[:n]...)
	}
	return n, err
}

func (r *processRequestRecorder) exactly(expected []byte) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return !r.overflow && bytes.Equal(r.recorded, expected)
}

type processCommitReplyGate struct {
	source   io.ReadCloser
	id       uint64
	digest   Hash
	expected Summary
	observed chan error
	closed   chan struct{}
	finished chan struct{}
	once     sync.Once
}

func (g *processCommitReplyGate) Read(_ []byte) (int, error) {
	defer close(g.finished)
	raw, err := readFrame(g.source, 145)
	if err == nil {
		if len(raw) != 145 || string(raw[:8]) != "ZVPLRSP1" ||
			binary.BigEndian.Uint64(raw[8:16]) != g.id || raw[16] != 0 ||
			!bytes.Equal(raw[17:49], g.digest[:]) {
			err = ErrProtocol
		} else if state, decodeErr := ActiveSegmentsV1.decodeSummary(raw[49:]); decodeErr != nil || state != g.expected {
			err = ErrProtocol
		}
	}
	g.observed <- err
	if err != nil {
		return 0, err
	}
	// The complete genuine success remains invisible to Client. Close must be
	// able to release this hold without waiting for Read or holding its mutex.
	<-g.closed
	return 0, io.ErrClosedPipe
}

func (g *processCommitReplyGate) Close() error {
	g.once.Do(func() { close(g.closed) })
	return g.source.Close()
}

func processRecoveryBytes(t *testing.T, path string) map[string][]byte {
	t.Helper()
	entries, err := os.ReadDir(path)
	if err != nil || len(entries) < 1 || len(entries) > 3 {
		t.Fatal("unexpected process-recovery directory inventory")
	}
	result := make(map[string][]byte, len(entries))
	for _, entry := range entries {
		name := filepath.Join(path, entry.Name())
		info, err := os.Lstat(name)
		if err != nil || !info.Mode().IsRegular() || info.Size() < 1 || info.Size() > ActiveSegmentBytes {
			t.Fatal("invalid process-recovery file")
		}
		raw, err := os.ReadFile(name)
		if err != nil || int64(len(raw)) != info.Size() {
			t.Fatal("process-recovery byte inspection failed after ownership release")
		}
		result[entry.Name()] = raw
	}
	return result
}

func processRecoveryEqual(t *testing.T, path string, expected map[string][]byte) {
	t.Helper()
	actual := processRecoveryBytes(t, path)
	if len(actual) != len(expected) {
		t.Fatal("process-recovery inventory changed")
	}
	for name, raw := range expected {
		if !bytes.Equal(actual[name], raw) {
			t.Fatal("process-recovery physical bytes differ")
		}
	}
}

func processRecoveryWait(t *testing.T, done <-chan struct{}, label string) {
	t.Helper()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal(label + " did not finish within five seconds")
	}
}

func processRecoveryClosed(t *testing.T, ctx context.Context, c *Client, tag Hash, tx []byte) {
	t.Helper()
	if _, err := c.Status(ctx); !errors.Is(err, ErrClosed) {
		t.Fatal("failed client still exposes Status")
	}
	if _, err := c.Commit(ctx, tag); !errors.Is(err, ErrClosed) {
		t.Fatal("failed client accepted another Commit exchange")
	}
	if err := c.Check(ctx, tx); !errors.Is(err, ErrClosed) {
		t.Fatal("failed client still exposes payment admission")
	}
}

func processRecoveryLoseReply(t *testing.T, ctx context.Context, c *Client, tag Hash, tx []byte, expected Summary) {
	t.Helper()
	request := make([]byte, 49)
	copy(request, "ZVPLREQ1")
	binary.BigEndian.PutUint64(request[8:16], c.id+1)
	request[16] = 3
	copy(request[17:], tag[:])
	framed := make([]byte, 4, 4+len(request))
	binary.BigEndian.PutUint32(framed, uint32(len(request)))
	framed = append(framed, request...)
	recorder := &processRequestRecorder{WriteCloser: c.in}
	gate := &processCommitReplyGate{
		source: c.out, id: c.id + 1, digest: sha256.Sum256(request), expected: expected,
		observed: make(chan error, 1), closed: make(chan struct{}), finished: make(chan struct{}),
	}
	// Finalize has returned, and there is no other in-flight exchange.
	c.in, c.out = recorder, gate
	requestContext, cancel := context.WithCancel(ctx)
	defer cancel()
	type outcome struct {
		state Summary
		err   error
	}
	completed := make(chan outcome, 1)
	go func() {
		state, err := c.Commit(requestContext, tag)
		completed <- outcome{state, err}
	}()
	select {
	case err := <-gate.observed:
		if err != nil {
			t.Fatal("did not capture the exact genuine Commit success")
		}
	case <-ctx.Done():
		t.Fatal("real Commit response observation exceeded the stage deadline")
	case <-time.After(60 * time.Second):
		t.Fatal("real Commit response observation exceeded sixty seconds")
	}
	cancel()
	select {
	case result := <-completed:
		if result.state != (Summary{}) || !errors.Is(result.err, ErrUnavailable) || !errors.Is(result.err, context.Canceled) {
			t.Fatal("lost Commit response was not reported as unavailable and canceled")
		}
	case <-time.After(10 * time.Second):
		t.Fatal("canceling the withheld response did not close the real client")
	}
	processRecoveryWait(t, gate.finished, "withheld reply reader")
	processRecoveryWait(t, c.done, "real worker after lost reply")
	processRecoveryClosed(t, ctx, c, tag, tx)
	if !recorder.exactly(framed) {
		t.Fatal("Commit was not transmitted exactly once, or a closed client sent more bytes")
	}
}

func TestActiveWorkerProcessFailureRecovery(t *testing.T) {
	for _, mode := range []string{"kill_after_finalize", "lose_commit_reply"} {
		t.Run(mode, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 4*time.Minute)
			defer cancel()
			root := t.TempDir()
			walletHome := filepath.Join(root, "wallets")
			if err := os.Mkdir(walletHome, 0700); err != nil {
				t.Fatal("process-recovery wallet directory creation failed")
			}
			r := &paymentResourceRun{t: t, ctx: ctx}
			r.walletPath = [2]string{filepath.Join(walletHome, "actor-0.zwallet"), filepath.Join(walletHome, "actor-1.zwallet")}
			pin := r.startScenario(walletHome)
			initial := r.state
			r.wallets = r.walletStatus(0, false)
			first := r.call(1, nil)
			r.wallets = r.walletStatus(0, true)
			worker := os.Getenv("ZEVUNE_POOL_WORKER")
			file, err := os.Open(worker)
			if err != nil {
				t.Fatal("actual process-recovery worker is required")
			}
			hash := sha256.New()
			n, hashErr := io.Copy(hash, io.LimitReader(file, 512<<20+1))
			closeErr := file.Close()
			if hashErr != nil || closeErr != nil || n < 1 || n > 512<<20 {
				t.Fatal("process-recovery worker digest failed")
			}
			var executablePin Hash
			copy(executablePin[:], hash.Sum(nil))
			options := Options{
				Executable: worker, ExpectedSHA256: executablePin,
				TestGenesis: filepath.Join(walletHome, "test-genesis.bin"), TestGenesisSHA256: pin,
				StartupTimeout: time.Minute, RequestTimeout: time.Minute,
			}
			start := func(path string, create bool) *Client {
				t.Helper()
				o := options
				o.Journal, o.Create = path, create
				c, err := Start(ctx, o)
				if err != nil || c.Profile() != ActiveSegmentsV1 {
					t.Fatal("real process-recovery worker startup or profile failed")
				}
				t.Cleanup(func() { _ = c.Close() })
				return c
			}
			closeWorker := func(c *Client) {
				t.Helper()
				if err := c.Close(); err != nil {
					t.Fatal("process-recovery worker ownership was not released")
				}
			}
			snapshot := func(c *Client, expected Summary) ActiveStorage {
				t.Helper()
				state, err := c.Status(ctx)
				capacity, capacityErr := c.ActiveCapacity(ctx)
				if err != nil || capacityErr != nil || state != expected || capacity.Summary != state {
					t.Fatal("complete replay Summary or active capacity differs")
				}
				return capacity
			}
			commit := func(c *Client, height uint64, tx []byte) Summary {
				t.Helper()
				preview, err := c.Preview(ctx, height, paymentResourceHash(height), [][]byte{tx})
				finalized, tag, finalizeErr := c.Finalize(ctx, height, paymentResourceHash(height), [][]byte{tx})
				if err != nil || finalizeErr != nil || finalized != preview {
					t.Fatal("real payment pre-execution failed")
				}
				state, err := c.Commit(ctx, tag)
				if err != nil || state != preview {
					t.Fatal("real payment Commit failed")
				}
				return state
			}
			path, referencePath := filepath.Join(root, "subject"), filepath.Join(root, "reference")
			c := start(path, true)
			initialCapacity := snapshot(c, initial)
			closeWorker(c)
			original := processRecoveryBytes(t, path)
			// A separate real worker executes the known genesis and exact payment.
			// Close it before reading its genesis on Windows. The wallet scenario
			// keeps its OLD history and exact pending payment throughout the fault.
			reference := start(referencePath, true)
			if snapshot(reference, initial) != initialCapacity {
				t.Fatal("independent worker genesis capacity differs")
			}
			expected := commit(reference, 1, first)
			expectedCapacity := snapshot(reference, expected)
			closeWorker(reference)
			expectedBytes := processRecoveryBytes(t, referencePath)
			c = start(path, false)
			competing := options
			competing.Journal = path
			if other, err := Start(ctx, competing); err == nil || other != nil || !errors.Is(err, ErrUnavailable) {
				if other != nil {
					closeWorker(other)
				}
				t.Fatal("second worker did not reject the live owner's lock")
			}
			finalized, tag, err := c.Finalize(ctx, 1, paymentResourceHash(1), [][]byte{first})
			if err != nil || finalized != expected || snapshot(c, initial) != initialCapacity {
				t.Fatal("Finalize changed committed state or differs from independent execution")
			}
			if mode == "kill_after_finalize" {
				// No stdin close and no Commit request precede this actual OS kill.
				if err := c.cmd.Process.Kill(); err != nil {
					t.Fatal("direct worker process termination failed")
				}
				processRecoveryWait(t, c.done, "directly killed worker")
				if c.cmd.ProcessState == nil || c.cmd.ProcessState.Success() {
					t.Fatal("direct kill did not produce a completed non-success exit")
				}
				if _, err := c.Status(ctx); !errors.Is(err, ErrUnavailable) {
					t.Fatal("dead worker was not reported unavailable")
				}
				processRecoveryClosed(t, ctx, c, tag, first)
				processRecoveryEqual(t, path, original)
			} else {
				processRecoveryLoseReply(t, ctx, c, tag, first, expected)
				processRecoveryEqual(t, path, expectedBytes)
			}
			// The caller has not resolved the subject's outcome yet. Restore the
			// existing encrypted outbox against unchanged reference history; do
			// not sign a replacement payment or clear its pending reservation.
			if restored := r.call(4, []byte{0}); !bytes.Equal(restored, first) {
				t.Fatal("outbox recovery changed the exact uncertain payment")
			}
			r.walletPath[0] = filepath.Join(walletHome, "backup-1-0.zwallet")
			if r.walletStatus(0, true) != r.wallets {
				t.Fatal("outbox recovery changed its pending reservation or storage receipt")
			}
			c = start(path, false)
			wantedState, wantedCapacity := expected, expectedCapacity
			if mode == "kill_after_finalize" {
				wantedState, wantedCapacity = initial, initialCapacity
			}
			if snapshot(c, wantedState) != wantedCapacity {
				t.Fatal("cold replay failed to resolve the process failure")
			}
			if _, err := c.Commit(ctx, tag); !errors.Is(err, ErrRejected) || snapshot(c, wantedState) != wantedCapacity {
				t.Fatal("old process pending tag survived cold replay")
			}
			if mode == "kill_after_finalize" && commit(c, 1, first) != expected {
				t.Fatal("fresh finalization of the uncommitted payment failed")
			}
			if snapshot(c, expected) != expectedCapacity {
				t.Fatal("resolved first payment differs from independent execution")
			}
			closeWorker(c)
			processRecoveryEqual(t, path, expectedBytes)
			paymentResourceCheckDisk(t, path, pin, initial, expectedCapacity, [][]byte{first}, []Summary{expected})
			c = start(path, false)
			if snapshot(c, expected) != expectedCapacity {
				t.Fatal("first payment did not survive another complete replay")
			}
			applyScenario := func(height uint64, tx []byte, state Summary) {
				t.Helper()
				raw, err := c.BlockBytes(height, paymentResourceHash(height), [][]byte{tx})
				if err != nil || r.summary(r.call(2, raw)) != state {
					t.Fatal("independent wallet history differs from resolved committed state")
				}
				r.state = state
				r.wallets = r.walletStatus(0, false)
			}
			applyScenario(1, first, expected)
			r.worker, r.capacity = c, expectedCapacity
			r.rejectSpent(path, [][]byte{first}, false)
			second := r.call(1, nil)
			r.wallets = r.walletStatus(0, true)
			reference = start(referencePath, false)
			continued := commit(reference, 2, second)
			continuedCapacity := snapshot(reference, continued)
			closeWorker(reference)
			continuedBytes := processRecoveryBytes(t, referencePath)
			if commit(c, 2, second) != continued || snapshot(c, continued) != continuedCapacity {
				t.Fatal("genuine onward payment after process recovery differs")
			}
			applyScenario(2, second, continued)
			r.capacity = continuedCapacity
			r.rejectSpent(path, [][]byte{first, second}, false)
			closeWorker(c)
			processRecoveryEqual(t, path, continuedBytes)
			paymentResourceCheckDisk(t, path, pin, initial, continuedCapacity, [][]byte{first, second}, []Summary{expected, continued})
			c = start(path, false)
			if snapshot(c, continued) != continuedCapacity {
				t.Fatal("onward payment did not survive complete replay")
			}
			closeWorker(c)
			r.closeScenario()
			t.Logf("ACTIVE_PROCESS_RECOVERY case=%s real_payments=2 exact_outbox=true full_replay=true physical_bytes=true old_tag_rejected=true duplicate_payments_rejected=true real_funds_allowed=false", mode)
		})
	}
}
