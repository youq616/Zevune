package labnet

import (
	"errors"
	"strconv"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// ErrStorageCheckpoint means the replayed tip is not the exact caller-selected
// checkpoint. It does not identify which of the two inputs is authoritative.
var ErrStorageCheckpoint = errors.New("offline journal does not match the expected checkpoint")

// StorageCheckpoint is an independently retained exact tip, not a lower bound,
// a server-supplied trust anchor, or a proof of consensus/freshness. AppHash binds
// the entire replayed laboratory state, including its pinned genesis identity.
// A newer journal also fails an older exact checkpoint: ancestry is not checked.
type StorageCheckpoint struct {
	Height  uint64
	AppHash Hash
}

func (c StorageCheckpoint) Validate() error {
	if c.Height > recordLimit || c.AppHash == (Hash{}) {
		return ErrBounds
	}
	return nil
}

// ParseStorageCheckpoint requires canonical unsigned decimal height (including
// "0") and a nonzero lower-case 32-byte hex hash. It does not read any file or
// contact a node. CLI presence is handled separately; two empty strings are not
// a checkpoint and cannot silently request an unpinned inspection here.
func ParseStorageCheckpoint(height, appHash string) (StorageCheckpoint, error) {
	if len(height) == 0 || len(height) > len(strconv.FormatUint(recordLimit, 10)) || len(appHash) != 64 {
		return StorageCheckpoint{}, ErrBounds
	}
	h, err := strconv.ParseUint(height, 10, 64)
	if err != nil || strconv.FormatUint(h, 10) != height {
		return StorageCheckpoint{}, ErrBounds
	}
	hash, err := ParseHash(appHash)
	if err != nil {
		return StorageCheckpoint{}, ErrBounds
	}
	c := StorageCheckpoint{Height: h, AppHash: hash}
	if err := c.Validate(); err != nil {
		return StorageCheckpoint{}, err
	}
	return c, nil
}

func storageReportAtCheckpoint(s poolbridge.Summary, size int64, expected *StorageCheckpoint) (StorageReport, error) {
	if expected != nil {
		if err := expected.Validate(); err != nil {
			return StorageReport{}, err
		}
		if s.Height != expected.Height || s.AppHash != expected.AppHash {
			// Never emit a partial capacity/success report for the wrong tip.
			return StorageReport{}, ErrStorageCheckpoint
		}
	}
	report, err := storageReport(s, size)
	if err != nil {
		return StorageReport{}, err
	}
	report.ExpectedCheckpointMatched = expected != nil
	return report, nil
}
