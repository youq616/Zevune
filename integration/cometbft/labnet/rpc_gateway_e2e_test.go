//go:build operator_e2e

package labnet

import (
	"testing"
	"time"
)

// Start the ACTUAL separately built gateway command with supported, inherited
// local pipes. Windows uses actual overlapped handles, not synchronous os.Pipe.
// The operator/proof workers still come from the isolated verified build bundle.
func launchGatewayForOperator(t *testing.T, config, pin, upstream string) string {
	t.Helper()
	address := gatewayTestAddress(t)
	args := []string{"--no-real-funds", "--config", config, "--config-sha256", pin, "--listen", address, "--upstream", upstream, "--onion-endpoint", privateTestEndpoint, "--stop-on-stdin-eof"}
	p := newGatewayCommand(t, args)
	p.start(t)
	p.ready(t)
	t.Cleanup(func() {
		p.input.Close()
		p.wait(t, 5*time.Second, true)
		gatewayListenerClosed(t, address)
	})
	return "http://" + address
}
