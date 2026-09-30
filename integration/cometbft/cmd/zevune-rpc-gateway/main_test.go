package main

import (
	"context"
	"errors"
	"testing"

	"github.com/youq616/Zevune/internal/rpcgate"
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

func TestInputCompletionDoesNotHideFailure(t *testing.T) {
	for _, tt := range []struct {
		name                       string
		serviceErr, inputErr, want error
	}{
		{"eof", nil, nil, nil},
		{"requested-cancel", nil, context.Canceled, nil},
		{"requested-deadline", nil, context.DeadlineExceeded, nil},
		{"input-io-failure", nil, rpcgate.ErrService, rpcgate.ErrService},
		{"input-unexpected-failure", nil, errors.New("not for diagnostics"), rpcgate.ErrService},
		{"preserve-ready-failure", rpcgate.ErrReady, rpcgate.ErrService, rpcgate.ErrReady},
		{"preserve-start-failure", rpcgate.ErrConfiguration, context.Canceled, rpcgate.ErrConfiguration},
	} {
		t.Run(tt.name, func(t *testing.T) {
			if got := inputCompletion(tt.serviceErr, tt.inputErr); got != tt.want {
				t.Fatalf("input completion got %v, want %v", got, tt.want)
			}
		})
	}
}
