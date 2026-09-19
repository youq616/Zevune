//go:build linux

package labnet

import (
	"math"
	"os"
	"path/filepath"
	"strconv"
	"testing"

	"github.com/youq616/Zevune/internal/poolbridge"
	"golang.org/x/sys/unix"
)

func TestDiskSpaceLinuxConversionRejectsInvalidAndOverflowingUnits(t *testing.T) {
	for _, tc := range []struct {
		name     string
		blocks   uint64
		fragment int64
		block    int64
		want     uint64
		valid    bool
	}{
		{"empty", 0, 4096, 4096, 0, true},
		{"normal", 3, 4096, 4096, 12288, true},
		{"fragment-unit", 3, 1024, 4096, 3072, true},
		{"zero-fragment-fallback", 3, 0, 4096, 12288, true},
		{"maximum-value", math.MaxUint64, 1, 1, math.MaxUint64, true},
		{"last-fitting-value", math.MaxUint64 / 4096, 4096, 4096, math.MaxUint64 / 4096 * 4096, true},
		{"first-overflow", math.MaxUint64/4096 + 1, 4096, 4096, 0, false},
		{"negative-fragment", 1, -1, 4096, 0, false},
		{"negative-fallback", 1, 0, -1, 0, false},
		{"no-unit", 1, 0, 0, 0, false},
		{"empty-invalid-unit", 0, 0, 0, 0, false},
		{"signed-size-overflow", 3, math.MaxInt64, 1, 0, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			available, err := diskSpaceLinuxBytes(tc.blocks, tc.fragment, tc.block)
			if (err == nil) != tc.valid || available != tc.want {
				t.Fatalf("conversion: available=%d error=%v", available, err)
			}
		})
	}
}

func TestDiskSpaceLinuxRetainsDescriptorAndRejectsReplacement(t *testing.T) {
	for _, profile := range []poolbridge.StorageProfile{poolbridge.LegacyJournal, poolbridge.ActiveSegmentsV1} {
		t.Run(strconv.Itoa(int(profile)), func(t *testing.T) {
			parent := t.TempDir()
			path := filepath.Join(parent, "target")
			if profile == poolbridge.LegacyJournal {
				if err := os.WriteFile(path, []byte("original"), 0600); err != nil {
					t.Fatal(err)
				}
			} else if err := os.Mkdir(path, 0700); err != nil {
				t.Fatal(err)
			}
			target, err := openDiskSpaceTarget(profile, path)
			if err != nil {
				t.Fatal(err)
			}
			defer target.close()
			original := target.retained.before
			if err := os.Rename(path, path+".original"); err != nil {
				t.Fatal(err)
			}
			if profile == poolbridge.LegacyJournal {
				if err := os.WriteFile(path, []byte("replaced"), 0600); err != nil {
					t.Fatal(err)
				}
				if err := os.Chtimes(path, original.ModTime(), original.ModTime()); err != nil {
					t.Fatal(err)
				}
			} else if err := os.Mkdir(path, 0700); err != nil {
				t.Fatal(err)
			}
			opened, err := target.retained.file.Stat()
			if err != nil || !os.SameFile(original, opened) {
				t.Fatal("original descriptor was not retained")
			}
			// Direct native query still uses the original descriptor. The public
			// sample must refuse its changed namespace rather than report this.
			if _, err := diskSpaceAvailable(target); err != nil {
				t.Fatal("descriptor query failed after rename:", err)
			}
			if report, err := target.sample(1); err == nil || report != (DiskSpaceReport{}) {
				t.Fatal("replacement target produced an observation")
			}
		})
	}
}

func TestDiskSpaceLinuxNativeQueryRejectsClosedDescriptor(t *testing.T) {
	journal, _ := diskSpaceTestJournal(t)
	target, err := openDiskSpaceTarget(poolbridge.LegacyJournal, journal)
	if err != nil {
		t.Fatal(err)
	}
	defer target.close()
	if err := target.retained.file.Close(); err != nil {
		t.Fatal(err)
	}
	if available, err := diskSpaceAvailable(target); err == nil || available != 0 {
		t.Fatal("closed descriptor query became an available-space result")
	}
}

func TestDiskSpaceLinuxRefusesFIFOAndNonblockingOpenCannotHang(t *testing.T) {
	fifo := filepath.Join(t.TempDir(), "fifo")
	if err := unix.Mkfifo(fifo, 0600); err != nil {
		t.Fatal(err)
	}
	for _, profile := range []poolbridge.StorageProfile{poolbridge.LegacyJournal, poolbridge.ActiveSegmentsV1} {
		if target, err := openDiskSpaceTarget(profile, fifo); err == nil || target != nil {
			if target != nil {
				_ = target.close()
			}
			t.Fatal("FIFO accepted as a journal or active directory")
		}
	}
	// A FIFO replacing a previously checked regular file must not hang the
	// retained open. O_NONBLOCK returns; the subsequent type check rejects it.
	handle, err := openDiskSpaceHandle(fifo, false)
	if err != nil {
		t.Fatal(err)
	}
	defer handle.Close()
	info, err := handle.Stat()
	if err != nil || validDiskSpaceInfo(info, false) {
		t.Fatal("FIFO was interpreted as a regular file")
	}
	conn, err := handle.SyscallConn()
	if err != nil {
		t.Fatal(err)
	}
	var flags int
	var flagErr error
	err = conn.Control(func(fd uintptr) { flags, flagErr = unix.FcntlInt(fd, unix.F_GETFL, 0) })
	if err != nil || flagErr != nil || flags&unix.O_NONBLOCK == 0 {
		t.Fatal("retained open can block on a substituted FIFO")
	}
}

func TestDiskSpaceLinuxNoFollowAndUnlinkedTarget(t *testing.T) {
	journal, _ := diskSpaceTestJournal(t)
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(journal, link); err != nil {
		t.Fatal(err)
	}
	if handle, err := openDiskSpaceHandle(link, false); err == nil || handle != nil {
		if handle != nil {
			_ = handle.Close()
		}
		t.Fatal("retained open followed a substituted symlink")
	}
	target, err := openDiskSpaceTarget(poolbridge.LegacyJournal, journal)
	if err != nil {
		t.Fatal(err)
	}
	defer target.close()
	if err := os.Remove(journal); err != nil {
		t.Fatal(err)
	}
	if report, err := target.sample(1); err == nil || report != (DiskSpaceReport{}) {
		t.Fatal("unlinked journal produced a report")
	}
}
