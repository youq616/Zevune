//! Native filesystem tests for retained archive directory and entry bindings.
//! These do not replace journal hashes, signature replay, or trusted parents.
use super::*;

#[cfg(unix)]
#[test]
fn replaced_manifest_with_identical_bytes_is_not_the_retained_object() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, _) = fixture(&source, 1);
    pack(&source, &folder, pin);
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    let path = folder.join(MANIFEST);
    let raw = fs::read(&path).unwrap();
    fs::rename(&path, d.path("old-manifest")).unwrap();
    fs::write(&path, &raw).unwrap();
    assert!(matches!(archive.verify(), Err(PoolError::Corrupt)));
    let output = d.path("must-not-create");
    assert!(archive.restore_new(&output).is_err());
    assert!(!output.exists());
    assert_eq!(fs::read(&path).unwrap(), raw);
    drop(archive);
    // A deliberate new open can authenticate the same bytes under a new object.
    // Requiring this explicit reopen is not key revocation or rollback protection.
    SegmentedArchive::open(&folder, pin).unwrap();
}

#[cfg(unix)]
#[test]
fn renamed_and_replaced_directory_cannot_be_verified_or_receive_restore_output() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let moved = d.path("moved-original");
    let (pin, _) = fixture(&source, 1);
    pack(&source, &folder, pin);
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    fs::rename(&folder, &moved).unwrap();
    fs::create_dir(&folder).unwrap();
    for entry in [MANIFEST.to_string(), name(0)] {
        fs::copy(moved.join(&entry), folder.join(&entry)).unwrap();
    }
    // Names and ALL bytes match, but the object originally opened was moved.
    assert!(matches!(archive.verify(), Err(PoolError::Corrupt)));
    let output = moved.join("must-not-pollute-original.journal");
    assert!(archive.restore_new(&output).is_err());
    assert!(!output.exists());
    assert_eq!(fs::read_dir(&folder).unwrap().count(), 2);
    assert_eq!(fs::read_dir(&moved).unwrap().count(), 2);
    drop(archive);
    SegmentedArchive::open(&folder, pin).unwrap();
    SegmentedArchive::open(&moved, pin).unwrap();
}

#[cfg(unix)]
#[test]
fn replaced_segment_symlink_is_rejected_even_when_it_targets_original_bytes() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, _) = fixture(&source, 1);
    pack(&source, &folder, pin);
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    let part = folder.join(name(0));
    let moved = d.path("original-part");
    fs::rename(&part, &moved).unwrap();
    std::os::unix::fs::symlink(&moved, &part).unwrap();
    assert!(matches!(archive.verify(), Err(PoolError::Corrupt)));
    let output = d.path("not-created");
    assert!(archive.restore_new(&output).is_err());
    assert!(!output.exists());
    assert!(fs::symlink_metadata(&part)
        .unwrap()
        .file_type()
        .is_symlink());
}

#[test]
fn unchanged_archives_retain_multiple_readers_and_release_handles_on_drop() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, original) = fixture(&source, 2);
    pack(&source, &folder, pin);
    let mut first = SegmentedArchive::open(&folder, pin).unwrap();
    let mut second = SegmentedArchive::open(&folder, pin).unwrap();
    first.verify().unwrap();
    second.verify().unwrap();
    first.restore_new(&d.path("restore-one")).unwrap();
    second.restore_new(&d.path("restore-two")).unwrap();
    assert_eq!(fs::read(d.path("restore-one")).unwrap(), original);
    assert_eq!(fs::read(d.path("restore-two")).unwrap(), original);
    drop(first);
    second.verify().unwrap();
    drop(second);
    let moved = d.path("closed-archive");
    fs::rename(&folder, &moved).unwrap();
    SegmentedArchive::open(&moved, pin).unwrap();
}

#[test]
fn failed_open_releases_directory_guard_and_all_acquired_file_locks() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, _) = fixture(&source, 1);
    pack(&source, &folder, pin);
    let part = folder.join(name(0));
    let mut corrupt = fs::read(&part).unwrap();
    corrupt[0] ^= 1;
    fs::write(&part, &corrupt).unwrap();
    assert!(matches!(
        SegmentedArchive::open(&folder, pin),
        Err(PoolError::Corrupt)
    ));
    for entry in [MANIFEST.to_string(), name(0)] {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(folder.join(entry))
            .unwrap();
        file.try_lock().unwrap();
    }
    // On Windows this also proves failed construction did not retain its
    // no-DELETE-share directory/file handles after returning the error.
    let moved = d.path("after-failed-open");
    fs::rename(&folder, &moved).unwrap();
    assert_eq!(fs::read(moved.join(name(0))).unwrap(), corrupt);
}

#[test]
fn extra_file_after_open_is_rejected_without_removal_or_output() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, _) = fixture(&source, 1);
    pack(&source, &folder, pin);
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    let extra = folder.join("unlisted");
    fs::write(&extra, b"must remain").unwrap();
    assert!(matches!(archive.verify(), Err(PoolError::Corrupt)));
    let target = d.path("must-not-create");
    assert!(archive.restore_new(&target).is_err());
    assert!(!target.exists());
    assert_eq!(fs::read(extra).unwrap(), b"must remain");
}

#[cfg(windows)]
fn assert_delete_sharing_denied(error: std::io::Error) {
    // A native sharing/access denial, not an unrelated missing path failure.
    assert!(matches!(error.raw_os_error(), Some(5 | 32)), "{error}");
}

#[cfg(windows)]
#[test]
fn windows_open_archive_rejects_entry_and_directory_rename_until_drop() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, _) = fixture(&source, 1);
    pack(&source, &folder, pin);
    let mut archive = SegmentedArchive::open(&folder, pin).unwrap();
    for entry in [MANIFEST.to_string(), name(0)] {
        let from = folder.join(&entry);
        let to = d.path(&format!("renamed-{entry}"));
        assert_delete_sharing_denied(fs::rename(&from, &to).unwrap_err());
        assert!(from.exists());
        assert!(!to.exists());
        archive.verify().unwrap();
    }
    let moved = d.path("renamed-archive");
    assert_delete_sharing_denied(fs::rename(&folder, &moved).unwrap_err());
    assert!(folder.is_dir());
    assert!(!moved.exists());
    drop(archive);
    fs::rename(&folder, &moved).unwrap();
    SegmentedArchive::open(&moved, pin).unwrap();
}

#[cfg(windows)]
#[test]
fn windows_newly_packed_handles_preserve_names_without_reopening() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let (pin, _) = fixture(&source, 1);
    let mut source = RecoveryArchive::open(&source, pin).unwrap();
    let mut packed = source.pack_new(&folder).unwrap();
    let part = folder.join(name(0));
    let moved = d.path("moved-part");
    assert_delete_sharing_denied(fs::rename(&part, &moved).unwrap_err());
    assert!(part.exists());
    assert!(!moved.exists());
    packed.verify().unwrap();
    packed.restore_new(&d.path("restored")).unwrap();
    drop(packed);
    fs::rename(&part, &moved).unwrap();
    fs::rename(&moved, &part).unwrap();
    SegmentedArchive::open(&folder, pin).unwrap();
}
