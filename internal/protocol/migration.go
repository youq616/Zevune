package protocol

import "errors"

var ErrInvalidMigration = errors.New("invalid protocol migration")

// Migration defines a deterministic protocol transition.
// The migration hash identifies the exact transition logic.
type Migration struct {
	FromVersion uint32
	ToVersion   uint32
	Height      uint64
	Hash        [32]byte
}

func (m Migration) Validate() error {
	if m.FromVersion == 0 || m.ToVersion <= m.FromVersion || m.Height == 0 {
		return ErrInvalidMigration
	}
	if m.Hash == ([32]byte{}) {
		return ErrInvalidMigration
	}
	return nil
}
