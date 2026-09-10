package orchardbridge

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestWorkerHelper(t *testing.T) {
	mode := os.Getenv("ZEVUNE_BRIDGE_TEST_HELPER")
	if mode == "" {
		return
	}
	// Test-only program. It is never the real cryptography worker.
	if mode == "startup_hang" {
		time.Sleep(time.Minute)
		os.Exit(0)
	}
	fp := protocolFingerprint()
	hello := append([]byte(helloMagic), fp[:]...)
	if mode == "bad_hello" {
		hello[8] ^= 1
	}
	if mode == "large_hello" {
		_, _ = os.Stdout.Write([]byte{255, 255, 255, 255})
		time.Sleep(time.Minute)
		os.Exit(0)
	}
	if err := writeFrame(os.Stdout, hello); err != nil {
		os.Exit(2)
	}
	for {
		b, err := readFrame(os.Stdin, maxFrame)
		if err != nil {
			os.Exit(0)
		}
		if len(b) < 20 {
			os.Exit(2)
		}
		switch mode {
		case "hang":
			time.Sleep(time.Minute)
		case "exit":
			os.Exit(3)
		case "stderr":
			_, _ = io.Copy(os.Stderr, io.LimitReader(zeroReader{}, 2<<20))
		case "large_response":
			_, _ = os.Stdout.Write([]byte{255, 255, 255, 255})
			continue
		}
		digest := PayloadDigest(b[20:])
		response := append([]byte(responseMagic), make([]byte, 41)...)
		copy(response[8:16], b[8:16])
		copy(response[17:], digest[:])
		switch mode {
		case "wrong_id":
			response[15] ^= 1
		case "wrong_digest":
			response[17] ^= 1
		case "unknown_status":
			response[16] = 7
		case "reject":
			response[16] = 1
		case "truncated":
			_ = writeFrame(os.Stdout, response[:30])
			continue
		case "stdout_noise":
			_, _ = os.Stdout.Write([]byte("log line"))
			continue
		}
		if err := writeFrame(os.Stdout, response); err != nil {
			os.Exit(2)
		}
	}
}

type zeroReader struct{}

func (zeroReader) Read(b []byte) (int, error) { clear(b); return len(b), nil }

