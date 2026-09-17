//! Filesystem/framing tests only. Synthetic bodies here are never presented to
//! State/PoolStore or called authorized blocks; active_flow_tests uses real ones.
use super::*;
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-active-io-{suffix}"));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn header() -> Vec<u8> {
    // A bounded test header, not a public genesis manifest or authenticated state.
    let mut raw = vec![0; 76];
    raw[..8].copy_from_slice(b"ZVOPOL03");
    raw
}
fn frame(length: u64) -> Vec<u8> {
    assert!((MIN_FRAME_BYTES..=MAX_FRAME_BYTES).contains(&length));
    let body_length = length as usize - 36;
    let mut raw = Vec::with_capacity(length as usize);
    raw.extend_from_slice(&(body_length as u32).to_be_bytes());
    raw.resize(4 + body_length, 0);
    raw[4..12].copy_from_slice(b"ZVOBLK01");
    let digest = Sha256::digest(&raw[4..]);
    raw.extend_from_slice(&digest);
    raw
}
fn create(path: &Path) -> (File, ActiveJournal) {
    ActiveJournal::create(path, &header()).unwrap()
}
fn physical_frames(journal: &ActiveJournal, genesis: &File) -> Result<Vec<u64>, PoolError> {
    // This scanner validates ONLY I/O layout/checksums, not Record decoding,
    // state transitions or authorization. The production caller uses Replay.
    let mut reader = journal.reader(genesis)?;
    let mut actual_header = vec![0; header().len()];
    reader
        .read_exact(&mut actual_header)
        .map_err(|_| PoolError::Corrupt)?;
    if actual_header != header() {
        return Err(PoolError::Genesis);
    }
    let mut position = actual_header.len() as u64;
    let mut lengths = Vec::new();
    while position < journal.length() {
        let start = position;
        let mut prefix = [0; 4];
        reader
            .read_exact(&mut prefix)
            .map_err(|_| PoolError::Corrupt)?;
        let n = u32::from_be_bytes(prefix) as usize;
        frame_size(n as u64 + 36)?;
        let mut raw = vec![0; n];
        reader
            .read_exact(&mut raw)
            .map_err(|_| PoolError::Corrupt)?;
        let mut digest = [0; 32];
        reader
            .read_exact(&mut digest)
            .map_err(|_| PoolError::Corrupt)?;
        if digest != <[u8; 32]>::from(Sha256::digest(&raw)) {
            return Err(PoolError::Corrupt);
        }
        position += n as u64 + 36;
        journal.validate_frame(start, position)?;
        lengths.push(position - start);
    }
    if position != journal.length() || reader.read(&mut [0]).map_err(|_| PoolError::Corrupt)? != 0 {
        return Err(PoolError::Corrupt);
    }
    journal.check(genesis)?;
    Ok(lengths)
}

#[test]
fn create_is_exclusive_bounded_and_preserves_existing_bytes() {
    let d = Dir::new();
    let path = d.path("ledger");
    assert!(ActiveJournal::create(Path::new("relative"), &header()).is_err());
    assert!(ActiveJournal::create(&path, &[]).is_err());
    assert!(!path.exists());
    let (genesis, journal) = create(&path);
    assert_eq!(journal.capacity(), (76, 0, 0));
    assert_eq!(
        physical_frames(&journal, &genesis).unwrap(),
        Vec::<u64>::new()
    );
    assert!(matches!(
        ActiveJournal::open(&path, &header()),
        Err(PoolError::Locked)
    ));
    assert!(ActiveJournal::create(&path, &header()).is_err());
    verify_header(&genesis, &header()).unwrap();
    assert_eq!(fs::read_dir(&path).unwrap().count(), 1);
    drop(journal);
    drop(genesis);
    let mut incorrect = header();
    incorrect[20] ^= 1;
    assert!(matches!(
        ActiveJournal::open(&path, &incorrect),
        Err(PoolError::Genesis)
    ));
    let (genesis, journal) = ActiveJournal::open(&path, &header()).unwrap();
    journal.check(&genesis).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(path.join(GENESIS))
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }
}

