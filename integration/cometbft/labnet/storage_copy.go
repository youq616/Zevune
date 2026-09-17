package labnet

import (
	"context"
	"crypto/sha256"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// ErrCopyPublicationUncertain never authorizes deletion or automatic retry. A
// complete destination may exist even though publication acknowledgement failed.
var ErrCopyPublicationUncertain = errors.New("journal copy publication uncertain; inspect the destination at the retained checkpoint before retrying")

// Active segments have no legacy single-file copy/recovery representation.
var ErrStorageProfile = errors.New("operation is unsupported for this authenticated storage profile")

type StorageCopyOptions struct {
	Worker      string
	WorkerPin   Hash
	Source      string
	Destination string
	Expected    StorageCheckpoint // mandatory, independently retained exact tip
}

type StorageCopyReport struct {
	Scope                     string `json:"scope"`
	Height                    uint64 `json:"height"`
	AppHash                   string `json:"app_hash"`
	JournalBytes              uint64 `json:"journal_bytes"`
	JournalSHA256             string `json:"journal_sha256"`
	ExpectedCheckpointMatched bool   `json:"expected_checkpoint_matched"`
	FileSynced                bool   `json:"file_synced"`
	DirectorySynced           bool   `json:"directory_synced"`
	ConsensusVerified         bool   `json:"consensus_verified"`
	RealFundsAllowed          bool   `json:"real_funds_allowed"`
}

// CopyStorageAtCheckpoint is the same verified, create-only operation for an
// offline backup or restore. It never resets or copies validator signing keys.
// Source and staged copy are each replayed by the genuine pinned worker. A
// separate copy, NOT a hard link to the source, is published only after replay.
//
// The source worker is closed before copying (Windows exclusive locks prevent a
// second reader). Therefore its earlier verdict is NOT reused as authorization:
// the exact staged copy must independently replay to Expected before publication.
// This is not a hot backup, a state-only snapshot, pruning, or a capacity increase.
func (n *Network) CopyStorageAtCheckpoint(ctx context.Context, o StorageCopyOptions) (StorageCopyReport, error) {
	if n != nil && n.profile != poolbridge.LegacyJournal {
		return StorageCopyReport{}, ErrStorageProfile
	}
	if ctx == nil || n == nil || ctx.Err() != nil || o.Expected.Validate() != nil ||
		!filepath.IsAbs(o.Worker) || o.WorkerPin == (Hash{}) {
		return StorageCopyReport{}, ErrBounds
	}
	before, err := copyPaths(o.Source, o.Destination)
	if err != nil {
		return StorageCopyReport{}, err
	}
	if _, err = n.InspectStorageAtCheckpoint(ctx, o.Worker, o.WorkerPin, o.Source, o.Expected); err != nil {
		return StorageCopyReport{}, err
	}
	parent := filepath.Dir(o.Destination)
	stageDir, err := os.MkdirTemp(parent, ".zevune-copy-")
	if err != nil {
		return StorageCopyReport{}, ErrStorage
	}
	stage := filepath.Join(stageDir, "journal.pending")
	// Remove only our two exact scratch names, never user data or the published
	// destination. Abrupt process termination can leave this private scratch dir.
	defer func() { _ = os.Remove(stage); _ = os.Remove(stageDir) }()
	digest, stagedInfo, err := stageJournalCopy(ctx, o.Source, stage, before)
	if err != nil {
		return StorageCopyReport{}, err
	}
	checked, err := n.verifyCopiedJournal(ctx, o, stage, stagedInfo, digest)
	if err != nil {
		return StorageCopyReport{}, err
	}
	after, err := journalInfo(o.Source)
	if err != nil || !sameJournal(before, after) {
		return StorageCopyReport{}, ErrStorage
	}
	directorySynced, err := publishJournalCopy(ctx, stage, o.Destination, stagedInfo, syncCopyDirectory)
	if err != nil {
		return StorageCopyReport{}, err
	}
	return StorageCopyReport{
		Scope: "offline_replayed_journal_copy_not_snapshot", Height: checked.Height,
		AppHash: checked.AppHash, JournalBytes: checked.JournalBytes,
		JournalSHA256: HashText(digest), ExpectedCheckpointMatched: true,
		FileSynced: true, DirectorySynced: directorySynced,
	}, nil
}

// The real caller and adversarial integration tests use this same final gate.
// A rewritten copy and a freshly recomputed file checksum still need genuine
// replay to the caller's independent checkpoint; there is no accepting callback.
func (n *Network) verifyCopiedJournal(ctx context.Context, o StorageCopyOptions, stage string, info os.FileInfo, digest Hash) (StorageReport, error) {
	checked, err := n.InspectStorageAtCheckpoint(ctx, o.Worker, o.WorkerPin, stage, o.Expected)
	if err != nil {
		return StorageReport{}, err
	}
	actual, err := journalDigest(ctx, stage, info)
	if err != nil || actual != digest || checked.JournalBytes != uint64(info.Size()) {
		return StorageReport{}, ErrStorage
	}
	return checked, nil
}

func copyPaths(source, destination string) (os.FileInfo, error) {
	if !filepath.IsAbs(source) || !filepath.IsAbs(destination) ||
		filepath.Clean(source) != source || filepath.Clean(destination) != destination || source == destination {
		return nil, ErrBounds
	}
	if _, err := os.Lstat(destination); !os.IsNotExist(err) {
		return nil, ErrStorage
	}
	parent, err := os.Lstat(filepath.Dir(destination))
	if err != nil || !parent.IsDir() || parent.Mode()&os.ModeSymlink != 0 {
		return nil, ErrStorage
	}
	return journalInfo(source)
}

type copyContextReader struct {
	ctx context.Context
	r   io.Reader
}

func (r copyContextReader) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.r.Read(p)
}

