package poolbridge

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"io"
	"os"
	"os/exec"
	"sync"
	"testing"
	"time"
)

// Test-only double; real proofs are checked by the separate Rust E2E suite.
func TestPoolProcessHelper(t *testing.T) {
	if os.Getenv("ZEVUNE_POOL_HELPER") != "1" {
		return
	}
	mode := os.Args[len(os.Args)-1]
	if mode == "nohello" {
		time.Sleep(5 * time.Second)
		os.Exit(0)
	}
	fp := sha256.Sum256([]byte(domain))
	hello := append([]byte("ZVPLHEL1"), fp[:]...)
	if mode == "badhello" {
		hello[8] ^= 1
	}
	if writeFrame(os.Stdout, hello) != nil {
		os.Exit(2)
	}
	for {
		b, e := readFrame(os.Stdin, maxFrame)
		if e != nil {
			os.Exit(0)
		}
		if mode == "exit" {
			os.Exit(0)
		}
		if mode == "hang" {
			time.Sleep(5 * time.Second)
		}
		if mode == "slow" {
			time.Sleep(80 * time.Millisecond)
		}
		out := make([]byte, 145)
		copy(out, "ZVPLRSP1")
		copy(out[8:16], b[8:16])
		h := sha256.Sum256(b)
		copy(out[17:49], h[:])
		if mode == "reject" {
			out[16] = 1
		}
		if mode == "badid" {
			out[15] ^= 1
		}
		if mode == "badhash" {
			out[17] ^= 1
		}
		if mode == "badstatus" {
			out[16] = 2
		}
		if mode == "badsum" {
			binary.BigEndian.PutUint64(out[49:57], 10001)
		}
		if mode == "truncated" {
			_, _ = os.Stdout.Write([]byte{0, 0, 0, 145, 1})
			os.Exit(0)
		}
		if writeFrame(os.Stdout, out) != nil {
			os.Exit(3)
		}
	}
}
func helper(t *testing.T, mode string, d time.Duration) *Client {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestPoolProcessHelper$", "--", mode)
	cmd.Env = append(os.Environ(), "ZEVUNE_POOL_HELPER=1")
	c, e := start(context.Background(), cmd, Options{StartupTimeout: 2 * time.Second, RequestTimeout: d})
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { _ = c.Close() })
	return c
}
func TestFrameBoundaries(t *testing.T) {
	for _, b := range [][]byte{nil, {0}, {0, 0, 0, 0}, {255, 255, 255, 255}, {0, 0, 0, 2, 1}} {
		if _, e := readFrame(bytes.NewReader(b), maxFrame); e == nil {
			t.Fatal("accepted malformed frame")
		}
	}
	var b bytes.Buffer
	if e := writeFrame(&b, []byte("abc")); e != nil {
		t.Fatal(e)
	}
	out, e := readFrame(&b, 3)
	if e != nil || string(out) != "abc" {
		t.Fatal(e)
	}
	if writeFrame(io.Discard, nil) == nil || writeFrame(io.Discard, make([]byte, maxFrame+1)) == nil {
		t.Fatal("write bounds")
	}
}

type shortWriter struct{ b bytes.Buffer }

