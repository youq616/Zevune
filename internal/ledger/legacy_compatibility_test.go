package ledger

import "testing"

// This is a public synthetic empty-state vector, not a network genesis.
func TestBrandRenamePreservesLegacyV0AppHash(t *testing.T) {
	e, err := New("veil-local-devnet-1", nil, UnavailableVerifier{})
	if err != nil {
		t.Fatal(err)
	}
	got := e.Summary().AppHash.String()
	if got != "6eacdc87321ba9c78a1bfa9e86c6bccf73b77e6134807f217d9d26eae7b3b735" {
		t.Fatalf("legacy app hash changed: %s", got)
	}
}
