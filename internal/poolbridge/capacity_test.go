package poolbridge

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"os"
	"os/exec"
	"testing"
	"time"
)

func capacityBytes(logical uint64, segments, tail uint32) []byte {
	raw := make([]byte, 16)
	binary.BigEndian.PutUint64(raw[:8], logical)
	binary.BigEndian.PutUint32(raw[8:12], segments)
	binary.BigEndian.PutUint32(raw[12:16], tail)
	return raw
}

// These are public response-framing checks. They do not construct a journal or
// replace the separate real worker/Orchard growth and recovery acceptance tests.
func TestActiveCapacityHeaderAndPhysicalSegmentRelations(t *testing.T) {
	for _, q := range []struct {
		height, header, logical uint64
		segments, tail          uint32
	}{
		{0, 108, 108, 0, 0},
		{0, 588, 588, 0, 0},
		{1, 108, 258, 1, 150},
		{6990, 108, 1048608, 1, 1048500},
		{6991, 108, 1048758, 2, 150},
		{10001, 108, 1500258, 2, 451650},
		{1, 108, 450466, 1, 450358},
	} {
		s := Summary{Height: q.height, AppHash: Hash{7}, Commitments: 2}
		r, err := decodeActiveStorage(s, capacityBytes(q.logical, q.segments, q.tail), q.header)
		if err != nil || r.Summary != s || r.LogicalBytes != q.logical || r.Segments != q.segments || r.TailBytes != q.tail {
			t.Fatal("valid bounded physical layout rejected", q, err)
		}
	}
	for _, q := range []struct {
		height, logical uint64
		segments, tail  uint32
	}{
		{0, 109, 0, 0},                     // An empty pool cannot hide extra bytes.
		{0, 108, 1, 0},                     // An empty segment is never canonical.
		{0, 108, 0, 1},                     // No tail without a segment.
		{1, 257, 1, 149},                   // The full empty-record framing is needed.
		{1, 259, 1, 150},                   // One segment must explain every data byte.
		{1, 258, 0, 150},                   // Records require a physical segment.
		{1, 258, 2, 150},                   // More nonempty segments than records.
		{2, 408, 2, 150},                   // Premature rollover is inconsistent.
		{6991, 1048758, 1, 1048650},         // A tail may not exceed 1 MiB.
		{10001, 1500257, 2, 451649},         // Logical count omits one framing byte.
		{10001, 1500258, 2, 0},             // A zero tail is not silently repairable.
		{10001, 1500258, 2, 149},           // A partial tail cannot be accepted.
		{10001, 1500258, 2049, 150},        // Physical segment-count bound.
		{1000001, 150000258, 144, 540150},  // Fixed active record-count bound.
		{1000000, 1073741825, 1025, 75000}, // Fixed active logical-byte bound.
		{1, 600108, 1, 600000},             // One block exceeds the maximum record frame.
	} {
		if _, err := decodeActiveStorage(Summary{Height: q.height}, capacityBytes(q.logical, q.segments, q.tail), 108); err == nil {
			t.Fatal("inconsistent capacity accepted", q)
		}
	}
	for _, header := range []uint64{0, 44, 76, 107, 109, 589, ^uint64(0)} {
		if _, err := decodeActiveStorage(Summary{}, capacityBytes(header, 0, 0), header); err == nil {
			t.Fatal("untrusted/impossible header accepted", header)
		}
	}
	for _, n := range []int{0, 15, 17} {
		if _, err := decodeActiveStorage(Summary{}, make([]byte, n), 108); err == nil {
			t.Fatal("variable-size capacity tail accepted")
		}
	}
	if _, err := decodeActiveStorage(Summary{}, capacityBytes(108, 0, 0), 588); err == nil {
		t.Fatal("worker reply replaced the header from the pinned manifest")
	}
}

