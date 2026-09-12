package protocol

import (
	"crypto/sha256"
	"encoding/binary"
	"errors"
)

// Version identifies the first frozen protocol domain.
const Version uint32 = 1

var ErrInvalidContext = errors.New("invalid protocol context")

// Context binds a transaction to one chain and one protocol interpretation.
type Context struct {
	ChainID             string
	GenesisDigest       [32]byte
	ValidatorSetDigest  [32]byte
	ProtocolVersion     uint32
	ActivationHeight    uint64
}

func (c Context) Valid(height uint64) error {
	if c.ChainID == "" || c.ProtocolVersion == 0 || height < c.ActivationHeight {
		return ErrInvalidContext
	}
	return nil
}

func (c Context) Digest() [32]byte {
	h := sha256.New()
	h.Write([]byte("ZEVUNE-PROTOCOL-CONTEXT-V1"))
	h.Write([]byte(c.ChainID))
	h.Write(c.GenesisDigest[:])
	h.Write(c.ValidatorSetDigest[:])
	var b [12]byte
	binary.BigEndian.PutUint32(b[:4], c.ProtocolVersion)
	binary.BigEndian.PutUint64(b[4:], c.ActivationHeight)
	h.Write(b[:])
	var out [32]byte
	copy(out[:], h.Sum(nil))
	return out
}
