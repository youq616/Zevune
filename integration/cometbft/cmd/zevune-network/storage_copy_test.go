package main

import (
	"bytes"
	"context"
	"errors"
	"path/filepath"
	"testing"

	"github.com/youq616/Zevune/integration/cometbft/labnet"
)

func TestStorageCopyRequiresExplicitCheckpointAndOfflinePaths(t *testing.T) {
	dir := t.TempDir()
	worker, source, output := filepath.Join(dir, "worker"), filepath.Join(dir, "source"), filepath.Join(dir, "copy")
	hash := labnet.HashText(labnet.Hash{1})
	base := []string{"storage-copy", "--no-real-funds", "--worker", worker, "--journal", source, "--output", output}
	for _, flags := range [][]string{
		nil, {"--expected-height=0"}, {"--expected-app-hash=" + hash},
		{"--expected-height", "", "--expected-app-hash", ""},
		{"--expected-height=0", "--expected-app-hash=" + hash, "--expected-height=0"},
		{"--expected-height=0", "--expected-app-hash=" + hash, "--create"},
		{"--expected-height=0", "--expected-app-hash=" + hash, "--endpoint=http://127.0.0.1:30000"},
		{"--expected-height=0", "--expected-app-hash=" + hash, "--output", "relative"},
	} {
		args := append(append([]string(nil), base...), flags...)
		var out bytes.Buffer
		if err := execute(context.Background(), args, nil, &out); !errors.Is(err, labnet.ErrBounds) || out.Len() != 0 {
			t.Fatal("invalid copy arguments did not fail closed before config/worker access", flags, err)
		}
	}
}
