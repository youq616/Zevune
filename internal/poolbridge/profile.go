package poolbridge

// StorageProfile is a fixed laboratory policy selected by an independently
// pinned genesis manifest. It is not a caller-selected capacity override.
type StorageProfile uint8

const (
	LegacyJournal StorageProfile = iota
	ActiveSegmentsV1
)

const (
	ActiveSegmentBytes = 1024 * 1024
	ActiveMaxSegments  = 2048
	EmptyRecordBytes   = 150
)

const activeDomain = "ZEVUNE-POOL-IPC-4:zevune-orchard-lab-1:16:28134:selection-64:active-segments-1:1000000:1073741824"

func (p StorageProfile) valid() bool {
	return p == LegacyJournal || p == ActiveSegmentsV1
}

// MaxHeight returns the fixed committed-record limit, or zero for an unknown
// profile. It does not change the requirement for consecutive block heights.
func (p StorageProfile) MaxHeight() uint64 {
	switch p {
	case LegacyJournal:
		return 10_000
	case ActiveSegmentsV1:
		return 1_000_000
	default:
		return 0
	}
}

// MaxJournalBytes counts the genesis header and complete record frames, not
// filesystem allocation, directory entries, or free space on the host.
func (p StorageProfile) MaxJournalBytes() uint64 {
	switch p {
	case LegacyJournal:
		return 64 * 1024 * 1024
	case ActiveSegmentsV1:
		return 1024 * 1024 * 1024
	default:
		return 0
	}
}

func (p StorageProfile) ipcDomain() string {
	switch p {
	case LegacyJournal:
		return domain
	case ActiveSegmentsV1:
		return activeDomain
	default:
		return ""
	}
}

// Profile is immutable after the pinned manifest and exact worker handshake
// have been checked. A worker response cannot select or upgrade this policy.
func (c *Client) Profile() StorageProfile { return c.profile }

// BlockBytes uses the same policy as Preview and Finalize, so callers can bind
// their pending candidate to the exact bytes without silently using legacy bounds.
func (c *Client) BlockBytes(height uint64, hash Hash, txs [][]byte) ([]byte, error) {
	return c.profile.BlockBytes(height, hash, txs)
}