#[test]
fn full_segment_and_next_frame_rotate_canonically_without_crossing() {
    let d = Dir::new();
    let path = d.path("ledger");
    let lengths = [
        MAX_FRAME_BYTES,
        MAX_FRAME_BYTES,
        SEGMENT_BYTES - 2 * MAX_FRAME_BYTES,
        MIN_FRAME_BYTES,
    ];
    let (genesis, mut journal) = create(&path);
    let mut expected = header();
    for length in lengths {
        let raw = frame(length);
        let before = journal.capacity();
        journal.check_frame(length).unwrap();
        assert_eq!(journal.capacity(), before);
        journal.append(&genesis, &raw).unwrap();
        expected.extend_from_slice(&raw);
    }
    assert_eq!(
        fs::metadata(path.join(name(0))).unwrap().len(),
        SEGMENT_BYTES
    );
    assert_eq!(
        fs::metadata(path.join(name(1))).unwrap().len(),
        MIN_FRAME_BYTES
    );
    assert_eq!(
        journal.capacity(),
        (
            76 + SEGMENT_BYTES + MIN_FRAME_BYTES,
            2,
            MIN_FRAME_BYTES as u32
        )
    );
    assert_eq!(physical_frames(&journal, &genesis).unwrap(), lengths);
    let mut actual = Vec::new();
    journal
        .reader(&genesis)
        .unwrap()
        .read_to_end(&mut actual)
        .unwrap();
    assert_eq!(actual, expected);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(path.join(name(0)))
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }
    drop(journal);
    drop(genesis);
    let (genesis, mut journal) = ActiveJournal::open(&path, &header()).unwrap();
    assert_eq!(physical_frames(&journal, &genesis).unwrap(), lengths);
    journal.append(&genesis, &frame(MIN_FRAME_BYTES)).unwrap();
    assert_eq!(journal.capacity().2, 2 * MIN_FRAME_BYTES as u32);
    assert_eq!(physical_frames(&journal, &genesis).unwrap().len(), 5);
}

#[test]
fn budgets_include_framing_total_tail_and_the_independent_segment_cap() {
    assert_eq!(frame_budget(76, 0, 0, MIN_FRAME_BYTES), Ok(true));
    assert_eq!(
        frame_budget(
            TOTAL_BYTES - MIN_FRAME_BYTES,
            1024,
            SEGMENT_BYTES - MIN_FRAME_BYTES,
            MIN_FRAME_BYTES
        ),
        Ok(false)
    );
    assert_eq!(
        frame_budget(
            TOTAL_BYTES - MIN_FRAME_BYTES + 1,
            1024,
            SEGMENT_BYTES - MIN_FRAME_BYTES,
            MIN_FRAME_BYTES
        ),
        Err(PoolError::Bounds)
    );
    assert_eq!(
        frame_budget(76, 0, 0, MIN_FRAME_BYTES - 1),
        Err(PoolError::Bounds)
    );
    assert_eq!(
        frame_budget(76, 0, 0, MAX_FRAME_BYTES + 1),
        Err(PoolError::Bounds)
    );
    assert_eq!(frame_budget(76, 0, 0, u64::MAX), Err(PoolError::Bounds));
    assert_eq!(
        frame_budget(u64::MAX, 1, MIN_FRAME_BYTES, MIN_FRAME_BYTES),
        Err(PoolError::Bounds)
    );
    assert_eq!(
        frame_budget(
            TOTAL_BYTES / 2,
            MAX_SEGMENTS,
            SEGMENT_BYTES - MIN_FRAME_BYTES,
            MIN_FRAME_BYTES
        ),
        Ok(false)
    );
    assert_eq!(
        frame_budget(
            TOTAL_BYTES / 2,
            MAX_SEGMENTS,
            SEGMENT_BYTES - MIN_FRAME_BYTES + 1,
            MIN_FRAME_BYTES
        ),
        Err(PoolError::Bounds)
    );
    assert_eq!(
        frame_budget(
            TOTAL_BYTES / 2,
            MAX_SEGMENTS - 1,
            SEGMENT_BYTES,
            MIN_FRAME_BYTES
        ),
        Ok(true)
    );
    for (count, tail) in [
        (0, 1),
        (1, 0),
        (1, SEGMENT_BYTES + 1),
        (MAX_SEGMENTS + 1, MIN_FRAME_BYTES),
    ] {
        assert_eq!(
            frame_budget(76, count, tail, MIN_FRAME_BYTES),
            Err(PoolError::Bounds)
        );
    }
}

