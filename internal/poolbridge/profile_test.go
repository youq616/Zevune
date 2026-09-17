package poolbridge

import (
	"bytes"
	"encoding/binary"
	"testing"
)

func TestStorageProfilesKeepLegacyHeightBounds(t *testing.T) {
	for _, height := range []uint64{0, 1, 9999, 10000, 10001, 1000000, 1000001, ^uint64(0)} {
		for _, profile := range []StorageProfile{LegacyJournal, ActiveSegmentsV1, StorageProfile(255)} {
			want := profile.valid() && height > 0 && height <= profile.MaxHeight()
			block, err := profile.BlockBytes(height, Hash{1}, nil)
			if (err == nil) != want {
				t.Fatal("wrong profile block bound", profile, height, err)
			}
			selected, _, selectErr := profile.selectionBytes(height, 0, nil)
			if (selectErr == nil) != want {
				t.Fatal("selection uses a different height policy", profile, height, selectErr)
			}
			if want && (binary.BigEndian.Uint64(block[:8]) != height || binary.BigEndian.Uint64(selected[:8]) != height) {
				t.Fatal("height encoding changed")
			}
		}
		_, err := BlockBytes(height, Hash{1}, nil)
		if (err == nil) != (height > 0 && height <= 10000) {
			t.Fatal("existing public encoder was silently expanded", height)
		}
	}
	if LegacyJournal.MaxJournalBytes() != 64<<20 || ActiveSegmentsV1.MaxJournalBytes() != 1<<30 ||
		StorageProfile(255).MaxHeight() != 0 || StorageProfile(255).MaxJournalBytes() != 0 || StorageProfile(255).ipcDomain() != "" {
		t.Fatal("unknown or legacy policy expanded")
	}
}

func TestActiveEncodingPreservesBytesAndTransactionBounds(t *testing.T) {
	tx := []byte{1, 2, 3}
	legacy, err := BlockBytes(17, Hash{7}, [][]byte{tx})
	if err != nil {
		t.Fatal(err)
	}
	active, err := ActiveSegmentsV1.BlockBytes(17, Hash{7}, [][]byte{tx})
	if err != nil || !bytes.Equal(legacy, active) {
		t.Fatal("profile changed the existing block encoding", err)
	}
	legacySelection, _, err := selectionBytes(17, 3, [][]byte{tx})
	if err != nil {
		t.Fatal(err)
	}
	activeSelection, owned, err := ActiveSegmentsV1.selectionBytes(17, 3, [][]byte{tx})
	if err != nil || !bytes.Equal(legacySelection, activeSelection) {
		t.Fatal("profile changed the existing selection encoding", err)
	}
	tx[0] = 9
	if active[46] != 1 || owned[0][0] != 1 {
		t.Fatal("new profile aliases caller memory")
	}
	for _, invalid := range [][][]byte{{nil}, {make([]byte, MaxTransactionBytes+1)}, make([][]byte, MaxTransactions+1)} {
		if _, err := ActiveSegmentsV1.BlockBytes(10001, Hash{1}, invalid); err == nil {
			t.Fatal("active profile weakened transaction bounds")
		}
	}
	if _, err := ActiveSegmentsV1.BlockBytes(10001, Hash{}, nil); err == nil {
		t.Fatal("active profile accepted a zero block identity")
	}
	if _, _, err := ActiveSegmentsV1.selectionBytes(10001, MaxProposalBytes+1, nil); err == nil {
		t.Fatal("active profile weakened proposal byte budget")
	}
	if _, _, err := ActiveSegmentsV1.selectionBytes(10001, 0, make([][]byte, MaxProposalCandidates+1)); err == nil {
		t.Fatal("active profile weakened candidate count")
	}
	if _, _, err := ActiveSegmentsV1.selectionBytes(10001, MaxProposalBytes, [][]byte{make([]byte, MaxTransactionBytes+1)}); err == nil {
		t.Fatal("active selector accepted an oversized candidate")
	}
}

func TestSummaryPolicyChangesOnlyHeightLimit(t *testing.T) {
	raw := make([]byte, 96)
	for _, height := range []uint64{0, 10000, 10001, 1000000, 1000001, ^uint64(0)} {
		binary.BigEndian.PutUint64(raw[:8], height)
		_, oldErr := decodeSummary(raw)
		_, newErr := ActiveSegmentsV1.decodeSummary(raw)
		if (oldErr == nil) != (height <= 10000) || (newErr == nil) != (height <= 1000000) {
			t.Fatal("summary did not enforce its pinned profile", height)
		}
	}
	binary.BigEndian.PutUint64(raw[:8], 10001)
	for _, offset := range []int{72, 80} {
		binary.BigEndian.PutUint64(raw[offset:offset+8], 65537)
		if _, err := ActiveSegmentsV1.decodeSummary(raw); err == nil {
			t.Fatal("activity growth expanded commitment/nullifier capacity")
		}
		clear(raw[offset : offset+8])
	}
	if _, err := StorageProfile(255).decodeSummary(make([]byte, 96)); err == nil {
		t.Fatal("unknown profile accepted a zero-height response")
	}
}

func FuzzPoolSummaryProfile(f *testing.F) {
	f.Add(make([]byte, 96))
	high := make([]byte, 96)
	binary.BigEndian.PutUint64(high[:8], 10001)
	f.Add(high)
	f.Fuzz(func(t *testing.T, raw []byte) {
		legacy, oldErr := LegacyJournal.decodeSummary(raw)
		active, newErr := ActiveSegmentsV1.decodeSummary(raw)
		if oldErr == nil && (newErr != nil || legacy != active) {
			t.Fatal("legacy summary changed under the extended profile")
		}
		if newErr == nil && active.Height <= 10000 && (oldErr != nil || legacy != active) {
			t.Fatal("active profile weakened another summary bound")
		}
	})
}
