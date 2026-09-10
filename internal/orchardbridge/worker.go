package orchardbridge

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"io"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

var (
	ErrExecutable  = errors.New("unapproved Orchard worker executable")
	ErrUnavailable = errors.New("Orchard worker unavailable; authorization not established")
	ErrRejected    = errors.New("Orchard cryptographic authorization rejected")
	ErrTimeout     = errors.New("Orchard worker deadline exceeded; authorization not established")
	ErrClosed      = errors.New("Orchard worker closed")
)

// Options pins a local executable by SHA-256. Obtain the expected digest from a
// trusted build manifest, NOT from an untrusted transaction or remote peer.
// Hash checking is integrity checking, not signing, attestation, or an audit.
type Options struct {
	Executable     string
	ExpectedSHA256 Hash
	StartupTimeout time.Duration
	RequestTimeout time.Duration
}

func (o Options) normalize() (Options, error) {
	if o.StartupTimeout == 0 {
		o.StartupTimeout = 30 * time.Second
	}
	if o.RequestTimeout == 0 {
		o.RequestTimeout = 10 * time.Second
	}
	if o.StartupTimeout < time.Millisecond || o.StartupTimeout > 2*time.Minute ||
		o.RequestTimeout < time.Millisecond || o.RequestTimeout > time.Minute {
		return o, ErrBounds
	}
	return o, nil
}

// Worker is serialized and bounded, keeps the upstream verifying key warm, and
// never retries an uncertain exchange. Timeout, EOF, malformed response or
// response-binding failure permanently close the instance. Start a fresh worker
// explicitly after investigating; there is no success-on-error fallback.
type Worker struct {
	cmd            *exec.Cmd
	in             io.WriteCloser
	out            io.ReadCloser
	done           chan struct{}
	stopped        chan struct{}
	gate           chan struct{}
	once           sync.Once
	requestTimeout time.Duration
	id             uint64
}

// Start never invokes a shell, accepts no extra arguments, and does not forward
// credential variables. The local OS, executable directory and administrator
// remain trusted; pre-exec hash checking does not defeat a malicious local OS.
func Start(ctx context.Context, o Options) (*Worker, error) {
	var err error
	if ctx == nil {
		return nil, ErrPolicy
	}
	if err = ctx.Err(); err != nil {
		return nil, err
	}
	o, err = o.normalize()
	if err != nil {
		return nil, err
	}
	if !filepath.IsAbs(o.Executable) || o.ExpectedSHA256 == (Hash{}) {
		return nil, ErrExecutable
	}
	info, err := os.Lstat(o.Executable)
	if err != nil || !info.Mode().IsRegular() || info.Size() <= 0 || info.Size() > 512<<20 {
		return nil, ErrExecutable
	}
	f, err := os.Open(o.Executable)
	if err != nil {
		return nil, ErrExecutable
	}
	h := sha256.New()
	n, readErr := io.Copy(h, io.LimitReader(f, info.Size()+1))
	closeErr := f.Close()
	if readErr != nil || closeErr != nil || n != info.Size() || !bytes.Equal(h.Sum(nil), o.ExpectedSHA256[:]) {
		return nil, ErrExecutable
	}
	cmd := exec.Command(o.Executable)
	// The executable runs outside the repository working directory. This is not
	// a sandbox and does not defend against malicious preapproved binaries.
	cmd.Dir = filepath.Dir(o.Executable)
	cmd.Env = workerEnvironment()
	return startCommand(ctx, cmd, o)
}

func workerEnvironment() []string {
	env := []string{"RAYON_NUM_THREADS=2"}
	for _, name := range []string{"SYSTEMROOT", "WINDIR", "TEMP", "TMP"} {
		for _, entry := range os.Environ() {
			key, _, found := strings.Cut(entry, "=")
			if found && strings.EqualFold(key, name) {
				env = append(env, entry)
				break
			}
		}
	}
	return env
}

