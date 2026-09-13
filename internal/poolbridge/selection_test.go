package poolbridge

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"testing"
	"time"
)

func TestSelectionEncodingBoundsAndOwnership(t *testing.T) {
	tx := []byte{1, 2, 3}
	b, owned, err := selectionBytes(7, 100, [][]byte{nil, tx})
	if err != nil || len(b) != 61 || binary.BigEndian.Uint64(b[:8]) != 7 || binary.BigEndian.Uint16(b[48:50]) != 2 {
		t.Fatal(err)
	}
	tx[0] = 9
	if owned[1][0] != 1 {
		t.Fatal("request aliases caller memory")
	}
	result, err := selectedBytes(owned, 2, 3)
	if err != nil || len(result) != 1 || !bytes.Equal(result[0], []byte{1, 2, 3}) {
		t.Fatal(err)
	}
	result[0][0] = 8
	if owned[1][0] != 1 {
		t.Fatal("result aliases frame")
	}
	for _, q := range []struct {
		h, b uint64
		txs  [][]byte
	}{
		{0, 0, nil}, {10001, 0, nil}, {1, MaxProposalBytes + 1, nil},
		{1, 0, make([][]byte, 65)}, {1, 0, [][]byte{make([]byte, MaxTransactionBytes+1)}},
	} {
		if _, _, err = selectionBytes(q.h, q.b, q.txs); err == nil {
			t.Fatal("bad request accepted")
		}
	}
	candidates := make([][]byte, 64)
	for i := range candidates {
		candidates[i] = make([]byte, MaxTransactionBytes)
	}
	b, _, err = selectionBytes(1, MaxProposalBytes, candidates)
	if err != nil || len(b)+17 > maxFrame {
		t.Fatal("maximum request does not fit", err)
	}
}
func TestSelectionMasksAndByteBudget(t *testing.T) {
	cases := []struct {
		txs         [][]byte
		mask, limit uint64
	}{
		{nil, 1, 1}, {[][]byte{{1}}, 2, 1}, {[][]byte{nil}, 1, 1},
		{[][]byte{{1, 2}}, 1, 1}, {make([][]byte, 64), (1 << 17) - 1, MaxProposalBytes},
		{make([][]byte, 65), 0, 0},
	}
	for _, q := range cases {
		if _, err := selectedBytes(q.txs, q.mask, q.limit); err == nil {
			t.Fatal("invalid mask accepted")
		}
	}
	txs := make([][]byte, 64)
	txs[63] = []byte{1}
	out, err := selectedBytes(txs, 1<<63, 1)
	if err != nil || len(out) != 1 {
		t.Fatal(err)
	}
}
func TestSelectionReplyFailClosed(t *testing.T) {
	for _, mode := range []string{"select-old-size", "select-badmask", "select-badheight", "select-reject-mask", "badid", "badhash"} {
		t.Run(mode, func(t *testing.T) {
			c := helper(t, mode, time.Second)
			if _, err := c.SelectProposal(context.Background(), 1, 10, [][]byte{{1}}); err == nil {
				t.Fatal("invalid response accepted")
			}
			if _, err := c.Status(context.Background()); !errors.Is(err, ErrClosed) {
				t.Fatal("bad worker remained usable", err)
			}
		})
	}
}
func TestSelectionExchangeAndOrdinaryRejection(t *testing.T) {
	c := helper(t, "select-ok", time.Second)
	txs, err := c.SelectProposal(context.Background(), 1, 3, [][]byte{{1, 2, 3}})
	if err != nil || len(txs) != 1 || !bytes.Equal(txs[0], []byte{1, 2, 3}) {
		t.Fatal(err)
	}
	if _, err = c.Status(context.Background()); err != nil {
		t.Fatal(err)
	}
	c = helper(t, "reject", time.Second)
	for i := 0; i < 2; i++ {
		if _, err = c.SelectProposal(context.Background(), 1, 0, nil); !errors.Is(err, ErrRejected) {
			t.Fatal(err)
		}
	}
}
func TestSelectionCancellationClosesInFlightWorker(t *testing.T) {
	c := helper(t, "hang", time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	_, err := c.SelectProposal(ctx, 1, 3, [][]byte{{1}})
	if !errors.Is(err, context.DeadlineExceeded) || !errors.Is(err, ErrUnavailable) {
		t.Fatal(err)
	}
	if _, err = c.Status(context.Background()); !errors.Is(err, ErrClosed) {
		t.Fatal(err)
	}
}
func FuzzSelectionReplyMask(f *testing.F) {
	f.Add(uint64(1), uint64(3), []byte{1, 2, 3})
	f.Add(uint64(1<<63), uint64(0), []byte{})
	f.Fuzz(func(t *testing.T, mask, limit uint64, raw []byte) {
		if len(raw) > MaxTransactionBytes {
			return
		}
		txs := [][]byte{raw}
		chosen, err := selectedBytes(txs, mask, limit)
		if err == nil && (mask > 1 || (mask == 1 && (len(raw) == 0 || uint64(len(raw)) > limit)) || len(chosen) > 1) {
			t.Fatal("accepted inconsistent selection")
		}
	})
}
