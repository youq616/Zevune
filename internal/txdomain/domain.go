// Package txdomain defines candidate, explicitly NOT activated domain-bound
// transactions. Structural decoding never verifies proofs, signatures or state.
package txdomain

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"math"

	"github.com/youq616/Zevune/internal/orchardbridge"
)

const (
	DomainSize                = 79
	PrefixSize                = 40
	MaxTransactionSize        = PrefixSize + orchardbridge.MaxEnvelopeSize
	domainMagic               = "ZVDOM001"
	transactionMagic          = "ZVTXB001"
	suite              uint16 = 1
)

type Kind uint8

const (
	Development Kind = 1
	Test        Kind = 2
)

type Hash = [32]byte

var (
	ErrEncoding = errors.New("invalid candidate protocol encoding")
	ErrDomain   = errors.New("candidate transaction domain mismatch")
	ErrMetadata = errors.New("invalid candidate signing metadata")
)

// Domain holds a public, independently authenticated descriptor. Private fields
// prevent mutation of validated descriptors. The zero value is always rejected.
type Domain struct{ raw [DomainSize]byte }

func New(kind Kind, genesis, rules Hash, epoch uint32) (Domain, error) {
	if (kind != Development && kind != Test) || genesis == (Hash{}) || rules == (Hash{}) || epoch == 0 {
		return Domain{}, ErrDomain
	}
	var d Domain
	copy(d.raw[:8], domainMagic)
	d.raw[8] = byte(kind)
	copy(d.raw[9:41], genesis[:])
	copy(d.raw[41:73], rules[:])
	binary.BigEndian.PutUint32(d.raw[73:77], epoch)
	binary.BigEndian.PutUint16(d.raw[77:79], suite)
	return d, nil
}

func DecodeDomain(raw []byte) (Domain, error) {
	if len(raw) != DomainSize || string(raw[:8]) != domainMagic || binary.BigEndian.Uint16(raw[77:79]) != suite {
		return Domain{}, ErrEncoding
	}
	var genesis, rules Hash
	copy(genesis[:], raw[9:41])
	copy(rules[:], raw[41:73])
	return New(Kind(raw[8]), genesis, rules, binary.BigEndian.Uint32(raw[73:77]))
}
func (d Domain) Bytes() ([]byte, error) {
	if _, err := DecodeDomain(d.raw[:]); err != nil {
		return nil, err
	}
	return bytes.Clone(d.raw[:]), nil
}
func (d Domain) ID() (Hash, error) {
	raw, err := d.Bytes()
	if err != nil {
		return Hash{}, err
	}
	h := sha256.New()
	h.Write([]byte("ZEVUNE-DOMAIN\x00\x01"))
	h.Write(raw)
	var result Hash
	copy(result[:], h.Sum(nil))
	return result, nil
}

// DigestForCommitment reproduces ONLY the candidate transcript. Computing the
// correct Orchard V5 bundle commitment requires the real upstream implementation.
// Receiving 32 bytes from a peer does not authenticate that commitment.
func (d Domain) DigestForCommitment(expiry, fee uint64, commitment Hash) (Hash, error) {
	id, err := d.ID()
	if err != nil {
		return Hash{}, err
	}
	if expiry == 0 || fee > math.MaxInt64 {
		return Hash{}, ErrMetadata
	}
	h := sha256.New()
	h.Write([]byte("ZEVUNE-TX-SIGHASH\x00\x01"))
	h.Write(id[:])
	var numbers [16]byte
	binary.BigEndian.PutUint64(numbers[:8], expiry)
	binary.BigEndian.PutUint64(numbers[8:], fee)
	h.Write(numbers[:])
	h.Write(commitment[:])
	var result Hash
	copy(result[:], h.Sum(nil))
	return result, nil
}

// Encode reuses a legacy byte layout, NOT its signature algorithm. Adding a
// prefix to an old signed transaction does not produce a valid bound signature.
func Encode(body *orchardbridge.Envelope, expected Domain) ([]byte, error) {
	id, err := expected.ID()
	if err != nil {
		return nil, err
	}
	raw, err := orchardbridge.Encode(body)
	if err != nil {
		return nil, ErrEncoding
	}
	out := make([]byte, 0, PrefixSize+len(raw))
	out = append(out, transactionMagic...)
	out = append(out, id[:]...)
	out = append(out, raw...)
	return out, nil
}

func Decode(raw []byte, expected Domain) (*orchardbridge.Envelope, error) {
	id, err := expected.ID()
	if err != nil {
		return nil, err
	}
	if len(raw) < PrefixSize+orchardbridge.HeaderSize || len(raw) > MaxTransactionSize || string(raw[:8]) != transactionMagic {
		return nil, ErrEncoding
	}
	if !bytes.Equal(raw[8:PrefixSize], id[:]) {
		return nil, ErrDomain
	}
	body, err := orchardbridge.Decode(raw[PrefixSize:])
	if err != nil {
		return nil, ErrEncoding
	}
	return body, nil
}

// PayloadDigest identifies exact authorizing bytes. It is not an effects-only
// transaction identifier and does not prove ledger admission or finality.
func PayloadDigest(raw []byte) Hash { return sha256.Sum256(raw) }