#[test]
fn malformed_frame_and_capacity_rejection_create_no_files_or_bytes() {
    let d = Dir::new();
    let path = d.path("ledger");
    let (genesis, mut journal) = create(&path);
    let before = journal.capacity();
    for raw in [vec![], vec![0; 149], vec![0; MAX_FRAME_BYTES as usize + 1]] {
        assert!(journal.append(&genesis, &raw).is_err());
    }
    let mut wrong_size = frame(MIN_FRAME_BYTES);
    wrong_size[3] ^= 1;
    assert!(journal.append(&genesis, &wrong_size).is_err());
    assert_eq!(journal.capacity(), before);
    assert_eq!(fs::read_dir(&path).unwrap().count(), 1);
    verify_header(&genesis, &header()).unwrap();
    journal.check(&genesis).unwrap();
}

#[test]
fn early_rotation_and_split_frames_are_rejected_even_with_valid_checksums() {
    let d = Dir::new();
    for split in [false, true] {
        let path = d.path(if split { "split" } else { "early" });
        let (genesis, journal) = create(&path);
        drop(journal);
        drop(genesis);
        let raw = frame(400);
        if split {
            fs::write(path.join(name(0)), &raw[..200]).unwrap();
            fs::write(path.join(name(1)), &raw[200..]).unwrap();
        } else {
            fs::write(path.join(name(0)), &raw).unwrap();
            fs::write(path.join(name(1)), frame(MIN_FRAME_BYTES)).unwrap();
        }
        let (genesis, journal) = ActiveJournal::open(&path, &header()).unwrap();
        assert!(physical_frames(&journal, &genesis).is_err());
    }
}

#[test]
fn unknown_missing_empty_and_truncated_segments_fail_closed_without_repair() {
    let d = Dir::new();
    for (label, filename, raw) in [
        ("unknown", "unlisted".to_string(), frame(400)),
        ("gap", name(1), frame(400)),
        ("empty", name(0), vec![]),
        ("short", name(0), vec![0; 149]),
        ("alternate", "0.journal".to_string(), frame(400)),
        ("out-of-range", name(MAX_SEGMENTS), frame(400)),
    ] {
        let path = d.path(label);
        let (genesis, journal) = create(&path);
        drop(journal);
        drop(genesis);
        fs::write(path.join(&filename), &raw).unwrap();
        assert!(ActiveJournal::open(&path, &header()).is_err(), "{label}");
        assert_eq!(fs::read(path.join(filename)).unwrap(), raw);
    }
    for (label, raw) in [
        ("truncated", frame(400)[..399].to_vec()),
        ("trailing", {
            let mut raw = frame(400);
            raw.push(0);
            raw
        }),
    ] {
        let path = d.path(label);
        let (genesis, journal) = create(&path);
        drop(journal);
        drop(genesis);
        fs::write(path.join(name(0)), &raw).unwrap();
        let (genesis, journal) = ActiveJournal::open(&path, &header()).unwrap();
        assert!(physical_frames(&journal, &genesis).is_err());
        assert_eq!(fs::read(path.join(name(0))).unwrap(), raw);
    }
}