func helper(t *testing.T, mode string, timeout time.Duration) *Worker {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestWorkerHelper$")
	cmd.Env = append(os.Environ(), "ZEVUNE_BRIDGE_TEST_HELPER="+mode)
	o := Options{StartupTimeout: 3 * time.Second, RequestTimeout: timeout}
	w, err := startCommand(context.Background(), cmd, o)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := w.Close(); err != nil {
			t.Error(err)
		}
	})
	return w
}
func TestWorkerBindsAndCopies(t *testing.T) {
	w := helper(t, "valid", time.Second)
	raw := syntheticBytes(t)
	digest := PayloadDigest(raw)
	a, err := w.VerifyAuthorization(context.Background(), raw)
	if err != nil {
		t.Fatal(err)
	}
	clear(raw)
	if a.Digest() != digest {
		t.Fatal("digest")
	}
	e, err := a.Envelope()
	if err != nil {
		t.Fatal(err)
	}
	e.Proof[0] = 1
	e2, err := a.Envelope()
	if err != nil || e2.Proof[0] != 0 {
		t.Fatal("alias")
	}
}
func TestWorkerRejectionStaysUsable(t *testing.T) {
	w := helper(t, "reject", time.Second)
	for i := 0; i < 3; i++ {
		if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); !errors.Is(err, ErrRejected) {
			t.Fatal(err)
		}
	}
}
func TestWorkerResponseFailuresClose(t *testing.T) {
	for _, mode := range []string{"wrong_id", "wrong_digest", "unknown_status", "large_response", "truncated", "stdout_noise", "exit"} {
		t.Run(mode, func(t *testing.T) {
			w := helper(t, mode, time.Second)
			if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); err == nil {
				t.Fatal("accepted")
			}
			if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); !errors.Is(err, ErrClosed) {
				t.Fatal("not permanently closed", err)
			}
		})
	}
}
func TestWorkerTimeoutClosesAndReaps(t *testing.T) {
	w := helper(t, "hang", 30*time.Millisecond)
	if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); !errors.Is(err, ErrTimeout) {
		t.Fatal(err)
	}
	select {
	case <-w.done:
	case <-time.After(time.Second):
		t.Fatal("orphan")
	}
	if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); !errors.Is(err, ErrClosed) {
		t.Fatal(err)
	}
}
func TestWorkerCancellationInFlight(t *testing.T) {
	w := helper(t, "hang", time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if _, err := w.VerifyAuthorization(ctx, syntheticBytes(t)); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatal(err)
	}
	if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); !errors.Is(err, ErrClosed) {
		t.Fatal(err)
	}
}
func TestWorkerCancelledBeforeSendStaysUsable(t *testing.T) {
	w := helper(t, "valid", time.Second)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := w.VerifyAuthorization(ctx, syntheticBytes(t)); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); err != nil {
		t.Fatal(err)
	}
}
func TestWorkerConcurrentSerialRequests(t *testing.T) {
	w := helper(t, "valid", time.Second)
	raw := syntheticBytes(t)
	var wg sync.WaitGroup
	for i := 0; i < 32; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			if _, err := w.VerifyAuthorization(ctx, raw); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
}
func TestWorkerWaitingCancellation(t *testing.T) {
	w := helper(t, "valid", time.Second)
	<-w.gate
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	if _, err := w.VerifyAuthorization(ctx, syntheticBytes(t)); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatal(err)
	}
	w.gate <- struct{}{}
	if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); err != nil {
		t.Fatal(err)
	}
}
func TestWorkerCloseDuringRequest(t *testing.T) {
	w := helper(t, "hang", time.Second)
	ch := make(chan error, 1)
	go func() { _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); ch <- err }()
	time.Sleep(10 * time.Millisecond)
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-ch:
		if err == nil {
			t.Fatal("accepted close")
		}
	case <-time.After(time.Second):
		t.Fatal("blocked caller")
	}
	if err := w.Close(); err != nil {
		t.Fatal("double close", err)
	}
}
func TestWorkerInvalidEncodingNeverSent(t *testing.T) {
	w := helper(t, "valid", time.Second)
	if _, err := w.VerifyAuthorization(context.Background(), []byte("secret-invalid")); err == nil {
		t.Fatal("accepted")
	}
	if w.id != 0 {
		t.Fatal("sent malformed payload")
	}
	if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); err != nil {
		t.Fatal(err)
	}
}
func TestWorkerStderrNotReturned(t *testing.T) {
	w := helper(t, "stderr", time.Second)
	if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); err != nil {
		t.Fatal(err)
	}
}
func TestWorkerCounterOverflow(t *testing.T) {
	w := helper(t, "valid", time.Second)
	w.id = math.MaxUint64
	if _, err := w.VerifyAuthorization(context.Background(), syntheticBytes(t)); !errors.Is(err, ErrWorkerProtocol) {
		t.Fatal(err)
	}
}
func TestWorkerHandshakeErrors(t *testing.T) {
	for _, mode := range []string{"bad_hello", "large_hello", "startup_hang"} {
		t.Run(mode, func(t *testing.T) {
			cmd := exec.Command(os.Args[0], "-test.run=^TestWorkerHelper$")
			cmd.Env = append(os.Environ(), "ZEVUNE_BRIDGE_TEST_HELPER="+mode)
			w, err := startCommand(context.Background(), cmd, Options{StartupTimeout: 80 * time.Millisecond, RequestTimeout: time.Second})
			if err == nil {
				_ = w.Close()
				t.Fatal("accepted handshake")
			}
		})
	}
}
func TestWorkerStartConstraints(t *testing.T) {
	file := filepath.Join(t.TempDir(), "worker")
	if err := os.WriteFile(file, []byte("not executable"), 0600); err != nil {
		t.Fatal(err)
	}
	cases := []Options{
		{Executable: "relative"},
		{Executable: file},
		{Executable: file, ExpectedSHA256: Hash{1}},
		{Executable: t.TempDir(), ExpectedSHA256: Hash{1}},
		{Executable: file, ExpectedSHA256: Hash{1}, RequestTimeout: -1},
		{Executable: file, ExpectedSHA256: Hash{1}, StartupTimeout: 3 * time.Minute},
	}
	for i, o := range cases {
		if w, err := Start(context.Background(), o); err == nil {
			_ = w.Close()
			t.Fatal(i)
		}
	}
	sum := sha256.Sum256([]byte("not executable"))
	if w, err := Start(context.Background(), Options{Executable: file, ExpectedSHA256: sum}); err == nil {
		_ = w.Close()
		t.Fatal("executed nonexecutable")
	}
}
func TestWorkerNoCredentialEnvironment(t *testing.T) {
	t.Setenv("GITHUB_TOKEN", "sensitive-test-token")
	t.Setenv("WALLET_SECRET", "sensitive-test-key")
	env := strings.Join(workerEnvironment(), "\n")
	if strings.Contains(env, "sensitive-test") || strings.Contains(env, "GITHUB_TOKEN") || strings.Contains(env, "WALLET_SECRET") {
		t.Fatal("credentials inherited")
	}
	if !strings.Contains(env, "RAYON_NUM_THREADS=2") {
		t.Fatal("resource bound missing")
	}
}
func TestWorkerNilAndCancelledContext(t *testing.T) {
	if _, err := Start(nil, Options{}); err == nil {
		t.Fatal("nil")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := Start(ctx, Options{}); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	w := helper(t, "valid", time.Second)
	if _, err := w.VerifyAuthorization(nil, syntheticBytes(t)); err == nil {
		t.Fatal("nil")
	}
}
func TestFrameFingerprintStable(t *testing.T) {
	got := fmt.Sprintf("%x", protocolFingerprint())
	// Independently fixed in the published protocol specification and Rust test.
	const expected = "3012f3ede49b551cd131e8bae049d66f37740a5cb084052394929f9b23e43ab6"
	if got != expected {
		t.Fatalf("fingerprint drift: %s", got)
	}
}
func TestDigestIncludesAuthorizingBytes(t *testing.T) {
	raw := syntheticBytes(t)
	before := PayloadDigest(raw)
	proofOffset := HeaderSize + 2*ActionSize + 4
	raw[proofOffset] ^= 1
	if PayloadDigest(raw) == before {
		t.Fatal("proof excluded")
	}
	raw[proofOffset] ^= 1
	raw[len(raw)-1] ^= 1
	if PayloadDigest(raw) == before {
		t.Fatal("binding excluded")
	}
}
func TestRequestHeaderEncoding(t *testing.T) {
	raw := syntheticBytes(t)
	b := append([]byte(requestMagic), make([]byte, 12)...)
	binary.BigEndian.PutUint64(b[8:16], 7)
	binary.BigEndian.PutUint32(b[16:20], uint32(len(raw)))
	b = append(b, raw...)
	if !bytes.Equal(b[20:], raw) || int(binary.BigEndian.Uint32(b[16:20])) != len(raw) {
		t.Fatal("wire")
	}
}
