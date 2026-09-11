// Package poolbridge owns a local, bounded, public-data-only durable Orchard
// worker. A failed Commit exchange is uncertain and is NEVER automatically retried.
package poolbridge

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

const Network = "zevune-orchard-lab-1"
const MaxTransactions = 16
const MaxTransactionBytes = 28102
const maxFrame = 524288
const domain = "ZEVUNE-POOL-IPC-1:zevune-orchard-lab-1:16:28102"

type Hash = [32]byte

var (
	ErrBounds      = errors.New("pool protocol bounds")
	ErrRejected    = errors.New("pool state transition rejected")
	ErrUnavailable = errors.New("pool worker unavailable; commit outcome may be uncertain")
	ErrProtocol    = errors.New("pool worker response mismatch")
	ErrClosed      = errors.New("pool worker closed")
)

type Summary struct {
	Height      uint64 `json:"height"`
	AppHash     Hash   `json:"app_hash"`
	Root        Hash   `json:"root"`
	Commitments uint64 `json:"commitments"`
	Nullifiers  uint64 `json:"nullifiers"`
	Fees        uint64 `json:"fees"`
}

// A checkpoint requires independently trusted consensus state, not a peer hash.
func (s Summary) Checkpoint(height uint64, hash Hash) error {
	if s.Height != height || s.AppHash != hash {
		return ErrRejected
	}
	return nil
}

type Options struct {
	Executable        string
	ExpectedSHA256    Hash
	TestGenesis       string
	TestGenesisSHA256 Hash
	Journal           string
	Create            bool // Reopen NEVER creates missing files.
	StartupTimeout    time.Duration
	RequestTimeout    time.Duration
}
type Client struct {
	cmd     *exec.Cmd
	in      io.WriteCloser
	out     io.ReadCloser
	done    chan struct{}
	stopped chan struct{}
	gate    chan struct{}
	once    sync.Once
	timeout time.Duration
	id      uint64
}

