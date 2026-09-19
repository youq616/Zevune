package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"syscall"
	"testing"
)

func TestRunFailureOutputContainsOnlyFixedLabels(t *testing.T) {
	for _, cause := range []error{syscall.EADDRINUSE, errors.New("arbitrary-peer-or-private-path")} {
		var out bytes.Buffer
		writeFailure(&out, []string{"run", "private-argument"}, fmt.Errorf("private-context: %w", cause))
		var report map[string]string
		if json.Unmarshal(out.Bytes(), &report) != nil || len(report) != 3 || report["status"] != "local_node_failed" || report["stage"] != "validation" {
			t.Fatal("missing bounded failure record")
		}
		want := "other"
		if errors.Is(cause, syscall.EADDRINUSE) {
			want = "address_in_use"
		}
		if report["code"] != want || bytes.Contains(out.Bytes(), []byte("private")) || bytes.Contains(out.Bytes(), []byte("arbitrary")) {
			t.Fatal("unsafe or misleading run diagnostic")
		}
	}
}
