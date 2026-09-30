package rpcgate

import (
	"context"
	"errors"
	"os"
	"time"
)

const ReadyRecord = "{\"gateway\":\"ready\",\"real_funds_allowed\":false}\n"
const FailureRecord = "gateway failed; no real funds permitted\n"

// WriteReady writes only through a validated pipe owner. There is NO output
// goroutine and no Close-then-wait assumption. OS/runtime write deadlines bound
// each attempt; the context bounds the whole record including partial writes.
func WriteReady(parent context.Context, out *Output) error {
	return writeRecord(parent, out, ReadyRecord, 2*time.Second)
}

// WriteFailure must never fall back to a raw inherited stderr on failure.
func WriteFailure(parent context.Context, out *Output) error {
	if writeRecord(parent, out, FailureRecord, time.Second) != nil {
		return ErrService
	}
	return nil
}

func writeRecord(parent context.Context, out *Output, record string, budget time.Duration) error {
	if parent == nil || !out.Valid() {
		return ErrReady
	}
	ctx, cancel := context.WithTimeout(parent, budget)
	defer cancel()
	remaining := []byte(record)
	for len(remaining) != 0 {
		if ctx.Err() != nil || out.file.SetWriteDeadline(streamDeadline(ctx)) != nil {
			return ErrReady
		}
		n, err := out.file.Write(remaining)
		remaining = remaining[n:]
		if err != nil && !errors.Is(err, os.ErrDeadlineExceeded) {
			return ErrReady
		}
		if n == 0 && err == nil {
			return ErrReady
		}
	}
	if ctx.Err() != nil {
		return ErrReady
	}
	return nil
}