func Start(ctx context.Context, o Options) (*Client, error) {
	if ctx == nil {
		return nil, ErrBounds
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if o.StartupTimeout == 0 {
		o.StartupTimeout = 60 * time.Second
	}
	if o.RequestTimeout == 0 {
		o.RequestTimeout = 20 * time.Second
	}
	if o.StartupTimeout < time.Millisecond || o.StartupTimeout > 5*time.Minute || o.RequestTimeout < time.Millisecond || o.RequestTimeout > time.Minute {
		return nil, ErrBounds
	}
	if !filepath.IsAbs(o.Executable) || !filepath.IsAbs(o.Journal) || o.ExpectedSHA256 == (Hash{}) {
		return nil, ErrBounds
	}
	fi, err := os.Lstat(o.Executable)
	if err != nil || !fi.Mode().IsRegular() || fi.Size() < 1 || fi.Size() > 512<<20 {
		return nil, ErrBounds
	}
	f, err := os.Open(o.Executable)
	if err != nil {
		return nil, ErrUnavailable
	}
	h := sha256.New()
	n, er := io.Copy(h, io.LimitReader(f, fi.Size()+1))
	ce := f.Close()
	if er != nil || ce != nil || n != fi.Size() || !bytes.Equal(h.Sum(nil), o.ExpectedSHA256[:]) {
		return nil, ErrBounds
	}
	// Digest checking is not a sandbox or a defense against a malicious local OS.
	mode := "open"
	if o.Create {
		mode = "create"
	}
	args, err := o.workerArgs(mode)
	if err != nil {
		return nil, err
	}
	cmd := exec.Command(o.Executable, args...)
	cmd.Dir = filepath.Dir(o.Executable)
	cmd.Env = []string{"RAYON_NUM_THREADS=2"}
	for _, entry := range os.Environ() {
		name, _, ok := strings.Cut(entry, "=")
		if ok && (strings.EqualFold(name, "SYSTEMROOT") || strings.EqualFold(name, "WINDIR") || strings.EqualFold(name, "TEMP") || strings.EqualFold(name, "TMP")) {
			cmd.Env = append(cmd.Env, entry)
		}
	}
	return start(ctx, cmd, o)
}
func start(ctx context.Context, cmd *exec.Cmd, o Options) (*Client, error) {
	in, err := cmd.StdinPipe()
	if err != nil {
		return nil, ErrUnavailable
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		_ = in.Close()
		return nil, ErrUnavailable
	}
	cmd.Stderr = io.Discard
	if err = cmd.Start(); err != nil {
		_ = in.Close()
		_ = out.Close()
		return nil, ErrUnavailable
	}
	c := &Client{cmd: cmd, in: in, out: out, done: make(chan struct{}), stopped: make(chan struct{}), gate: make(chan struct{}, 1), timeout: o.RequestTimeout}
	c.gate <- struct{}{}
	go func() { _ = cmd.Wait(); close(c.done) }()
	ready := make(chan error, 1)
	go func() {
		b, e := readFrame(out, 40)
		fp := sha256.Sum256([]byte(domain))
		if e == nil && (len(b) != 40 || string(b[:8]) != "ZVPLHEL1" || !bytes.Equal(b[8:], fp[:])) {
			e = ErrProtocol
		}
		ready <- e
	}()
	timer := time.NewTimer(o.StartupTimeout)
	defer timer.Stop()
	select {
	case err = <-ready:
		if err == nil {
			err = ctx.Err()
		}
		if err == nil {
			return c, nil
		}
	case <-ctx.Done():
		err = ctx.Err()
	case <-timer.C:
		err = context.DeadlineExceeded
	}
	_ = c.Close()
	return nil, errors.Join(ErrUnavailable, err)
}
func readFrame(r io.Reader, limit int) ([]byte, error) {
	var b [4]byte
	if _, e := io.ReadFull(r, b[:]); e != nil {
		return nil, e
	}
	n := binary.BigEndian.Uint32(b[:])
	if n == 0 || uint64(n) > uint64(limit) {
		return nil, ErrBounds
	}
	out := make([]byte, int(n))
	_, e := io.ReadFull(r, out)
	return out, e
}
func writeAll(w io.Writer, b []byte) error {
	for len(b) > 0 {
		n, e := w.Write(b)
		if n < 0 || n > len(b) {
			return ErrProtocol
		}
		if e != nil {
			return e
		}
		if n == 0 {
			return io.ErrShortWrite
		}
		b = b[n:]
	}
	return nil
}
func writeFrame(w io.Writer, b []byte) error {
	if len(b) == 0 || len(b) > maxFrame {
		return ErrBounds
	}
	var p [4]byte
	binary.BigEndian.PutUint32(p[:], uint32(len(b)))
	if e := writeAll(w, p[:]); e != nil {
		return e
	}
	return writeAll(w, b)
}
func decodeSummary(b []byte) (Summary, error) {
	var s Summary
	if len(b) != 96 {
		return s, ErrProtocol
	}
	s.Height = binary.BigEndian.Uint64(b[:8])
	copy(s.AppHash[:], b[8:40])
	copy(s.Root[:], b[40:72])
	s.Commitments = binary.BigEndian.Uint64(b[72:80])
	s.Nullifiers = binary.BigEndian.Uint64(b[80:88])
	s.Fees = binary.BigEndian.Uint64(b[88:96])
	if s.Height > 10000 || s.Commitments > 65536 || s.Nullifiers > 65536 {
		return Summary{}, ErrProtocol
	}
	return s, nil
}
func BlockBytes(height uint64, hash Hash, txs [][]byte) ([]byte, error) {
	if height == 0 || height > 10000 || hash == (Hash{}) || len(txs) > MaxTransactions {
		return nil, ErrBounds
	}
	b := make([]byte, 42)
	binary.BigEndian.PutUint64(b[:8], height)
	copy(b[8:40], hash[:])
	binary.BigEndian.PutUint16(b[40:42], uint16(len(txs)))
	for _, tx := range txs {
		if len(tx) == 0 || len(tx) > MaxTransactionBytes {
			return nil, ErrBounds
		}
		var p [4]byte
		binary.BigEndian.PutUint32(p[:], uint32(len(tx)))
		b = append(b, p[:]...)
		b = append(b, tx...)
	}
	return b, nil
}
func (c *Client) exchange(ctx context.Context, op byte, payload []byte) (Summary, error) {
	if ctx == nil || op > 4 || len(payload) > maxFrame-17 {
		return Summary{}, ErrBounds
	}
	if e := ctx.Err(); e != nil {
		return Summary{}, e
	}
	select {
	case <-ctx.Done():
		return Summary{}, ctx.Err()
	case <-c.stopped:
		return Summary{}, ErrClosed
	case <-c.gate:
	}
	defer func() { c.gate <- struct{}{} }()
	select {
	case <-c.stopped:
		return Summary{}, ErrClosed
	default:
	}
	if e := ctx.Err(); e != nil {
		return Summary{}, e
	}
	if c.id == math.MaxUint64 {
		_ = c.Close()
		return Summary{}, ErrProtocol
	}
	c.id++
	b := make([]byte, 17, len(payload)+17)
	copy(b, "ZVPLREQ1")
	binary.BigEndian.PutUint64(b[8:16], c.id)
	b[16] = op
	b = append(b, payload...)
	expected := sha256.Sum256(b)
	type reply struct {
		b []byte
		e error
	}
	ch := make(chan reply, 1)
	go func() {
		e := writeFrame(c.in, b)
		var out []byte
		if e == nil {
			out, e = readFrame(c.out, 145)
		}
		ch <- reply{out, e}
	}()
	timer := time.NewTimer(c.timeout)
	defer timer.Stop()
	var r reply
	select {
	case r = <-ch:
	case <-ctx.Done():
		_ = c.Close()
		return Summary{}, errors.Join(ErrUnavailable, ctx.Err())
	case <-timer.C:
		_ = c.Close()
		return Summary{}, errors.Join(ErrUnavailable, context.DeadlineExceeded)
	case <-c.stopped:
		return Summary{}, ErrUnavailable
	}
	if r.e != nil {
		_ = c.Close()
		return Summary{}, ErrUnavailable
	}
	b = r.b
	if len(b) != 145 || string(b[:8]) != "ZVPLRSP1" || binary.BigEndian.Uint64(b[8:16]) != c.id || b[16] > 1 || !bytes.Equal(b[17:49], expected[:]) {
		_ = c.Close()
		return Summary{}, ErrProtocol
	}
	s, e := decodeSummary(b[49:])
	if e != nil {
		_ = c.Close()
		return Summary{}, e
	}
	if e = ctx.Err(); e != nil {
		_ = c.Close()
		return Summary{}, errors.Join(ErrUnavailable, e)
	}
	select {
	case <-c.stopped:
		return Summary{}, ErrUnavailable
	default:
	}
	if b[16] == 1 {
		return Summary{}, ErrRejected
	}
	return s, nil
}
func (c *Client) Status(ctx context.Context) (Summary, error) { return c.exchange(ctx, 0, nil) }
func (c *Client) Check(ctx context.Context, tx []byte) error {
	if len(tx) == 0 || len(tx) > MaxTransactionBytes {
		return ErrBounds
	}
	_, e := c.exchange(ctx, 4, tx)
	return e
}
func (c *Client) Preview(ctx context.Context, height uint64, hash Hash, txs [][]byte) (Summary, error) {
	b, e := BlockBytes(height, hash, txs)
	if e != nil {
		return Summary{}, e
	}
	return c.exchange(ctx, 1, b)
}
func (c *Client) Finalize(ctx context.Context, height uint64, hash Hash, txs [][]byte) (Summary, Hash, error) {
	b, e := BlockBytes(height, hash, txs)
	if e != nil {
		return Summary{}, Hash{}, e
	}
	tag := sha256.Sum256(b)
	s, e := c.exchange(ctx, 2, b)
	return s, tag, e
}
func (c *Client) Commit(ctx context.Context, tag Hash) (Summary, error) {
	return c.exchange(ctx, 3, tag[:])
}

// Close never removes data or retries an unacknowledged state transition.
func (c *Client) Close() error {
	if c == nil {
		return nil
	}
	c.once.Do(func() {
		close(c.stopped)
		_ = c.in.Close()
		_ = c.out.Close()
		if c.cmd.Process != nil {
			_ = c.cmd.Process.Kill()
		}
	})
	select {
	case <-c.done:
		return nil
	case <-time.After(5 * time.Second):
		return ErrUnavailable
	}
}
