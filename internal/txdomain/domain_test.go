package txdomain

import (
	"bytes"
	"encoding/hex"
	"errors"
	"math"
	"os"
	"strings"
	"testing"

	"github.com/youq616/Zevune/internal/orchardbridge"
)

func testDomain(t *testing.T) Domain {
	t.Helper()
	var genesis, rules Hash
	for i := range genesis {
		genesis[i] = 0x11
		rules[i] = 0x22
	}
	d, err := New(Test, genesis, rules, 17)
	if err != nil {
		t.Fatal(err)
	}
	return d
}
func fixture(t *testing.T) []byte {
	t.Helper()
	e := &orchardbridge.Envelope{Expiry: 100, Fee: 1000, ValueBalance: 1000, Actions: make([]orchardbridge.Action, 2), Proof: make([]byte, 7264)}
	// Structural-only synthetic fixture; not a signed or proven transaction.
	e.Actions[1].Nullifier[0] = 1
	e.Actions[1].Commitment[0] = 1
	raw, err := Encode(e, testDomain(t))
	if err != nil {
		t.Fatal(err)
	}
	return raw
}
func TestIndependentTranscriptVector(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/domain-v1.txt")
	if err != nil {
		t.Fatal(err)
	}
	v := strings.Fields(string(raw))
	if len(v) != 6 {
		t.Fatal("vector fields")
	}
	d := testDomain(t)
	encoded, _ := d.Bytes()
	id, _ := d.ID()
	if hex.EncodeToString(encoded) != v[0] || hex.EncodeToString(id[:]) != v[1] {
		t.Fatal("descriptor vector")
	}
	var commitment Hash
	for i := range commitment {
		commitment[i] = 0x33
	}
	digest, err := d.DigestForCommitment(100, 1000, commitment)
	if err != nil || hex.EncodeToString(digest[:]) != v[5] {
		t.Fatal("signing vector", err)
	}
}
func TestDescriptorCanonicalBoundsAndIsolation(t *testing.T) {
	d := testDomain(t)
	raw, _ := d.Bytes()
	for i := 0; i < len(raw); i++ {
		if _, e := DecodeDomain(raw[:i]); e == nil {
			t.Fatal("truncation", i)
		}
	}
	if _, e := DecodeDomain(append(bytes.Clone(raw), 0)); e == nil {
		t.Fatal("trailing byte")
	}
	for _, index := range []int{0, 8, 77, 78} {
		changed := bytes.Clone(raw)
		changed[index] = 255
		if _, e := DecodeDomain(changed); e == nil {
			t.Fatal("unsupported", index)
		}
	}
	for _, span := range [][2]int{{9, 41}, {41, 73}, {73, 77}} {
		c := bytes.Clone(raw)
		clear(c[span[0]:span[1]])
		if _, e := DecodeDomain(c); e == nil {
			t.Fatal("empty identity", span)
		}
	}
	before, _ := d.ID()
	raw[9] ^= 1
	after, _ := d.ID()
	if before != after {
		t.Fatal("mutable alias")
	}
	if _, e := (Domain{}).ID(); e == nil {
		t.Fatal("zero value accepted")
	}
}
func TestEachDomainComponentChangesTheIDAndSignature(t *testing.T) {
	d := testDomain(t)
	raw, _ := d.Bytes()
	id, _ := d.ID()
	sig, _ := d.DigestForCommitment(100, 1000, Hash{1})
	for _, index := range []int{8, 9, 40, 41, 72, 76} {
		c := bytes.Clone(raw)
		c[index] ^= 1
		if index == 8 {
			c[index] = byte(Development)
		}
		changed, e := DecodeDomain(c)
		if e != nil {
			t.Fatal(e)
		}
		next, _ := changed.ID()
		signed, _ := changed.DigestForCommitment(100, 1000, Hash{1})
		if next == id || signed == sig {
			t.Fatal("not bound", index)
		}
	}
}
func TestSigningMetadataBounds(t *testing.T) {
	d := testDomain(t)
	for _, v := range [][2]uint64{{0, 0}, {100, math.MaxUint64}, {100, math.MaxInt64 + 1}} {
		if _, e := d.DigestForCommitment(v[0], v[1], Hash{}); !errors.Is(e, ErrMetadata) {
			t.Fatal(e)
		}
	}
	if _, e := d.DigestForCommitment(math.MaxUint64, math.MaxInt64, Hash{}); e != nil {
		t.Fatal(e)
	}
	a, _ := d.DigestForCommitment(1, 0, Hash{1})
	b, _ := d.DigestForCommitment(2, 0, Hash{1})
	c, _ := d.DigestForCommitment(1, 1, Hash{1})
	x, _ := d.DigestForCommitment(1, 0, Hash{2})
	if a == b || a == c || a == x {
		t.Fatal("unsigned metadata")
	}
}
func TestBoundEnvelopeIsCanonicalOwnedAndNotLegacy(t *testing.T) {
	raw := fixture(t)
	d := testDomain(t)
	body, e := Decode(raw, d)
	if e != nil {
		t.Fatal(e)
	}
	out, e := Encode(body, d)
	if e != nil || !bytes.Equal(out, raw) {
		t.Fatal("roundtrip")
	}
	raw[len(raw)-1] ^= 1
	if bytes.Equal(body.BindingSignature[:], raw[len(raw)-64:]) {
		t.Fatal("shared input memory")
	}
	if _, e := orchardbridge.Decode(out); e == nil {
		t.Fatal("legacy accepted bound format")
	}
	if _, e := Decode(out[PrefixSize:], d); e == nil {
		t.Fatal("silent legacy fallback")
	}
}
func TestPayloadRejectsForeignDomainTruncationsAndTrailingBytes(t *testing.T) {
	d := testDomain(t)
	raw := fixture(t)
	for i := 0; i < len(raw); i++ {
		if _, e := Decode(raw[:i], d); e == nil {
			t.Fatal("truncated", i)
		}
	}
	if _, e := Decode(append(bytes.Clone(raw), 0), d); e == nil {
		t.Fatal("trailing")
	}
	raw[8] ^= 1
	if _, e := Decode(raw, d); !errors.Is(e, ErrDomain) {
		t.Fatal(e)
	}
	if _, e := Decode(make([]byte, MaxTransactionSize+1), d); e == nil {
		t.Fatal("oversized")
	}
}
func FuzzDomainDescriptor(f *testing.F) {
	var a, b Hash
	a[0] = 1
	b[0] = 2
	d, _ := New(Test, a, b, 1)
	raw, _ := d.Bytes()
	f.Add(raw)
	f.Add([]byte{})
	f.Fuzz(func(t *testing.T, raw []byte) {
		d, e := DecodeDomain(raw)
		if e != nil {
			return
		}
		back, e := d.Bytes()
		if e != nil || !bytes.Equal(back, raw) {
			t.Fatal("noncanonical")
		}
	})
}
func FuzzBoundEnvelope(f *testing.F) {
	var a, b Hash
	a[0] = 1
	b[0] = 2
	d, _ := New(Test, a, b, 1)
	body := &orchardbridge.Envelope{Expiry: 1, Actions: make([]orchardbridge.Action, 2), Proof: make([]byte, 7264)}
	body.Actions[1].Nullifier[0] = 1
	body.Actions[1].Commitment[0] = 1
	raw, _ := Encode(body, d)
	f.Add(raw)
	f.Add([]byte{})
	f.Fuzz(func(t *testing.T, raw []byte) {
		out, e := Decode(raw, d)
		if e != nil {
			return
		}
		back, e := Encode(out, d)
		if e != nil || !bytes.Equal(back, raw) {
			t.Fatal("noncanonical")
		}
	})
}