func startCommand(ctx context.Context, cmd *exec.Cmd, o Options) (*Worker, error) {
	in, err := cmd.StdinPipe()
	if err != nil {
		return nil, ErrUnavailable
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		_ = in.Close()
		return nil, ErrUnavailable
	}
	// Never collect/return child diagnostics: this prevents accidental echoing of
	// untrusted payloads or secrets into parent reports. No child controls logs.
	cmd.Stderr = io.Discard
	if err = cmd.Start(); err != nil {
		_ = in.Close()
		_ = out.Close()
		return nil, ErrUnavailable
	}
	w := &Worker{cmd: cmd, in: in, out: out, done: make(chan struct{}), stopped: make(chan struct{}),
		gate: make(chan struct{}, 1), requestTimeout: o.RequestTimeout}
	w.gate <- struct{}{}
	go func() { _ = cmd.Wait(); close(w.done) }()
	ready := make(chan error, 1)
	go func() {
		b, er := readFrame(out, 40)
		fp := protocolFingerprint()
		if er == nil && (len(b) != 40 || string(b[:8]) != helloMagic || !bytes.Equal(b[8:], fp[:])) {
			er = ErrWorkerProtocol
		}
		ready <- er
	}()
	t := time.NewTimer(o.StartupTimeout)
	defer t.Stop()
	select {
	case err = <-ready:
		if err == nil {
			if err = ctx.Err(); err == nil {
				return w, nil
			}
		}
		_ = w.Close()
		return nil, errors.Join(ErrUnavailable, err)
	case <-ctx.Done():
		_ = w.Close()
		return nil, ctx.Err()
	case <-t.C:
		_ = w.Close()
		return nil, ErrTimeout
	}
}

// Authorization is only cryptographic authorization under the experimental
// format. It proves neither committed membership nor absence of previous spends.
// This type is deliberately NOT a consensus or ledger commit receipt.
type Authorization struct {
	raw    []byte
	digest Hash
}

func (a Authorization) Digest() Hash                 { return a.digest }
func (a Authorization) Envelope() (*Envelope, error) { return Decode(a.raw) }

// VerifyAuthorization may be called concurrently. Waiting callers honor their
// own contexts; only one request can be in flight per worker. Callers must not
// concurrently mutate raw during this call (the standard Go ownership rule).
func (w *Worker) VerifyAuthorization(ctx context.Context, raw []byte) (Authorization, error) {
	if ctx == nil {
		return Authorization{}, ErrPolicy
	}
	if err := ctx.Err(); err != nil {
		return Authorization{}, err
	}
	if _, err := Decode(raw); err != nil {
		return Authorization{}, err
	}
	owned := bytes.Clone(raw)
	select {
	case <-ctx.Done():
		return Authorization{}, ctx.Err()
	case <-w.stopped:
		return Authorization{}, ErrClosed
	case <-w.gate:
	}
	defer func() { w.gate <- struct{}{} }()
	select {
	case <-w.stopped:
		return Authorization{}, ErrClosed
	default:
	}
	if err := ctx.Err(); err != nil {
		return Authorization{}, err
	}
	if w.id == math.MaxUint64 {
		_ = w.Close()
		return Authorization{}, ErrWorkerProtocol
	}
	w.id++
	id := w.id
	digest := PayloadDigest(owned)
	request := append([]byte(requestMagic), make([]byte, 12)...)
	binary.BigEndian.PutUint64(request[8:16], id)
	binary.BigEndian.PutUint32(request[16:20], uint32(len(owned)))
	request = append(request, owned...)
	type result struct {
		raw []byte
		err error
	}
	ch := make(chan result, 1)
	go func() {
		err := writeFrame(w.in, request)
		var b []byte
		if err == nil {
			b, err = readFrame(w.out, responseSize)
		}
		ch <- result{b, err}
	}()
	t := time.NewTimer(w.requestTimeout)
	defer t.Stop()
	var r result
	select {
	case r = <-ch:
	case <-ctx.Done():
		_ = w.Close()
		return Authorization{}, ctx.Err()
	case <-t.C:
		_ = w.Close()
		return Authorization{}, ErrTimeout
	case <-w.stopped:
		return Authorization{}, ErrClosed
	}
	if r.err != nil {
		_ = w.Close()
		return Authorization{}, ErrUnavailable
	}
	b := r.raw
	if len(b) != responseSize || string(b[:8]) != responseMagic || binary.BigEndian.Uint64(b[8:16]) != id || !bytes.Equal(b[17:], digest[:]) || b[16] > 1 {
		_ = w.Close()
		return Authorization{}, ErrWorkerProtocol
	}
	if b[16] == 1 {
		return Authorization{}, ErrRejected
	}
	if err := ctx.Err(); err != nil {
		_ = w.Close()
		return Authorization{}, err
	}
	select {
	case <-w.stopped:
		return Authorization{}, ErrClosed
	default:
	}
	return Authorization{raw: owned, digest: digest}, nil
}

// Close terminates the owned child and reaps it. It never deletes data or keys.
// A close during an uncertain request is not reported as successful verification.
func (w *Worker) Close() error {
	if w == nil {
		return nil
	}
	w.once.Do(func() {
		close(w.stopped)
		_ = w.in.Close()
		_ = w.out.Close()
		if w.cmd.Process != nil {
			_ = w.cmd.Process.Kill()
		}
	})
	select {
	case <-w.done:
		return nil
	case <-time.After(5 * time.Second):
		return ErrTimeout
	}
}
