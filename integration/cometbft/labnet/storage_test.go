package labnet

import (
	"context"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/poolbridge"
)

func TestStorageReportBoundariesAndNoFinalityClaims(t *testing.T) {
	normal := poolbridge.Summary{Height: 1, Commitments: 2, AppHash: Hash{1}}
	for _, tc := range []struct {
		name     string
		state    poolbridge.Summary
		size     int64
		fits     bool
		warnings []string
	}{
		{"normal", normal, 194, true, []string{}},
		{"exact-empty", normal, int64(journalLimitBytes - 150), true, []string{"journal_byte_limit_approaching"}},
		{"one-short", normal, int64(journalLimitBytes - 149), false, []string{"insufficient_bytes_for_empty_record"}},
		{"byte-limit", normal, int64(journalLimitBytes), false, []string{"insufficient_bytes_for_empty_record"}},
		{"record-limit", poolbridge.Summary{Height: recordLimit}, int64(44 + 150*recordLimit), false, []string{"record_limit_reached"}},
		{"record-warning", poolbridge.Summary{Height: 9000}, 1350044, true, []string{"record_limit_approaching"}},
		{"record-before-warning", poolbridge.Summary{Height: 8999}, 1349894, true, []string{}},
		{"one-output-slot", poolbridge.Summary{Commitments: commitmentLimit - 1}, 44, true, []string{"insufficient_commitment_slots_for_payment"}},
		{"two-output-slots", poolbridge.Summary{Commitments: commitmentLimit - 2}, 44, true, []string{"commitment_limit_approaching"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r, err := storageReport(tc.state, tc.size)
			if err != nil {
				t.Fatal(err)
			}
			if r.EmptyBlockFitsLimits != tc.fits || !reflect.DeepEqual(r.Warnings, tc.warnings) {
				t.Fatalf("wrong margins/warnings: %+v", r)
			}
			if r.JournalBytes+r.JournalRemainingBytes != journalLimitBytes ||
				r.RecordsRemaining+r.Height != recordLimit ||
				r.Commitments+r.CommitmentsRemaining != commitmentLimit {
				t.Fatal("accounting identity failed")
			}
			if r.ConsensusVerified || r.NetworkAccessed || r.RealFundsAllowed ||
				r.Scope != "offline_replayed_journal_capacity_not_finality" {
				t.Fatal("overstated inspection")
			}
		})
	}
}

func TestStorageReportRejectsContradictoryCounts(t *testing.T) {
	for _, tc := range []struct {
		s    poolbridge.Summary
		size int64
	}{
		{poolbridge.Summary{}, -1}, {poolbridge.Summary{}, math.MaxInt64},
		{poolbridge.Summary{}, 43}, {poolbridge.Summary{Height: 1}, 193},
		{poolbridge.Summary{Height: recordLimit + 1}, int64(journalLimitBytes)},
		{poolbridge.Summary{Height: math.MaxUint64}, int64(journalLimitBytes)},
		{poolbridge.Summary{Commitments: commitmentLimit + 1}, 44},
		{poolbridge.Summary{Nullifiers: commitmentLimit + 1}, 44},
	} {
		if r, err := storageReport(tc.s, tc.size); err == nil || r.Scope != "" {
			t.Fatal("invalid capacity produced report")
		}
	}
}

func TestJournalMetadataIsReadOnlyAndDetectsOrdinaryChanges(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "journal")
	if err := os.WriteFile(path, make([]byte, 44), 0600); err != nil {
		t.Fatal(err)
	}
	first, err := journalInfo(path)
	if err != nil {
		t.Fatal(err)
	}
	again, err := journalInfo(path)
	if err != nil || !sameJournal(first, again) {
		t.Fatal("same file rejected")
	}
	if sameJournal(nil, again) || sameJournal(first, nil) {
		t.Fatal("nil metadata accepted")
	}
	if err := os.Chtimes(path, time.Now(), first.ModTime().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	changed, err := journalInfo(path)
	if err != nil || sameJournal(first, changed) {
		t.Fatal("mtime change accepted")
	}
	if err := os.WriteFile(path, make([]byte, 45), 0600); err != nil {
		t.Fatal(err)
	}
	changed, err = journalInfo(path)
	if err != nil || sameJournal(first, changed) {
		t.Fatal("size change accepted")
	}
	replacement := filepath.Join(dir, "replacement")
	if err := os.WriteFile(replacement, make([]byte, 44), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(replacement, first.ModTime(), first.ModTime()); err != nil {
		t.Fatal(err)
	}
	other, err := journalInfo(replacement)
	if err != nil || sameJournal(first, other) {
		t.Fatal("different inode accepted")
	}
}

func TestStorageMissingInvalidPathsNeverCreateData(t *testing.T) {
	dir := t.TempDir()
	missing := filepath.Join(dir, "absent")
	for _, path := range []string{"relative", "", dir, missing} {
		if _, err := journalInfo(path); err == nil {
			t.Fatal("invalid path accepted")
		}
	}
	n := &Network{}
	for _, ctx := range []context.Context{nil, context.Background()} {
		if _, err := n.InspectStorage(ctx, "", Hash{}, missing); err == nil {
			t.Fatal("invalid request accepted")
		}
	}
	var absent *Network
	if _, err := absent.InspectStorage(context.Background(), "", Hash{}, missing); err == nil {
		t.Fatal("nil network accepted")
	}
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Fatal("inspection created absent file")
	}
	small := filepath.Join(dir, "small")
	if err := os.WriteFile(small, make([]byte, 43), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := journalInfo(small); err == nil {
		t.Fatal("short journal accepted")
	}
}

func FuzzStorageAccounting(f *testing.F) {
	f.Add(uint64(0), uint64(0), uint64(0), int64(44))
	f.Add(uint64(recordLimit), uint64(commitmentLimit), uint64(commitmentLimit), int64(journalLimitBytes))
	f.Fuzz(func(t *testing.T, h, c, n uint64, size int64) {
		r, err := storageReport(poolbridge.Summary{Height: h, Commitments: c, Nullifiers: n}, size)
		if err != nil {
			return
		}
		if r.JournalBytes+r.JournalRemainingBytes != journalLimitBytes ||
			r.Height+r.RecordsRemaining != recordLimit ||
			r.Commitments+r.CommitmentsRemaining != commitmentLimit ||
			r.ConsensusVerified || r.NetworkAccessed || r.RealFundsAllowed {
			t.Fatal("unsafe capacity report")
		}
	})
}
