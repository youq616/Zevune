package rpcgate

import (
	"os"
	"syscall"
	"testing"
)

func descriptorFlags(t *testing.T, f *os.File) uintptr {
	t.Helper()
	raw, err := f.SyscallConn()
	if err != nil {
		t.Fatal(err)
	}
	var flags uintptr
	if err := raw.Control(func(fd uintptr) {
		var errno syscall.Errno
		flags, _, errno = syscall.Syscall(syscall.SYS_FCNTL, fd, syscall.F_GETFL, 0)
		if errno != 0 {
			t.Error(errno)
		}
	}); err != nil {
		t.Fatal(err)
	}
	return flags
}

func TestAdoptingLinuxPipeDoesNotMutateSharedDescription(t *testing.T) {
	r, w := streamTestPipe(t)
	// Calling Fd explicitly models an inherited BLOCKING endpoint. A duplicate
	// retains the same original open-file description for the post-check.
	fd := int(w.Fd())
	probeFD, err := syscall.Dup(fd)
	if err != nil {
		t.Fatal(err)
	}
	probe := os.NewFile(uintptr(probeFD), "probe")
	defer probe.Close()
	before := descriptorFlags(t, probe)
	if before&syscall.O_NONBLOCK != 0 {
		t.Fatal("probe not blocking")
	}
	out, err := OpenOutput(w)
	if err != nil {
		t.Fatal(err)
	}
	defer out.Close()
	if descriptorFlags(t, probe) != before || descriptorFlags(t, out.file)&syscall.O_NONBLOCK == 0 {
		t.Fatal("shared parent mode changed or owned descriptor not nonblocking")
	}
	r.Close()
}

func TestLinuxWrongDirectionIsRejected(t *testing.T) {
	r, _ := streamTestPipe(t)
	if _, err := OpenOutput(r); err == nil {
		t.Fatal("read endpoint adopted for output")
	}
	_, w := streamTestPipe(t)
	if _, err := OpenInput(w); err == nil {
		t.Fatal("write endpoint adopted for input")
	}
}