// This helper verifies bounded copying, NOT journal validity. Only genuine
// staged replay in CopyStorageAtCheckpoint can establish the required state.
func copyJournalBytes(ctx context.Context, dst io.Writer, src io.Reader, length int64) (Hash, error) {
	if ctx == nil || length < int64(minimumJournalHeaderBytes) || length > int64(journalLimitBytes) {
		return Hash{}, ErrBounds
	}
	h := sha256.New()
	limited := io.LimitReader(copyContextReader{ctx, src}, length+1)
	n, err := io.CopyBuffer(io.MultiWriter(dst, h), limited, make([]byte, 64*1024))
	if err != nil {
		return Hash{}, err
	}
	if n != length {
		return Hash{}, ErrStorage
	}
	if err := ctx.Err(); err != nil {
		return Hash{}, err
	}
	var digest Hash
	copy(digest[:], h.Sum(nil))
	return digest, nil
}

func stageJournalCopy(ctx context.Context, source, stage string, expected os.FileInfo) (Hash, os.FileInfo, error) {
	in, err := os.Open(source)
	if err != nil {
		return Hash{}, nil, ErrStorage
	}
	defer in.Close()
	opened, err := in.Stat()
	if err != nil || !sameJournal(expected, opened) {
		return Hash{}, nil, ErrStorage
	}
	out, err := os.OpenFile(stage, os.O_CREATE|os.O_EXCL|os.O_RDWR, 0600)
	if err != nil {
		return Hash{}, nil, ErrStorage
	}
	defer out.Close()
	digest, err := copyJournalBytes(ctx, out, in, opened.Size())
	if err != nil {
		return Hash{}, nil, err
	}
	after, err := in.Stat()
	if err != nil || !sameJournal(opened, after) {
		return Hash{}, nil, ErrStorage
	}
	if err = out.Sync(); err != nil {
		return Hash{}, nil, ErrStorage
	}
	written, err := out.Stat()
	if err != nil || written.Size() != opened.Size() || !written.Mode().IsRegular() {
		return Hash{}, nil, ErrStorage
	}
	if err = out.Close(); err != nil {
		return Hash{}, nil, ErrStorage
	}
	return digest, written, nil
}

func journalDigest(ctx context.Context, path string, expected os.FileInfo) (Hash, error) {
	info, err := journalInfo(path)
	if err != nil || !sameJournal(expected, info) {
		return Hash{}, ErrStorage
	}
	file, err := os.Open(path)
	if err != nil {
		return Hash{}, ErrStorage
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !sameJournal(expected, opened) {
		return Hash{}, ErrStorage
	}
	digest, err := copyJournalBytes(ctx, io.Discard, file, expected.Size())
	if err != nil {
		return Hash{}, err
	}
	after, err := file.Stat()
	if err != nil || !sameJournal(expected, after) {
		return Hash{}, ErrStorage
	}
	return digest, nil
}

// Link is deliberate: Rename may overwrite an existing destination. No fallback
// to overwrite/copy is permitted on a filesystem without hard-link support.
// Only filesystem synchronization is injected here for failure-path unit tests;
// callers cannot replace the genuine replay performed by the public API.
func publishJournalCopy(ctx context.Context, stage, destination string, expected os.FileInfo, syncDir func(string) (bool, error)) (bool, error) {
	if err := ctx.Err(); err != nil {
		return false, err
	}
	before, err := journalInfo(stage)
	if err != nil || !sameJournal(expected, before) {
		return false, ErrStorage
	}
	if err = os.Link(stage, destination); err != nil {
		if os.IsExist(err) {
			return false, ErrStorage
		}
		// Some filesystems can lose acknowledgement of a completed metadata
		// operation. Do not assert definite non-creation after an I/O error.
		return false, ErrCopyPublicationUncertain
	}
	// From this point every failure is uncertain, not evidence of non-creation.
	linked, err := journalInfo(destination)
	if err != nil || !sameJournal(expected, linked) {
		return false, ErrCopyPublicationUncertain
	}
	synced, err := syncDir(filepath.Dir(destination))
	if err != nil || ctx.Err() != nil {
		return false, ErrCopyPublicationUncertain
	}
	return synced, nil
}

func syncCopyDirectory(path string) (bool, error) {
	if runtime.GOOS == "windows" {
		// File.Sync is performed on all platforms. This is NOT a Windows parent
		// directory durability guarantee; report the difference explicitly.
		return false, nil
	}
	dir, err := os.Open(path)
	if err != nil {
		return false, err
	}
	defer dir.Close()
	if err = dir.Sync(); err != nil {
		return false, err
	}
	return true, nil
}
