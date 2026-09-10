//go:build windows

package ledger

import (
	"os"
	"runtime"
	"syscall"
	"unsafe"
)

var lockFileEx = syscall.NewLazyDLL("kernel32.dll").NewProc("LockFileEx")

func lockJournal(f *os.File) error {
	var overlapped syscall.Overlapped
	// Exclusive, non-blocking OS lock; released when this file handle closes.
	r, _, err := lockFileEx.Call(f.Fd(), 3, 0, 1, 0, uintptr(unsafe.Pointer(&overlapped)))
	runtime.KeepAlive(f)
	if r == 0 {
		return err
	}
	return nil
}

// File.Sync flushes journal contents. No directory-fsync durability guarantee is
// claimed on Windows, network shares, removable media, or sudden power loss.
func syncJournalDirectory(string) error { return nil }
