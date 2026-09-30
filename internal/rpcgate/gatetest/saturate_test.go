package gatetest

import (
	"errors"
	"io"
	"os"
	"testing"
	"time"
)

func TestSaturateRetainsBytesAndBlocksSmallRecord(t *testing.T) {
	r, w, err := Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	defer w.Close()
	written, err := Saturate(w)
	if err != nil || written <= 0 {
		t.Fatal("saturation not established", written, err)
	}
	// Verify the exact problematic size class BEFORE any read. Reaching this
	// assertion with an empty pipe (after canceling one large Write) must fail.
	record := []byte("{\"gateway\":\"ready\",\"real_funds_allowed\":false}\n")
	if err := w.SetWriteDeadline(time.Now().Add(100 * time.Millisecond)); err != nil {
		t.Fatal(err)
	}
	if n, err := w.Write(record); n != 0 || !errors.Is(err, os.ErrDeadlineExceeded) {
		t.Fatal("small record not blocked", n, err)
	}
	w.Close()
	raw, err := io.ReadAll(r)
	if err != nil || len(raw) < written {
		t.Fatal("completed fill bytes were not retained", len(raw), written, err)
	}
	t.Logf("completed_fill_bytes=%d retained_bytes=%d; small record blocked before drain", written, len(raw))
}

func TestSaturateRejectsMissingClosedAndNonPipe(t *testing.T) {
	if _, err := Saturate(nil); err == nil {
		t.Fatal("nil pipe accepted")
	}
	f, err := os.CreateTemp(t.TempDir(), "not-a-pipe-")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if _, err := Saturate(f); err == nil {
		t.Fatal("regular file accepted")
	}
	stat, err := f.Stat()
	if err != nil || stat.Size() != 0 {
		t.Fatal("non-pipe modified")
	}
	r, w, err := Pipe()
	if err != nil {
		t.Fatal(err)
	}
	r.Close()
	w.Close()
	if _, err := Saturate(w); err == nil {
		t.Fatal("closed pipe accepted")
	}
}
