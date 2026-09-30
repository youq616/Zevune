package gatetest

import (
	"errors"
	"io"
	"os"
	"time"
)

// Saturate establishes a real full-pipe precondition without a reader or a
// detached writer. Call only with an exclusively owned, deadline-capable test
// write endpoint while the opposite endpoint is open and is NOT being read.
//
// An oversized pending write that times out can be canceled without retaining
// its bytes (notably on Windows). A timeout alone therefore does not establish
// fullness. Retain completed small writes, then finish with single-byte writes
// until a fresh, nonexpired deadline blocks even one byte. Return only after
// that I/O completes, and clear the deadline before handing the file to a child.
// This is test setup, not a production gateway capability.
func Saturate(w *os.File) (written int, err error) {
	if w == nil {
		return 0, errors.New("missing test pipe")
	}
	stat, err := w.Stat()
	if err != nil || stat.Mode()&os.ModeNamedPipe == 0 {
		return 0, errors.New("test saturation requires a pipe")
	}
	if err = w.SetWriteDeadline(time.Time{}); err != nil {
		return 0, err
	}
	defer func() {
		if reset := w.SetWriteDeadline(time.Time{}); reset != nil && err == nil {
			err = reset
		}
	}()
	const maxBytes = 1024 * 1024
	const attemptBudget = 100 * time.Millisecond
	end := time.Now().Add(2 * time.Second)
	var block [4096]byte
	size := len(block)
	for written < maxBytes {
		until := time.Now().Add(attemptBudget)
		if until.After(end) {
			return written, errors.New("test saturation budget exceeded")
		}
		if err = w.SetWriteDeadline(until); err != nil {
			return written, err
		}
		// Never count a call made after an already-expired deadline as proof of
		// backpressure; a descheduled fixture must fail instead of false-pass.
		if !time.Now().Before(until) {
			return written, errors.New("test saturation deadline expired before write")
		}
		n, writeErr := w.Write(block[:size])
		written += n
		if errors.Is(writeErr, os.ErrDeadlineExceeded) {
			if size == 1 && n == 0 {
				if written == 0 {
					return 0, errors.New("no completed test pipe writes")
				}
				return written, nil
			}
			size = 1 // a failed large write need not mean a small record is blocked
			continue
		}
		if writeErr != nil {
			return written, writeErr
		}
		if n != size {
			return written, io.ErrShortWrite
		}
	}
	return written, errors.New("test pipe exceeded saturation byte bound")
}
