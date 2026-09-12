package networkdomain

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"testing"

	"github.com/youq616/Zevune/internal/orchardbridge"
)

func TestDescriptorCanonicalEncodingAndVersion(t *testing.T) {
	a, err := New(ID{1}, ID{2})
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := a.Encode()
	decoded, err := Decode(raw[:])
	if err != nil || decoded != a {
		t.Fatal("descriptor roundtrip")
	}
	for n := 0; n < len(raw); n++ {
		if _, err = Decode(raw[:n]); err == nil {
			t.Fatalf("accepted prefix %d", n)
		}
	}
	for _, offset := range []int{0, 7, 72, 103} {
		changed := raw
		changed[offset] ^= 1
		if _, err = Decode(changed[:]); err == nil {
			t.Fatal("accepted unknown magic or rules")
		}
	}
	if _, err = Decode(append(raw[:], 0)); err == nil {
		t.Fatal("accepted trailing byte")
	}
	for _, pair := range [][2]ID{{{}, ID{1}}, {ID{1}, {}}} {
		if _, err = New(pair[0], pair[1]); err == nil {
			t.Fatal("accepted zero identity")
		}
	}
	if _, err = (Descriptor{}).ID(); err == nil {
		t.Fatal("zero value unexpectedly usable")
	}
}

func TestIndependentGoldenDescriptor(t *testing.T) {
	var network, genesis ID
	for i := range network {
		network[i] = byte(i + 1)
		genesis[i] = byte(i + 33)
	}
	d, err := New(network, genesis)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := d.Encode()
	id, _ := d.ID()
	// Golden values independently generated using Python hashlib, not this API.
	if hex.EncodeToString(id[:]) != "6418d64157c1f482123804763244c63521a55bb8a398b4972962875cabfe2569" {
		t.Fatal("domain ID changed")
	}
	rules := sha256.Sum256([]byte(Rules))
	if hex.EncodeToString(rules[:]) != "d506193ea22ad9eca0087c20685e83997d2de70072436341bf887a252ff5ca68" {
		t.Fatal("rule-set digest changed")
	}
	if hex.EncodeToString(raw[:]) != "5a56444f4d4e30320102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f40d506193ea22ad9eca0087c20685e83997d2de70072436341bf887a252ff5ca68" {
		t.Fatal("descriptor bytes changed")
	}
}

func TestEnvelopeNoFallbackAndOwnedBuffers(t *testing.T) {
	e := &orchardbridge.Envelope{Expiry: 20, Fee: 1, ValueBalance: 1, Actions: make([]orchardbridge.Action, 2), Proof: make([]byte, 7264)}
	e.Actions[1].Nullifier[0] = 1
	e.Actions[1].Commitment[0] = 1
	// Synthetic framing only, never supplied to any executable verifier.
	id := ID{9}
	raw, err := EncodeEnvelope(e, id)
	if err != nil {
		t.Fatal(err)
	}
	got, err := DecodeEnvelope(raw, id)
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := EncodeEnvelope(got, id)
	if err != nil || !bytes.Equal(raw, encoded) {
		t.Fatal("noncanonical framing")
	}
	if _, err = DecodeEnvelope(raw, ID{8}); !errors.Is(err, ErrDomain) {
		t.Fatal("foreign domain accepted")
	}
	if _, err = DecodeEnvelope(raw, ID{}); err == nil {
		t.Fatal("zero expected domain accepted")
	}
	old, _ := orchardbridge.Encode(e)
	if _, err = DecodeEnvelope(old, id); err == nil {
		t.Fatal("V1 fallback")
	}
	if _, err = orchardbridge.Decode(raw); err == nil {
		t.Fatal("legacy decoder accepted V2")
	}
	for n := 0; n < len(raw); n++ {
		if _, err = DecodeEnvelope(raw[:n], id); err == nil {
			t.Fatal("accepted truncation")
		}
	}
	if _, err = DecodeEnvelope(append(raw, 0), id); err == nil {
		t.Fatal("trailing data")
	}
	if _, err = DecodeEnvelope(make([]byte, MaxEnvelopeSize+1), id); !errors.Is(err, orchardbridge.ErrBounds) {
		t.Fatal("size limit")
	}
	before := got.Proof[0]
	raw[orchardbridge.HeaderSize+32+2*orchardbridge.ActionSize+4] ^= 255
	if got.Proof[0] != before {
		t.Fatal("decoded value aliases input")
	}
}

func FuzzDescriptorAndBoundEnvelope(f *testing.F) {
	d, _ := New(ID{1}, ID{2})
	r, _ := d.Encode()
	f.Add(r[:])
	f.Add([]byte("ZVORLAB2"))
	f.Fuzz(func(t *testing.T, raw []byte) {
		d, err := Decode(raw)
		if err == nil {
			encoded, _ := d.Encode()
			if !bytes.Equal(encoded[:], raw) {
				t.Fatal("noncanonical descriptor")
			}
		}
		e, err := DecodeEnvelope(raw, ID{9})
		if err == nil {
			encoded, _ := EncodeEnvelope(e, ID{9})
			if !bytes.Equal(encoded, raw) {
				t.Fatal("noncanonical envelope")
			}
		}
	})
}
