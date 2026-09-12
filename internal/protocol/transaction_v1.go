package protocol

import (
	"crypto/sha256"
	"encoding/binary"
	"errors"
)

var ErrInvalidTransactionV1 = errors.New("invalid transaction v1")

type TransactionV1 struct {
	ContextDigest [32]byte
	ExpiryHeight uint64
	Fee uint64
	Payload []byte
	Signature []byte
}

func (t TransactionV1) SigningDigest() [32]byte {
	h := sha256.New()
	h.Write([]byte("ZEVUNE-TX-V1"))
	h.Write(t.ContextDigest[:])
	var b [8]byte
	binary.BigEndian.PutUint64(b[:], t.ExpiryHeight)
	h.Write(b[:])
	binary.BigEndian.PutUint64(b[:], t.Fee)
	h.Write(b[:])
	h.Write(t.Payload)
	return sha256.Sum256(h.Sum(nil))
}

func (t TransactionV1) Valid(height uint64) error {
	if t.ContextDigest == ([32]byte{}) || len(t.Payload) == 0 || height > t.ExpiryHeight {
		return ErrInvalidTransactionV1
	}
	return nil
}
