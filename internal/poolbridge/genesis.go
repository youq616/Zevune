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
// a worker. Both domain-bound profiles require a nonzero nonce. This does not
// convert legacy data, validate Orchard note openings, or authorize any issuance.
func ValidateTestGenesisFrame(raw []byte) error {
	_, err := TestGenesisProfile(raw)
	return err
}

// TestGenesisProfile checks the entire public framing before returning its
// fixed storage policy. Callers must independently pin these exact bytes; full
// note/curve and unique-commitment validation still takes place in Rust.
func TestGenesisProfile(raw []byte) (StorageProfile, error) {
	if len(raw) < MinTestGenesisBytes || len(raw) > MaxTestGenesisBytes {
		return LegacyJournal, ErrBounds
	}
	header := 0
	profile := LegacyJournal
	switch string(raw[:8]) {
	case "ZVTGEN01":
		header = 50
	case "ZVTGEN02":
		header = 82
	case "ZVTGEN03":
		header = 82
		profile = ActiveSegmentsV1
	default:
		return LegacyJournal, ErrBounds
	}
	network := sha256.Sum256([]byte("zevune-orchard-lab-1"))
	count := int(binary.BigEndian.Uint16(raw[48:50]))
	if !bytes.Equal(raw[8:40], network[:]) ||
		binary.BigEndian.Uint64(raw[40:48]) != testGenesisSupply ||
		count < 1 || count > testGenesisMaxAllocations ||
		len(raw) != header+testGenesisEntryBytes*count {
		return LegacyJournal, ErrBounds
	}
	if header == 82 && bytes.Equal(raw[50:82], make([]byte, 32)) {
		return LegacyJournal, ErrBounds
	}
	// Subtract from a bounded remainder so even uint64-max allocations cannot
	// wrap an accumulator and appear to match the fixed laboratory supply.
	remaining := testGenesisSupply
	for offset := header; offset < len(raw); offset += testGenesisEntryBytes {
		value := binary.BigEndian.Uint64(raw[offset+43 : offset+51])
		if value == 0 || value > remaining {
			return LegacyJournal, ErrBounds
		}
		remaining -= value
	}
	if remaining != 0 {
		return LegacyJournal, ErrBounds
	}
	return profile, nil
}

// These flags only work with the separately built local-funding-lab Rust
// feature. A normal worker rejects them; no implicit fallback or new issuance.
func (o Options) workerArgs(mode string) ([]string, error) {
	launch, err := o.workerLaunch(mode)
	return launch.args, err
}

type workerLaunch struct {
	args        []string
	profile     StorageProfile
	headerBytes uint64
}

// Read and authenticate the manifest once for both process arguments and IPC
// policy. The Rust worker independently checks the same pin before any opening.
func (o Options) workerLaunch(mode string) (workerLaunch, error) {
	if mode != "create" && mode != "open" {
		return workerLaunch{}, ErrBounds
	}
	args := []string{mode, o.Journal}
	if o.TestGenesis == "" && o.TestGenesisSHA256 == (Hash{}) {
		return workerLaunch{args: args, profile: LegacyJournal, headerBytes: 44}, nil
	}
	if !filepath.IsAbs(o.TestGenesis) || o.TestGenesisSHA256 == (Hash{}) {
		return workerLaunch{}, ErrBounds
	}
	info, err := os.Lstat(o.TestGenesis)
	if err != nil || !info.Mode().IsRegular() || info.Size() < MinTestGenesisBytes || info.Size() > MaxTestGenesisBytes {
		return workerLaunch{}, ErrBounds
	}
	f, err := os.Open(o.TestGenesis)
	if err != nil {
		return workerLaunch{}, ErrBounds
	}
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		f.Close()
		return workerLaunch{}, ErrBounds
	}
	b, err := io.ReadAll(io.LimitReader(f, MaxTestGenesisBytes+1))
	closeErr := f.Close()
	digest := sha256.Sum256(b)
	if err != nil || closeErr != nil || int64(len(b)) != info.Size() || !bytes.Equal(digest[:], o.TestGenesisSHA256[:]) {
		return workerLaunch{}, ErrBounds
	}
	profile, err := TestGenesisProfile(b)
	if err != nil {
		return workerLaunch{}, err
	}
	headerBytes := uint64(44)
	if string(b[:8]) != "ZVTGEN01" {
		headerBytes = 76
	}
	headerBytes += 32 * uint64(binary.BigEndian.Uint16(b[48:50]))
	return workerLaunch{
		args:        append(args, o.TestGenesis, hex.EncodeToString(o.TestGenesisSHA256[:])),
		profile:     profile,
		headerBytes: headerBytes,
	}, nil
}
