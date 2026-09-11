// zevune-network operates an explicit local, fixed-validator NO-FUNDS network.
// It never accepts a wallet secret or resets an existing data directory.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/youq616/Zevune/integration/cometbft/labnet"
	"github.com/youq616/Zevune/internal/poolbridge"
)

func transactionFile(path string) ([]byte, error) {
	if !filepath.IsAbs(path) {
		return nil, labnet.ErrBounds
	}
	before, err := os.Lstat(path)
	if err != nil || !before.Mode().IsRegular() || before.Size() <= 0 || before.Size() > poolbridge.MaxTransactionBytes {
		return nil, labnet.ErrBounds
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, labnet.ErrStorage
	}
	defer f.Close()
	after, err := f.Stat()
	if err != nil || !after.Mode().IsRegular() || !os.SameFile(before, after) {
		return nil, labnet.ErrStorage
	}
	raw, err := io.ReadAll(io.LimitReader(f, poolbridge.MaxTransactionBytes+1))
	if err != nil || int64(len(raw)) != before.Size() || len(raw) > poolbridge.MaxTransactionBytes {
		return nil, labnet.ErrBounds
	}
	return raw, nil
}

// Strict flag shape also rejects duplicate flags instead of silently selecting
// the last pin, endpoint or file path. No positional arguments are accepted.
func strictFlags(f *flag.FlagSet, args []string) error {
	seen := make(map[string]bool)
	for i := 0; i < len(args); i++ {
		text := args[i]
		if !strings.HasPrefix(text, "--") || text == "--" {
			return labnet.ErrBounds
		}
		name, value, hasValue := strings.Cut(text[2:], "=")
		entry := f.Lookup(name)
		if entry == nil || seen[name] {
			return labnet.ErrBounds
		}
		seen[name] = true
		isBool := false
		if v, ok := entry.Value.(interface{ IsBoolFlag() bool }); ok {
			isBool = v.IsBoolFlag()
		}
		if hasValue {
			if value == "" {
				return labnet.ErrBounds
			}
			continue
		}
		if !isBool {
			i++
			if i >= len(args) || strings.HasPrefix(args[i], "--") {
				return labnet.ErrBounds
			}
		}
	}
	if err := f.Parse(args); err != nil || f.NArg() != 0 {
		return labnet.ErrBounds
	}
	return nil
}
func execute(ctx context.Context, args []string, input io.Reader, output io.Writer) error {
	if len(args) == 1 && args[0] == "version" {
		return json.NewEncoder(output).Encode(map[string]any{"version": labnet.Version, "real_funds_allowed": false})
	}
	if len(args) == 0 {
		return labnet.ErrBounds
	}
	command := args[0]
	if command != "init" && command != "run" && command != "sync" && command != "submit" {
		return labnet.ErrBounds
	}
	f := flag.NewFlagSet(command, flag.ContinueOnError)
	f.SetOutput(io.Discard)
	noFunds := f.Bool("no-real-funds", false, "required local-only acknowledgement")
	worker := f.String("worker", "", "absolute trusted Rust worker path")
	workerDigest := f.String("worker-sha256", "", "independently verified worker digest")
	var home, manifest, assetDigest, config, configDigest, endpoint, journal, txfile string
	var index, ports int
	var create, stopOnEOF bool
	var limit uint64
	if command == "init" {
		f.StringVar(&home, "home", "", "new private network directory")
		f.StringVar(&manifest, "genesis", "", "public test asset manifest")
		f.StringVar(&assetDigest, "genesis-sha256", "", "pinned asset manifest digest")
	} else {
		f.StringVar(&config, "config", "", "public network configuration")
		f.StringVar(&configDigest, "config-sha256", "", "independently pinned configuration digest")
		if command == "run" {
			f.IntVar(&index, "node", -1, "node index 0..3")
			f.IntVar(&ports, "base-port", 30000, "local port base")
			f.BoolVar(&stopOnEOF, "stop-on-stdin-eof", false, "stop when supervising process closes stdin")
		} else {
			f.StringVar(&endpoint, "endpoint", "", "numeric loopback HTTP endpoint")
			f.StringVar(&journal, "journal", "", "wallet reference journal, not node journal")
			f.Uint64Var(&limit, "limit", 128, "maximum blocks for this call")
			if command == "sync" {
				f.BoolVar(&create, "create", false, "explicitly create a NEW reference journal")
			}
			if command == "submit" {
				f.StringVar(&txfile, "tx", "", "exact signed transaction file")
			}
		}
	}
	if err := strictFlags(f, args[1:]); err != nil || !*noFunds || !filepath.IsAbs(*worker) {
		return labnet.ErrBounds
	}
	pin, err := labnet.ParseHash(*workerDigest)
	if err != nil {
		return err
	}
	emit := json.NewEncoder(output)
	if command == "init" {
		asset, err := labnet.ParseHash(assetDigest)
		if err != nil {
			return err
		}
		bounded, cancel := context.WithTimeout(ctx, 5*time.Minute)
		defer cancel()
		digest, err := labnet.Initialize(bounded, labnet.InitOptions{Home: home, Worker: *worker, WorkerSHA256: pin, AssetManifest: manifest, AssetSHA256: asset})
		if err != nil {
			return err
		}
		return emit.Encode(map[string]any{"status": "initialized_local_network", "config_sha256": labnet.HashText(digest), "real_funds_allowed": false})
	}
	configPin, err := labnet.ParseHash(configDigest)
	if err != nil {
		return err
	}
	network, err := labnet.Load(config, configPin)
	if err != nil {
		return err
	}
	if command == "run" {
		running, cancel := context.WithCancel(ctx)
		defer cancel()
		if stopOnEOF {
			go func() { _, _ = io.Copy(io.Discard, input); cancel() }()
		}
		return network.Run(running, *worker, pin, index, ports, func() {
			if emit.Encode(map[string]any{"status": "local_node_started", "node": index, "real_funds_allowed": false}) != nil {
				cancel()
			}
		})
	}
	bounded, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()
	o := labnet.SyncOptions{Endpoint: endpoint, Worker: *worker, WorkerSHA256: pin, Journal: journal, Create: create, Limit: limit}
	if command == "sync" {
		result, err := network.Synchronize(bounded, o)
		if err != nil {
			return err
		}
		return emit.Encode(result)
	}
	raw, err := transactionFile(txfile)
	if err != nil {
		return err
	}
	result, err := network.Submit(bounded, o, raw)
	if writeErr := emit.Encode(result); writeErr != nil {
		return writeErr
	}
	return err
}
func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := execute(ctx, os.Args[1:], os.Stdin, os.Stdout); err != nil {
		// Do not echo arbitrary peer text, transaction contents or local paths.
		fmt.Fprintln(os.Stderr, "Local network operation not completed; no automatic reset or retry. Reconcile signed history and preserve pending wallet state.")
		if errors.Is(err, context.Canceled) {
			os.Exit(130)
		}
		os.Exit(1)
	}
}
