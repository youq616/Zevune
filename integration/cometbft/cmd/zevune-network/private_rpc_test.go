package main

import (
	"context"
	"errors"
	"io"
	"path/filepath"
	"strings"
	"testing"

	"github.com/youq616/Zevune/integration/cometbft/labnet"
)

func TestPrivateRPCFlagsRejectEmptyAndInvalidBeforeFileAccess(t *testing.T) {
	endpoint := "http://pg6mmjiyjmcrsslvykfwnntlaru7p5svn6y2ymmju6nubxndf4pscryd.onion:8080"
	for _, command := range []string{"sync", "submit"} {
		for _, proxy := range []string{"", "localhost:9050", "127.0.0.1:80", "http://127.0.0.1:9050"} {
			args := []string{command, "--no-real-funds", "--worker", filepath.Join(t.TempDir(), "missing-worker"), "--endpoint", endpoint, "--socks-proxy", proxy}
			if err := execute(context.Background(), args, strings.NewReader(""), io.Discard); !errors.Is(err, labnet.ErrEndpoint) {
				t.Fatalf("private route not rejected before worker/config access: %v", err)
			}
		}
	}
}

func TestPrivateRPCFlagIsUnavailableToNodeAndStorageCommands(t *testing.T) {
	for _, command := range []string{"init", "run", "storage", "storage-copy"} {
		args := []string{command, "--no-real-funds", "--worker", filepath.Join(t.TempDir(), "missing-worker"), "--socks-proxy", "127.0.0.1:9050"}
		if err := execute(context.Background(), args, strings.NewReader(""), io.Discard); !errors.Is(err, labnet.ErrBounds) {
			t.Fatal("private flag widened unrelated command", err)
		}
	}
}

func TestPrivateRPCFlagsRejectDuplicatesAndEqualsEmpty(t *testing.T) {
	for _, tail := range [][]string{{"--socks-proxy="}, {"--socks-proxy", "127.0.0.1:9050", "--socks-proxy", "127.0.0.1:9150"}} {
		args := []string{"sync", "--no-real-funds", "--worker", filepath.Join(t.TempDir(), "missing-worker")}
		args = append(args, tail...)
		if err := execute(context.Background(), args, strings.NewReader(""), io.Discard); !errors.Is(err, labnet.ErrBounds) {
			t.Fatal("ambiguous private flag accepted", err)
		}
	}
}
