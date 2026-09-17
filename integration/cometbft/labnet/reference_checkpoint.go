package labnet

import (
	"context"

	"github.com/youq616/Zevune/internal/poolbridge"
)

func validateReferenceCheckpoint(o SyncOptions, expected *StorageCheckpoint) error {
	return (&Network{}).validateReferenceCheckpoint(o, expected)
}

func (n *Network) validateReferenceCheckpoint(o SyncOptions, expected *StorageCheckpoint) error {
	if n == nil {
		return ErrBounds
	}
	if expected == nil {
		return nil
	}
	if o.Create {
		return ErrBounds
	}
	return n.ValidateStorageCheckpoint(*expected)
}

// This runs on the worker that will execute the sync, after genuine replay and
// acquisition of its exclusive file lock, but before the first remote request.
// Caller-provided checkpoint values are never inferred from this journal.
func checkReferenceCheckpoint(ctx context.Context, store *poolbridge.Client, expected *StorageCheckpoint) error {
	if expected == nil {
		return nil
	}
	state, err := store.Status(ctx)
	if err != nil {
		return err
	}
	if state.Height != expected.Height || state.AppHash != expected.AppHash {
		return ErrStorageCheckpoint
	}
	return ctx.Err()
}
