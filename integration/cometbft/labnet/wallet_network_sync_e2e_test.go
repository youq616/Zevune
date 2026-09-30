//go:build operator_e2e && wallet_network_e2e

package labnet

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"sync/atomic"
	"testing"
	"time"
)

// Progress frames contain only public test coordinates/stages. Passwords and
// wallet receipts never cross this boundary. Each reader is joined on failure.
func walletNetworkFrame(t *testing.T, p *process) map[string]any {
	t.Helper()
	type result struct {
		value map[string]any
		err   error
	}
	done := make(chan result, 1)
	go func() {
		var prefix [4]byte
		_, err := io.ReadFull(p.out, prefix[:])
		size := binary.BigEndian.Uint32(prefix[:])
		if err != nil || size == 0 || size > 4096 {
			done <- result{err: ErrResponse}
			return
		}
		raw := make([]byte, size)
		_, err = io.ReadFull(p.out, raw)
		var value map[string]any
		if err == nil {
			err = json.Unmarshal(raw, &value)
		}
		done <- result{value, err}
	}()
	select {
	case r := <-done:
		if r.err != nil {
			t.Fatal("native wallet-network stage failed")
		}
		if r.value["stage"] == "failed" {
			step, _ := r.value["step"].(string)
			switch step {
			case "setup", "network-start", "initial-catchup", "real-payment-and-pending", "explicit-fixture-broadcast", "payment-rescan", "restart-rescan", "false-peer-refusal", "stale-handoff-refusal", "final-rescan":
				t.Fatal("native wallet-network failed at fixed stage:", step)
			default:
				t.Fatal("native wallet-network failed")
			}
		}
		return r.value
	case <-time.After(3 * time.Minute):
		_ = p.cmd.Process.Kill()
		_ = p.out.Close()
		<-done
		t.Fatal("native wallet-network stage timed out")
		return nil
	}
}

func walletNetworkSend(t *testing.T, p *process, value any) {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil || len(raw) == 0 || len(raw) > 4096 {
		t.Fatal("public coordination bounds")
	}
	var prefix [4]byte
	binary.BigEndian.PutUint32(prefix[:], uint32(len(raw)))
	if _, err := io.Copy(p.in, bytes.NewReader(append(prefix[:], raw...))); err != nil {
		t.Fatal("public coordination failed")
	}
}

// This test runs in its own native workflow, not by increasing the old operator
// suite timeout. Original payment/post-state/restart tests remain unmodified.
func TestRealWalletNetworkSynchronization(t *testing.T) {
	for _, profile := range []string{"02", "03"} {
		t.Run(profile, func(t *testing.T) {
			root := t.TempDir()
			walletRoot := filepath.Join(root, "ephemeral-wallets")
			if err := os.Mkdir(walletRoot, 0700); err != nil {
				t.Fatal(err)
			}
			networkExe := requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR")
			worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
			walletExe := requiredExecutable(t, "ZEVUNE_WALLET_LOCAL")
			driver := launch(t, requiredExecutable(t, "ZEVUNE_PYTHON"), "-I",
				requiredExecutable(t, "ZEVUNE_WALLET_NETWORK_SCENARIO"), walletRoot, networkExe, worker, walletExe, profile)
			initial := walletNetworkFrame(t, driver)
			assetPin, ok := initial["genesis_sha256"].(string)
			if initial["stage"] != "genesis" || !ok {
				t.Fatal("genuine public genesis missing")
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
				t.Fatal("real network initialization failed")
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
			start := func() {
				for i := range nodes {
					args := append([]string{"run"}, common...)
					args = append(args, "--node", strconv.Itoa(i), "--base-port", strconv.Itoa(base), "--stop-on-stdin-eof")
					nodes[i] = launchNode(t, networkExe, i, network.config.NodeIDs[i], args...)
					peers[i], err = newPeer(Endpoint(base, i))
					if err != nil {
						t.Fatal(err)
					}
					t.Cleanup(peers[i].close)
				}
			}
			start()
			awaitNetworkHeight(t, nodes, peers, 3)
			proxy, connections := privateOperatorProxy(t, Endpoint(base, 0))
			var falseRequests atomic.Int64
			falsePeer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				falseRequests.Add(1)
				defer r.Body.Close()
				var req struct {
					ID     json.RawMessage `json:"id"`
					Method string          `json:"method"`
				}
				if json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&req) != nil {
					w.WriteHeader(http.StatusBadRequest)
					return
				}
				result := map[string]any{}
				if req.Method == "status" {
					result["node_info"] = map[string]string{"network": "zevune-orchard-lab-1"}
					result["sync_info"] = map[string]string{"latest_block_height": "4"}
				}
				// No signed header: the original Go verifier must refuse it. This
				// is an adversarial *_test.go provider, not an accepting backend.
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": req.ID, "result": result})
			}))
			defer falsePeer.Close()
			walletNetworkSend(t, driver, map[string]string{"config": config, "config_sha256": initialized.Pin,
				"endpoint": privateTestEndpoint, "socks_proxy": proxy, "false_endpoint": falsePeer.URL})
			if walletNetworkFrame(t, driver)["stage"] != "submitted" {
				t.Fatal("single genuine broadcast missing")
			}
			raw, err := os.ReadFile(filepath.Join(walletRoot, "payment.tx"))
			if err != nil {
				t.Fatal("public transaction missing")
			}
			height := findInclusion(t, peers[0], raw, 1)
			awaitNetworkHeight(t, nodes, peers, height+1)
			walletNetworkSend(t, driver, map[string]string{"stage": "included"})
			restart := walletNetworkFrame(t, driver)
			h, ok := restart["height"].(float64)
			if restart["stage"] != "restart" || !ok || h < 1 || h > 10000 || float64(int64(h)) != h {
				t.Fatal("verified rescan missing")
			}
			for _, node := range nodes {
				node.stop(t)
			}
			for _, peer := range peers {
				peer.close()
			}
			start()
			awaitNetworkHeight(t, nodes, peers, int64(h)+3)
			walletNetworkSend(t, driver, map[string]string{"stage": "restarted"})
			last := walletNetworkFrame(t, driver)
			if last["stage"] != "done" || last["real_funds_allowed"] != false ||
				last["private_route_exercised"] != true || last["false_peer_rejected"] != true ||
				last["stale_handoff_rejected"] != true || falseRequests.Load() < 2 || connections.Load() < 10 {
				t.Fatal("native closed-loop assertions incomplete")
			}
			driver.stop(t)
			for _, node := range nodes {
				node.stop(t)
			}
			t.Log("actual Python command/Go quorum replay/Rust checkpoint scan; partial catchup, real 7-unit payment, retained pending bytes, recipient balance, full restart, unsigned peer and stale handoff rejection passed; local NO-FUNDS/SOCKS fixture only")
		})
	}
}
