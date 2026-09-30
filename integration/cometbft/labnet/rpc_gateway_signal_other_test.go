//go:build operator_e2e && !linux && !windows

package labnet

import (
	"os/exec"
	"testing"
)

func prepareGatewaySignal(t *testing.T, _ *exec.Cmd) {
	t.Fatal("unsupported native gateway signal host")
}
func signalGateway(t *testing.T, _ *exec.Cmd) { t.Fatal("unsupported native gateway signal host") }
