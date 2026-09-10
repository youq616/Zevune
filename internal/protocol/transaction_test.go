package protocol

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"strings"
	"testing"
)

func fixture() Envelope {
	return Envelope{Version: Version, ChainID: "veil-local-devnet-1", CircuitID: CircuitID, Anchor: sha256.Sum256([]byte("root")), ExpiryHeight: 100, Fee: 1, Nullifiers: []Hash{sha256.Sum256([]byte("n"))}, Outputs: []Output{{Commitment: sha256.Sum256([]byte("c")), EphemeralKey: sha256.Sum256([]byte("e")), Ciphertext: make([]byte, CiphertextBytes)}}, Proof: []byte("synthetic-not-zk")}
}
func TestCodecRoundTrip(t *testing.T) {
	x := fixture()
	a, e := x.MarshalBinary()
	if e != nil {
		t.Fatal(e)
	}
	y, e := DecodeBinary(a)
	if e != nil {
		t.Fatal(e)
	}
	b, e := y.MarshalBinary()
	if e != nil || !bytes.Equal(a, b) {
		t.Fatal("noncanonical round trip", e)
	}
}
func TestCodecRejectsEveryTruncation(t *testing.T) {
	b, _ := fixture().MarshalBinary()
	for i := 0; i < len(b); i++ {
		if _, e := DecodeBinary(b[:i]); e == nil {
			t.Fatalf("accepted prefix %d", i)
		}
	}
}
func TestCodecRejectsTrailing(t *testing.T) {
	b, _ := fixture().MarshalBinary()
	if _, e := DecodeBinary(append(b, 0)); e == nil {
		t.Fatal("accepted trailing bytes")
	}
}
func TestCodecRejectsOversize(t *testing.T) {
	if _, e := DecodeBinary(make([]byte, MaxTxBytes+1)); e == nil {
		t.Fatal("oversize")
	}
}
func TestShapeRejections(t *testing.T) {
	cases := map[string]func(*Envelope){
		"version": func(x *Envelope) { x.Version++ }, "chain": func(x *Envelope) { x.ChainID = "../evil" }, "circuit": func(x *Envelope) { x.CircuitID = "bypass" }, "expiry": func(x *Envelope) { x.ExpiryHeight = 0 }, "fee": func(x *Envelope) { x.Fee = MaxFee + 1 }, "no-nullifiers": func(x *Envelope) { x.Nullifiers = nil }, "no-outputs": func(x *Envelope) { x.Outputs = nil }, "many-nullifiers": func(x *Envelope) { x.Nullifiers = make([]Hash, MaxItems+1) }, "many-outputs": func(x *Envelope) { x.Outputs = make([]Output, MaxItems+1) }, "no-proof": func(x *Envelope) { x.Proof = nil }, "large-proof": func(x *Envelope) { x.Proof = make([]byte, MaxProofBytes+1) }, "ciphertext": func(x *Envelope) { x.Outputs[0].Ciphertext = []byte{0} },
	}
	for name, mut := range cases {
		t.Run(name, func(t *testing.T) {
			x := fixture()
			mut(&x)
			if x.ValidateShape() == nil {
				t.Fatal("accepted malformed shape")
			}
		})
	}
}
func TestEffectDigestBindsAllPublicEffects(t *testing.T) {
	x := fixture()
	base, _ := x.EffectDigest()
	cases := map[string]func(*Envelope){"chain": func(x *Envelope) { x.ChainID = "other-chain" }, "expiry": func(x *Envelope) { x.ExpiryHeight++ }, "fee": func(x *Envelope) { x.Fee++ }, "anchor": func(x *Envelope) { x.Anchor[0]++ }, "nullifier": func(x *Envelope) { x.Nullifiers[0][0]++ }, "commitment": func(x *Envelope) { x.Outputs[0].Commitment[0]++ }, "ephemeral": func(x *Envelope) { x.Outputs[0].EphemeralKey[0]++ }, "ciphertext": func(x *Envelope) { x.Outputs[0].Ciphertext[0]++ }}
	for name, mut := range cases {
		t.Run(name, func(t *testing.T) {
			y := x.Clone()
			mut(&y)
			h, e := y.EffectDigest()
			if e != nil || h == base {
				t.Fatal("unbound public effect", e)
			}
		})
	}
}
func TestProofExcludedFromEffectsButIncludedInID(t *testing.T) {
	x := fixture()
	a, _ := x.EffectDigest()
	id, _ := x.ID()
	x.Proof = []byte("other fake proof")
	b, _ := x.EffectDigest()
	other, _ := x.ID()
	if a != b || id == other {
		t.Fatal("incorrect transcript boundary")
	}
}
func TestCloneOwnsSlices(t *testing.T) {
	x := fixture()
	y := x.Clone()
	y.Proof[0]++
	y.Nullifiers[0][0]++
	y.Outputs[0].Ciphertext[0]++
	if bytes.Equal(x.Proof, y.Proof) || x.Nullifiers[0] == y.Nullifiers[0] || bytes.Equal(x.Outputs[0].Ciphertext, y.Outputs[0].Ciphertext) {
		t.Fatal("alias")
	}
}
func TestHashEncoding(t *testing.T) {
	h := Hash{255}
	p, e := ParseHash(h.String())
	if e != nil || p != h {
		t.Fatal(e)
	}
	if _, e = ParseHash(strings.ToUpper(h.String())); e == nil {
		t.Fatal("noncanonical hex")
	}
	if _, e = ParseHash("00"); e == nil {
		t.Fatal("short hash")
	}
	b, _ := json.Marshal(h)
	if string(b) != "\""+h.String()+"\"" {
		t.Fatal(string(b))
	}
}
func FuzzDecodeBinary(f *testing.F) {
	b, _ := fixture().MarshalBinary()
	f.Add(b)
	f.Add([]byte{})
	f.Add([]byte("not a transaction"))
	f.Fuzz(func(t *testing.T, b []byte) {
		tx, e := DecodeBinary(b)
		if e == nil {
			again, e := tx.MarshalBinary()
			if e != nil || !bytes.Equal(again, b) {
				t.Fatal("decoder accepted noncanonical data")
			}
		}
	})
}