// Test-only transport adversary. It never validates a transaction or supplies a
// test substitute to a production entry point; genuine execution runs in Rust.
func TestActivePoolProcessHelper(t *testing.T) {
	if os.Getenv("ZEVUNE_ACTIVE_POOL_HELPER") != "1" {
		return
	}
	mode := os.Args[len(os.Args)-1]
	advertised := activeDomain
	if mode == "hello-legacy" {
		advertised = domain
	}
	if mode == "hello-future" {
		advertised += ":unknown"
	}
	fingerprint := sha256.Sum256([]byte(advertised))
	if writeFrame(os.Stdout, append([]byte("ZVPLHEL1"), fingerprint[:]...)) != nil {
		os.Exit(2)
	}
	for {
		raw, err := readFrame(os.Stdin, maxFrame)
		if err != nil {
			os.Exit(0)
		}
		if mode == "exit" {
			os.Exit(0)
		}
		if mode == "hang" {
			time.Sleep(5 * time.Second)
		}
		if mode == "truncated" {
			_, _ = os.Stdout.Write([]byte{0, 0, 0, 161, 1})
			os.Exit(0)
		}
		size := 145
		if raw[16] == 5 {
			size = 153
		}
		if raw[16] == 6 && mode != "old-size" {
			size = 161
		}
		out := make([]byte, size)
		copy(out, "ZVPLRSP1")
		copy(out[8:16], raw[8:16])
		digest := sha256.Sum256(raw)
		copy(out[17:49], digest[:])
		height := uint64(10001)
		if raw[16] == 1 || raw[16] == 2 || raw[16] == 5 {
			height = binary.BigEndian.Uint64(raw[17:25])
		}
		if mode == "bad-height" {
			height = 1000001
		}
		binary.BigEndian.PutUint64(out[49:57], height)
		if mode == "bad-commitments" {
			binary.BigEndian.PutUint64(out[121:129], 65537)
		}
		if size == 161 {
			copy(out[145:], capacityBytes(1500258, 2, 451650))
			if mode == "bad-capacity" {
				out[152]--
			}
			if mode == "reject" || mode == "reject-nonzero" {
				out[16] = 1
				clear(out[145:])
				if mode == "reject-nonzero" {
					out[160] = 1
				}
			}
		}
		if mode == "bad-id" {
			out[15] ^= 1
		}
		if mode == "bad-hash" {
			out[17] ^= 1
		}
		if mode == "bad-status" {
			out[16] = 2
		}
		if writeFrame(os.Stdout, out) != nil {
			os.Exit(3)
		}
	}
}

func activeHelper(t *testing.T, mode string, timeout time.Duration) *Client {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestActivePoolProcessHelper$", "--", mode)
	cmd.Env = append(os.Environ(), "ZEVUNE_ACTIVE_POOL_HELPER=1")
	c, err := startProfile(context.Background(), cmd, Options{StartupTimeout: 2 * time.Second, RequestTimeout: timeout}, ActiveSegmentsV1, 108)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = c.Close() })
	return c
}

func TestStorageProfileHandshakeRejectsDowngradeAndUnknownGeneration(t *testing.T) {
	for _, q := range []struct {
		profile StorageProfile
		mode    string
	}{
		{ActiveSegmentsV1, "hello-legacy"},
		{ActiveSegmentsV1, "hello-future"},
		{LegacyJournal, "ok"},
	} {
		cmd := exec.Command(os.Args[0], "-test.run=^TestActivePoolProcessHelper$", "--", q.mode)
		cmd.Env = append(os.Environ(), "ZEVUNE_ACTIVE_POOL_HELPER=1")
		c, err := startProfile(context.Background(), cmd, Options{StartupTimeout: 2 * time.Second}, q.profile, 108)
		if c != nil {
			_ = c.Close()
		}
		if err == nil || !errors.Is(err, ErrProtocol) {
			t.Fatal("mixed profile handshake did not fail closed", q, err)
		}
	}
}

func TestActiveClientUsesOneProfileAcrossOperations(t *testing.T) {
	c := activeHelper(t, "ok", time.Second)
	ctx := context.Background()
	if c.Profile() != ActiveSegmentsV1 {
		t.Fatal("client lost its launch policy")
	}
	if state, err := c.Status(ctx); err != nil || state.Height != 10001 {
		t.Fatal("active status rejected high height", err)
	}
	if _, err := c.BlockBytes(10001, Hash{7}, nil); err != nil {
		t.Fatal(err)
	}
	if state, err := c.Preview(ctx, 10001, Hash{7}, nil); err != nil || state.Height != 10001 {
		t.Fatal("preview did not use pinned active bounds", err)
	}
	if txs, err := c.SelectProposal(ctx, 10001, 0, nil); err != nil || len(txs) != 0 {
		t.Fatal("selector did not use pinned active bounds", err)
	}
	prepared, tag, err := c.Finalize(ctx, 10001, Hash{7}, nil)
	if err != nil || prepared.Height != 10001 {
		t.Fatal("finalize did not use pinned active bounds", err)
	}
	encoded, err := c.BlockBytes(10001, Hash{7}, nil)
	if err != nil || tag != sha256.Sum256(encoded) {
		t.Fatal("ABCI and worker candidate bytes would disagree", err)
	}
	if state, err := c.Commit(ctx, tag); err != nil || state.Height != 10001 {
		t.Fatal("active commit response rejected", err)
	}
	r, err := c.ActiveCapacity(ctx)
	if err != nil || r.Summary.Height != 10001 || r.LogicalBytes != 1500258 || r.Segments != 2 || r.TailBytes != 451650 {
		t.Fatal("active capacity exchange lost its bound summary", err)
	}
	if err := c.Check(ctx, []byte{1}); err != nil {
		t.Fatal("ordinary framing stopped working after capacity exchange", err)
	}
}

