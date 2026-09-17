//! Native namespace and lock behavior; these checks do not replace real replay.
use super::*;

#[test]
fn active_archive_locks_coordinate_real_processes() {
    const PATH_ENV: &str = "ZEVUNE_TEST_ACTIVE_ARCHIVE_LOCK_PATH";
    const PIN_ENV: &str = "ZEVUNE_TEST_ACTIVE_ARCHIVE_LOCK_PIN";
    const MODE_ENV: &str = "ZEVUNE_TEST_ACTIVE_ARCHIVE_LOCK_MODE";
    const TEST_NAME: &str = concat!(
        "pool::recovery::active::tests::namespace_tests::",
        "active_archive_locks_coordinate_real_processes"
    );
    if let Some(path) = std::env::var_os(PATH_ENV) {
        let encoded = std::env::var(PIN_ENV).unwrap();
        assert_eq!(encoded.len(), 256);
        let raw: Vec<u8> = (0..128)
            .map(|i| u8::from_str_radix(&encoded[2 * i..2 * i + 2], 16).unwrap())
            .collect();
        let pin = ActiveRecoveryCheckpoint::from_bytes(&raw).unwrap();
        match std::env::var(MODE_ENV).unwrap().as_str() {
            "archive-locked" => assert!(matches!(
                ActiveArchive::open(Path::new(&path), pin),
                Err(PoolError::Locked)
            )),
            "archive-open" => ActiveArchive::open(Path::new(&path), pin)
                .unwrap()
                .verify()
                .unwrap(),
            "writer-locked" => assert!(matches!(
                active_open(Path::new(&path)),
                Err(PoolError::Locked)
            )),
            "writer-open" => active_open(Path::new(&path))
                .unwrap()
                .check_checkpoint(pin.height(), pin.app_hash())
                .unwrap(),
            mode => panic!("unexpected lock probe mode: {mode}"),
        }
        return;
    }
    let d = Dir::new();
    let source = d.path("source");
    let (pin, original) = fixture(&source, 2);
    let encoded: String = pin.to_bytes().iter().map(|b| format!("{b:02x}")).collect();
    let probe = |mode: &str| {
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", TEST_NAME, "--nocapture"])
            .env(PATH_ENV, &source)
            .env(PIN_ENV, &encoded)
            .env(MODE_ENV, mode)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "lock subprocess failed: {} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(String::from_utf8_lossy(&output.stdout).contains("1 passed"));
    };
    let writer = active_open(&source).unwrap();
    probe("archive-locked");
    drop(writer);
    probe("archive-open");
    let mut first = ActiveArchive::open(&source, pin).unwrap();
    let mut second = ActiveArchive::open(&source, pin).unwrap();
    first.verify().unwrap();
    second.verify().unwrap();
    probe("archive-open");
    probe("writer-locked");
    drop(first);
    second.verify().unwrap();
    probe("writer-locked");
    let target = d.path("copy");
    assert_eq!(second.copy_new(&target).unwrap(), pin);
    assert_eq!(directory_bytes(&target), original);
    second.verify().unwrap();
    probe("writer-locked");
    drop(second);
    probe("writer-open");
    assert_eq!(directory_bytes(&source), original);
}

