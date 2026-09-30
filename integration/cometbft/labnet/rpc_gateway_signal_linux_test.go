//go:build operator_e2e

package labnet

import (
	"os/exec"
	"syscall"
	"testing"
)

func prepareGatewaySignal(*testing.T, *exec.Cmd) {}
func signalGateway(t *testing.T, cmd *exec.Cmd) {
	t.Helper()
	if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
}
