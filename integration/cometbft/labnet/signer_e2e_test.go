//go:build operator_e2e

package labnet

import (
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	cfg "github.com/cometbft/cometbft/config"
)

func TestRealDamagedSignerFailsSafelyAndReleasesWorker(t *testing.T) {
	worker, workerPin, asset, assetPin := activeStartupFixture(t)
	network := initializeStartupNetwork(t, worker, workerPin, asset, assetPin)
	config := cfg.DefaultConfig().SetRoot(filepath.Join(network.home, "node0"))
	keyPath, statePath := config.PrivValidatorKeyFile(), config.PrivValidatorStateFile()
	original := signerFileBytes(t, keyPath, statePath)
	journal := filepath.Join(config.RootDir, "pool.journal")
	for _, tc := range []struct {
		name string
		path string
		raw  []byte
	}{
		{"key-json", keyPath, []byte("{ damaged-key-json")},
		{"state-json", statePath, []byte("{ damaged-state-json")},
		{"missing-history-fields", statePath, []byte("{}")},
	} {
		if !t.Run(tc.name, func(t *testing.T) {
			// Restore only this test's known fixture between independent fault
			// cases. The CLI and production loader never reset or repair files.
			for path, raw := range original {
				if os.WriteFile(path, raw, 0600) != nil {
					t.Fatal("cannot restore independent signer test fixture")
				}
			}
			if os.WriteFile(tc.path, tc.raw, 0600) != nil {
				t.Fatal("cannot write damaged signer fixture")
			}
			before := signerFileBytes(t, keyPath, statePath)
			ledgerBefore := activeStorageDirectoryBytes(t, journal)
			stderr, stdout := &boundedProcessOutput{}, &boundedProcessOutput{}
			p, err := startTestProcess(requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR"), startupNodeArgs(network, worker, workerPin, 0, freePorts(t)), stderr)
			if err != nil {
				t.Fatal("cannot start real signer rejection process")
			}
			t.Cleanup(func() { p.stop(t) })
			readDone := make(chan error, 1)
			go func() {
				_, err := io.Copy(stdout, p.out)
				readDone <- err
			}()
			ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
			defer cancel()
			select {
			case <-p.done:
			case <-ctx.Done():
				t.Fatal("damaged signer did not fail within the startup budget")
			}
			p.stopped = true // The nonzero exit is the expected test outcome.
			_ = p.in.Close()
			defer p.out.Close()
			select {
			case err := <-readDone:
				if err != nil {
					t.Fatal("failed to drain bounded signer stdout")
				}
			case <-ctx.Done():
				t.Fatal("signer stdout was not closed after process exit")
			}
			if p.exitCode() != 1 || len(stdout.data) != 0 || stdout.truncated {
				t.Fatalf("signer rejection must exit 1 with empty stdout: exit_code=%d captured_stdout_bytes=%d truncated=%v", p.exitCode(), len(stdout.data), stdout.truncated)
			}
			want := []byte("{\"status\":\"local_node_failed\",\"stage\":\"signer_load\",\"code\":\"storage\"}\n")
			if stderr.truncated || !bytes.Equal(stderr.data, want) {
				t.Fatal("signer rejection did not emit only the fixed safe failure record")
			}
			requireSignerFilesUnchanged(t, before)
			if !reflect.DeepEqual(ledgerBefore, activeStorageDirectoryBytes(t, journal)) {
				t.Fatal("rejected signer load changed the ledger")
			}
			report, err := network.InspectStorage(ctx, worker, workerPin, journal)
			if err != nil || report.Height != 0 {
				t.Fatal("signer failure retained worker ownership or advanced the ledger")
			}
			requireSignerFilesUnchanged(t, before)
			if !reflect.DeepEqual(ledgerBefore, activeStorageDirectoryBytes(t, journal)) {
				t.Fatal("post-failure worker reopen changed the ledger")
			}
		}) {
			t.FailNow()
		}
	}
}
