package main

import (
	"bytes"
	"context"
	"path/filepath"
	"strings"
	"testing"

	"github.com/youq616/Zevune/integration/cometbft/labnet"
)

func TestStorageCheckpointFlagPair(t *testing.T) {
	hash := labnet.HashText(labnet.Hash{1})
	if c, err := storageCheckpointFlags("", ""); err != nil || c != nil {
		t.Fatal("absent optional checkpoint rejected")
	}
	if c, err := storageCheckpointFlags("0", hash); err != nil || c == nil || c.Height != 0 || c.AppHash != (labnet.Hash{1}) {
		t.Fatal("height-zero checkpoint treated as absent")
	}
	for _, pair := range [][2]string{{"0", ""}, {"", hash}, {"00", hash}, {"10001", hash}, {"1", strings.Repeat("0", 64)}} {
		if c, err := storageCheckpointFlags(pair[0], pair[1]); err == nil || c != nil {
			t.Fatal("partial or malformed checkpoint accepted")
		}
	}
}

func TestStorageCheckpointCLIRejectsPartialDuplicateAndWrongCommands(t *testing.T) {
	hash := labnet.HashText(labnet.Hash{1})
	// These invalid forms fail before configuration/file access. Real execution
	// with a valid pair is covered by the operator_e2e suite, not a mock worker.
	worker := filepath.Join(t.TempDir(), "does-not-exist")
	for _, flags := range [][]string{
		{"--expected-height=0"}, {"--expected-app-hash=" + hash},
		{"--expected-height=0", "--expected-app-hash=" + hash, "--expected-height=1"},
		{"--expected-height=0", "--expected-app-hash="},
		{"--expected-height=0x00", "--expected-app-hash=" + hash},
	} {
		args := append([]string{"storage", "--no-real-funds", "--worker", worker}, flags...)
		var out bytes.Buffer
		if err := execute(context.Background(), args, nil, &out); err == nil || out.Len() != 0 {
			t.Fatal("invalid checkpoint flags emitted a result")
		}
	}
	for _, cmd := range []string{"init", "run", "sync", "submit"} {
		args := []string{cmd, "--no-real-funds", "--worker", worker, "--expected-height=0", "--expected-app-hash=" + hash}
		var out bytes.Buffer
		if execute(context.Background(), args, nil, &out) == nil || out.Len() != 0 {
			t.Fatal("unrelated command accepted storage checkpoint flags")
		}
	}
}
