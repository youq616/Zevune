//go:build pool_e2e

package poolapp

import (
	"fmt"
	"net"
	"os"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
)

// Retain the existing 3000 aligned eight-port blocks and 50 probe attempts.
// On Linux exclude the ACTUAL automatic source-port range: closing a successful
// listen probe is not a reservation, and later RPC/P2P connects can consume it.
// Do not change sysctls, retry node startup, or call this an atomic socket lease.
// Other hosts retain their existing selection policy; this is a Linux fix.
func fixturePortCandidates(t *testing.T) []int {
	t.Helper()
	low, high := 0, 0
	if runtime.GOOS == "linux" {
		raw, err := os.ReadFile("/proc/sys/net/ipv4/ip_local_port_range")
		if err != nil {
			t.Fatalf("read fixture ephemeral port range: %v", err)
		}
		low, high, err = parseFixturePortRange(string(raw))
		if err != nil {
			t.Fatal(err)
		}
	}
	candidates := fixturePortBlocks(low, high)
	if len(candidates) == 0 {
		t.Fatalf("no fixture port block outside automatic source range %d..%d", low, high)
	}
	t.Logf("fixture port plan: automatic source range %d..%d (0 means unchanged non-Linux policy); %d candidate blocks; probes are not leases", low, high, len(candidates))
	return candidates
}

func parseFixturePortRange(raw string) (int, int, error) {
	parts := strings.Fields(raw)
	if len(parts) != 2 {
		return 0, 0, fmt.Errorf("invalid fixture ephemeral port range")
	}
	low, err1 := strconv.Atoi(parts[0])
	high, err2 := strconv.Atoi(parts[1])
	if err1 != nil || err2 != nil || low < 1 || high > 65535 || low > high ||
		strconv.Itoa(low) != parts[0] || strconv.Itoa(high) != parts[1] {
		return 0, 0, fmt.Errorf("invalid fixture ephemeral port range")
	}
	return low, high, nil
}

func fixturePortBlocks(low, high int) []int {
	candidates := make([]int, 0, 3000)
	for base := 30000; base < 54000; base += 8 {
		if high == 0 || base+7 < low || base > high {
			candidates = append(candidates, base)
		}
	}
	return candidates
}

func TestPoolFixturePorts(t *testing.T) {
	t.Run("exact_range_and_whole_blocks", func(t *testing.T) {
		for _, raw := range []string{"", "32768", "32768 60999 extra", "0 65535", "65535 65534", "1 65536", "+1 100", "01 100", "1 -2"} {
			if _, _, err := parseFixturePortRange(raw); err == nil {
				t.Fatalf("invalid range accepted: %q", raw)
			}
		}
		for _, tc := range []struct {
			raw       string
			low, high int
			blocks    int
		}{
			{"32768\t60999\n", 32768, 60999, 346},
			{"30003 30004", 30003, 30004, 2999},
			{"53999 65535", 53999, 65535, 2999},
			{"30000 53999", 30000, 53999, 0},
			{"1 65535", 1, 65535, 0},
		} {
			low, high, err := parseFixturePortRange(tc.raw)
			if err != nil || low != tc.low || high != tc.high {
				t.Fatalf("range parse: %q %v", tc.raw, err)
			}
			blocks := fixturePortBlocks(low, high)
			if len(blocks) != tc.blocks {
				t.Fatalf("candidate count for %q: %d", tc.raw, len(blocks))
			}
			for _, base := range blocks {
				if base < 30000 || base > 53992 || base%8 != 0 || !(base+7 < low || base > high) {
					t.Fatalf("overlapping or changed port block: %d", base)
				}
			}
		}
		if len(fixturePortBlocks(0, 0)) != 3000 {
			t.Fatal("changed non-Linux fixture policy")
		}
	})
	t.Run("actual_kernel_plan_and_automatic_dials", func(t *testing.T) {
		blocks := fixturePortCandidates(t)
		inPlan := make(map[int]bool)
		for _, base := range blocks {
			for i := 0; i < 8; i++ {
				inPlan[base+i] = true
			}
		}
		server, err := net.Listen("tcp4", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		defer server.Close()
		for i := 0; i < 16; i++ {
			client, err := net.DialTimeout("tcp4", server.Addr().String(), time.Second)
			if err != nil {
				t.Fatal(err)
			}
			peer, err := server.Accept()
			if err != nil {
				client.Close()
				t.Fatal(err)
			}
			port := client.LocalAddr().(*net.TCPAddr).Port
			client.Close()
			peer.Close()
			if runtime.GOOS == "linux" && inPlan[port] {
				t.Fatalf("automatic TCP source port %d overlaps fixture plan", port)
			}
		}
	})
}
