//go:build operator_e2e

package labnet

import (
	"bufio"
	"io"
	"net"
	"os/exec"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/rpcgate"
)

// Start the ACTUAL separately built gateway command. The preexisting operator
// and proof workers are still taken from their isolated, verified build bundle.
func launchGatewayForOperator(t *testing.T, config, pin, upstream string) string {
	t.Helper()
	address := gatewayTestAddress(t)
	cmd := exec.Command(requiredExecutable(t, "ZEVUNE_RPC_GATEWAY"), "--no-real-funds", "--config", config, "--config-sha256", pin, "--listen", address, "--upstream", upstream, "--onion-endpoint", privateTestEndpoint, "--stop-on-stdin-eof")
	input, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	output, err := cmd.StdoutPipe()
	if err != nil {
		input.Close()
		t.Fatal(err)
	}
	cmd.Stderr = io.Discard // command errors are fixed; never print scenario data
	if err = cmd.Start(); err != nil {
		input.Close()
		output.Close()
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	t.Cleanup(func() {
		input.Close()
		select {
		case err := <-done:
			if err != nil {
				t.Error("gateway process failed", err)
			}
		case <-time.After(5 * time.Second):
			cmd.Process.Kill()
			<-done
			t.Error("gateway did not stop on stdin EOF")
		}
		output.Close()
		c, err := net.DialTimeout("tcp4", address, 200*time.Millisecond)
		if err == nil {
			c.Close()
			t.Error("gateway left listener after process stop")
		}
	})
	ready := make(chan string, 1)
	go func() { line, _ := bufio.NewReader(io.LimitReader(output, 512)).ReadString('\n'); ready <- line }()
	select {
	case line := <-ready:
		if line != rpcgate.ReadyRecord {
			t.Fatal("gateway readiness rejected")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("gateway readiness timeout")
	}
	return "http://" + address
}
