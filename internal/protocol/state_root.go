package protocol

import (
	"crypto/sha256"
	"encoding/binary"
)

// StateRoot commits the deterministic state components used by protocol v1.
// It is intentionally independent from any storage implementation.
type StateRoot struct {
	OrchardRoot   [32]byte
	NullifierRoot [32]byte
	ValidatorRoot [32]byte
	Height        uint64
}

func (s StateRoot) Digest() [32]byte {
	h := sha256.New()
	h.Write([]byte("ZEVUNE-STATE-ROOT-V1"))
	h.Write(s.OrchardRoot[:])
	h.Write(s.NullifierRoot[:])
	h.Write(s.ValidatorRoot[:])
	var height [8]byte
	binary.BigEndian.PutUint64(height[:], s.Height)
	h.Write(height[:])
	var out [32]byte
	copy(out[:], h.Sum(nil))
	return out
}
