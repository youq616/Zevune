package main

import (
	"bytes"
	"context"
	"errors"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/youq616/Zevune/integration/cometbft/labnet"
)

func TestDiskReserveFlagCanonicalPositiveRangeAndPresence(t *testing.T) {
	if value, err := diskReserveFlag("", false); err != nil || value != 0 {
		t.Fatal("absent optional disk check rejected")
	}
	for _, value := range []uint64{1, 1 << 30, math.MaxUint64} {
		got, err := diskReserveFlag(strconv.FormatUint(value, 10), true)
		if err != nil || got != value {
			t.Fatal("valid positive reserve rejected")
		}
	}
	for _, text := range []string{"", "0", "00", "01", "+1", "-1", " 1", "1 ", "1\n", "1.0", "0x10", "1e3", "١", "18446744073709551616", strings.Repeat("1", 4096)} {
		if value, err := diskReserveFlag(text, true); !errors.Is(err, labnet.ErrBounds) || value != 0 {
			t.Fatal("explicit malformed reserve disabled or passed the check")
		}
	}
	if value, err := diskReserveFlag("1", false); !errors.Is(err, labnet.ErrBounds) || value != 0 {
		t.Fatal("inconsistent absence request accepted")
	}
}

func TestDiskReserveCLIValidatesBeforeConfigurationAccess(t *testing.T) {
	dir := t.TempDir()
	worker := filepath.Join(dir, "absent-worker")
	config := filepath.Join(dir, "absent-config")
	journal := filepath.Join(dir, "absent-journal")
	hash := labnet.HashText(labnet.Hash{1})
	base := []string{"storage", "--no-real-funds", "--worker", worker, "--worker-sha256", hash,
		"--config", config, "--config-sha256", hash, "--journal", journal}
	for _, flags := range [][]string{
		{"--disk-reserve-bytes="}, {"--disk-reserve-bytes", ""},
		{"--disk-reserve-bytes=0"}, {"--disk-reserve-bytes=-1"},
		{"--disk-reserve-bytes=01"}, {"--disk-reserve-bytes=+1"},
		{"--disk-reserve-bytes=18446744073709551616"},
		{"--disk-reserve-bytes=1", "--disk-reserve-bytes=2"},
		{"--disk-reserve-bytes", "1", "--disk-reserve-bytes", "1"},
		{"--disk-reserve-bytes=1", "--expected-height=0"},
		{"--disk-reserve-bytes=1", "--expected-height=0", "--expected-app-hash="},
	} {
		args := append(append([]string(nil), base...), flags...)
		var out bytes.Buffer
		if err := execute(context.Background(), args, nil, &out); !errors.Is(err, labnet.ErrBounds) || out.Len() != 0 {
			t.Fatalf("invalid disk flags reached file access or emitted a result: %v", err)
		}
	}
	// A missing absolute configuration with valid pins yields ErrStorage. This
	// distinguishes successful flag validation from an unrelated malformed pin.
	for _, flags := range [][]string{
		nil, {"--disk-reserve-bytes=1"}, {"--disk-reserve-bytes", "18446744073709551615"},
		{"--disk-reserve-bytes=1", "--expected-height=0", "--expected-app-hash=" + hash},
	} {
		args := append(append([]string(nil), base...), flags...)
		var out bytes.Buffer
		if err := execute(context.Background(), args, nil, &out); !errors.Is(err, labnet.ErrStorage) || out.Len() != 0 {
			t.Fatalf("valid disk flags failed syntax checking or emitted a result: %v", err)
		}
	}
	for _, path := range []string{worker, config, journal} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatal("disk command validation created a source file")
		}
	}
}

func TestDiskReserveFlagIsExclusiveToStorageCommand(t *testing.T) {
	dir := t.TempDir()
	hash := labnet.HashText(labnet.Hash{1})
	for _, command := range []string{"init", "run", "sync", "submit", "storage-copy", "version"} {
		args := []string{command, "--no-real-funds", "--worker", filepath.Join(dir, "worker"), "--worker-sha256", hash}
		if command == "init" {
			args = append(args, "--home", filepath.Join(dir, "home"), "--genesis", filepath.Join(dir, "genesis"), "--genesis-sha256", hash)
		} else if command != "version" {
			args = append(args, "--config", filepath.Join(dir, "config"), "--config-sha256", hash)
		}
		if command == "storage-copy" {
			args = append(args, "--journal", filepath.Join(dir, "journal"), "--output", filepath.Join(dir, "copy"),
				"--expected-height=0", "--expected-app-hash="+hash)
		}
		var out bytes.Buffer
		if err := execute(context.Background(), append(args, "--disk-reserve-bytes=1"), nil, &out); !errors.Is(err, labnet.ErrBounds) || out.Len() != 0 {
			t.Fatal("another command accepted the storage disk flag")
		}
	}
}
