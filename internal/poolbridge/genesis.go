package poolbridge

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
)

// Public framing limits are shared by the launcher and network configuration
// loader. Full note/curve parsing, unique commitments and issuance verification
// remain mandatory in Rust; passing this preflight is NOT genesis authorization.
const (
	MinTestGenesisBytes              = 165
	MaxTestGenesisBytes              = 1922
	testGenesisEntryBytes            = 115
	testGenesisMaxAllocations        = 16
	testGenesisSupply         uint64 = 100_000
)

// ValidateTestGenesisFrame rejects unknown or ambiguous profiles before starting
// a worker. LAB1 has no deployment binding. LAB2 requires a nonzero nonce. This
// does not convert LAB1 to LAB2 or validate Orchard note openings.
func ValidateTestGenesisFrame(raw []byte) error {
	if len(raw) < MinTestGenesisBytes || len(raw) > MaxTestGenesisBytes {
		return ErrBounds
	}
	header := 0
	switch string(raw[:8]) {
	case "ZVTGEN01":
		header = 50
	case "ZVTGEN02":
		header = 82
	default:
		return ErrBounds
	}
	network := sha256.Sum256([]byte("zevune-orchard-lab-1"))
	count := int(binary.BigEndian.Uint16(raw[48:50]))
	if !bytes.Equal(raw[8:40], network[:]) ||
		binary.BigEndian.Uint64(raw[40:48]) != testGenesisSupply ||
		count < 1 || count > testGenesisMaxAllocations ||
		len(raw) != header+testGenesisEntryBytes*count {
		return ErrBounds
	}
	if header == 82 && bytes.Equal(raw[50:82], make([]byte, 32)) {
		return ErrBounds
	}
	// Subtract from a bounded remainder so even uint64-max allocations cannot
	// wrap an accumulator and appear to match the fixed laboratory supply.
	remaining := testGenesisSupply
	for offset := header; offset < len(raw); offset += testGenesisEntryBytes {
		value := binary.BigEndian.Uint64(raw[offset+43 : offset+51])
		if value == 0 || value > remaining {
			return ErrBounds
		}
		remaining -= value
	}
	if remaining != 0 {
		return ErrBounds
	}
	return nil
}

// These flags only work with the separately built local-funding-lab Rust
// feature. A normal worker rejects them; no implicit fallback or new issuance.
func (o Options) workerArgs(mode string) ([]string, error) {
	args := []string{mode, o.Journal}
	if o.TestGenesis == "" && o.TestGenesisSHA256 == (Hash{}) {
		return args, nil
	}
	if !filepath.IsAbs(o.TestGenesis) || o.TestGenesisSHA256 == (Hash{}) {
		return nil, ErrBounds
	}
	info, err := os.Lstat(o.TestGenesis)
	if err != nil || !info.Mode().IsRegular() || info.Size() < MinTestGenesisBytes || info.Size() > MaxTestGenesisBytes {
		return nil, ErrBounds
	}
	f, err := os.Open(o.TestGenesis)
	if err != nil {
		return nil, ErrBounds
	}
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		f.Close()
		return nil, ErrBounds
	}
	b, err := io.ReadAll(io.LimitReader(f, MaxTestGenesisBytes+1))
	closeErr := f.Close()
	digest := sha256.Sum256(b)
	if err != nil || closeErr != nil || int64(len(b)) != info.Size() || !bytes.Equal(digest[:], o.TestGenesisSHA256[:]) {
		return nil, ErrBounds
	}
	if err := ValidateTestGenesisFrame(b); err != nil {
		return nil, err
	}
	return append(args, o.TestGenesis, hex.EncodeToString(o.TestGenesisSHA256[:])), nil
}
