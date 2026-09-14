package main

import (
	"bytes"
	"context"
	"errors"
	"path/filepath"
	"testing"

	"github.com/youq616/Zevune/integration/cometbft/labnet"
)

func TestSyncSubmitRejectInvalidCheckpointBeforeOtherInput(t *testing.T) {
	worker := filepath.Join(t.TempDir(), "must-not-start")
	hash := labnet.HashText(labnet.Hash{1})
	for _, command := range []string{"sync", "submit"} {
		for _, flags := range [][]string{
			{"--expected-height", "", "--expected-app-hash", ""},
			{"--expected-height", ""}, {"--expected-app-hash", ""},
			{"--expected-height=0"}, {"--expected-app-hash=" + hash},
			{"--expected-height=00", "--expected-app-hash=" + hash},
			{"--expected-height=0", "--expected-app-hash=" + hash, "--expected-height=1"},
		} {
			args := append([]string{command, "--no-real-funds", "--worker", worker}, flags...)
			var out bytes.Buffer
			if err := execute(context.Background(), args, nil, &out); !errors.Is(err, labnet.ErrBounds) || out.Len() != 0 {
				t.Fatal("invalid checkpoint did not fail before other input", command, err)
			}
		}
	}
	args := []string{"sync", "--no-real-funds", "--worker", worker, "--create", "--expected-height=0", "--expected-app-hash=" + hash}
	var out bytes.Buffer
	if err := execute(context.Background(), args, nil, &out); !errors.Is(err, labnet.ErrBounds) || out.Len() != 0 {
		t.Fatal("create plus checkpoint did not fail before file access", err)
	}
}
