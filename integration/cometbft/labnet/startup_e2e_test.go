//go:build operator_e2e

package labnet

import (
	"context"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// Use the genuine scenario's public active genesis without requesting a payment
// or generating payment proofs. No alternative verifier or synthetic worker is
// introduced for these startup and failure diagnostics.
func activeStartupFixture(t *testing.T) (string, Hash, string, Hash) {
	t.Helper()
	wallets := filepath.Join(t.TempDir(), "wallets")
	if err := os.Mkdir(wallets, 0700); err != nil {
		t.Fatal(err)
	}
	driver := launch(t, requiredExecutable(t, "ZEVUNE_FUNDED_SCENARIO"), wallets, "--active-segments-v1")
	ready := driver.frame(t)
	if len(ready) != 128 || parseSummary(t, ready[32:]).Height != 0 {
		t.Fatal("unexpected genuine active startup fixture")
	}
	var assetPin Hash
	copy(assetPin[:], ready[:32])
	worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
	return worker, executablePin(t, worker), filepath.Join(wallets, "test-genesis.bin"), assetPin
}

func initializeStartupNetwork(t *testing.T, worker string, workerPin Hash, asset string, assetPin Hash) *Network {
	t.Helper()
	home := filepath.Join(t.TempDir(), "network")
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	pin, err := Initialize(ctx, InitOptions{Home: home, Worker: worker, WorkerSHA256: workerPin, AssetManifest: asset, AssetSHA256: assetPin})
	if err != nil {
		t.Fatal("startup network initialization failed:", nodeFailureCode(err))
	}
	network, err := Load(filepath.Join(home, configName), pin)
	if err != nil || network.Profile() != poolbridge.ActiveSegmentsV1 {
		t.Fatal("startup network configuration did not authenticate")
	}
	return network
}

func startupNodeArgs(network *Network, worker string, workerPin Hash, index, base int) []string {
	return []string{"run", "--no-real-funds", "--worker", worker, "--worker-sha256", HashText(workerPin),
		"--config", filepath.Join(network.home, configName), "--config-sha256", HashText(network.ConfigDigest()),
		"--node", strconv.Itoa(index), "--base-port", strconv.Itoa(base), "--stop-on-stdin-eof"}
}

func TestRealActiveFourNodeStartupRounds(t *testing.T) {
	worker, workerPin, asset, assetPin := activeStartupFixture(t)
	for round := 1; round <= 3; round++ {
		if !t.Run(fmt.Sprintf("round-%d", round), func(t *testing.T) {
			network := initializeStartupNetwork(t, worker, workerPin, asset, assetPin)
			// Preserve the original port selection/start pattern. A failed round
			// is evidence to investigate, never a reason to retry until one passes.
			base := freePorts(t)
			nodes, peers := make([]*process, 4), make([]*peer, 4)
			for i := range nodes {
				nodes[i] = launchNode(t, requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR"), i, network.config.NodeIDs[i], startupNodeArgs(network, worker, workerPin, i, base)...)
				var err error
				peers[i], err = newPeer(Endpoint(base, i))
				if err != nil {
					t.Fatal(err)
				}
				defer peers[i].close()
			}
			awaitNetworkHeight(t, nodes, peers, 3)
			for _, node := range nodes {
				node.stop(t)
			}
			if t.Failed() {
				t.FailNow()
			}
			t.Log("all four pinned node IDs matched and reached height 3; all processes stopped")
		}) {
			t.FailNow()
		}
	}
}

func TestRealNodeOccupiedPortsReportFailureAndReleaseWorker(t *testing.T) {
	worker, workerPin, asset, assetPin := activeStartupFixture(t)
	network := initializeStartupNetwork(t, worker, workerPin, asset, assetPin)
	for _, tc := range []struct {
		name   string
		offset int
		code   string
	}{
		// CometBFT 0.38.26 formats the RPC listener error with %v, losing the
		// errno chain. P2P preserves it. Never guess the RPC cause from text.
		{"rpc", 0, "other"}, {"p2p", 1, "address_in_use"},
	} {
		if !t.Run(tc.name, func(t *testing.T) {
			base := freePorts(t)
			held, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", base+tc.offset))
			if err != nil {
				t.Fatal("cannot hold controlled test port:", nodeFailureCode(err))
			}
			defer held.Close()
			p := launchNode(t, requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR"), 0, network.config.NodeIDs[0], startupNodeArgs(network, worker, workerPin, 0, base)...)
			ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
			defer cancel()
			select {
			case <-p.done:
			case <-ctx.Done():
				t.Fatal("occupied port did not terminate the node within its startup budget")
			}
			// This subprocess is expected to fail; its exit must still be fully
			// observed/reaped before reusing its node directory or socket ports.
			p.stopped = true
			_ = p.in.Close()
			defer p.out.Close()
			select {
			case <-p.readyDone:
			case <-ctx.Done():
				t.Fatal("occupied-port process left its ready reader unfinished")
			}
			failure := p.failure()
			if p.exitCode() != 1 || p.readyErr == nil || failure != (NodeFailure{Stage: "consensus_start", Code: tc.code}) {
				t.Fatalf("controlled occupied-port failure: exit_code=%d ready=%v diagnostic=%+v", p.exitCode(), p.readyErr == nil, failure)
			}
			if err := held.Close(); err != nil {
				t.Fatal(err)
			}
			for offset := 0; offset <= 1; offset++ {
				listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", base+offset))
				if err != nil {
					t.Fatal("failed node retained a listener:", nodeFailureCode(err))
				}
				if err := listener.Close(); err != nil {
					t.Fatal(err)
				}
			}
			report, err := network.InspectStorage(ctx, worker, workerPin, filepath.Join(network.home, "node0", "pool.journal"))
			if err != nil || report.Height != 0 || report.StorageProfile != "active_segments_v1" {
				t.Fatal("failed startup retained worker ownership or advanced the ledger")
			}
			t.Logf("controlled %s occupancy: stage=%s code=%s exit_code=1, sockets and worker ownership released", tc.name, failure.Stage, failure.Code)
		}) {
			t.FailNow()
		}
	}
}
