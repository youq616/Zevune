package rpcgate

import (
	"context"
	"io"
	"time"
)

const ReadyRecord = "{\"gateway\":\"ready\",\"real_funds_allowed\":false}\n"
const FailureRecord = "gateway failed; no real funds permitted\n"

// WriteReady owns this single write and, on timeout/cancellation, Close.
// out MUST support concurrent Close that interrupts Write (as an os.File pipe
// does). An arbitrary noninterruptible writer is not a supported adapter.
// The command supplies its exclusively owned stdout. No detached writer or
// late closer is left after return; the service caller then stops and joins.
func WriteReady(parent context.Context, out io.WriteCloser) error {
	return writeRecord(parent, out, ReadyRecord, 2*time.Second)
}

// WriteFailure uses the same interruptible output contract, after service
// cleanup, so a blocked stderr pipe cannot indefinitely retain the command.
func WriteFailure(parent context.Context, out io.WriteCloser) error {
	if writeRecord(parent, out, FailureRecord, time.Second) != nil {
		return ErrService
	}
	return nil
}

func writeRecord(parent context.Context, out io.WriteCloser, record string, budget time.Duration) error {
	if parent == nil || out == nil {
		return ErrReady
	}
	ctx, cancel := context.WithTimeout(parent, budget)
	defer cancel()
	if ctx.Err() != nil {
		return ErrReady
	}
	done := make(chan error, 1)
	go func() {
		n, err := io.WriteString(out, record)
		if n != len(record) && err == nil {
			err = io.ErrShortWrite
		}
		done <- err
	}()
	select {
	case err := <-done:
		if err != nil || ctx.Err() != nil {
			return ErrReady
		}
		return nil
	case <-ctx.Done():
		_ = out.Close()
		<-done
		return ErrReady
	}
}
