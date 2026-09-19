package labnet

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"strings"
	"syscall"
	"testing"

	"github.com/youq616/Zevune/internal/poolbridge"
)

func TestNodeFailureKeepsClassificationAndHidesUnderlyingText(t *testing.T) {
	for _, tc := range []struct {
		err  error
		code string
	}{
		{&net.OpError{Op: "listen", Net: "tcp", Err: syscall.EADDRINUSE}, "address_in_use"},
		{context.DeadlineExceeded, "deadline"},
		{poolbridge.ErrUnavailable, "worker_unavailable"},
		{ErrNodeStopped, "consensus_stopped"},
		{errors.New("unclassified sensitive fixture"), "configuration"},
	} {
		cause := fmt.Errorf("do-not-emit-this-path: %w", tc.err)
		err := &nodeRunError{stage: "consensus_start", err: errors.Join(ErrConfiguration, cause)}
		if !errors.Is(err, tc.err) || !errors.Is(err, ErrConfiguration) {
			t.Fatal("node failure discarded original error identity")
		}
		report := DescribeNodeFailure(err)
		if report.Stage != "consensus_start" || report.Code != tc.code {
			t.Fatal("wrong public failure classification", report)
		}
		raw, marshalErr := json.Marshal(report)
		if marshalErr != nil || strings.Contains(string(raw), "do-not-emit") || strings.Contains(err.Error(), "do-not-emit") {
			t.Fatal("diagnostic exposed underlying error text")
		}
	}
}

func TestNodeValidationFailureHasSafeStage(t *testing.T) {
	var network *Network
	err := network.Run(context.Background(), "", Hash{}, 0, 35000, nil)
	if !errors.Is(err, ErrBounds) || DescribeNodeFailure(err) != (NodeFailure{Stage: "validation", Code: "bounds"}) {
		t.Fatal("invalid node request lost its safe failure stage", err)
	}
}

func TestActualOccupiedSocketHasSafeAddressInUseCode(t *testing.T) {
	held, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal("cannot hold diagnostic socket")
	}
	defer held.Close()
	other, err := net.Listen("tcp", held.Addr().String())
	if err == nil {
		_ = other.Close()
		t.Fatal("occupied socket unexpectedly accepted another listener")
	}
	if code := nodeFailureCode(err); code != "address_in_use" {
		t.Fatal("native socket error did not retain its safe classification", code)
	}
}
