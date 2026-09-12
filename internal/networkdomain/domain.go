// Package networkdomain implements ONLY public V2 descriptor and wire framing.
// It does not authenticate a descriptor, prove a transaction, or authorize a
// state transition. Current V1 network entry points never auto-upgrade to V2.
package networkdomain

import (
	"crypto/sha256"
	"errors"

	"github.com/youq616/Zevune/internal/orchardbridge"
)

const (
	DescriptorMagic = "ZVDOMN02"
	DescriptorSize  = 104
	WireMagic       = "ZVORLAB2"
	MaxEnvelopeSize = orchardbridge.MaxEnvelopeSize + 32
	Rules           = "ZEVUNE-BOUND-LAB-RULES\x00\x02;orchard=0.15.5;bundle=orchard_v2;circuit=FixedPostNu6_2;commitment=v5;actions=2..8;flags=3;fee=value_balance>=0;expiry=inclusive;anchors=preblock;block_txs<=16;commitments<=65536;height<=10000;anchors<=64;test_supply=100000"
)

var (
	ErrDescriptor = errors.New("invalid V2 network descriptor")
	ErrDomain     = errors.New("V2 transaction domain does not match configured network")
)

type ID [32]byte

type Descriptor struct {
	network ID
	genesis ID
}

func New(network, genesis ID) (Descriptor, error) {
	if network == (ID{}) || genesis == (ID{}) {
		return Descriptor{}, ErrDescriptor
	}
	return Descriptor{network: network, genesis: genesis}, nil
}

func (d Descriptor) Encode() ([DescriptorSize]byte, error) {
	var out [DescriptorSize]byte
	if d.network == (ID{}) || d.genesis == (ID{}) {
		return out, ErrDescriptor
	}
	copy(out[:8], DescriptorMagic)
	copy(out[8:40], d.network[:])
	copy(out[40:72], d.genesis[:])
	rules := sha256.Sum256([]byte(Rules))
	copy(out[72:], rules[:])
	return out, nil
}

func Decode(raw []byte) (Descriptor, error) {
	if len(raw) != DescriptorSize || string(raw[:8]) != DescriptorMagic {
		return Descriptor{}, ErrDescriptor
	}
	var network, genesis ID
	copy(network[:], raw[8:40])
	copy(genesis[:], raw[40:72])
	d, err := New(network, genesis)
	if err != nil {
		return Descriptor{}, err
	}
	encoded, _ := d.Encode()
	// Exact comparison also pins the immutable rules fingerprint.
	if string(encoded[:]) != string(raw) {
		return Descriptor{}, ErrDescriptor
	}
	return d, nil
}

func (d Descriptor) ID() (ID, error) {
	raw, err := d.Encode()
	if err != nil {
		return ID{}, err
	}
	h := sha256.New()
	h.Write([]byte("ZEVUNE-NETWORK-DOMAIN\x00\x02"))
	h.Write(raw[:])
	var out ID
	copy(out[:], h.Sum(nil))
	return out, nil
}

// DecodeEnvelope is structural only. Expected MUST come from independently
// pinned configuration, not from raw[8:40]. Curve/signature/proof checks are Rust's
// responsibility, followed by committed state checks. No V1 fallback is tried.
func DecodeEnvelope(raw []byte, expected ID) (*orchardbridge.Envelope, error) {
	if len(raw) > MaxEnvelopeSize {
		return nil, orchardbridge.ErrBounds
	}
	if len(raw) < orchardbridge.HeaderSize+32 || string(raw[:8]) != WireMagic {
		return nil, orchardbridge.ErrEncoding
	}
	if expected == (ID{}) || string(raw[8:40]) != string(expected[:]) {
		return nil, ErrDomain
	}
	normalized := make([]byte, 0, len(raw)-32)
	normalized = append(normalized, orchardbridge.WireMagic...)
	normalized = append(normalized, raw[40:]...)
	return orchardbridge.Decode(normalized)
}

// EncodeEnvelope serializes existing signatures; it does not re-sign or upgrade
// an existing V1 transaction. Wrapping V1 authorizations does not make them V2.
func EncodeEnvelope(e *orchardbridge.Envelope, domain ID) ([]byte, error) {
	if domain == (ID{}) {
		return nil, ErrDomain
	}
	body, err := orchardbridge.Encode(e)
	if err != nil {
		return nil, err
	}
	out := make([]byte, 0, len(body)+32)
	out = append(out, WireMagic...)
	out = append(out, domain[:]...)
	out = append(out, body[8:]...)
	return out, nil
}
