// Package orchardbridge is a bounded, local-only boundary to the experimental
// Orchard verifier. It is NOT a ledger, wallet, consensus adapter, or payment API.
// Structural decoding and successful IPC do not establish proof validity.
package orchardbridge

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"math"
)

const (
	Network         = "zevune-orchard-lab-1"
	WireMagic       = "ZVORLAB1"
	MinActions      = 2
	MaxActions      = 8
	HeaderSize      = 66
	ActionSize      = 884
	ProofBaseSize   = 2720
	ProofPerAction  = 2272
	TailSize        = 68 // u32 proof length and 64-byte binding signature
	MaxEnvelopeSize = HeaderSize + MaxActions*ActionSize + ProofBaseSize + MaxActions*ProofPerAction + TailSize
)

var (
	ErrEncoding = errors.New("invalid experimental Orchard envelope")
	ErrBounds   = errors.New("experimental Orchard resource limit exceeded")
	ErrPolicy   = errors.New("experimental Orchard policy mismatch")
	ErrState    = errors.New("experimental Orchard state check failed")
)

type Hash [32]byte

type Action struct {
	ValueCommitment Hash
	Nullifier       Hash
	RandomizedKey   Hash
	Commitment      Hash
	EphemeralKey    Hash
	NoteCiphertext  [580]byte
	OutCiphertext   [80]byte
	Signature       [64]byte
}

// Envelope contains public wire fields only. A decoded Envelope has NOT passed
// curve-point checks, signature checks, proof verification, or ledger checks.
type Envelope struct {
	Expiry           uint64
	Fee              uint64
	ValueBalance     int64
	Anchor           Hash
	Actions          []Action
	Proof            []byte
	BindingSignature [64]byte
}

func proofSize(n int) int { return ProofBaseSize + n*ProofPerAction }
func wireSize(n int) int  { return HeaderSize + n*ActionSize + proofSize(n) + TailSize }

func (e *Envelope) structural() error {
	if e == nil || len(e.Actions) < MinActions || len(e.Actions) > MaxActions {
		return ErrBounds
	}
	if e.Expiry == 0 || e.Fee > math.MaxInt64 || e.ValueBalance < 0 || uint64(e.ValueBalance) != e.Fee {
		return ErrPolicy
	}
	if len(e.Proof) != proofSize(len(e.Actions)) {
		return ErrEncoding
	}
	nfs := make(map[Hash]struct{}, len(e.Actions))
	cms := make(map[Hash]struct{}, len(e.Actions))
	for _, a := range e.Actions {
		if _, ok := nfs[a.Nullifier]; ok {
			return ErrPolicy
		}
		if _, ok := cms[a.Commitment]; ok {
			return ErrPolicy
		}
		nfs[a.Nullifier] = struct{}{}
		cms[a.Commitment] = struct{}{}
	}
	return nil
}

// Encode uses exactly one encoding for supported fields. This format is local
// experimental transport, NOT ZIP-244 or the final Zevune transaction format.
func Encode(e *Envelope) ([]byte, error) {
	if err := e.structural(); err != nil {
		return nil, err
	}
	out := make([]byte, 0, wireSize(len(e.Actions)))
	out = append(out, WireMagic...)
	out = binary.BigEndian.AppendUint64(out, e.Expiry)
	out = binary.BigEndian.AppendUint64(out, e.Fee)
	out = binary.BigEndian.AppendUint64(out, uint64(e.ValueBalance))
	out = append(out, e.Anchor[:]...)
	out = append(out, byte(len(e.Actions)), 3) // only patched Orchard V2 default flags
	for _, a := range e.Actions {
		out = append(out, a.ValueCommitment[:]...)
		out = append(out, a.Nullifier[:]...)
		out = append(out, a.RandomizedKey[:]...)
		out = append(out, a.Commitment[:]...)
		out = append(out, a.EphemeralKey[:]...)
		out = append(out, a.NoteCiphertext[:]...)
		out = append(out, a.OutCiphertext[:]...)
		out = append(out, a.Signature[:]...)
	}
	out = binary.BigEndian.AppendUint32(out, uint32(len(e.Proof)))
	out = append(out, e.Proof...)
	out = append(out, e.BindingSignature[:]...)
	return out, nil
}

// Decode checks size before allocating and returns an owned copy. It deliberately
// does not pretend to implement Orchard's point or zero-knowledge verification.
func Decode(raw []byte) (*Envelope, error) {
	if len(raw) > MaxEnvelopeSize {
		return nil, ErrBounds
	}
	if len(raw) < HeaderSize || string(raw[:8]) != WireMagic {
		return nil, ErrEncoding
	}
	n := int(raw[64])
	if n < MinActions || n > MaxActions {
		return nil, ErrBounds
	}
	if raw[65] != 3 {
		return nil, ErrPolicy
	}
	if len(raw) != wireSize(n) {
		return nil, ErrEncoding
	}
	e := &Envelope{
		Expiry:       binary.BigEndian.Uint64(raw[8:16]),
		Fee:          binary.BigEndian.Uint64(raw[16:24]),
		ValueBalance: int64(binary.BigEndian.Uint64(raw[24:32])),
		Actions:      make([]Action, n),
	}
	copy(e.Anchor[:], raw[32:64])
	offset := HeaderSize
	take := func(dst []byte) { copy(dst, raw[offset:offset+len(dst)]); offset += len(dst) }
	for i := range e.Actions {
		a := &e.Actions[i]
		take(a.ValueCommitment[:])
		take(a.Nullifier[:])
		take(a.RandomizedKey[:])
		take(a.Commitment[:])
		take(a.EphemeralKey[:])
		take(a.NoteCiphertext[:])
		take(a.OutCiphertext[:])
		take(a.Signature[:])
	}
	if binary.BigEndian.Uint32(raw[offset:offset+4]) != uint32(proofSize(n)) {
		return nil, ErrEncoding
	}
	offset += 4
	e.Proof = bytes.Clone(raw[offset : offset+proofSize(n)])
	offset += proofSize(n)
	copy(e.BindingSignature[:], raw[offset:])
	if err := e.structural(); err != nil {
		return nil, err
	}
	return e, nil
}

// PayloadDigest identifies the EXACT authorizing bytes, including signatures and
// proof. It is not the final network transaction-ID rule or a finality proof.
func PayloadDigest(raw []byte) Hash { return sha256.Sum256(raw) }

func protocolFingerprint() Hash {
	return sha256.Sum256([]byte("ZEVUNE-BRIDGE-V1\x00orchard=0.15.5\x00circuit=FixedPostNu6_2\x00network=" + Network + "\x00wire=" + WireMagic + "\x00"))
}