#[test]
fn readers_retain_the_exclusive_root_lock_and_have_independent_positions() {
    let d = Dir::new();
    let path = d.path("ledger");
    let (genesis, mut journal) = create(&path);
    let raw = frame(400);
    journal.append(&genesis, &raw).unwrap();
    let mut first = journal.reader(&genesis).unwrap();
    let mut second = journal.reader(&genesis).unwrap();
    let mut prefix = [0; 10];
    first.read_exact(&mut prefix).unwrap();
    assert_eq!(&prefix, &header()[..10]);
    let mut entire = Vec::new();
    second.read_to_end(&mut entire).unwrap();
    let mut expected = header();
    expected.extend_from_slice(&raw);
    assert_eq!(entire, expected);
    let mut remaining = Vec::new();
    first.read_to_end(&mut remaining).unwrap();
    assert_eq!(remaining, expected[10..]);
    drop(journal);
    drop(genesis);
    assert!(matches!(
        ActiveJournal::open(&path, &header()),
        Err(PoolError::Locked)
    ));
    drop(first);
    assert!(matches!(
        ActiveJournal::open(&path, &header()),
        Err(PoolError::Locked)
    ));
    drop(second);
    ActiveJournal::open(&path, &header()).unwrap();
}

#[test]
fn another_process_cannot_open_held_genesis_lock() {
    const PATH_ENV: &str = "ZEVUNE_TEST_ACTIVE_LOCK_PATH";
    const HELD_ENV: &str = "ZEVUNE_TEST_ACTIVE_LOCK_HELD";
    if let Some(path) = std::env::var_os(PATH_ENV) {
        let opened = ActiveJournal::open(Path::new(&path), &header());
        if std::env::var_os(HELD_ENV).is_some() {
            assert!(matches!(opened, Err(PoolError::Locked)));
        } else {
            let (genesis, journal) = opened.unwrap();
            journal.check(&genesis).unwrap();
        }
        return;
    }
    let d = Dir::new();
    let path = d.path("ledger");
    let (genesis, journal) = create(&path);
    let probe = |held: bool| {
        let mut command = std::process::Command::new(std::env::current_exe().unwrap());
        command.args([
            "--exact",
            "pool::active::tests::another_process_cannot_open_held_genesis_lock",
            "--nocapture",
        ]);
        command.env(PATH_ENV, &path);
        if held {
            command.env(HELD_ENV, "1");
        } else {
            command.env_remove(HELD_ENV);
        }
        let output = command.output().unwrap();
        assert!(
            output.status.success(),
            "lock subprocess failed: {} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(String::from_utf8_lossy(&output.stdout).contains("1 passed"));
    };
    probe(true);
    journal.check(&genesis).unwrap();
    drop(journal);
    drop(genesis);
    probe(false);
}

#[test]
fn captured_reader_requires_each_real_eof_and_poisoned_readers_cannot_resume() {
    let d = Dir::new();
    for truncate in [false, true] {
        let path = d.path(if truncate { "shorter" } else { "longer" });
        let (genesis, mut journal) = create(&path);
        journal.append(&genesis, &frame(400)).unwrap();
        let mut reader = journal.reader(&genesis).unwrap();
        let external = OpenOptions::new()
            .write(true)
            .open(path.join(name(0)))
            .unwrap();
        external.set_len(if truncate { 399 } else { 401 }).unwrap();
        assert!(reader.read_to_end(&mut Vec::new()).is_err());
        assert!(reader.read(&mut [0]).is_err());
        assert!(journal.check(&genesis).is_err());
    }
}

#[test]
fn unknown_entry_after_open_is_not_ignored_or_removed() {
    let d = Dir::new();
    let path = d.path("ledger");
    let (genesis, mut journal) = create(&path);
    let mut reader = journal.reader(&genesis).unwrap();
    fs::write(path.join("unexpected"), b"retain for inspection").unwrap();
    assert!(journal.check(&genesis).is_err());
    assert!(journal.reader(&genesis).is_err());
    assert!(reader.read_to_end(&mut Vec::new()).is_err());
    // With no tail, this append requires full inventory validation before create.
    assert!(journal.append(&genesis, &frame(400)).is_err());
    assert!(!path.join(name(0)).exists());
    assert_eq!(
        fs::read(path.join("unexpected")).unwrap(),
        b"retain for inspection"
    );
    assert_eq!(journal.capacity(), (76, 0, 0));
}

#[test]
fn interruption_leaves_metadata_unchanged_and_preserves_the_recoverable_prefix() {
    let d = Dir::new();
    for fault in 1..=4 {
        for existing in [false, true] {
            if fault == 1 && existing {
                continue; // This injection is specifically after create_new.
            }
            let path = d.path(&format!("fault-{fault}-{existing}"));
            let (genesis, mut journal) = create(&path);
            let first = frame(400);
            if existing {
                journal.append(&genesis, &first).unwrap();
            }
            let before = journal.capacity();
            journal.fault = fault;
            assert_eq!(
                journal.append(&genesis, &frame(600)),
                Err(PoolError::Storage)
            );
            assert_eq!(journal.capacity(), before);
            let raw = fs::read(path.join(name(0))).unwrap();
            if existing {
                assert_eq!(&raw[..first.len()], &first);
            }
            assert_eq!(
                raw.len(),
                if existing { 400 } else { 0 }
                    + match fault {
                        1 => 0,
                        2 => 300,
                        _ => 600,
                    }
            );
            assert!(journal.check(&genesis).is_err());
            drop(journal);
            drop(genesis);
            let reopened = ActiveJournal::open(&path, &header());
            if fault == 1 {
                assert!(reopened.is_err());
            } else {
                let (genesis, journal) = reopened.unwrap();
                let scanned = physical_frames(&journal, &genesis);
                if fault == 2 {
                    assert!(scanned.is_err());
                } else {
                    // A failed acknowledgement can expose a complete record.
                    // Fault 3 makes NO persistence/power-loss claim.
                    assert_eq!(
                        scanned.unwrap(),
                        if existing { vec![400, 600] } else { vec![600] }
                    );
                }
            }
        }
    }
}

#[test]
fn failed_next_segment_publication_keeps_all_sealed_prefix_bytes_and_no_repair() {
    let d = Dir::new();
    for fault in 1..=4 {
        let path = d.path(&format!("rotate-fault-{fault}"));
        let (genesis, mut journal) = create(&path);
        for length in [
            MAX_FRAME_BYTES,
            MAX_FRAME_BYTES,
            SEGMENT_BYTES - 2 * MAX_FRAME_BYTES,
        ] {
            journal.append(&genesis, &frame(length)).unwrap();
        }
        let before = journal.capacity();
        assert_eq!(before, (76 + SEGMENT_BYTES, 1, SEGMENT_BYTES as u32));
        let prefix = fs::read(path.join(name(0))).unwrap();
        journal.fault = fault;
        assert_eq!(
            journal.append(&genesis, &frame(MIN_FRAME_BYTES)),
            Err(PoolError::Storage)
        );
        assert_eq!(journal.capacity(), before);
        assert_eq!(fs::read(path.join(name(0))).unwrap(), prefix);
        let next = fs::read(path.join(name(1))).unwrap();
        assert_eq!(
            next.len(),
            match fault {
                1 => 0,
                2 => MIN_FRAME_BYTES as usize / 2,
                _ => MIN_FRAME_BYTES as usize,
            }
        );
        assert!(journal.check(&genesis).is_err());
        drop(journal);
        drop(genesis);
        let reopened = ActiveJournal::open(&path, &header());
        if fault <= 2 {
            assert!(reopened.is_err());
        } else {
            let (genesis, journal) = reopened.unwrap();
            assert_eq!(physical_frames(&journal, &genesis).unwrap().len(), 4);
        }
        // Failed opens neither remove the partial tail nor truncate committed
        // segments. A full write may replay even though commit returned error.
        assert_eq!(fs::read(path.join(name(0))).unwrap(), prefix);
        assert_eq!(fs::read(path.join(name(1))).unwrap(), next);
        assert_eq!(fs::read_dir(&path).unwrap().count(), 3);
    }
}

#[cfg(unix)]
#[test]
fn symlinks_hard_links_and_replaced_names_are_rejected() {
    use std::os::unix::fs::symlink;
    let d = Dir::new();
    for target in [GENESIS.to_string(), name(0)] {
        let path = d.path(&format!("replace-{target}"));
        let (genesis, mut journal) = create(&path);
        journal.append(&genesis, &frame(400)).unwrap();
        let part = path.join(&target);
        let moved = d.path(&format!("original-{target}"));
        fs::rename(&part, &moved).unwrap();
        fs::copy(&moved, &part).unwrap();
        assert!(journal.check(&genesis).is_err());
        assert!(journal.append(&genesis, &frame(400)).is_err());
        fs::remove_file(&part).unwrap();
        symlink(&moved, &part).unwrap();
        assert!(journal.check(&genesis).is_err());
        drop(journal);
        drop(genesis);
        assert!(ActiveJournal::open(&path, &header()).is_err());
        fs::remove_file(&part).unwrap();
        fs::hard_link(&moved, &part).unwrap();
        assert!(ActiveJournal::open(&path, &header()).is_err());
        assert_eq!(fs::read(&part).unwrap(), fs::read(&moved).unwrap());
    }
    let path = d.path("directory");
    let moved = d.path("moved-directory");
    let (genesis, journal) = create(&path);
    fs::rename(&path, &moved).unwrap();
    fs::create_dir(&path).unwrap();
    fs::copy(moved.join(GENESIS), path.join(GENESIS)).unwrap();
    assert!(journal.check(&genesis).is_err());
    drop(journal);
    drop(genesis);
    let linked = d.path("directory-link");
    symlink(&moved, &linked).unwrap();
    assert!(ActiveJournal::open(&linked, &header()).is_err());
}

#[cfg(unix)]
#[test]
fn adding_a_hard_link_after_open_poison_checks_without_modifying_ledger_bytes() {
    let d = Dir::new();
    let path = d.path("ledger");
    let (genesis, mut journal) = create(&path);
    journal.append(&genesis, &frame(400)).unwrap();
    fs::hard_link(path.join(name(0)), d.path("alias")).unwrap();
    assert!(journal.check(&genesis).is_err());
    assert!(journal.append(&genesis, &frame(400)).is_err());
    assert_eq!(fs::read(path.join(name(0))).unwrap(), frame(400));
}

#[cfg(windows)]
#[test]
fn windows_retained_handles_block_file_and_directory_rename_until_drop() {
    let d = Dir::new();
    let path = d.path("ledger");
    let (genesis, mut journal) = create(&path);
    journal.append(&genesis, &frame(400)).unwrap();
    for entry in [GENESIS.to_string(), name(0)] {
        let error = fs::rename(path.join(&entry), d.path(&format!("moved-{entry}"))).unwrap_err();
        assert!(matches!(error.raw_os_error(), Some(5 | 32)), "{error}");
    }
    let moved = d.path("moved-ledger");
    let error = fs::rename(&path, &moved).unwrap_err();
    assert!(matches!(error.raw_os_error(), Some(5 | 32)), "{error}");
    journal.check(&genesis).unwrap();
    drop(journal);
    drop(genesis);
    fs::rename(&path, &moved).unwrap();
    ActiveJournal::open(&moved, &header()).unwrap();
}
