//go:build linux

package labnet

import (
	"math"
	"os"

	"golang.org/x/sys/unix"
)

const diskSpaceScope = "linux_f_bavail_bytes"
const diskSpaceSupported = true
const diskSpaceUsesDirectory = false

func diskSpacePlatformInfo(_ os.FileInfo) bool { return true }

func openDiskSpaceHandle(path string, directory bool) (*os.File, error) {
	flags := unix.O_RDONLY | unix.O_CLOEXEC | unix.O_NOFOLLOW | unix.O_NONBLOCK
	if directory {
		flags |= unix.O_DIRECTORY
	}
	fd, err := unix.Open(path, flags, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), path), nil
}

// Linux's statvfs conversion uses f_frsize as the allocation unit, falling back
// to f_bsize only when f_frsize is zero. f_bavail counts blocks available to an
// unprivileged user; it is not an assertion of per-user quota or writeability.
func diskSpaceLinuxBytes(availableBlocks uint64, fragmentSize, blockSize int64) (uint64, error) {
	unit := fragmentSize
	if unit == 0 {
		unit = blockSize
	}
	if unit <= 0 || availableBlocks > math.MaxUint64/uint64(unit) {
		return 0, errDiskSpace
	}
	return availableBlocks * uint64(unit), nil
}

func diskSpaceAvailable(target *diskSpaceTarget) (uint64, error) {
	conn, err := target.retained.file.SyscallConn()
	if err != nil {
		return 0, errDiskSpace
	}
	var stat unix.Statfs_t
	var queryErr error
	// Control keeps the original descriptor valid for the real Fstatfs call;
	// the namespace pathname is never substituted as the Linux query target.
	if err := conn.Control(func(fd uintptr) { queryErr = unix.Fstatfs(int(fd), &stat) }); err != nil || queryErr != nil {
		return 0, errDiskSpace
	}
	return diskSpaceLinuxBytes(stat.Bavail, int64(stat.Frsize), int64(stat.Bsize))
}
