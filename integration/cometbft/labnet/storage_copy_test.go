package labnet

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// The bytes in the ordinary filesystem tests are not Orchard journals. These
// tests cannot authorize their publication through CopyStorageAtCheckpoint.
func TestBoundedCopyRejectsShortLongAndCancelledInput(t *testing.T) {
	data := bytes.Repeat([]byte{7}, 150)
	for _, length := range []int64{-1, 0, 43, 149, 151, int64(journalLimitBytes) + 1} {
		var dst bytes.Buffer
		if _, err := copyJournalBytes(context.Background(), &dst, bytes.NewReader(data), length); err == nil {
			t.Fatal("bad source length accepted", length)
		}
	}
	var dst bytes.Buffer
	digest, err := copyJournalBytes(context.Background(), &dst, bytes.NewReader(data), int64(len(data)))
	if err != nil || digest != sha256.Sum256(data) || !bytes.Equal(data, dst.Bytes()) {
		t.Fatal("exact copy failed", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	dst.Reset()
	if _, err := copyJournalBytes(ctx, &dst, bytes.NewReader(data), 150); !errors.Is(err, context.Canceled) || dst.Len() != 0 {
		t.Fatal("cancelled copy wrote bytes", err)
	}
}

type failingCopyWriter struct{ bytes.Buffer }

func (w *failingCopyWriter) Write(b []byte) (int, error) {
	n, _ := w.Buffer.Write(b[:3])
	return n, io.ErrShortWrite
}

type cancelCopyReader struct {
	cancel context.CancelFunc
	reads  int
}

func (r *cancelCopyReader) Read(p []byte) (int, error) {
	r.reads++
	p[0] = 1
	r.cancel()
	return 1, nil
}

func TestCopyIOFailureAndMidstreamCancelNeverYieldDigest(t *testing.T) {
	var dst failingCopyWriter
	if h, err := copyJournalBytes(context.Background(), &dst, bytes.NewReader(make([]byte, 150)), 150); err == nil || h != (Hash{}) || dst.Len() != 3 {
		t.Fatal("partial write reported success")
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	src := &cancelCopyReader{cancel: cancel}
	var out bytes.Buffer
	if h, err := copyJournalBytes(ctx, &out, src, 150); !errors.Is(err, context.Canceled) || h != (Hash{}) || src.reads != 1 {
		t.Fatal("midstream cancellation ignored")
	}
}

func TestCopyPathsAndPublicEntryRejectBeforeWorker(t *testing.T) {
	dir := t.TempDir()
	source := filepath.Join(dir, "source.journal")
	if err := os.WriteFile(source, make([]byte, 150), 0600); err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(dir, "new.journal")
	valid := StorageCheckpoint{AppHash: Hash{1}}
	for _, o := range []StorageCopyOptions{
		{Source: source, Destination: destination},
		{Worker: filepath.Join(dir, "missing-worker"), WorkerPin: Hash{1}, Source: source, Destination: destination},
		{Worker: filepath.Join(dir, "missing-worker"), WorkerPin: Hash{1}, Source: source, Destination: source, Expected: valid},
		{Worker: filepath.Join(dir, "missing-worker"), WorkerPin: Hash{1}, Source: "relative", Destination: destination, Expected: valid},
	} {
		if r, err := (&Network{}).CopyStorageAtCheckpoint(context.Background(), o); err == nil || r != (StorageCopyReport{}) {
			t.Fatal("invalid request reported a copy")
		}
	}
	var n *Network
	if _, err := n.CopyStorageAtCheckpoint(context.Background(), StorageCopyOptions{}); !errors.Is(err, ErrBounds) {
		t.Fatal("nil receiver accepted")
	}
	if _, err := (&Network{}).CopyStorageAtCheckpoint(nil, StorageCopyOptions{}); !errors.Is(err, ErrBounds) {
		t.Fatal("nil context accepted")
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		t.Fatal("invalid request created output")
	}
	if _, err := copyPaths(source, dir); err == nil {
		t.Fatal("existing directory accepted as destination")
	}
}

func TestPublishCopyIsCreateOnlyAndDoesNotLinkSource(t *testing.T) {
	dir := t.TempDir()
	source, staged, destination := filepath.Join(dir, "source"), filepath.Join(dir, "staged"), filepath.Join(dir, "published")
	data := bytes.Repeat([]byte{3}, 150)
	if err := os.WriteFile(source, data, 0600); err != nil {
		t.Fatal(err)
	}
	info, _ := journalInfo(source)
	h, written, err := stageJournalCopy(context.Background(), source, staged, info)
	if err != nil || h != sha256.Sum256(data) || os.SameFile(info, written) {
		t.Fatal("copy reused source inode", err)
	}
	var calls int
	syncer := func(string) (bool, error) { calls++; return true, nil }
	if _, err := publishJournalCopy(context.Background(), staged, destination, written, syncer); err != nil || calls != 1 {
		t.Fatal("publish failed", err)
	}
	target, _ := journalInfo(destination)
	if !os.SameFile(written, target) || os.SameFile(info, target) {
		t.Fatal("published link is not to the separate staged copy")
	}
	if _, err := publishJournalCopy(context.Background(), staged, destination, written, syncer); err == nil || calls != 1 {
		t.Fatal("destination collision did not fail before sync")
	}
	if err := os.Remove(staged); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(destination)
	if err != nil || !bytes.Equal(got, data) {
		t.Fatal("removing owned staging name affected destination")
	}
}

func TestPublicationFailureAfterLinkIsExplicitlyUncertain(t *testing.T) {
	dir := t.TempDir()
	stage, destination := filepath.Join(dir, "stage"), filepath.Join(dir, "output")
	data := make([]byte, 150)
	if err := os.WriteFile(stage, data, 0600); err != nil {
		t.Fatal(err)
	}
	info, _ := journalInfo(stage)
	if _, err := publishJournalCopy(context.Background(), stage, destination, info, func(string) (bool, error) {
		return false, errors.New("test-only directory sync failure")
	}); !errors.Is(err, ErrCopyPublicationUncertain) {
		t.Fatal("post-publication failure reported as definite non-creation", err)
	}
	got, err := os.ReadFile(destination)
	if err != nil || !bytes.Equal(got, data) {
		t.Fatal("published destination removed or changed after error")
	}
}

func TestPublicationCancellationAndExistingSymlinkDoNotOverwrite(t *testing.T) {
	dir := t.TempDir()
	stage, output := filepath.Join(dir, "stage"), filepath.Join(dir, "output")
	if err := os.WriteFile(stage, make([]byte, 150), 0600); err != nil {
		t.Fatal(err)
	}
	info, _ := journalInfo(stage)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := publishJournalCopy(ctx, stage, output, info, syncCopyDirectory); !errors.Is(err, context.Canceled) {
		t.Fatal("pre-publication cancellation ignored")
	}
	if _, err := os.Lstat(output); !os.IsNotExist(err) {
		t.Fatal("cancelled publication created output")
	}
	if runtime.GOOS == "windows" {
		return // symlink privileges are not required for the Windows product
	}
	missing := filepath.Join(dir, "missing")
	if err := os.Symlink(missing, output); err != nil {
		t.Fatal(err)
	}
	if _, err := copyPaths(stage, output); err == nil {
		t.Fatal("dangling destination symlink accepted")
	}
	if _, err := publishJournalCopy(context.Background(), stage, output, info, syncCopyDirectory); err == nil {
		t.Fatal("existing symlink overwritten")
	}
	if got, err := os.Readlink(output); err != nil || got != missing {
		t.Fatal("original link changed")
	}
}

func TestCopyReportDoesNotClaimConsensusOrFunds(t *testing.T) {
	b, err := json.Marshal(StorageCopyReport{ExpectedCheckpointMatched: true, FileSynced: true})
	if err != nil || !strings.Contains(string(b), `"consensus_verified":false`) || !strings.Contains(string(b), `"real_funds_allowed":false`) {
		t.Fatal("copy overclaims verification")
	}
}

func TestJournalDigestDetectsChangedAndReplacedFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "journal")
	data := make([]byte, 150)
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	info, _ := journalInfo(path)
	want := sha256.Sum256(data)
	if got, err := journalDigest(context.Background(), path, info); err != nil || got != want {
		t.Fatal("baseline fingerprint", err)
	}
	if err := os.Rename(path, path+".old"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := journalDigest(context.Background(), path, info); err == nil {
		t.Fatal("same-byte different-inode replacement accepted")
	}
	fresh, _ := journalInfo(path)
	if err := os.WriteFile(path, append(data, 1), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := journalDigest(context.Background(), path, fresh); err == nil {
		t.Fatal("growing journal accepted")
	}
}

func TestCancelAfterPublishRetainsCompleteCopyWithUncertainResult(t *testing.T) {
	dir := t.TempDir()
	stage, output := filepath.Join(dir, "stage"), filepath.Join(dir, "out")
	data := make([]byte, 150)
	if err := os.WriteFile(stage, data, 0600); err != nil {
		t.Fatal(err)
	}
	info, _ := journalInfo(stage)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if _, err := publishJournalCopy(ctx, stage, output, info, func(string) (bool, error) {
		cancel()
		return true, nil
	}); !errors.Is(err, ErrCopyPublicationUncertain) {
		t.Fatal("post-link cancel gave definite failure", err)
	}
	got, err := os.ReadFile(output)
	if err != nil || !bytes.Equal(got, data) {
		t.Fatal("complete output lost", err)
	}
}
