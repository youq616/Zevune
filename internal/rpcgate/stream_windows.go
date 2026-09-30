package rpcgate

import (
	"os"
	"syscall"
	"unsafe"
)

var queryStreamObject = syscall.NewLazyDLL("ntdll.dll").NewProc("NtQueryObject")

// PUBLIC_OBJECT_BASIC_INFORMATION is the documented, fixed-size result of
// NtQueryObject(ObjectBasicInformation). Query only the handle's granted access;
// never trial-Read/Write (which could block, consume input or emit output).
// https://learn.microsoft.com/windows/win32/api/winternl/nf-winternl-ntqueryobject
func streamAccess(handle syscall.Handle, read bool) error {
	// Go's syscall.InvalidHandle is ^Handle(0), which is also Windows'
	// current-process pseudo-handle value. This helper accepts pipe/file handles
	// only; reject null and pseudo/sentinel handles before querying object access.
	if handle == 0 || handle == syscall.InvalidHandle {
		return ErrConfiguration
	}
	if err := queryStreamObject.Find(); err != nil {
		return ErrConfiguration
	}
	var basic struct {
		Attributes, GrantedAccess, HandleCount, PointerCount uint32
		Reserved                                             [10]uint32
	}
	var returned uint32
	status, _, _ := queryStreamObject.Call(uintptr(handle), 0,
		uintptr(unsafe.Pointer(&basic)), unsafe.Sizeof(basic), uintptr(unsafe.Pointer(&returned)))
	// NTSTATUS, not GetLastError, is authoritative. An unavailable/changed
	// query contract must fail closed, not silently skip the access check.
	if status != 0 || returned != uint32(unsafe.Sizeof(basic)) {
		return ErrConfiguration
	}
	const fileReadData = 0x00000001
	const fileWriteData = 0x00000002
	required := uint32(fileWriteData)
	if read {
		required = fileReadData
	}
	if basic.GrantedAccess&required != required {
		return ErrConfiguration
	}
	return nil
}

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
	// Deadline capability does not prove read/write permission. Check the
	// original granted direction before duplicating or starting any service.
	if err := streamAccess(h, read); err != nil {
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
