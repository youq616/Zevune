package rpcgate

import (
	"context"
	"errors"
	"io"
	"os"
	"time"
)

const streamPoll = 50 * time.Millisecond

// Input and Output are exclusive, deadline-capable pipe owners, not arbitrary
// Read/WriteClosers. Their files are never exposed. Do not copy these values or
// use/close them concurrently. Close only after the operation has returned.
// The CLI joins its one input watcher before closing Input; output has no worker.
type Input struct{ file *os.File }
type Output struct{ file *os.File }

// OpenInput consumes f on BOTH success and failure. No other task/process may
// operate on the transferred pipe endpoint (the opposite endpoint is separate).
// Unsupported files fail before any Read/Write. See platform implementations.
func OpenInput(f *os.File) (*Input, error) {
	p, err := prepareStream(f, true)
	if err != nil {
		return nil, ErrConfiguration
	}
	return &Input{file: p}, nil
}

// OpenOutput has the same ownership contract as OpenInput. There is no fallback
// to synchronous inherited stdout/stderr, a terminal or an arbitrary Writer.
func OpenOutput(f *os.File) (*Output, error) {
	p, err := prepareStream(f, false)
	if err != nil {
		return nil, ErrConfiguration
	}
	return &Output{file: p}, nil
}

func prepareStream(f *os.File, read bool) (*os.File, error) {
	if f == nil {
		return nil, ErrConfiguration
	}
	defer f.Close()
	stat, err := f.Stat()
	if err != nil || stat.Mode()&os.ModeNamedPipe == 0 {
		return nil, ErrConfiguration
	}
	p, err := streamPipe(f, read)
	if err != nil {
		return nil, ErrConfiguration
	}
	// A descriptor's interface/name does not establish cancellation capability.
	// streamPipe establishes nonblocking/overlapped mode; deadlines must ALSO
	// work, or the descriptor is rejected before a task/listener can start.
	if read {
		err = p.SetReadDeadline(time.Time{})
	} else {
		err = p.SetWriteDeadline(time.Time{})
	}
	if err != nil {
		p.Close()
		return nil, ErrConfiguration
	}
	return p, nil
}

func (in *Input) Close() error {
	if in == nil || in.file == nil {
		return nil
	}
	return in.file.Close()
}
func (out *Output) Close() error {
	if out == nil || out.file == nil {
		return nil
	}
	return out.file.Close()
}

// Valid reports whether this exclusively owned output still supports deadlines.
// Used before starting the service. It does not promise that the reader is alive.
func (out *Output) Valid() bool {
	return out != nil && out.file != nil && out.file.SetWriteDeadline(time.Time{}) == nil
}

// UntilEOF discards input until EOF/error/cancellation. Each real read has a
// short OS/runtime deadline; cancellation does not depend on Close interrupting
// a blocking descriptor. No I/O is delegated to an unjoined goroutine.
func (in *Input) UntilEOF(ctx context.Context) error {
	if ctx == nil || in == nil || in.file == nil {
		return ErrConfiguration
	}
	var buf [256]byte
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		if err := in.file.SetReadDeadline(streamDeadline(ctx)); err != nil {
			return ErrService
		}
		n, err := in.file.Read(buf[:])
		if err == io.EOF {
			return nil
		}
		if err != nil && !errors.Is(err, os.ErrDeadlineExceeded) {
			return ErrService
		}
		if n == 0 && err == nil {
			return ErrService
		}
	}
}

func streamDeadline(ctx context.Context) time.Time {
	end := time.Now().Add(streamPoll)
	if d, ok := ctx.Deadline(); ok && d.Before(end) {
		return d
	}
	return end
}
