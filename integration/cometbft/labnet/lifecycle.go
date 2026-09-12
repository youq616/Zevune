package labnet

import (
	"context"
	"errors"
)

var ErrNodeStopped = errors.New("local consensus engine stopped unexpectedly")

// A process must not remain apparently alive after its consensus engine exits.
// Cancellation is a requested shutdown, never evidence of network finality.
func awaitNodeStop(ctx context.Context, quit <-chan struct{}) error {
	if ctx == nil {
		return ErrBounds
	}
	select {
	case <-ctx.Done():
		return nil
	case <-quit:
		if ctx.Err() != nil {
			return nil
		}
		return ErrNodeStopped
	}
}
