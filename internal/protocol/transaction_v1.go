package protocol

import (
	"crypto/sha256"
	"encoding/binary"
	"errors"
)

var ErrInvalidTransactionV1 = errors.New("invalid transaction v1")

// TransactionV1 binds a transaction envelope to a single protocol domain.
// Shielded payload validation remains delegated to the Orchard layer.
type TransactionV1 struct {
	Context      Context
	ExpiryHeight uint64
	Fee          uint64
	Payload      []byte
	Signature    []byte
}

func (t TransactionV1) SigningDigest() [32]byte {
	h := sha256.New()
	h.Write([]byte("ZEVUNE-TX-V1"))
	ctx := t.Context.Digest()
	h.Write(ctx[:])
	var b [8]byte
	binary.BigEndian.PutUint64(b[:], t.ExpiryHeight)
	h.Write(b[:])
	binary.BigEndian.PutUint64(b[:], t.Fee)
	h.Write(b[:])
	h.Write(t.Payload)
	return sha256.Sum256(h.Sum(nil))
}

func (t TransactionV1) Valid(height uint64) error {
	if t.Context.ChainID == "" || t.Context.ProtocolVersion == 0 {
		return ErrInvalidTransactionV1
	}
	if len(t.Payload) == 0 {
		return ErrInvalidTransactionV1
	}
	if t.ExpiryHeight != 0 && height > t.ExpiryHeight {
		return ErrInvalidTransactionV1
	}
	return nil
}
