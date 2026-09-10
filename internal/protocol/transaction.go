// Package protocol specifies a deliberately provisional PUBLIC transaction envelope.
// Bytes named Commitment, Proof or Ciphertext are NOT cryptography implementations.
package protocol

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"regexp"
)

const (
	Version         uint16 = 0
	CircuitID              = "UNIMPLEMENTED-shielded-transfer-v0"
	MaxItems               = 8
	CiphertextBytes        = 256 // Placeholder; MUST be replaced by the selected protocol's encoding.
	MaxProofBytes          = 64 * 1024
	MaxTxBytes             = 96 * 1024
	MaxFee          uint64 = 1_000_000_000
)

var chainPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,62}$`)
var ErrMalformed = errors.New("malformed prototype envelope")

type Hash [32]byte

func (h Hash) String() string               { return hex.EncodeToString(h[:]) }
func (h Hash) MarshalText() ([]byte, error) { return []byte(h.String()), nil }
func ParseHash(s string) (Hash, error) {
	var h Hash
	b, err := hex.DecodeString(s)
	if err != nil || len(b) != 32 || s != hex.EncodeToString(b) {
		return h, fmt.Errorf("%w: non-canonical hash", ErrMalformed)
	}
	copy(h[:], b)
	return h, nil
}
func ValidChainID(s string) bool { return chainPattern.MatchString(s) }

type Output struct {
	Commitment   Hash
	EphemeralKey Hash
	Ciphertext   []byte
}

// Envelope intentionally contains no cleartext sender, recipient or payment amount.
// This schema alone provides NO privacy, spend authorization or supply protection.
type Envelope struct {
	Version      uint16
	ChainID      string
	CircuitID    string
	Anchor       Hash
	ExpiryHeight uint64
	Fee          uint64 // Explicitly public in this prototype.
	Nullifiers   []Hash
	Outputs      []Output
	Proof        []byte
}

func (t Envelope) ValidateShape() error {
	bad := func(s string) error { return fmt.Errorf("%w: %s", ErrMalformed, s) }
	if t.Version != Version {
		return bad("unsupported version")
	}
	if !ValidChainID(t.ChainID) {
		return bad("invalid chain id")
	}
	if t.CircuitID != CircuitID {
		return bad("unsupported circuit id")
	}
	if t.ExpiryHeight == 0 {
		return bad("zero expiry height")
	}
	if t.Fee > MaxFee {
		return bad("fee above prototype bound")
	}
	if len(t.Nullifiers) < 1 || len(t.Nullifiers) > MaxItems {
		return bad("nullifier count")
	}
	if len(t.Outputs) < 1 || len(t.Outputs) > MaxItems {
		return bad("output count")
	}
	if len(t.Proof) < 1 || len(t.Proof) > MaxProofBytes {
		return bad("proof length")
	}
	for _, o := range t.Outputs {
		if len(o.Ciphertext) != CiphertextBytes {
			return bad("ciphertext length")
		}
	}
	return nil
}
func (t Envelope) Clone() Envelope {
	c := t
	c.Nullifiers = append([]Hash(nil), t.Nullifiers...)
	c.Outputs = make([]Output, len(t.Outputs))
	for i, o := range t.Outputs {
		c.Outputs[i] = o
		c.Outputs[i].Ciphertext = bytes.Clone(o.Ciphertext)
	}
	c.Proof = bytes.Clone(t.Proof)
	return c
}

// effectBytes is a deterministic framing transcript, NOT a note-commitment scheme.
func (t Envelope) effectBytes() ([]byte, error) {
	if err := t.ValidateShape(); err != nil {
		return nil, err
	}
	var b bytes.Buffer
	b.WriteString("VEIL-PROTOTYPE-EFFECTS\x00")
	_ = binary.Write(&b, binary.BigEndian, t.Version)
	for _, s := range []string{t.ChainID, t.CircuitID} {
		b.WriteByte(byte(len(s)))
		b.WriteString(s)
	}
	b.Write(t.Anchor[:])
	_ = binary.Write(&b, binary.BigEndian, t.ExpiryHeight)
	_ = binary.Write(&b, binary.BigEndian, t.Fee)
	b.WriteByte(byte(len(t.Nullifiers)))
	for _, n := range t.Nullifiers {
		b.Write(n[:])
	}
	b.WriteByte(byte(len(t.Outputs)))
	for _, o := range t.Outputs {
		b.Write(o.Commitment[:])
		b.Write(o.EphemeralKey[:])
		b.Write(o.Ciphertext)
	}
	return b.Bytes(), nil
}
func (t Envelope) EffectDigest() (Hash, error) {
	b, err := t.effectBytes()
	if err != nil {
		return Hash{}, err
	}
	return sha256.Sum256(b), nil
}
func (t Envelope) MarshalBinary() ([]byte, error) {
	b, err := t.effectBytes()
	if err != nil {
		return nil, err
	}
	var out bytes.Buffer
	out.Write(b)
	_ = binary.Write(&out, binary.BigEndian, uint32(len(t.Proof)))
	out.Write(t.Proof)
	if out.Len() > MaxTxBytes {
		return nil, ErrMalformed
	}
	return out.Bytes(), nil
}
func (t Envelope) ID() (Hash, error) {
	b, err := t.MarshalBinary()
	if err != nil {
		return Hash{}, err
	}
	return sha256.Sum256(append([]byte("VEIL-PROTOTYPE-TXID\x00"), b...)), nil
}

// DecodeBinary rejects unknown versions, trailing bytes and unbounded allocations.
func DecodeBinary(data []byte) (Envelope, error) {
	var t Envelope
	if len(data) > MaxTxBytes {
		return t, ErrMalformed
	}
	r := bytes.NewReader(data)
	read := func(b []byte) error { _, err := io.ReadFull(r, b); return err }
	bad := func() (Envelope, error) { return Envelope{}, ErrMalformed }
	prefix := make([]byte, len("VEIL-PROTOTYPE-EFFECTS\x00"))
	if read(prefix) != nil || string(prefix) != "VEIL-PROTOTYPE-EFFECTS\x00" {
		return bad()
	}
	if binary.Read(r, binary.BigEndian, &t.Version) != nil {
		return bad()
	}
	text := func() (string, error) {
		n, e := r.ReadByte()
		if e != nil || n > 64 {
			return "", ErrMalformed
		}
		b := make([]byte, int(n))
		e = read(b)
		return string(b), e
	}
	var err error
	if t.ChainID, err = text(); err != nil {
		return bad()
	}
	if t.CircuitID, err = text(); err != nil {
		return bad()
	}
	if read(t.Anchor[:]) != nil {
		return bad()
	}
	if binary.Read(r, binary.BigEndian, &t.ExpiryHeight) != nil {
		return bad()
	}
	if binary.Read(r, binary.BigEndian, &t.Fee) != nil {
		return bad()
	}
	n, err := r.ReadByte()
	if err != nil || n < 1 || n > MaxItems {
		return bad()
	}
	t.Nullifiers = make([]Hash, int(n))
	for i := range t.Nullifiers {
		if read(t.Nullifiers[i][:]) != nil {
			return bad()
		}
	}
	n, err = r.ReadByte()
	if err != nil || n < 1 || n > MaxItems {
		return bad()
	}
	t.Outputs = make([]Output, int(n))
	for i := range t.Outputs {
		o := &t.Outputs[i]
		o.Ciphertext = make([]byte, CiphertextBytes)
		if read(o.Commitment[:]) != nil || read(o.EphemeralKey[:]) != nil || read(o.Ciphertext) != nil {
			return bad()
		}
	}
	var size uint32
	if binary.Read(r, binary.BigEndian, &size) != nil || size == 0 || size > MaxProofBytes || uint64(size) > uint64(r.Len()) {
		return bad()
	}
	t.Proof = make([]byte, int(size))
	if read(t.Proof) != nil || r.Len() != 0 {
		return bad()
	}
	if err = t.ValidateShape(); err != nil {
		return Envelope{}, err
	}
	return t, nil
}
