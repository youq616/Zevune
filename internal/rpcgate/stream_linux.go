package rpcgate

import (
	"os"
	"strconv"
	"syscall"
)

// Reopening a pipe through proc creates a NEW open-file description. Merely
// dup+SetNonblock would change the parent's shared O_NONBLOCK status as well.
// No Fd call (which can switch os.Pipe back to blocking) is used on Linux.
// procfs and exclusive ownership of the original descriptor are prerequisites.
func streamPipe(f *os.File, read bool) (*os.File, error) {
	raw, err := f.SyscallConn()
	if err != nil {
		return nil, err
	}
	var p *os.File
	var openErr error
	err = raw.Control(func(fd uintptr) {
		flags, _, errno := syscall.Syscall(syscall.SYS_FCNTL, fd, syscall.F_GETFL, 0)
		if errno != 0 {
			openErr = errno
			return
		}
		access := int(flags) & syscall.O_ACCMODE
		mode := os.O_WRONLY
		if read {
			mode = os.O_RDONLY
		}
		if access != mode && access != os.O_RDWR {
			openErr = ErrConfiguration
			return
		}
		p, openErr = os.OpenFile("/proc/self/fd/"+strconv.FormatUint(uint64(fd), 10), mode|syscall.O_NONBLOCK, 0)
	})
	if err != nil || openErr != nil {
		if p != nil {
			p.Close()
		}
		return nil, ErrConfiguration
	}
	before, e1 := f.Stat()
	after, e2 := p.Stat()
	if e1 != nil || e2 != nil || !os.SameFile(before, after) || after.Mode()&os.ModeNamedPipe == 0 {
		p.Close()
		return nil, ErrConfiguration
	}
	return p, nil
}
