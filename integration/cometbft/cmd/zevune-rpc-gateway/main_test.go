package main

import (
	"context"
	"testing"
)

func TestStrictGatewayFlags(t *testing.T) {
	good := []string{"--no-real-funds", "--config", "/not-opened", "--config-sha256", "pin", "--listen", "127.0.0.1:8080", "--upstream", "http://127.0.0.1:26657", "--onion-endpoint", "explicit-onion"}
	o, err := parse(good)
	if err != nil || !o.gateway.NoRealFunds {
		t.Fatal("flag parsing", err)
	}
	tests := [][]string{nil, {"--no-real-funds"}, append(append([]string{}, good...), "extra"), append(append([]string{}, good...), "--listen", "127.0.0.1:9000"), append(append([]string{}, good...), "--skip-proof"), append(append([]string{}, good...), "--stop-on-stdin-eof=")}
	for _, args := range tests {
		if _, err := parse(args); err == nil {
			t.Fatal("invalid flags accepted")
		}
	}
	// Rejection does not need a network, wallet, listener or readiness writer.
	if execute(context.Background(), good, nil, nil) == nil {
		t.Fatal("missing output")
	}
}
