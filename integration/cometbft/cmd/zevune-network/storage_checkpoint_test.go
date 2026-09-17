package main

import (
	"bytes"
	"context"
	"flag"
	"path/filepath"
	"strings"
	"testing"

	"github.com/youq616/Zevune/integration/cometbft/labnet"
)

func TestStorageCheckpointFlagPair(t *testing.T) {
	hash := labnet.HashText(labnet.Hash{1})
	if c, err := storageCheckpointFlags("", "", false); err != nil || c != nil {
		t.Fatal("absent optional checkpoint rejected")
	}
	if c, err := storageCheckpointFlags("0", hash, true); err != nil || c == nil || c.Height != 0 || c.AppHash != (labnet.Hash{1}) {
		t.Fatal("height-zero checkpoint treated as absent")
	}
	if c, err := storageCheckpointFlags("0", hash, false); err == nil || c != nil {
		t.Fatal("inconsistent absence request accepted")
	}
	for _, pair := range [][2]string{{"", ""}, {"0", ""}, {"", hash}, {"00", hash}, {"10001", hash}, {"1", strings.Repeat("0", 64)}} {
		if c, err := storageCheckpointFlags(pair[0], pair[1], true); err == nil || c != nil {
			t.Fatal("partial or malformed checkpoint accepted")
		}
	}
}

func TestCheckpointSyntaxDoesNotSelectAStorageProfile(t *testing.T) {
	hash := labnet.HashText(labnet.Hash{1})
	for _, height := range []string{"0", "10000", "10001", "1000000"} {
		if err := checkpointFlagSyntax(height, hash, true); err != nil {
			t.Fatal("bounded canonical checkpoint syntax rejected before network loading", height)
		}
	}
	for _, height := range []string{"", "010001", "-1", "+1", "1000001", "18446744073709551616"} {
		if err := checkpointFlagSyntax(height, hash, true); err == nil {
			t.Fatal("invalid checkpoint syntax accepted before network loading")
		}
	}
	// Allowing bounded syntax does not make a legacy parser accept active height.
	if _, err := parseCheckpointFlags("10001", hash, true, labnet.ParseStorageCheckpoint); err == nil {
		t.Fatal("syntax checking silently relaxed the selected profile")
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
	for _, cmd := range []string{"init", "run"} {
		args := []string{cmd, "--no-real-funds", "--worker", worker, "--expected-height=0", "--expected-app-hash=" + hash}
		var out bytes.Buffer
		if execute(context.Background(), args, nil, &out) == nil || out.Len() != 0 {
			t.Fatal("unrelated command accepted storage checkpoint flags")
		}
	}
}

// A caller can pass two empty shell variables as separate flag arguments. This
// must be an error, never the same request as omitting checkpoint verification.
func TestExplicitEmptyStorageCheckpointDoesNotDisableCheck(t *testing.T) {
	f := flag.NewFlagSet("storage", flag.ContinueOnError)
	var height, hash string
	f.StringVar(&height, "expected-height", "", "")
	f.StringVar(&hash, "expected-app-hash", "", "")
	err := strictFlags(f, []string{"--expected-height", "", "--expected-app-hash", ""})
	if err != nil {
		return
	}
	requested := false
	f.Visit(func(v *flag.Flag) {
		if v.Name == "expected-height" || v.Name == "expected-app-hash" {
			requested = true
		}
	})
	if !requested {
		t.Fatal("test did not actually request a checkpoint")
	}
	if checkpoint, err := storageCheckpointFlags(height, hash, requested); err == nil || checkpoint != nil {
		t.Fatal("explicit empty checkpoint silently disabled verification")
	}
}
