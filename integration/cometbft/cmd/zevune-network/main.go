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
	"strconv"
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
func storageCheckpointFlags(height, appHash string, requested bool) (*labnet.StorageCheckpoint, error) {
	return parseCheckpointFlags(height, appHash, requested, labnet.ParseStorageCheckpoint)
}

func parseCheckpointFlags(height, appHash string, requested bool, parse func(string, string) (labnet.StorageCheckpoint, error)) (*labnet.StorageCheckpoint, error) {
	if !requested {
		if height != "" || appHash != "" {
			return nil, labnet.ErrBounds
		}
		return nil, nil
	}
	checkpoint, err := parse(height, appHash)
	if err != nil {
		return nil, err
	}
	return &checkpoint, nil
}

// This is syntax validation before file access, not selection of storage rules.
// The authenticated Network parser below applies its own fixed height bound.
func checkpointFlagSyntax(height, appHash string, requested bool) error {
	if !requested {
		if height != "" || appHash != "" {
			return labnet.ErrBounds
		}
		return nil
	}
	h, err := strconv.ParseUint(height, 10, 64)
	if err != nil || strconv.FormatUint(h, 10) != height || h > poolbridge.ActiveSegmentsV1.MaxHeight() {
		return labnet.ErrBounds
	}
	if _, err := labnet.ParseHash(appHash); err != nil {
		return labnet.ErrBounds
	}
	return nil
}

func diskReserveFlag(text string, requested bool) (uint64, error) {
	if !requested {
		if text != "" {
			return 0, labnet.ErrBounds
		}
		return 0, nil
	}
	if len(text) == 0 || len(text) > 20 {
		return 0, labnet.ErrBounds
	}
	reserve, err := strconv.ParseUint(text, 10, 64)
	if err != nil || reserve == 0 || strconv.FormatUint(reserve, 10) != text {
		return 0, labnet.ErrBounds
	}
	return reserve, nil
}

func execute(ctx context.Context, args []string, input io.Reader, output io.Writer) error {
	if len(args) == 1 && args[0] == "version" {
		return json.NewEncoder(output).Encode(map[string]any{"version": labnet.Version, "real_funds_allowed": false})
	}
	if len(args) == 0 {
		return labnet.ErrBounds
	}
	command := args[0]
	if command != "init" && command != "run" && command != "sync" && command != "submit" && command != "storage" && command != "storage-copy" {
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
	var expectedHeight, expectedAppHash, destination, diskReserveText string
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
		} else if command == "storage" || command == "storage-copy" {
			f.StringVar(&journal, "journal", "", "existing offline node or reference journal; never created")
			if command == "storage" {
				f.StringVar(&diskReserveText, "disk-reserve-bytes", "", "positive OS disk warning threshold; available <= threshold sets low_space; no bytes reserved")
			}
			if command == "storage-copy" {
				f.StringVar(&destination, "output", "", "new journal backup or restore path; never overwritten")
			}
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
	if command == "storage" || command == "storage-copy" || command == "sync" || command == "submit" {
		f.StringVar(&expectedHeight, "expected-height", "", "exact independently retained local starting height; requires --expected-app-hash")
		f.StringVar(&expectedAppHash, "expected-app-hash", "", "exact independently retained local starting state hash; requires --expected-height")
	}
	if err := strictFlags(f, args[1:]); err != nil || !*noFunds || !filepath.IsAbs(*worker) {
		return labnet.ErrBounds
	}
	// Track flag presence separately from its value: passing empty shell
	// variables must fail, not silently disable a checkpoint or disk inspection.
	checkpointRequested, diskRequested := false, false
	f.Visit(func(v *flag.Flag) {
		if v.Name == "expected-height" || v.Name == "expected-app-hash" {
			checkpointRequested = true
		}
		if v.Name == "disk-reserve-bytes" {
			diskRequested = true
		}
	})
	// Validate before configuration/file access. Explicit height 0 is a real
	// genesis checkpoint, not the default/absent value.
	if err := checkpointFlagSyntax(expectedHeight, expectedAppHash, checkpointRequested); err != nil || (checkpointRequested && create) ||
		(command == "storage-copy" && (!checkpointRequested || !filepath.IsAbs(destination) || !filepath.IsAbs(journal))) {
		return labnet.ErrBounds
	}
	diskReserve, err := diskReserveFlag(diskReserveText, diskRequested)
	if err != nil {
		return err
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
	expected, err := parseCheckpointFlags(expectedHeight, expectedAppHash, checkpointRequested, network.ParseStorageCheckpoint)
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
	if command == "storage-copy" {
		result, err := network.CopyStorageAtCheckpoint(bounded, labnet.StorageCopyOptions{
			Worker: *worker, WorkerPin: pin, Source: journal, Destination: destination, Expected: *expected,
		})
		if err != nil {
			return err
		}
		if err = emit.Encode(result); err != nil {
			return labnet.ErrCopyPublicationUncertain
		}
		return nil
	}
	if command == "storage" {
		var result labnet.StorageReport
		var err error
		if diskRequested {
			result, err = network.InspectStorageWithDiskSpace(bounded, *worker, pin, journal, diskReserve, expected)
		} else if expected == nil {
			result, err = network.InspectStorage(bounded, *worker, pin, journal)
		} else {
			result, err = network.InspectStorageAtCheckpoint(bounded, *worker, pin, journal, *expected)
		}
		if err != nil {
			return err
		}
		return emit.Encode(result)
	}
	o := labnet.SyncOptions{Endpoint: endpoint, Worker: *worker, WorkerSHA256: pin, Journal: journal, Create: create, Limit: limit}
	if command == "sync" {
		var result labnet.SyncResult
		var err error
		if expected == nil {
			result, err = network.Synchronize(bounded, o)
		} else {
			result, err = network.SynchronizeAtCheckpoint(bounded, o, *expected)
		}
		if err != nil {
			return err
		}
		return emit.Encode(result)
	}
	raw, err := transactionFile(txfile)
	if err != nil {
		return err
	}
	var result labnet.Submission
	if expected == nil {
		result, err = network.Submit(bounded, o, raw)
	} else {
		result, err = network.SubmitAtCheckpoint(bounded, o, raw, *expected)
	}
	if writeErr := emit.Encode(result); writeErr != nil {
		return writeErr
	}
	return err
}
func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := execute(ctx, os.Args[1:], os.Stdin, os.Stdout); err != nil {
		writeFailure(os.Stderr, os.Args[1:], err)
		if errors.Is(err, context.Canceled) {
			os.Exit(130)
		}
		os.Exit(1)
	}
}

func writeFailure(output io.Writer, args []string, err error) {
	// Do not echo arbitrary peer text, transaction contents or local paths.
	if len(args) > 0 && args[0] == "run" {
		failure := labnet.DescribeNodeFailure(err)
		_ = json.NewEncoder(output).Encode(struct {
			Status string `json:"status"`
			Stage  string `json:"stage"`
			Code   string `json:"code"`
		}{"local_node_failed", failure.Stage, failure.Code})
		return
	}
	_, _ = fmt.Fprintln(output, "Local network operation not completed; no automatic reset or retry. Reconcile signed history and preserve pending wallet state.")
}