#[cfg(any(unix, windows))]
#[test]
fn readonly_source_files_copy_into_a_normally_writable_active_directory() {
    struct RestorePermissions(Vec<(std::path::PathBuf, fs::Permissions)>);
    impl Drop for RestorePermissions {
        fn drop(&mut self) {
            for (path, permissions) in &self.0 {
                let _ = fs::set_permissions(path, permissions.clone());
            }
        }
    }
    let d = Dir::new();
    let source = d.path("source");
    let (pin, original) = fixture(&source, 2);
    let mut restore = RestorePermissions(Vec::new());
    for name in original.keys() {
        let path = source.join(name);
        let mut permissions = fs::metadata(&path).unwrap().permissions();
        restore.0.push((path.clone(), permissions.clone()));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            permissions.set_mode(permissions.mode() & !0o222);
        }
        #[cfg(windows)]
        permissions.set_readonly(true);
        fs::set_permissions(&path, permissions).unwrap();
        #[cfg(windows)]
        {
            // Prove denied write access before any archive lock can mask it.
            let error = OpenOptions::new()
                .read(true)
                .write(true)
                .open(&path)
                .unwrap_err();
            assert_eq!(error.raw_os_error(), Some(5));
        }
    }
    let mut archive = ActiveArchive::open(&source, pin).unwrap();
    archive.verify().unwrap();
    let target = d.path("copy");
    assert_eq!(archive.copy_new(&target).unwrap(), pin);
    assert_eq!(directory_bytes(&target), original);
    let mut restored = active_open(&target).unwrap();
    restored
        .check_checkpoint(pin.height(), pin.app_hash())
        .unwrap();
    let next = restored.prepare(pin.height() + 1, [31; 32], &[]).unwrap();
    assert_eq!(restored.commit(next).unwrap().height, pin.height() + 1);
    drop(restored);
    archive.verify().unwrap();
    assert_eq!(directory_bytes(&source), original);
    for name in original.keys() {
        assert!(fs::metadata(source.join(name))
            .unwrap()
            .permissions()
            .readonly());
    }
    drop(archive);
    drop(restore);
}

#[cfg(unix)]
#[test]
fn persistent_entry_replacements_symlinks_and_hardlinks_are_not_certified() {
    use std::os::unix::fs::{symlink, MetadataExt};
    let d = Dir::new();
    for entry in ["genesis", "00000000.journal"] {
        for kind in ["replacement", "symlink", "hardlink"] {
            let source = d.path(&format!("{kind}-{entry}"));
            let (pin, original) = fixture(&source, 1);
            let mut archive = ActiveArchive::open(&source, pin).unwrap();
            let part = source.join(entry);
            let moved = d.path(&format!("old-{kind}-{entry}"));
            fs::rename(&part, &moved).unwrap();
            match kind {
                "replacement" => fs::write(&part, &original[entry]).unwrap(),
                "symlink" => symlink(&moved, &part).unwrap(),
                _ => fs::hard_link(&moved, &part).unwrap(),
            }
            assert!(matches!(archive.verify(), Err(PoolError::Corrupt)));
            let target = d.path(&format!("not-created-{kind}-{entry}"));
            assert!(archive.copy_new(&target).is_err());
            assert!(!target.exists());
            if kind == "symlink" {
                assert!(fs::symlink_metadata(&part)
                    .unwrap()
                    .file_type()
                    .is_symlink());
                assert_eq!(fs::read_dir(&source).unwrap().count(), original.len());
                for (name, raw) in &original {
                    assert_eq!(&fs::read(source.join(name)).unwrap(), raw);
                }
            } else {
                assert_eq!(directory_bytes(&source), original);
            }
            drop(archive);
            if kind == "replacement" {
                // A deliberate reopen may authenticate the same bytes anew.
                ActiveArchive::open(&source, pin).unwrap().verify().unwrap();
            } else {
                assert!(ActiveArchive::open(&source, pin).is_err());
                if kind == "hardlink" {
                    assert_eq!(fs::symlink_metadata(&part).unwrap().nlink(), 2);
                }
            }
        }
    }
}

#[cfg(unix)]
#[test]
fn parent_aliases_and_replaced_directories_cannot_redirect_a_retained_archive() {
    use std::os::unix::fs::symlink;
    let d = Dir::new();
    let source = d.path("source");
    let alias = d.path("parent-alias");
    let moved = d.path("moved");
    let (pin, original) = fixture(&source, 1);
    let mut archive = ActiveArchive::open(&source, pin).unwrap();
    symlink(&source, &alias).unwrap();
    assert!(matches!(
        ActiveArchive::open(&alias, pin),
        Err(PoolError::Bounds)
    ));
    for parent in [&source, &alias] {
        let target = parent.join("must-not-create");
        assert!(matches!(archive.copy_new(&target), Err(PoolError::Bounds)));
        assert!(!target.exists());
    }
    archive.verify().unwrap();
    fs::rename(&source, &moved).unwrap();
    fs::create_dir(&source).unwrap();
    for (name, raw) in &original {
        fs::write(source.join(name), raw).unwrap();
    }
    assert!(matches!(archive.verify(), Err(PoolError::Corrupt)));
    let target = moved.join("must-not-pollute-original");
    assert!(archive.copy_new(&target).is_err());
    assert!(!target.exists());
    assert_eq!(directory_bytes(&source), original);
    assert_eq!(directory_bytes(&moved), original);
    drop(archive);
    ActiveArchive::open(&source, pin).unwrap().verify().unwrap();
    ActiveArchive::open(&moved, pin).unwrap().verify().unwrap();
}

