//go:build windows

package labnet

import (
	"errors"
	"syscall"

	"golang.org/x/sys/windows"
)

// Windows socket operations return Winsock values, not the generic errno
// constants. Retain both identities without inspecting arbitrary error text.
func isAddressInUse(err error) bool {
	return errors.Is(err, windows.WSAEADDRINUSE) || errors.Is(err, syscall.EADDRINUSE)
}

func isConnectionRefused(err error) bool {
	return errors.Is(err, windows.WSAECONNREFUSED) || errors.Is(err, syscall.ECONNREFUSED)
}
