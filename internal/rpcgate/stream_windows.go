package rpcgate

import (
	"os"
	"syscall"
)

// Only inherited FILE_FLAG_OVERLAPPED pipes are supported on Windows. Go's
// NewFile attempts IOCP registration for these handles; prepareStream checks
// that a deadline was actually enabled. Ordinary CreatePipe/console/disk handles
// are deliberately rejected, never used as synchronous cancellation fallbacks.
//
// No I/O is in flight on this endpoint: ownership is transferred before calling
// this function. Fd detaches a pre-existing Go IOCP association (Go 1.27.1).
// The duplicate differs from syscall.Stdin, whose NewFile path skips mode
// detection. Close the old wrapper before registering the duplicate with IOCP.
func streamPipe(f *os.File, read bool) (*os.File, error) {
	h := syscall.Handle(f.Fd())
	typ, err := syscall.GetFileType(h)
	if err != nil || typ != syscall.FILE_TYPE_PIPE {
		return nil, ErrConfiguration
	}
	process, err := syscall.GetCurrentProcess()
	if err != nil {
		return nil, ErrConfiguration
	}
	var duplicate syscall.Handle
	if err := syscall.DuplicateHandle(process, h, process, &duplicate, 0, false, syscall.DUPLICATE_SAME_ACCESS); err != nil {
		return nil, ErrConfiguration
	}
	if err := f.Close(); err != nil {
		syscall.CloseHandle(duplicate)
		return nil, ErrConfiguration
	}
	p := os.NewFile(uintptr(duplicate), "gateway-pipe")
	if p == nil {
		syscall.CloseHandle(duplicate)
		return nil, ErrConfiguration
	}
	return p, nil
}
