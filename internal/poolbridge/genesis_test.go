package poolbridge

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"os"
	"path/filepath"
	"testing"
)

func TestTestGenesisArgumentsAreExplicitAndPinned(t *testing.T) {
	o := Options{Journal: filepath.Join(t.TempDir(), "state.journal")}
	args, err := o.workerArgs("open")
	if err != nil || len(args) != 2 {
		t.Fatal("legacy arguments changed", err)
	}
	p := filepath.Join(t.TempDir(), "genesis.bin")
	b := genesisFrame(false, 1) // Framing-only dummy; Rust must still reject the zero Orchard opening.
	if err := os.WriteFile(p, b, 0600); err != nil {
		t.Fatal(err)
	}
	o.TestGenesis = p
	if _, err := o.workerArgs("open"); err == nil {
		t.Fatal("missing pin accepted")
	}
	o.TestGenesisSHA256 = sha256.Sum256(b)
	args, err = o.workerArgs("open")
	if err != nil || len(args) != 4 || args[2] != p {
		t.Fatal(err)
	}
	b[0] = 1
	if err := os.WriteFile(p, b, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := o.workerArgs("open"); err == nil {
		t.Fatal("modified manifest accepted")
	}
	o.TestGenesis = "relative.bin"
	if _, err := o.workerArgs("open"); err == nil {
		t.Fatal("relative path accepted")
	}
	o.TestGenesis = ""
	if _, err := o.workerArgs("open"); err == nil {
		t.Fatal("orphan pin accepted")
	}
}

// Deliberately invalid note openings, used ONLY to test public framing. No mock
// verifier is exposed to executables and no test treats this as spendable value.
func genesisFrame(bound bool, count int) []byte {
	header, magic := 50, "ZVTGEN01"
	if bound {
		header, magic = 82, "ZVTGEN02"
	}
	b := make([]byte, header+count*testGenesisEntryBytes)
	copy(b, magic)
	network := sha256.Sum256([]byte("zevune-orchard-lab-1"))
	copy(b[8:40], network[:])
	binary.BigEndian.PutUint64(b[40:48], testGenesisSupply)
	binary.BigEndian.PutUint16(b[48:50], uint16(count))
	if bound {
		b[50] = 1
	}
	for i := 0; i < count; i++ {
		value := testGenesisSupply / uint64(count)
		if i == count-1 {
			value += testGenesisSupply % uint64(count)
		}
		binary.BigEndian.PutUint64(b[header+i*testGenesisEntryBytes+43:], value)
	}
	return b
}

func TestGenesisFrameBothProfilesAndAllCounts(t *testing.T) {
	for _, bound := range []bool{false, true} {
		for n := 1; n <= testGenesisMaxAllocations; n++ {
			b := genesisFrame(bound, n)
			before := bytes.Clone(b)
			if err := ValidateTestGenesisFrame(b); err != nil {
				t.Fatal(bound, n, err)
			}
			if !bytes.Equal(before, b) {
				t.Fatal("preflight mutated input")
			}
		}
	}
}

func TestGenesisFrameTruncationAndTrailingData(t *testing.T) {
	for _, bound := range []bool{false, true} {
		for _, count := range []int{1, 16} {
			b := genesisFrame(bound, count)
			for i := 0; i < len(b); i++ {
				if ValidateTestGenesisFrame(b[:i]) == nil {
					t.Fatalf("accepted prefix %d", i)
				}
			}
			if ValidateTestGenesisFrame(append(bytes.Clone(b), 0)) == nil {
				t.Fatal("accepted trailing bytes")
			}
		}
	}
}

func TestGenesisFrameRejectsHeaderAndSupplyMutations(t *testing.T) {
	tests := map[string]func([]byte){
		"unknown profile": func(b []byte) { b[7] = '3' },
		"wrong network":   func(b []byte) { b[8] ^= 1 },
		"wrong supply":    func(b []byte) { b[47] ^= 1 },
		"zero count":      func(b []byte) { b[49] = 0 },
		"huge count":      func(b []byte) { b[48], b[49] = 255, 255 },
		"zero nonce":      func(b []byte) { clear(b[50:82]) },
		"zero value":      func(b []byte) { clear(b[125:133]) },
		"overflow":        func(b []byte) { binary.BigEndian.PutUint64(b[125:133], ^uint64(0)) },
		"below total":     func(b []byte) { binary.BigEndian.PutUint64(b[125:133], testGenesisSupply-1) },
	}
	for name, change := range tests {
		t.Run(name, func(t *testing.T) {
			b := genesisFrame(true, 1)
			change(b)
			if ValidateTestGenesisFrame(b) == nil {
				t.Fatal("accepted malformed manifest")
			}
		})
	}
	b := genesisFrame(true, 2)
	binary.BigEndian.PutUint64(b[125:133], testGenesisSupply)
	if ValidateTestGenesisFrame(b) == nil {
		t.Fatal("accepted cumulative oversupply")
	}
}

func TestPinnedMalformedGenesisIsRejectedBeforeWorkerStart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "malformed.bin")
	b := make([]byte, MinTestGenesisBytes)
	if err := os.WriteFile(path, b, 0600); err != nil {
		t.Fatal(err)
	}
	o := Options{Journal: filepath.Join(t.TempDir(), "journal"), TestGenesis: path, TestGenesisSHA256: sha256.Sum256(b)}
	if _, err := o.workerArgs("create"); err == nil {
		t.Fatal("a valid hash must not bless an unknown genesis profile")
	}
}

func FuzzTestGenesisFrame(f *testing.F) {
	f.Add(genesisFrame(false, 1))
	f.Add(genesisFrame(true, 16))
	f.Add([]byte("ZVTGEN03"))
	f.Fuzz(func(t *testing.T, b []byte) {
		before := bytes.Clone(b)
		err := ValidateTestGenesisFrame(b)
		if !bytes.Equal(before, b) {
			t.Fatal("input mutated")
		}
		if err == nil && (len(b) < MinTestGenesisBytes || len(b) > MaxTestGenesisBytes) {
			t.Fatal("accepted outside bounds")
		}
	})
}
