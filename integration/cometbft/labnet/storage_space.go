package labnet

import (
	"errors"
	"os"
	"path/filepath"
	"strings"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// DiskSpaceReport is a transient OS observation after successful offline replay.
// ReserveBytes is only a warning threshold: no space is allocated or reserved.
// AvailableBytes is neither journal capacity nor a promise that a write, fsync,
// or future allocation will succeed. Scope identifies the OS-specific meaning.
type DiskSpaceReport struct {
	Scope          string `json:"scope"`
	AvailableBytes uint64 `json:"available_bytes"`
	ReserveBytes   uint64 `json:"reserve_bytes"`
	LowSpace       bool   `json:"low_space"`
	SpaceReserved  bool   `json:"space_reserved"`
}

var errDiskSpace = errors.New("disk space could not be inspected")
var errDiskSpaceUnsupported = errors.New("disk space inspection is unsupported on this platform")

// A retained file identifies the original object without reading its contents.
// These private handles are used by one inspection goroutine, never shared with
// a worker or exposed to callers. An OS query does not replace worker replay.
type diskSpaceFile struct {
	path      string
	file      *os.File
	before    os.FileInfo
	directory bool
}

type diskSpaceTarget struct {
	retained *diskSpaceFile
	// Windows queries directories by pathname, so a legacy journal also keeps
	// its containing directory open. Linux queries the journal's own descriptor.
	queryDirectory *diskSpaceFile
	closed         bool
	closeErr       error
}

func validDiskSpaceInfo(info os.FileInfo, directory bool) bool {
	if info == nil || info.Mode()&os.ModeSymlink != 0 || !diskSpacePlatformInfo(info) {
		return false
	}
	if directory {
		return info.IsDir()
	}
	return info.Mode().IsRegular()
}

func openDiskSpaceFile(path string, directory bool) (*diskSpaceFile, error) {
	before, err := os.Lstat(path)
	if err != nil || !validDiskSpaceInfo(before, directory) {
		return nil, ErrStorage
	}
	// Windows FileInfo may load its file ID lazily. Materialize it before the
	// retained open instead of resolving the initial name only after that open.
	if !os.SameFile(before, before) {
		return nil, ErrStorage
	}
	file, err := openDiskSpaceHandle(path, directory)
	if err != nil {
		return nil, errDiskSpace
	}
	retained := &diskSpaceFile{path: path, file: file, before: before, directory: directory}
	if err := retained.verify(); err != nil {
		_ = file.Close()
		return nil, err
	}
	return retained, nil
}

func openDiskSpaceTarget(profile poolbridge.StorageProfile, journal string) (*diskSpaceTarget, error) {
	if profile != poolbridge.LegacyJournal && profile != poolbridge.ActiveSegmentsV1 {
		return nil, ErrStorageProfile
	}
	if !diskSpaceSupported {
		return nil, errDiskSpaceUnsupported
	}
	// Do not clean away a final symlink/. or a symlink/.. traversal and then
	// inspect a different object from the pathname supplied to the worker.
	if !filepath.IsAbs(journal) || strings.ContainsRune(journal, '\x00') ||
		filepath.Clean(journal) != filepath.FromSlash(journal) {
		return nil, ErrBounds
	}
	path := filepath.Clean(journal)
	retained, err := openDiskSpaceFile(path, profile == poolbridge.ActiveSegmentsV1)
	if err != nil {
		return nil, err
	}
	target := &diskSpaceTarget{retained: retained}
	if diskSpaceUsesDirectory && !retained.directory {
		target.queryDirectory, err = openDiskSpaceFile(filepath.Dir(path), true)
		if err != nil {
			_ = target.close()
			return nil, err
		}
	}
	if err := target.verify(); err != nil {
		_ = target.close()
		return nil, err
	}
	return target, nil
}

func (f *diskSpaceFile) verify() error {
	if f == nil || f.file == nil || !validDiskSpaceInfo(f.before, f.directory) {
		return errDiskSpace
	}
	named, err := os.Lstat(f.path)
	if err != nil || !validDiskSpaceInfo(named, f.directory) {
		return ErrStorage
	}
	opened, err := f.file.Stat()
	if err != nil || !validDiskSpaceInfo(opened, f.directory) {
		return ErrStorage
	}
	if !os.SameFile(f.before, opened) || !os.SameFile(opened, named) {
		return ErrStorage
	}
	if !f.directory && (f.before.Size() != opened.Size() || f.before.Size() != named.Size() ||
		!f.before.ModTime().Equal(opened.ModTime()) || !f.before.ModTime().Equal(named.ModTime())) {
		return ErrStorage
	}
	return nil
}

// verify detects ordinary replacement or unlinking of the retained target and
// query directory. Ancestors and the OS remain trusted; pathname checks around
// a query do not form an atomic snapshot against an adversarial local host.
func (t *diskSpaceTarget) verify() error {
	if t == nil || t.closed || t.retained == nil {
		return errDiskSpace
	}
	if err := t.retained.verify(); err != nil {
		return err
	}
	if t.queryDirectory != nil {
		return t.queryDirectory.verify()
	}
	return nil
}

func diskSpaceReport(available, reserve uint64) (DiskSpaceReport, error) {
	if reserve == 0 {
		return DiskSpaceReport{}, ErrBounds
	}
	return DiskSpaceReport{
		Scope: diskSpaceScope, AvailableBytes: available, ReserveBytes: reserve,
		LowSpace: available <= reserve, SpaceReserved: false,
	}, nil
}

func (t *diskSpaceTarget) sample(reserve uint64) (DiskSpaceReport, error) {
	if reserve == 0 {
		return DiskSpaceReport{}, ErrBounds
	}
	if err := t.verify(); err != nil {
		return DiskSpaceReport{}, err
	}
	available, err := diskSpaceAvailable(t)
	if err != nil {
		return DiskSpaceReport{}, err
	}
	if err := t.verify(); err != nil {
		return DiskSpaceReport{}, err
	}
	return diskSpaceReport(available, reserve)
}

// close is idempotent only after a successful close. A failed close is never
// turned into success by a later cleanup call; callers must reject that sample.
func (t *diskSpaceTarget) close() error {
	if t == nil {
		return nil
	}
	if t.closed {
		return t.closeErr
	}
	t.closed = true
	var result error
	if t.queryDirectory != nil && t.queryDirectory.file != nil {
		if err := t.queryDirectory.file.Close(); err != nil {
			result = errDiskSpace
		}
	}
	if t.retained != nil && t.retained.file != nil {
		if err := t.retained.file.Close(); err != nil {
			result = errDiskSpace
		}
	}
	t.closeErr = result
	return t.closeErr
}
