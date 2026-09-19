//go:build linux || windows

package labnet

import (
	"bytes"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/poolbridge"
)

func diskSpaceTestJournal(t *testing.T) (string, []byte) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "journal")
	data := []byte("disk probe metadata fixture; not a valid worker journal")
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	return path, data
}

func TestDiskSpaceRealTargetsAreReadOnlyAndRetained(t *testing.T) {
	journal, content := diskSpaceTestJournal(t)
	for _, tc := range []struct {
		name    string
		profile poolbridge.StorageProfile
		path    string
	}{
		{"legacy", poolbridge.LegacyJournal, journal},
		{"active", poolbridge.ActiveSegmentsV1, t.TempDir()},
	} {
		t.Run(tc.name, func(t *testing.T) {
			before, err := os.Stat(tc.path)
			if err != nil {
				t.Fatal(err)
			}
			target, err := openDiskSpaceTarget(tc.profile, tc.path)
			if err != nil {
				t.Fatal(err)
			}
			defer target.close()
			if err := target.verify(); err != nil {
				t.Fatal(err)
			}
			for _, reserve := range []uint64{1, math.MaxUint64} {
				report, err := target.sample(reserve)
				if err != nil {
					t.Fatal(err)
				}
				if report.Scope != diskSpaceScope || report.ReserveBytes != reserve || report.SpaceReserved ||
					report.LowSpace != (report.AvailableBytes <= reserve) {
					t.Fatalf("invalid OS sample: %+v", report)
				}
			}
			if _, err := target.retained.file.Write([]byte("must not be written")); err == nil {
				t.Fatal("retained disk probe handle is writable")
			}
			if err := target.close(); err != nil {
				t.Fatal(err)
			}
			if err := target.close(); err != nil {
				t.Fatal("successful cleanup is not idempotent")
			}
			if report, err := target.sample(1); err == nil || report != (DiskSpaceReport{}) {
				t.Fatal("closed target produced a sample")
			}
			after, err := os.Stat(tc.path)
			if err != nil || !os.SameFile(before, after) || before.Size() != after.Size() ||
				!before.ModTime().Equal(after.ModTime()) {
				t.Fatal("disk query changed the target")
			}
			if tc.profile == poolbridge.ActiveSegmentsV1 {
				entries, err := os.ReadDir(tc.path)
				if err != nil || len(entries) != 0 {
					t.Fatal("disk query created a probe file")
				}
			}
		})
	}
	after, err := os.ReadFile(journal)
	if err != nil || !bytes.Equal(content, after) {
		t.Fatal("disk inspection changed journal bytes")
	}
}

func TestDiskSpaceRejectsMissingWrongTypeAndAmbiguousPaths(t *testing.T) {
	journal, _ := diskSpaceTestJournal(t)
	directory := t.TempDir()
	missing := filepath.Join(directory, "missing")
	for _, tc := range []struct {
		profile poolbridge.StorageProfile
		path    string
	}{
		{poolbridge.LegacyJournal, ""},
		{poolbridge.LegacyJournal, "journal"},
		{poolbridge.LegacyJournal, missing},
		{poolbridge.ActiveSegmentsV1, missing},
		{poolbridge.LegacyJournal, directory},
		{poolbridge.ActiveSegmentsV1, journal},
		{poolbridge.ActiveSegmentsV1, directory + string(os.PathSeparator) + "."},
		{poolbridge.LegacyJournal, journal + "\x00"},
		{poolbridge.StorageProfile(255), journal},
	} {
		if target, err := openDiskSpaceTarget(tc.profile, tc.path); err == nil || target != nil {
			if target != nil {
				_ = target.close()
			}
			t.Fatalf("invalid disk target accepted: profile=%v path=%q", tc.profile, tc.path)
		}
	}
	if _, err := os.Lstat(missing); !os.IsNotExist(err) {
		t.Fatal("missing target was created")
	}
	if validDiskSpaceInfo(nil, false) || validDiskSpaceInfo(nil, true) {
		t.Fatal("nil file metadata accepted")
	}
}

func TestDiskSpaceRefusesSymbolicLinkRoots(t *testing.T) {
	journal, _ := diskSpaceTestJournal(t)
	for _, tc := range []struct {
		profile poolbridge.StorageProfile
		path    string
	}{
		{poolbridge.LegacyJournal, journal},
		{poolbridge.ActiveSegmentsV1, t.TempDir()},
	} {
		link := filepath.Join(t.TempDir(), "link")
		if err := os.Symlink(tc.path, link); err != nil {
			if runtime.GOOS == "windows" {
				t.Skipf("Windows symlink creation unavailable: %v", err)
			}
			t.Fatal(err)
		}
		if target, err := openDiskSpaceTarget(tc.profile, link); err == nil || target != nil {
			if target != nil {
				_ = target.close()
			}
			t.Fatal("disk query accepted a symbolic link root")
		}
	}
}

func TestDiskSpaceDetectsJournalGrowthAndMetadataChanges(t *testing.T) {
	for _, change := range []string{"size", "mtime"} {
		t.Run(change, func(t *testing.T) {
			journal, content := diskSpaceTestJournal(t)
			target, err := openDiskSpaceTarget(poolbridge.LegacyJournal, journal)
			if err != nil {
				t.Fatal(err)
			}
			defer target.close()
			if change == "size" {
				if err := os.WriteFile(journal, append(content, 0), 0600); err != nil {
					t.Fatal(err)
				}
			} else {
				changed := target.retained.before.ModTime().Add(2 * time.Second)
				if err := os.Chtimes(journal, changed, changed); err != nil {
					t.Fatal(err)
				}
			}
			if err := target.verify(); err == nil {
				t.Fatal("journal change was accepted")
			}
			if report, err := target.sample(1); err == nil || report != (DiskSpaceReport{}) {
				t.Fatal("journal change produced a health report")
			}
		})
	}
}

func TestDiskSpaceClosedHandlesReturnErrorsWithoutReports(t *testing.T) {
	journal, _ := diskSpaceTestJournal(t)
	target, err := openDiskSpaceTarget(poolbridge.LegacyJournal, journal)
	if err != nil {
		t.Fatal(err)
	}
	defer target.close()
	if err := target.retained.file.Close(); err != nil {
		t.Fatal(err)
	}
	if err := target.verify(); err == nil {
		t.Fatal("closed handle accepted")
	}
	if report, err := target.sample(math.MaxUint64); err == nil || report != (DiskSpaceReport{}) {
		t.Fatal("closed handle was converted into low space or healthy report")
	}
	if err := target.close(); err == nil {
		t.Fatal("underlying close error was hidden")
	}
	if err := target.close(); err == nil {
		t.Fatal("subsequent cleanup erased the close error")
	}
	if target.queryDirectory != nil {
		if _, err := target.queryDirectory.file.Stat(); err == nil {
			t.Fatal("failed target close leaked the query directory handle")
		}
	}
}
