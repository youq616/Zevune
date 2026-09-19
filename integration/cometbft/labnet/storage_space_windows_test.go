//go:build windows

package labnet

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/youq616/Zevune/internal/poolbridge"
	"golang.org/x/sys/windows"
)

func TestDiskSpaceWindowsQueriesCallerAvailableAndRejectsOSErrors(t *testing.T) {
	dir := t.TempDir()
	if _, err := diskSpaceWindowsBytes(dir); err != nil {
		t.Fatal("real GetDiskFreeSpaceEx query failed:", err)
	}
	for _, path := range []string{filepath.Join(dir, "missing"), dir + "\x00"} {
		if available, err := diskSpaceWindowsBytes(path); err == nil || available != 0 {
			t.Fatal("OS query failure became zero-space or healthy observation")
		}
	}
}

func TestDiskSpaceWindowsRetainedNamesDenyDeleteAndRename(t *testing.T) {
	journal, _ := diskSpaceTestJournal(t)
	for _, tc := range []struct {
		profile poolbridge.StorageProfile
		path    string
	}{
		{poolbridge.LegacyJournal, journal},
		{poolbridge.ActiveSegmentsV1, t.TempDir()},
	} {
		target, err := openDiskSpaceTarget(tc.profile, tc.path)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.Rename(tc.path, tc.path+".renamed"); err == nil {
			_ = target.close()
			t.Fatal("retained target allowed rename")
		}
		if err := os.Remove(tc.path); err == nil {
			_ = target.close()
			t.Fatal("retained target allowed deletion")
		}
		if err := target.verify(); err != nil {
			_ = target.close()
			t.Fatal("denied mutation changed the target:", err)
		}
		if err := target.close(); err != nil {
			t.Fatal(err)
		}
	}
}

func TestDiskSpaceWindowsLegacyQueryDirectoryIsRetained(t *testing.T) {
	parent := filepath.Join(t.TempDir(), "parent")
	if err := os.Mkdir(parent, 0700); err != nil {
		t.Fatal(err)
	}
	journal := filepath.Join(parent, "journal")
	if err := os.WriteFile(journal, []byte("metadata fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	target, err := openDiskSpaceTarget(poolbridge.LegacyJournal, journal)
	if err != nil {
		t.Fatal(err)
	}
	defer target.close()
	if target.queryDirectory == nil || target.queryDirectory.path != parent {
		t.Fatal("legacy GetDiskFreeSpaceEx has no retained query directory")
	}
	if err := os.Rename(parent, parent+".renamed"); err == nil {
		t.Fatal("query directory allowed rename")
	}
	if err := target.queryDirectory.file.Close(); err != nil {
		t.Fatal(err)
	}
	if report, err := target.sample(1); err == nil || report != (DiskSpaceReport{}) {
		t.Fatal("closed query directory produced a report")
	}
	if err := target.close(); err == nil {
		t.Fatal("query directory close failure was hidden")
	}
	if _, err := target.retained.file.Stat(); err == nil {
		t.Fatal("query directory failure leaked the journal handle")
	}
}

func TestDiskSpaceWindowsReadOnlyHandleCoexistsWithExclusiveByteLock(t *testing.T) {
	journal, _ := diskSpaceTestJournal(t)
	target, err := openDiskSpaceTarget(poolbridge.LegacyJournal, journal)
	if err != nil {
		t.Fatal(err)
	}
	defer target.close()
	worker, err := os.OpenFile(journal, os.O_RDWR, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer worker.Close()
	var overlapped windows.Overlapped
	if err := windows.LockFileEx(windows.Handle(worker.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY,
		0, 1, 0, &overlapped); err != nil {
		t.Fatal("retained read-only handle prevented an exclusive worker lock:", err)
	}
	defer windows.UnlockFileEx(windows.Handle(worker.Fd()), 0, 1, 0, &overlapped)
	if report, err := target.sample(1); err != nil || report.Scope != diskSpaceScope {
		t.Fatal("OS observation tried to read locked journal bytes:", err)
	}
}
