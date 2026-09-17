package labnet

import (
	"context"
	"os"
	"path/filepath"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// Legacy helpers retain the existing single-file laboratory limits. Active
// capacity comes only from the pinned worker's committed capacity snapshot.
const journalLimitBytes uint64 = 64 * 1024 * 1024
const commitmentLimit uint64 = 65536
const recordLimit uint64 = 10000
const minimumJournalHeaderBytes uint64 = 44
const emptyRecordBytes uint64 = 150

// StorageReport describes one offline journal after genuine worker replay. It
// says nothing about consensus freshness, disk free space, or spend permission.
type StorageReport struct {
	Scope                     string   `json:"scope"`
	StorageProfile            string   `json:"storage_profile"`
	Height                    uint64   `json:"height"`
	AppHash                   string   `json:"app_hash"`
	JournalBytes              uint64   `json:"journal_bytes"`
	JournalLimitBytes         uint64   `json:"journal_limit_bytes"`
	JournalRemainingBytes     uint64   `json:"journal_remaining_bytes"`
	RecordsRemaining          uint64   `json:"records_remaining"`
	Commitments               uint64   `json:"commitments"`
	CommitmentsRemaining      uint64   `json:"commitments_remaining"`
	EmptyRecordBytes          uint64   `json:"empty_record_bytes"`
	EmptyBlockFitsLimits      bool     `json:"empty_block_fits_limits"`
	Warnings                  []string `json:"warnings"`
	ExpectedCheckpointMatched bool     `json:"expected_checkpoint_matched"`
	ConsensusVerified         bool     `json:"consensus_verified"`
	NetworkAccessed           bool     `json:"network_accessed"`
	RealFundsAllowed          bool     `json:"real_funds_allowed"`
	Segments                  uint32   `json:"segments,omitempty"`
	SegmentLimit              uint32   `json:"segment_limit,omitempty"`
	TailBytes                 uint32   `json:"tail_bytes,omitempty"`
}

func storageReport(s poolbridge.Summary, size int64) (StorageReport, error) {
	return storageReportForProfile(poolbridge.LegacyJournal, s, size)
}

func storageReportForProfile(profile poolbridge.StorageProfile, s poolbridge.Summary, size int64) (StorageReport, error) {
	byteLimit, heightLimit := profile.MaxJournalBytes(), profile.MaxHeight()
	if byteLimit == 0 || heightLimit == 0 || size < 0 || uint64(size) > byteLimit || s.Height > heightLimit ||
		s.Commitments > commitmentLimit || s.Nullifiers > commitmentLimit {
		return StorageReport{}, ErrBounds
	}
	// Every committed block consumes framing, even an empty block. The
	// multiplication is bounded by the authenticated profile's height limit.
	if uint64(size) < minimumJournalHeaderBytes+s.Height*emptyRecordBytes {
		return StorageReport{}, ErrStorage
	}
	r := StorageReport{
		Scope: "offline_replayed_journal_capacity_not_finality", StorageProfile: "legacy_journal", Height: s.Height,
		AppHash: HashText(s.AppHash), JournalBytes: uint64(size),
		JournalLimitBytes:     byteLimit,
		JournalRemainingBytes: byteLimit - uint64(size),
		RecordsRemaining:      heightLimit - s.Height, Commitments: s.Commitments,
		CommitmentsRemaining: commitmentLimit - s.Commitments,
		EmptyRecordBytes:     emptyRecordBytes, Warnings: []string{},
	}
	r.EmptyBlockFitsLimits = r.RecordsRemaining > 0 && r.JournalRemainingBytes >= emptyRecordBytes
	if r.RecordsRemaining == 0 {
		r.Warnings = append(r.Warnings, "record_limit_reached")
	} else if r.RecordsRemaining <= heightLimit/10 {
		r.Warnings = append(r.Warnings, "record_limit_approaching")
	}
	if r.JournalRemainingBytes < emptyRecordBytes {
		r.Warnings = append(r.Warnings, "insufficient_bytes_for_empty_record")
	} else if r.JournalRemainingBytes <= byteLimit/10 {
		r.Warnings = append(r.Warnings, "journal_byte_limit_approaching")
	}
	if r.CommitmentsRemaining < 2 {
		r.Warnings = append(r.Warnings, "insufficient_commitment_slots_for_payment")
	} else if r.CommitmentsRemaining <= commitmentLimit/10 {
		r.Warnings = append(r.Warnings, "commitment_limit_approaching")
	}
	return r, nil
}

func activeStorageReport(snapshot poolbridge.ActiveStorage, expected *StorageCheckpoint) (StorageReport, error) {
	profile := poolbridge.ActiveSegmentsV1
	s := snapshot.Summary
	if expected != nil {
		if err := expected.validate(profile); err != nil {
			return StorageReport{}, err
		}
		if s.Height != expected.Height || s.AppHash != expected.AppHash {
			return StorageReport{}, ErrStorageCheckpoint
		}
	}
	// ActiveCapacity already checks the exact pinned genesis header length and
	// framing relations. Retain profile/segment bounds here before converting.
	if snapshot.LogicalBytes > profile.MaxJournalBytes() || snapshot.Segments > poolbridge.ActiveMaxSegments || snapshot.TailBytes > poolbridge.ActiveSegmentBytes ||
		(s.Height == 0 && (snapshot.Segments != 0 || snapshot.TailBytes != 0)) ||
		(s.Height > 0 && (snapshot.Segments == 0 || snapshot.TailBytes < uint32(emptyRecordBytes))) {
		return StorageReport{}, ErrStorage
	}
	r, err := storageReportForProfile(profile, s, int64(snapshot.LogicalBytes))
	if err != nil {
		return StorageReport{}, err
	}
	r.Scope = "offline_replayed_active_segments_capacity_not_finality"
	r.StorageProfile = "active_segments_v1"
	r.Segments, r.SegmentLimit, r.TailBytes = snapshot.Segments, poolbridge.ActiveMaxSegments, snapshot.TailBytes
	r.ExpectedCheckpointMatched = expected != nil
	if snapshot.Segments == poolbridge.ActiveMaxSegments && uint64(snapshot.TailBytes)+emptyRecordBytes > poolbridge.ActiveSegmentBytes {
		r.EmptyBlockFitsLimits = false
		r.Warnings = append(r.Warnings, "no_segment_available_for_empty_record")
	} else if snapshot.Segments >= poolbridge.ActiveMaxSegments-poolbridge.ActiveMaxSegments/10 {
		r.Warnings = append(r.Warnings, "segment_limit_approaching")
	}
	return r, nil
}

func journalInfo(path string) (os.FileInfo, error) {
	if !filepath.IsAbs(path) {
		return nil, ErrBounds
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() < int64(minimumJournalHeaderBytes) ||
		info.Size() > int64(journalLimitBytes) {
		return nil, ErrStorage
	}
	return info, nil
}

func sameJournal(before, after os.FileInfo) bool {
	return before != nil && after != nil && after.Mode().IsRegular() &&
		os.SameFile(before, after) && before.Size() == after.Size() && before.ModTime() == after.ModTime()
}

// InspectStorage never connects to an RPC or creates a journal. The existing
// pinned worker takes the exclusive journal lock and replays every record with
// real authorization checks. A running node's journal is deliberately refused.
// Metadata checks detect ordinary replacement/growth during inspection; they
// are not a defense against malicious local OS or same-size/mtime tampering.
func (n *Network) InspectStorage(ctx context.Context, worker string, workerPin Hash, journal string) (StorageReport, error) {
	return n.inspectStorage(ctx, worker, workerPin, journal, nil)
}

// InspectStorageAtCheckpoint performs the same genuine offline replay and lock
// checks as InspectStorage, then requires an exact independently selected tip.
// No checkpoint is derived from the candidate journal or fetched from an RPC.
func (n *Network) InspectStorageAtCheckpoint(ctx context.Context, worker string, workerPin Hash, journal string, expected StorageCheckpoint) (StorageReport, error) {
	if err := n.ValidateStorageCheckpoint(expected); err != nil {
		return StorageReport{}, err
	}
	// Copy by value so the caller cannot change the requirement during replay.
	return n.inspectStorage(ctx, worker, workerPin, journal, &expected)
}

func (n *Network) inspectStorage(ctx context.Context, worker string, workerPin Hash, journal string, expected *StorageCheckpoint) (StorageReport, error) {
	if n == nil || ctx == nil || ctx.Err() != nil {
		return StorageReport{}, ErrBounds
	}
	if n.profile == poolbridge.ActiveSegmentsV1 {
		return n.inspectActiveStorage(ctx, worker, workerPin, journal, expected)
	}
	if n.profile != poolbridge.LegacyJournal {
		return StorageReport{}, ErrStorageProfile
	}
	before, err := journalInfo(journal)
	if err != nil {
		return StorageReport{}, err
	}
	store, err := poolbridge.Start(ctx, n.workerOptions(worker, workerPin, journal, false))
	if err != nil {
		return StorageReport{}, err
	}
	defer store.Close()
	s, err := store.Status(ctx)
	if err != nil {
		return StorageReport{}, err
	}
	after, err := journalInfo(journal)
	if err != nil || !sameJournal(before, after) {
		return StorageReport{}, ErrStorage
	}
	if err := ctx.Err(); err != nil {
		return StorageReport{}, err
	}
	if err := store.Close(); err != nil {
		return StorageReport{}, err
	}
	if err := ctx.Err(); err != nil {
		return StorageReport{}, err
	}
	return storageReportAtCheckpoint(s, after.Size(), expected)
}

func (n *Network) inspectActiveStorage(ctx context.Context, worker string, workerPin Hash, journal string, expected *StorageCheckpoint) (StorageReport, error) {
	store, err := poolbridge.Start(ctx, n.workerOptions(worker, workerPin, journal, false))
	if err != nil {
		return StorageReport{}, err
	}
	defer store.Close()
	if store.Profile() != n.profile {
		return StorageReport{}, ErrConfiguration
	}
	snapshot, err := store.ActiveCapacity(ctx)
	if err != nil {
		return StorageReport{}, err
	}
	if err := store.Close(); err != nil {
		return StorageReport{}, err
	}
	if err := ctx.Err(); err != nil {
		return StorageReport{}, err
	}
	return activeStorageReport(snapshot, expected)
}
