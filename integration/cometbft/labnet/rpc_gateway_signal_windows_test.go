//go:build operator_e2e

package labnet

import (
	"os/exec"
	"syscall"
	"testing"
	"unsafe"
)

// CTRL_BREAK targets only the child's NEW process group. Ensure the test runner
// owns a console so GenerateConsoleCtrlEvent can deliver a genuine OS signal;
// do not replace the command with a helper or add a production test-only flag.
func prepareGatewaySignal(t *testing.T, cmd *exec.Cmd) {
	t.Helper()
	kernel := syscall.NewLazyDLL("kernel32.dll")
	var process uint32
	count, _, _ := kernel.NewProc("GetConsoleProcessList").Call(uintptr(unsafe.Pointer(&process)), 1)
	if count == 0 {
		ok, _, err := kernel.NewProc("AllocConsole").Call()
		if ok == 0 {
			t.Fatal("test could not allocate signal console", err)
		}
		t.Cleanup(func() { kernel.NewProc("FreeConsole").Call() })
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: syscall.CREATE_NEW_PROCESS_GROUP}
}

func signalGateway(t *testing.T, cmd *exec.Cmd) {
	t.Helper()
	const ctrlBreak = 1
	ok, _, err := syscall.NewLazyDLL("kernel32.dll").NewProc("GenerateConsoleCtrlEvent").Call(ctrlBreak, uintptr(cmd.Process.Pid))
	if ok == 0 {
		t.Fatal("test could not send child control signal", err)
	}
}
