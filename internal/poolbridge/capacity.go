package poolbridge

import (
	"context"
	"encoding/binary"
)

// ActiveStorage is a bounded snapshot for the same committed Summary. Logical
// bytes count the genesis header and full records; segment tail space is not
// counted. This is not a filesystem-free-space or fresh authorization guarantee.
type ActiveStorage struct {
	Summary      Summary
	LogicalBytes uint64
	Segments     uint32
	TailBytes    uint32
}

const maxRecordBytes = EmptyRecordBytes + MaxTransactions*(4+MaxTransactionBytes)

func decodeActiveStorage(s Summary, raw []byte, headerBytes uint64) (ActiveStorage, error) {
	if len(raw) != 16 || headerBytes < 108 || headerBytes > 76+32*testGenesisMaxAllocations ||
		(headerBytes-76)%32 != 0 || s.Height > ActiveSegmentsV1.MaxHeight() ||
		s.Commitments > 65536 || s.Nullifiers > 65536 {
		return ActiveStorage{}, ErrProtocol
	}
	r := ActiveStorage{
		Summary:      s,
		LogicalBytes: binary.BigEndian.Uint64(raw[:8]),
		Segments:     binary.BigEndian.Uint32(raw[8:12]),
		TailBytes:    binary.BigEndian.Uint32(raw[12:16]),
	}
	if r.LogicalBytes < headerBytes+s.Height*EmptyRecordBytes ||
		r.LogicalBytes > ActiveSegmentsV1.MaxJournalBytes() || r.Segments > ActiveMaxSegments ||
		r.TailBytes > ActiveSegmentBytes {
		return ActiveStorage{}, ErrProtocol
	}
	if s.Height == 0 {
		if r.LogicalBytes != headerBytes || r.Segments != 0 || r.TailBytes != 0 {
			return ActiveStorage{}, ErrProtocol
		}
		return r, nil
	}
	if r.Segments == 0 || uint64(r.Segments) > s.Height || r.TailBytes < EmptyRecordBytes {
		return ActiveStorage{}, ErrProtocol
	}
	// Every non-tail segment closed only because the next full record did not
	// fit. Even the largest permitted record could not justify an earlier roll.
	sealed := uint64(r.Segments - 1)
	data := r.LogicalBytes - headerBytes
	if data < sealed*(ActiveSegmentBytes-maxRecordBytes+1)+uint64(r.TailBytes) ||
		data > sealed*ActiveSegmentBytes+uint64(r.TailBytes) ||
		data > s.Height*maxRecordBytes {
		return ActiveStorage{}, ErrProtocol
	}
	return r, nil
}

// ActiveCapacity is only available for the pinned IPC4 profile. Ordinary
// rejection preserves the client; malformed replies and I/O uncertainty close
// it through the same fail-closed exchange used by Commit.
func (c *Client) ActiveCapacity(ctx context.Context) (ActiveStorage, error) {
	if c.profile != ActiveSegmentsV1 {
		return ActiveStorage{}, ErrBounds
	}
	var snapshot ActiveStorage
	if _, err := c.exchangeReply(ctx, 6, nil, nil, &snapshot); err != nil {
		return ActiveStorage{}, err
	}
	return snapshot, nil
}
