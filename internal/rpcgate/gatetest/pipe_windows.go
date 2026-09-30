package gatetest

import (
	"crypto/rand"
	"encoding/hex"
	"os"
	"syscall"
	"unsafe"
)

// Windows os.Pipe uses synchronous CreatePipe handles. This fixture instead
// creates actual local byte pipes with FILE_FLAG_OVERLAPPED on BOTH endpoints.
// The production CLI neither creates nor connects named pipes; it only adopts
// independently supplied inherited handles and verifies deadline capability.
func Pipe() (*os.File, *os.File, error) {
	var nonce [16]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return nil, nil, err
	}
	path, err := syscall.UTF16PtrFromString(`\\.\pipe\zevune-gateway-test-` + hex.EncodeToString(nonce[:]))
	if err != nil {
		return nil, nil, err
	}
	create := syscall.NewLazyDLL("kernel32.dll").NewProc("CreateNamedPipeW")
	const inbound = 1
	const firstInstance = 0x00080000
	const rejectRemoteClients = 8
	h, _, callErr := create.Call(uintptr(unsafe.Pointer(path)), inbound|syscall.FILE_FLAG_OVERLAPPED|firstInstance, rejectRemoteClients, 1, 4096, 4096, 0, 0)
	server := syscall.Handle(h)
	if server == syscall.InvalidHandle {
		return nil, nil, callErr
	}
	client, err := syscall.CreateFile(path, syscall.GENERIC_WRITE, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OVERLAPPED, 0)
	if err != nil {
		syscall.CloseHandle(server)
		return nil, nil, err
	}
	// CreateFile has connected the client to this sole server instance already.
	return os.NewFile(uintptr(server), "gateway-test-read"), os.NewFile(uintptr(client), "gateway-test-write"), nil
}