#[test]
fn failed_open_releases_all_acquired_file_and_directory_handles() {
    let d = Dir::new();
    let source = d.path("source");
    let (pin, mut changed) = fixture(&source, 1);
    let part = changed.get_mut("00000000.journal").unwrap();
    *part.last_mut().unwrap() ^= 1;
    fs::write(source.join("00000000.journal"), part).unwrap();
    assert!(matches!(
        ActiveArchive::open(&source, pin),
        Err(PoolError::Corrupt)
    ));
    for name in changed.keys() {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(source.join(name))
            .unwrap();
        file.try_lock().unwrap();
        drop(file);
        let moved = d.path(&format!("released-{name}"));
        fs::rename(source.join(name), &moved).unwrap();
        fs::rename(&moved, source.join(name)).unwrap();
    }
    let moved = d.path("released-directory");
    fs::rename(&source, &moved).unwrap();
    assert_eq!(directory_bytes(&moved), changed);
}

#[test]
fn unknown_entry_after_open_prevents_verification_and_creates_no_target() {
    let d = Dir::new();
    let source = d.path("source");
    let (pin, mut expected) = fixture(&source, 1);
    let mut archive = ActiveArchive::open(&source, pin).unwrap();
    let extra = b"retain for inspection".to_vec();
    fs::write(source.join("unexpected"), &extra).unwrap();
    expected.insert("unexpected".to_string(), extra);
    assert!(matches!(archive.verify(), Err(PoolError::Corrupt)));
    let target = d.path("must-not-create");
    assert!(archive.copy_new(&target).is_err());
    assert!(!target.exists());
    assert_eq!(directory_bytes(&source), expected);
}

#[cfg(windows)]
#[test]
fn windows_files_and_directory_cannot_be_renamed_or_deleted_until_last_reader_drops() {
    let d = Dir::new();
    let source = d.path("source");
    let moved = d.path("moved-source");
    let (pin, original) = fixture(&source, 1);
    let first = ActiveArchive::open(&source, pin).unwrap();
    let mut second = ActiveArchive::open(&source, pin).unwrap();
    let assert_denied = |error: std::io::Error| {
        assert!(matches!(error.raw_os_error(), Some(5 | 32)), "{error}");
    };
    let probe = || {
        for name in original.keys() {
            let from = source.join(name);
            let to = d.path(&format!("moved-{name}"));
            assert!(!fs::metadata(&from).unwrap().permissions().readonly());
            assert_denied(fs::rename(&from, &to).unwrap_err());
            assert_denied(fs::remove_file(&from).unwrap_err());
            assert!(from.is_file());
            assert!(!to.exists());
        }
        assert_denied(fs::rename(&source, &moved).unwrap_err());
        assert!(source.is_dir());
        assert!(!moved.exists());
    };
    probe();
    drop(first);
    probe();
    second.verify().unwrap();
    assert_eq!(directory_bytes(&source), original);
    drop(second);
    for name in original.keys() {
        let to = d.path(&format!("moved-{name}"));
        fs::rename(source.join(name), &to).unwrap();
        fs::rename(&to, source.join(name)).unwrap();
    }
    fs::rename(&source, &moved).unwrap();
    ActiveArchive::open(&moved, pin).unwrap().verify().unwrap();
    assert_eq!(directory_bytes(&moved), original);
    // Positive delete controls use normal files after every archive is dropped.
    for name in original.keys() {
        fs::remove_file(moved.join(name)).unwrap();
    }
    fs::remove_dir(&moved).unwrap();
}
