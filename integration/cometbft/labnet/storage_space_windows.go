//go:build windows

package labnet

import (
	"os"
	"strings"
	"syscall"

	"golang.org/x/sys/windows"
)

const diskSpaceScope = "windows_caller_available_bytes"
const diskSpaceSupported = true
const diskSpaceUsesDirectory = true

func diskSpacePlatformInfo(info os.FileInfo) bool {
	attributes, ok := info.Sys().(*syscall.Win32FileAttributeData)
	return ok && attributes.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT == 0
}

func openDiskSpaceHandle(path string, directory bool) (*os.File, error) {
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	access := uint32(windows.FILE_READ_ATTRIBUTES)
	if directory {
		access |= windows.FILE_LIST_DIRECTORY
	} else {
		// Data-read access makes the retained file participate in sharing
		// checks. The probe never reads its contents, so a worker's exclusive
		// byte-range lock remains compatible with these metadata operations.
		access |= windows.FILE_READ_DATA
	}
	// Denying DELETE sharing retains the name during normal rename/delete
	// attempts; OPEN_REPARSE_POINT permits explicit refusal of reparse points.
	handle, err := windows.CreateFile(name, access, windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE,
		nil, windows.OPEN_EXISTING, windows.FILE_FLAG_BACKUP_SEMANTICS|windows.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(handle), path), nil
}

func diskSpaceWindowsBytes(directory string) (uint64, error) {
	// GetDiskFreeSpaceEx accepts a directory, including a non-root directory.
	// UNC directory names require a trailing backslash. The caller retains and
	// verifies that directory before and after this pathname-based operation.
	name, err := windows.UTF16PtrFromString(strings.TrimRight(directory, `\`) + `\`)
	if err != nil {
		return 0, errDiskSpace
	}
	var available uint64
	// The first output is available to this calling thread's user, including
	// applicable per-user quotas. Total/free volume outputs have other meanings.
	if err := windows.GetDiskFreeSpaceEx(name, &available, nil, nil); err != nil {
		return 0, errDiskSpace
	}
	return available, nil
}

func diskSpaceAvailable(target *diskSpaceTarget) (uint64, error) {
	directory := target.retained
	if !directory.directory {
		directory = target.queryDirectory
	}
	if directory == nil {
		return 0, errDiskSpace
	}
	return diskSpaceWindowsBytes(directory.path)
}
