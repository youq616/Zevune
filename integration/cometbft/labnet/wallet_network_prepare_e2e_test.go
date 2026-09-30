//go:build operator_e2e && wallet_network_e2e

package labnet

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"sync/atomic"
	"testing"
)

// Real nodes, original RPC verifier, real encrypted wallet and real Orchard
// proof. Test-only HTTP forwarding observes forbidden broadcast attempts and
// preserves the original CometBFT responses; it is not an accepting verifier.
func TestRealWalletNetworkPreparation(t *testing.T) {
	for _, profile := range []string{"02", "03"} {
		t.Run(profile, func(t *testing.T) {
			root := t.TempDir()
			walletRoot := filepath.Join(root, "ephemeral-preparation")
			if err := os.Mkdir(walletRoot, 0700); err != nil {
				t.Fatal(err)
			}
			networkExe := requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR")
			worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
			walletExe := requiredExecutable(t, "ZEVUNE_WALLET_LOCAL")
			driver := launch(t, requiredExecutable(t, "ZEVUNE_PYTHON"), "-I",
				requiredExecutable(t, "ZEVUNE_WALLET_NETWORK_PREPARE_SCENARIO"), walletRoot, networkExe, worker, walletExe, profile)
			initial := walletNetworkFrame(t, driver)
			assetPin, ok := initial["genesis_sha256"].(string)
			if initial["stage"] != "genesis" || !ok {
				t.Fatal("genuine genesis missing")
			}
			if _, err := ParseHash(assetPin); err != nil {
				t.Fatal(err)
			}
			home := filepath.Join(root, "network")
			common := []string{"--no-real-funds", "--worker", worker, "--worker-sha256", HashText(executablePin(t, worker))}
			initArgs := append([]string{"init"}, common...)
			initArgs = append(initArgs, "--home", home, "--genesis", filepath.Join(walletRoot, "genesis.bin"), "--genesis-sha256", assetPin)
			var initialized struct {
				Pin string `json:"config_sha256"`
			}
			if json.Unmarshal(operator(t, initArgs, true), &initialized) != nil {
				t.Fatal("network initialization")
			}
			pin, err := ParseHash(initialized.Pin)
			if err != nil {
				t.Fatal(err)
			}
			config := filepath.Join(home, configName)
			network, err := Load(config, pin)
			if err != nil {
				t.Fatal(err)
			}
			common = append(common, "--config", config, "--config-sha256", initialized.Pin)
			base := freePorts(t)
			nodes := make([]*process, 4)
			peers := make([]*peer, 4)
			running := make([]bool, 4)
			start := func() {
				for i := range nodes {
					args := append([]string{"run"}, common...)
					args = append(args, "--node", strconv.Itoa(i), "--base-port", strconv.Itoa(base), "--stop-on-stdin-eof")
					nodes[i] = launchNode(t, networkExe, i, network.config.NodeIDs[i], args...)
					running[i] = true
					peers[i], err = newPeer(Endpoint(base, i))
					if err != nil {
						t.Fatal(err)
					}
					t.Cleanup(peers[i].close)
				}
			}
			// Pause quorum only after genuine signed headers exist. Node0's real
			// RPC remains available. This keeps the public test reference stable
			// while real proof generation runs; no simulated clock/header.
			pause := func() {
				for i := 1; i < len(nodes); i++ {
					nodes[i].stop(t)
					running[i] = false
				}
			}
			start()
			awaitNetworkHeight(t, nodes, peers, 3)
			pause()
			upstream, err := url.Parse(Endpoint(base, 0))
			if err != nil {
				t.Fatal(err)
			}
			forwarding := httputil.NewSingleHostReverseProxy(upstream)
			transport := &http.Transport{Proxy: nil}
			forwarding.Transport = transport
			defer transport.CloseIdleConnections()
			var broadcasts atomic.Int64
			relay := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				raw, err := io.ReadAll(io.LimitReader(r.Body, 65537))
				r.Body.Close()
				var q struct {
					Method string `json:"method"`
				}
				if err != nil || len(raw) > 65536 || json.Unmarshal(raw, &q) != nil {
					w.WriteHeader(400)
					return
				}
				if q.Method == "broadcast_tx_sync" {
					broadcasts.Add(1)
					w.WriteHeader(400)
					return
				}
				r.Body = io.NopCloser(bytes.NewReader(raw))
				forwarding.ServeHTTP(w, r)
			}))
			defer relay.Close()
			proxy, connections := privateOperatorProxy(t, relay.URL)
			var falseRequests atomic.Int64
			falsePeer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				falseRequests.Add(1)
				defer r.Body.Close()
				var q struct {
					ID     json.RawMessage `json:"id"`
					Method string          `json:"method"`
				}
				if json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&q) != nil {
					w.WriteHeader(400)
					return
				}
				result := map[string]any{}
				if q.Method == "status" {
					result["node_info"] = map[string]string{"network": "zevune-orchard-lab-1"}
					result["sync_info"] = map[string]string{"latest_block_height": "4"}
				}
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": q.ID, "result": result})
			}))
			defer falsePeer.Close()
			walletNetworkSend(t, driver, map[string]string{"config": config, "config_sha256": initialized.Pin,
				"endpoint": privateTestEndpoint, "socks_proxy": proxy, "false_endpoint": falsePeer.URL})
			restart := walletNetworkFrame(t, driver)
			h, ok := restart["height"].(float64)
			if restart["stage"] != "restart" || !ok || h < 1 || h > 1000000 || float64(int64(h)) != h {
				t.Fatal("preparation missing")
			}
			for i, node := range nodes {
				if running[i] {
					node.stop(t)
					running[i] = false
				}
			}
			for _, peer := range peers {
				peer.close()
			}
			start()
			awaitNetworkHeight(t, nodes, peers, int64(h)+3)
			pause()
			walletNetworkSend(t, driver, map[string]string{"stage": "restarted"})
			last := walletNetworkFrame(t, driver)
			if last["stage"] != "done" || last["real_funds_allowed"] != false || last["partial_refused"] != true ||
				last["stale_handoff_rejected"] != true || last["false_peer_rejected"] != true ||
				last["pending_preserved"] != true || broadcasts.Load() != 0 || falseRequests.Load() < 2 || connections.Load() < 5 {
				t.Fatal("native preparation assertions incomplete")
			}
			driver.stop(t)
			for i, node := range nodes {
				if running[i] {
					node.stop(t)
					running[i] = false
				}
			}
			t.Log("real Go verification to opcode12; one durable record, exact pending, private route, stale/partial/false-node refusal, complete restart; ZERO broadcast attempts; valueless local fixture only")
		})
	}
}