func TestLegacyCapacityRejectedBeforeExchange(t *testing.T) {
	c := helper(t, "ok", time.Second)
	if c.Profile() != LegacyJournal {
		t.Fatal("legacy client silently upgraded")
	}
	if _, err := c.ActiveCapacity(context.Background()); !errors.Is(err, ErrBounds) || c.id != 0 {
		t.Fatal("legacy client sent an unsupported op6", err)
	}
	if _, err := c.Status(context.Background()); err != nil || c.id != 1 {
		t.Fatal("unsupported capacity request damaged the legacy session", err)
	}
}

func TestActiveCapacityMalformedReplyClosesClient(t *testing.T) {
	for _, mode := range []string{"old-size", "bad-height", "bad-commitments", "bad-capacity", "reject-nonzero", "bad-id", "bad-hash", "bad-status", "truncated", "exit", "hang"} {
		t.Run(mode, func(t *testing.T) {
			timeout := time.Second
			want := ErrProtocol
			if mode == "truncated" || mode == "exit" || mode == "hang" {
				want = ErrUnavailable
			}
			if mode == "hang" {
				timeout = 100 * time.Millisecond
			}
			c := activeHelper(t, mode, timeout)
			if r, err := c.ActiveCapacity(context.Background()); !errors.Is(err, want) || r != (ActiveStorage{}) {
				t.Fatal("malformed reply returned a capacity snapshot", err)
			}
			if _, err := c.Status(context.Background()); !errors.Is(err, ErrClosed) {
				t.Fatal("invalid capacity reply left client usable", err)
			}
		})
	}
}

func TestActiveCapacityRejectsUnsupportedRequestShapesBeforeWriting(t *testing.T) {
	c := activeHelper(t, "ok", time.Second)
	ctx := context.Background()
	var capacity ActiveStorage
	var mask uint64
	for _, q := range []struct {
		op      byte
		payload []byte
		mask    *uint64
		out     *ActiveStorage
	}{
		{6, []byte{1}, nil, &capacity},
		{6, nil, nil, nil},
		{6, nil, &mask, &capacity},
		{5, nil, &mask, &capacity},
		{7, nil, nil, nil},
	} {
		if _, err := c.exchangeReply(ctx, q.op, q.payload, q.mask, q.out); !errors.Is(err, ErrBounds) || c.id != 0 {
			t.Fatal("unsupported request reached the worker", err)
		}
	}
	if _, err := c.ActiveCapacity(nil); !errors.Is(err, ErrBounds) || c.id != 0 {
		t.Fatal("nil context reached the worker", err)
	}
	if _, err := c.ActiveCapacity(ctx); err != nil || c.id != 1 {
		t.Fatal("rejected preflight poisoned the session", err)
	}
}

func TestActiveCapacityOrdinaryRejectionAndCancellation(t *testing.T) {
	c := activeHelper(t, "reject", time.Second)
	for i := 0; i < 2; i++ {
		if r, err := c.ActiveCapacity(context.Background()); !errors.Is(err, ErrRejected) || r != (ActiveStorage{}) {
			t.Fatal("ordinary rejection was not preserved", err)
		}
	}
	if _, err := c.Status(context.Background()); err != nil {
		t.Fatal("ordinary rejection closed the session", err)
	}
	c = activeHelper(t, "hang", time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if _, err := c.ActiveCapacity(ctx); !errors.Is(err, ErrUnavailable) || !errors.Is(err, context.DeadlineExceeded) {
		t.Fatal("inflight cancellation lost failure propagation", err)
	}
	if _, err := c.Status(context.Background()); !errors.Is(err, ErrClosed) {
		t.Fatal("inflight cancellation did not close the session", err)
	}
}

func FuzzActiveCapacity(f *testing.F) {
	f.Add(uint64(10001), capacityBytes(1500258, 2, 451650), uint64(108))
	f.Add(uint64(0), capacityBytes(588, 0, 0), uint64(588))
	f.Fuzz(func(t *testing.T, height uint64, raw []byte, header uint64) {
		s := Summary{Height: height, AppHash: Hash{1}}
		r, err := decodeActiveStorage(s, raw, header)
		if err == nil && (r.Summary != s || len(raw) != 16 ||
			r.LogicalBytes != binary.BigEndian.Uint64(raw[:8]) ||
			r.Segments != binary.BigEndian.Uint32(raw[8:12]) || r.TailBytes != binary.BigEndian.Uint32(raw[12:16])) {
			t.Fatal("capacity decode did not preserve its bound fields")
		}
	})
}
