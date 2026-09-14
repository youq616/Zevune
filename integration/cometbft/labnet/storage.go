package labnet

import (
	"context"
	"os"
	"path/filepath"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// These are the existing bounded laboratory limits, NOT new storage policy.
// A new storage format/limit must update this inspector and its acceptance tests.
const journalLimitBytes uint64 = 64 * 1024 * 1024
const commitmentLimit uint64 = 65536
const recordLimit uint64 = uint64(maxHeight)
const minimumJournalHeaderBytes uint64 = 44
const emptyRecordBytes uint64 = 150

// StorageReport describes one offline journal after genuine worker replay. It
// says nothing about consensus freshness, disk free space, or spend permission.
type StorageReport struct {
	Scope                 string   `json:"scope"`
	Height                uint64   `json:"height"`
	AppHash               string   `json:"app_hash"`
	JournalBytes          uint64   `json:"journal_bytes"`
	JournalLimitBytes     uint64   `json:"journal_limit_bytes"`
	JournalRemainingBytes uint64   `json:"journal_remaining_bytes"`
	RecordsRemaining      uint64   `json:"records_remaining"`
	Commitments           uint64   `json:"commitments"`
	CommitmentsRemaining  uint64   `json:"commitments_remaining"`
	EmptyRecordBytes      uint64   `json:"empty_record_bytes"`
	EmptyBlockFitsLimits  bool     `json:"empty_block_fits_limits"`
	Warnings              []string `json:"warnings"`
	ConsensusVerified     bool     `json:"consensus_verified"`
	NetworkAccessed       bool     `json:"network_accessed"`
	RealFundsAllowed      bool     `json:"real_funds_allowed"`
}

func storageReport(s poolbridge.Summary, size int64) (StorageReport, error) {
	if size < 0 || uint64(size) > journalLimitBytes || s.Height > recordLimit ||
		s.Commitments > commitmentLimit || s.Nullifiers > commitmentLimit {
		return StorageReport{}, ErrBounds
	}
	// Every committed block consumes framing, even an empty block. The
	// multiplication is bounded by the height check above (maximum 10000).
	if uint64(size) < minimumJournalHeaderBytes+s.Height*emptyRecordBytes {
		return StorageReport{}, ErrStorage
	}
	r := StorageReport{
		Scope: "offline_replayed_journal_capacity_not_finality", Height: s.Height,
		AppHash: HashText(s.AppHash), JournalBytes: uint64(size),
		JournalLimitBytes:     journalLimitBytes,
		JournalRemainingBytes: journalLimitBytes - uint64(size),
		RecordsRemaining:      recordLimit - s.Height, Commitments: s.Commitments,
		CommitmentsRemaining: commitmentLimit - s.Commitments,
		EmptyRecordBytes:     emptyRecordBytes, Warnings: []string{},
	}
	r.EmptyBlockFitsLimits = r.RecordsRemaining > 0 && r.JournalRemainingBytes >= emptyRecordBytes
	if r.RecordsRemaining == 0 {
		r.Warnings = append(r.Warnings, "record_limit_reached")
	} else if r.RecordsRemaining <= recordLimit/10 {
		r.Warnings = append(r.Warnings, "record_limit_approaching")
	}
	if r.JournalRemainingBytes < emptyRecordBytes {
		r.Warnings = append(r.Warnings, "insufficient_bytes_for_empty_record")
	} else if r.JournalRemainingBytes <= journalLimitBytes/10 {
		r.Warnings = append(r.Warnings, "journal_byte_limit_approaching")
	}
	if r.CommitmentsRemaining < 2 {
		r.Warnings = append(r.Warnings, "insufficient_commitment_slots_for_payment")
	} else if r.CommitmentsRemaining <= commitmentLimit/10 {
		r.Warnings = append(r.Warnings, "commitment_limit_approaching")
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
	if n == nil || ctx == nil || ctx.Err() != nil {
		return StorageReport{}, ErrBounds
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
	return storageReport(s, after.Size())
}