func (w *shortWriter) Write(b []byte) (int, error) {
	if len(b) > 1 {
		b = b[:1]
	}
	return w.b.Write(b)
}
func TestFrameShortWrites(t *testing.T) {
	w := &shortWriter{}
	if e := writeFrame(w, []byte("abc")); e != nil {
		t.Fatal(e)
	}
	b, e := readFrame(&w.b, 3)
	if e != nil || string(b) != "abc" {
		t.Fatal(e)
	}
}
func TestBlockEncodingAndOwnership(t *testing.T) {
	tx := []byte{1, 2, 3}
	b, e := BlockBytes(1, Hash{1}, [][]byte{tx})
	if e != nil || len(b) != 49 {
		t.Fatal(e)
	}
	tx[0] = 9
	if b[46] != 1 {
		t.Fatal("aliased transaction")
	}
	cases := []struct {
		h   uint64
		id  Hash
		txs [][]byte
	}{{0, Hash{1}, nil}, {10001, Hash{1}, nil}, {1, Hash{}, nil}, {1, Hash{1}, make([][]byte, 17)}, {1, Hash{1}, [][]byte{nil}}, {1, Hash{1}, [][]byte{make([]byte, MaxTransactionBytes+1)}}}
	for _, c := range cases {
		if _, e = BlockBytes(c.h, c.id, c.txs); e == nil {
			t.Fatal("accepted invalid block")
		}
	}
}
func TestReplyBindingsAndFailClosed(t *testing.T) {
	for _, mode := range []string{"exit", "badid", "badhash", "badstatus", "badsum", "truncated", "hang"} {
		t.Run(mode, func(t *testing.T) {
			c := helper(t, mode, 100*time.Millisecond)
			if _, e := c.Status(context.Background()); e == nil {
				t.Fatal("accepted invalid exchange")
			}
			if _, e := c.Status(context.Background()); !errors.Is(e, ErrClosed) {
				t.Fatalf("worker not closed: %v", e)
			}
		})
	}
}
func TestNormalRejectionDoesNotCloseWorker(t *testing.T) {
	c := helper(t, "reject", time.Second)
	for i := 0; i < 2; i++ {
		if _, e := c.Status(context.Background()); !errors.Is(e, ErrRejected) {
			t.Fatal(e)
		}
	}
}
func TestCanceledInflightIsUncertain(t *testing.T) {
	c := helper(t, "hang", time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	_, e := c.Commit(ctx, Hash{1})
	if !errors.Is(e, ErrUnavailable) || !errors.Is(e, context.DeadlineExceeded) {
		t.Fatal(e)
	}
	if _, e = c.Status(context.Background()); !errors.Is(e, ErrClosed) {
		t.Fatal(e)
	}
}
func TestConcurrentCallsSerialize(t *testing.T) {
	c := helper(t, "ok", time.Second)
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, e := c.Status(context.Background()); e != nil {
				t.Error(e)
			}
		}()
	}
	wg.Wait()
}
func TestCanceledBeforeQueueDoesNotClose(t *testing.T) {
	c := helper(t, "ok", time.Second)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, e := c.Status(ctx); !errors.Is(e, context.Canceled) {
		t.Fatal(e)
	}
	if _, e := c.Status(context.Background()); e != nil {
		t.Fatal(e)
	}
}
func TestStartupFailures(t *testing.T) {
	for _, mode := range []string{"nohello", "badhello"} {
		cmd := exec.Command(os.Args[0], "-test.run=^TestPoolProcessHelper$", "--", mode)
		cmd.Env = append(os.Environ(), "ZEVUNE_POOL_HELPER=1")
		c, e := start(context.Background(), cmd, Options{StartupTimeout: 100 * time.Millisecond, RequestTimeout: time.Second})
		if e == nil {
			_ = c.Close()
			t.Fatal("bad startup accepted")
		}
	}
}
func TestExecutableAndOptionBounds(t *testing.T) {
	for _, o := range []Options{{}, {Executable: "relative", Journal: "relative", ExpectedSHA256: Hash{1}}, {StartupTimeout: -1}, {RequestTimeout: 2 * time.Minute}} {
		if c, e := Start(context.Background(), o); e == nil {
			_ = c.Close()
			t.Fatal("bad options accepted")
		}
	}
}
func TestSummaryCheckpoint(t *testing.T) {
	s := Summary{Height: 3, AppHash: Hash{7}}
	if s.Checkpoint(3, Hash{7}) != nil || s.Checkpoint(2, Hash{7}) == nil || s.Checkpoint(3, Hash{8}) == nil {
		t.Fatal("checkpoint")
	}
	if _, e := decodeSummary(make([]byte, 95)); e == nil {
		t.Fatal("summary bounds")
	}
}
func FuzzPoolFrame(f *testing.F) {
	f.Add([]byte{0, 0, 0, 1, 1})
	f.Fuzz(func(t *testing.T, b []byte) { _, _ = readFrame(bytes.NewReader(b), maxFrame) })
}
