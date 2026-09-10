package protocol

import "testing"

// These synthetic framing vectors were captured before the brand/module rename.
// They are not proofs, payment records, or production cryptographic test vectors.
func TestBrandRenamePreservesLegacyV0Encoding(t *testing.T) {
	tx := fixture()
	encoded, err := tx.MarshalBinary()
	if err != nil || len(encoded) != 502 {
		t.Fatalf("legacy encoding changed: len=%d err=%v", len(encoded), err)
	}
	effects, err := tx.EffectDigest()
	if err != nil || effects.String() != "14089555563ccc72e653a4b145830047db9025b4ee640c30083b0ee9f5b5fb83" {
		t.Fatalf("legacy effects changed: %v %v", effects, err)
	}
	id, err := tx.ID()
	if err != nil || id.String() != "92803654bc3757dbeb82c5a1c99ab86f8429cc5d24187f2d45723e3302072612" {
		t.Fatalf("legacy transaction ID changed: %v %v", id, err)
	}
}
