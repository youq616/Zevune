//go:build domain_fixture

package networkdomain

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// This validates Rust-produced genuine signed bytes against Go's independent
// structural codec. It is NOT a second implementation of ZK/signature checks.
func TestRustGenuineBoundTransactionMatchesGoCodec(t *testing.T) {
	dir := os.Getenv("ZEVUNE_BOUND_FIXTURE_DIR")
	if !filepath.IsAbs(dir) {
		t.Fatal("real Rust public fixture directory is required; no skip")
	}
	descriptor, err := os.ReadFile(filepath.Join(dir, "domain.bin"))
	if err != nil {
		t.Fatal(err)
	}
	d, err := Decode(descriptor)
	if err != nil {
		t.Fatal(err)
	}
	id, err := d.ID()
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(dir, "payment.bin"))
	if err != nil {
		t.Fatal(err)
	}
	e, err := DecodeEnvelope(raw, id)
	if err != nil {
		t.Fatal(err)
	}
	if e.Fee != 1000 || e.ValueBalance != 1000 || e.Expiry != 20 || len(e.Actions) != 2 {
		t.Fatal("unexpected real fixture")
	}
	encoded, err := EncodeEnvelope(e, id)
	if err != nil || !bytes.Equal(encoded, raw) {
		t.Fatal("Go/Rust encoding disagreement")
	}
	changed := id
	changed[0] ^= 1
	if _, err := DecodeEnvelope(raw, changed); err == nil {
		t.Fatal("wrong independently pinned domain accepted")
	}
}
