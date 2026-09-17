//! Active archive contracts through real ordinary empty-block commits. These
//! fixtures do not inject journal records or stand in for payment authorization;
//! the funded flow tests cover real payments and production-size rotation.
use super::*;
use crate::pool::{PoolStore, StorageProfile, Summary, MAX_COMMITMENTS};
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::{Read, Seek, Write};
use std::path::{Path, PathBuf};

const DOMAIN: [u8; 32] = [7; 32];
const SEGMENT: &str = "00000000.journal";
const SECOND_SEGMENT: &str = "00000001.journal";
const SEGMENT_LIMIT: u64 = 1_048_576;
const ACTIVE_LIMIT: u64 = 1_073_741_824;
type DirectoryBytes = BTreeMap<String, Vec<u8>>;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let suffix: String = nonce.iter().map(|byte| format!("{byte:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-active-archive-{suffix}"));
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

fn active_create(path: &Path) -> PoolStore {
    PoolStore::create_with_profile(path, &[], Some(DOMAIN), StorageProfile::ActiveSegmentsV1)
        .unwrap()
}

fn active_open(path: &Path) -> Result<PoolStore, PoolError> {
    PoolStore::open_with_profile(path, &[], Some(DOMAIN), StorageProfile::ActiveSegmentsV1)
}

fn commit_empty(pool: &mut PoolStore, height: u64, variant: u8) -> Summary {
    let mut id = [variant; 32];
    id[..8].copy_from_slice(&height.to_be_bytes());
    let prepared = pool.prepare(height, id, &[]).unwrap();
    let expected = prepared.result().clone();
    let actual = pool.commit(prepared).unwrap();
    assert_eq!(actual, expected);
    actual
}

fn fixture(path: &Path, blocks: u64) -> (ActiveRecoveryCheckpoint, DirectoryBytes) {
    let mut pool = active_create(path);
    for height in 1..=blocks {
        commit_empty(&mut pool, height, 0);
    }
    let pin = pool.active_recovery_checkpoint().unwrap();
    drop(pool);
    (pin, directory_bytes(path))
}

// On Windows an independent read of genesis while a writer holds its exclusive
// lock would test OS locking instead of content. All callers release that writer
// first; read-only archives use shared locks and permit these inspection reads.
fn directory_bytes(path: &Path) -> DirectoryBytes {
    fs::read_dir(path)
        .unwrap()
        .map(|entry| {
            let entry = entry.unwrap();
            assert!(entry.file_type().unwrap().is_file());
            (
                entry.file_name().into_string().unwrap(),
                fs::read(entry.path()).unwrap(),
            )
        })
        .collect()
}

fn write_directory(path: &Path, entries: &DirectoryBytes) {
    fs::create_dir(path).unwrap();
    for (name, raw) in entries {
        fs::write(path.join(name), raw).unwrap();
    }
}

fn owned_bytes(pool: &PoolStore) -> Vec<u8> {
    let mut reader = pool.active.as_ref().unwrap().reader(&pool.file).unwrap();
    let mut raw = Vec::new();
    reader.read_to_end(&mut raw).unwrap();
    raw
}

// Deliberately repin corrupt fixtures so tests can reach the actual header,
// framing or state-replay rejection instead of merely failing the old hash.
// This does NOT authenticate an externally supplied checkpoint. The hard-coded
// independent vector below separately checks the production layout encoding.
fn repin(
    mut pin: ActiveRecoveryCheckpoint,
    entries: &DirectoryBytes,
) -> ActiveRecoveryCheckpoint {
    let header = &entries["genesis"];
    pin.genesis = Sha256::digest(header).into();
    pin.header_length = u32::try_from(header.len()).unwrap();
    pin.segment_count = u32::try_from(entries.len() - 1).unwrap();
    pin.length = entries.values().map(|raw| raw.len() as u64).sum();
    let mut hash = Sha256::new();
    hash.update(b"ZVARLY01");
    hash.update(pin.header_length.to_be_bytes());
    hash.update(header);
    hash.update(pin.segment_count.to_be_bytes());
    for index in 0..pin.segment_count {
        let raw = &entries[&format!("{index:08}.journal")];
        hash.update(index.to_be_bytes());
        hash.update(u32::try_from(raw.len()).unwrap().to_be_bytes());
        hash.update(raw);
    }
    pin.layout_hash = hash.finalize().into();
    pin
}

fn assert_layout_pin_matches(path: &Path, pin: ActiveRecoveryCheckpoint) {
    // Prove the new pin clears the actual production byte-digest check before
    // claiming a later Corrupt result exercises framing or replay validation.
    let (file, journal) = ActiveJournal::open_readonly(path, pin.header_length).unwrap();
    assert_eq!(journal.layout_hash(&file).unwrap(), pin.layout_hash);
}

fn structural_pin(
    height: u64,
    header_length: u32,
    segment_count: u32,
    length: u64,
) -> ActiveRecoveryCheckpoint {
    ActiveRecoveryCheckpoint {
        genesis: [1; 32],
        height,
        app_hash: [2; 32],
        length,
        header_length,
        segment_count,
        layout_hash: [3; 32],
    }
}

#[test]
fn checkpoint_codec_has_exact_length_distinct_magic_and_bounded_arithmetic() {
    let maximum_header = u32::try_from(76 + 32 * MAX_COMMITMENTS).unwrap();
    // These are codec-only metadata, not authenticated journals or claims that
    // the stated physical layout is canonical. Real replay is still required.
    let valid = [
        structural_pin(0, 76, 0, 76),
        structural_pin(0, maximum_header, 0, u64::from(maximum_header)),
        structural_pin(1, 76, 1, 226),
        structural_pin(1, 76, 1, 76 + SEGMENT_LIMIT),
        structural_pin(1_000_000, 76, 144, 76 + 150_000_000),
        structural_pin(1_000_000, 76, 1024, ACTIVE_LIMIT),
        structural_pin(2048, 76, 2048, 76 + 150 * 2048),
    ];
    for pin in valid {
        let raw = pin.to_bytes();
        assert_eq!(raw.len(), 128);
        assert_eq!(&raw[..8], b"ZVARCP01");
        assert_eq!(ActiveRecoveryCheckpoint::from_bytes(&raw).unwrap(), pin);
        assert_eq!(pin.height(), pin.height);
        assert_eq!(pin.app_hash(), pin.app_hash);
        assert_eq!(pin.length(), pin.length);
        assert_eq!(pin.segment_count(), pin.segment_count);
    }
    let raw = valid[2].to_bytes();
    for cut in 0..raw.len() {
        assert_eq!(
            ActiveRecoveryCheckpoint::from_bytes(&raw[..cut]),
            Err(PoolError::Bounds),
            "accepted truncation {cut}"
        );
    }
    let mut extra = raw.to_vec();
    extra.push(0);
    assert_eq!(
        ActiveRecoveryCheckpoint::from_bytes(&extra),
        Err(PoolError::Bounds)
    );
    for range in [8..40, 48..80, 96..128] {
        let mut changed = raw;
        changed[range].fill(0);
        assert_eq!(
            ActiveRecoveryCheckpoint::from_bytes(&changed),
            Err(PoolError::Bounds)
        );
    }
    let mut wrong_magic = raw;
    wrong_magic[..8].copy_from_slice(b"ZVPRCP01");
    assert_eq!(
        ActiveRecoveryCheckpoint::from_bytes(&wrong_magic),
        Err(PoolError::Bounds)
    );
    assert_eq!(
        crate::pool::recovery::RecoveryCheckpoint::from_bytes(&raw),
        Err(PoolError::Bounds)
    );
    let invalid = [
        structural_pin(1_000_001, 76, 144, 76 + 150_000_150),
        structural_pin(u64::MAX, 76, 1, ACTIVE_LIMIT),
        structural_pin(1, 76, 1, ACTIVE_LIMIT + 1),
        structural_pin(1, 76, 1, u64::MAX),
        structural_pin(0, 75, 0, 75),
        structural_pin(0, 77, 0, 77),
        structural_pin(0, maximum_header + 32, 0, u64::from(maximum_header) + 32),
        structural_pin(0, u32::MAX, 0, u64::from(u32::MAX)),
        structural_pin(0, 76, 0, 75),
        structural_pin(0, 76, 0, 77),
        structural_pin(0, 76, 1, 226),
        structural_pin(1, 76, 0, 226),
        structural_pin(1, 76, 2, 376),
        structural_pin(2049, 76, 2049, 76 + 150 * 2049),
        structural_pin(1, 76, u32::MAX, 226),
        structural_pin(1, 76, 1, 0),
        structural_pin(1, 76, 1, 75),
        structural_pin(1, 76, 1, 225),
        structural_pin(2, 76, 1, 375),
        structural_pin(1, 76, 1, 77 + SEGMENT_LIMIT),
    ];
    for pin in invalid {
        assert_eq!(
            ActiveRecoveryCheckpoint::from_bytes(&pin.to_bytes()),
            Err(PoolError::Bounds),
            "accepted structural bounds {pin:?}"
        );
    }
}

#[test]
fn exported_genesis_checkpoint_matches_independent_fixed_layout_vector() {
    let d = Dir::new();
    let (pin, original) = fixture(&d.path("source"), 0);
    assert_eq!(original.len(), 1);
    assert_eq!(original["genesis"].len(), 76);
    assert_eq!(pin.header_length, 76);
    assert_eq!(pin.segment_count(), 0);
    assert_eq!(pin.length(), 76);
    // Independent Python hashlib vector: ZVARLY01 || u32(76) || the exact
    // ZVOPOL03 empty header for NETWORK and domain [7;32] || u32(0), 92 bytes.
    // Constants are not generated by the production digest implementation.
    assert_eq!(
        pin.genesis,
        [
            0x07, 0x78, 0x23, 0x93, 0xf4, 0x02, 0x1c, 0xab, 0xba, 0x3a, 0x8a, 0x09, 0xf0, 0xd2,
            0x74, 0x7e, 0x6a, 0xe4, 0x40, 0x44, 0x57, 0x47, 0x5c, 0x6e, 0x9d, 0xf8, 0x51, 0x00,
            0xf7, 0x34, 0xbc, 0x1e,
        ]
    );
    assert_eq!(
        pin.layout_hash,
        [
            0x32, 0x5f, 0xba, 0x79, 0xe5, 0xd3, 0x67, 0x64, 0x6d, 0x57, 0xa5, 0x8c, 0x59, 0x42,
            0x64, 0xae, 0x5b, 0x0d, 0x21, 0x6a, 0xf5, 0xce, 0x18, 0x58, 0xe8, 0x8b, 0x0f, 0x26,
            0xa6, 0xa8, 0x82, 0xed,
        ]
    );
}

#[test]
fn genesis_and_committed_archive_copies_preserve_every_file_and_continue_normally() {
    let d = Dir::new();
    for height in [0, 3] {
        let source = d.path(&format!("source-{height}"));
        let (pin, original) = fixture(&source, height);
        let mut archive = ActiveArchive::open(&source, pin).unwrap();
        assert_eq!(archive.checkpoint(), pin);
        archive.verify().unwrap();
        archive.verify().unwrap();
        let backup = d.path(&format!("backup-{height}"));
        assert_eq!(archive.copy_new(&backup).unwrap(), pin);
        assert_eq!(directory_bytes(&backup), original);
        assert!(!backup.join("MANIFEST").exists());
        let mut backup_archive = ActiveArchive::open(&backup, pin).unwrap();
        let restored = d.path(&format!("restored-{height}"));
        assert_eq!(backup_archive.copy_new(&restored).unwrap(), pin);
        backup_archive.verify().unwrap();
        archive.verify().unwrap();
        assert_eq!(directory_bytes(&restored), original);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&restored).unwrap().permissions().mode() & 0o777,
                0o700
            );
            for name in original.keys() {
                assert_eq!(
                    fs::metadata(restored.join(name)).unwrap().permissions().mode() & 0o777,
                    0o600
                );
            }
        }
        // copy_new returns only a pin: the target guards must be released on
        // return, allowing its ordinary writer to open and commit explicitly.
        let mut pool = active_open(&restored).unwrap();
        pool.check_checkpoint(pin.height(), pin.app_hash()).unwrap();
        assert_eq!(pool.active_recovery_checkpoint().unwrap(), pin);
        assert_eq!(commit_empty(&mut pool, height + 1, 0).height, height + 1);
        drop(pool);
        assert_eq!(directory_bytes(&source), original);
        assert_eq!(directory_bytes(&backup), original);
    }
}

#[test]
fn checkpoint_export_preserves_prepared_work_and_never_certifies_uncommitted_bytes() {
    let d = Dir::new();
    let source = d.path("source");
    let mut pool = active_create(&source);
    commit_empty(&mut pool, 1, 0);
    let committed = pool.summary().unwrap();
    let prepared = pool.prepare(2, [29; 32], &[]).unwrap();
    let predicted = prepared.result().clone();
    let before = owned_bytes(&pool);
    let pin = pool.active_recovery_checkpoint().unwrap();
    assert_eq!(pin.height(), committed.height);
    assert_eq!(pin.app_hash(), committed.app_hash);
    assert_eq!(pin.length(), before.len() as u64);
    assert_eq!(pool.summary().unwrap(), committed);
    assert_eq!(owned_bytes(&pool), before);
    assert_eq!(pool.active_recovery_checkpoint().unwrap(), pin);
    assert_eq!(pool.commit(prepared).unwrap(), predicted);
    let fresh = pool.active_recovery_checkpoint().unwrap();
    assert_eq!(fresh.height(), 2);
    assert_ne!(fresh, pin);
    drop(pool);
    assert!(ActiveArchive::open(&source, pin).is_err());
    ActiveArchive::open(&source, fresh).unwrap().verify().unwrap();
}

#[test]
fn incompatible_checkpoint_profiles_reject_without_poisoning_healthy_stores() {
    let d = Dir::new();
    let mut active = active_create(&d.path("active"));
    let active_prepared = active.prepare(1, [1; 32], &[]).unwrap();
    assert_eq!(active.recovery_checkpoint(), Err(PoolError::Bounds));
    assert_eq!(active.summary().unwrap().height, 0);
    assert_eq!(active.commit(active_prepared).unwrap().height, 1);
    let new_pin = active.active_recovery_checkpoint().unwrap();
    let mut legacy = PoolStore::create(&d.path("legacy")).unwrap();
    let legacy_prepared = legacy.prepare(1, [1; 32], &[]).unwrap();
    assert_eq!(legacy.active_recovery_checkpoint(), Err(PoolError::Bounds));
    assert_eq!(legacy.summary().unwrap().height, 0);
    assert_eq!(legacy.commit(legacy_prepared).unwrap().height, 1);
    let old_pin = legacy.recovery_checkpoint().unwrap();
    assert_eq!(
        ActiveRecoveryCheckpoint::from_bytes(&old_pin.to_bytes()),
        Err(PoolError::Bounds)
    );
    assert_eq!(
        crate::pool::recovery::RecoveryCheckpoint::from_bytes(&new_pin.to_bytes()),
        Err(PoolError::Bounds)
    );
}

#[test]
fn checkpoint_export_replays_same_length_replacement_and_never_publishes_its_state() {
    let d = Dir::new();
    let source = d.path("source");
    let (_, original) = fixture(&source, 2);
    let replacement_path = d.path("other-valid-history");
    let mut other = active_create(&replacement_path);
    for height in 1..=2 {
        commit_empty(&mut other, height, 91);
    }
    let replacement_summary = other.summary().unwrap();
    other.active_recovery_checkpoint().unwrap();
    drop(other);
    let replacement = directory_bytes(&replacement_path);
    assert_eq!(original["genesis"], replacement["genesis"]);
    assert_eq!(original[SEGMENT].len(), replacement[SEGMENT].len());
    assert_ne!(original[SEGMENT], replacement[SEGMENT]);
    let mut pool = active_open(&source).unwrap();
    let committed = pool.summary().unwrap();
    assert_ne!(committed, replacement_summary);
    let prepared = pool.prepare(3, [3; 32], &[]).unwrap();
    // Active segment handles are read/write, with only genesis locked. This
    // explicit uncooperative test writer keeps the same file identity/length;
    // it does not mutate the exclusively locked genesis through another handle.
    let mut writer = OpenOptions::new()
        .write(true)
        .open(source.join(SEGMENT))
        .unwrap();
    writer.write_all(&replacement[SEGMENT]).unwrap();
    writer.sync_all().unwrap();
    drop(writer);
    assert_eq!(fs::read(source.join(SEGMENT)).unwrap(), replacement[SEGMENT]);
    assert_eq!(pool.active_recovery_checkpoint(), Err(PoolError::Corrupt));
    assert_eq!(pool.state.summary(), committed);
    assert_eq!(pool.summary(), Err(PoolError::Unavailable));
    assert_eq!(pool.commit(prepared), Err(PoolError::Unavailable));
    assert!(matches!(active_open(&source), Err(PoolError::Locked)));
    drop(pool);
    assert_eq!(directory_bytes(&source), replacement);
}

#[test]
fn retained_replay_binds_the_independently_expected_genesis_after_a_same_length_change() {
    let d = Dir::new();
    let source = d.path("source");
    let mut pool = active_create(&source);
    let committed = pool.summary().unwrap();
    let expected_genesis = pool.state.genesis;
    let mut changed = owned_bytes(&pool);
    assert_eq!(changed.len(), 76);
    changed[40..72].fill(8);
    // This test-only overwrite uses the ORIGINAL owning handle, preserving its
    // exclusive Windows lock. A second path handle must not mask the corruption.
    pool.file.rewind().unwrap();
    pool.file.write_all(&changed).unwrap();
    pool.file.sync_all().unwrap();
    assert_eq!(owned_bytes(&pool), changed);
    assert!(matches!(
        PoolStore::replay_active_handles(
            &pool.file,
            pool.active.as_ref().unwrap(),
            expected_genesis
        ),
        Err(PoolError::Genesis)
    ));
    assert_eq!(pool.summary().unwrap(), committed);
    assert_eq!(pool.state.genesis, expected_genesis);
    assert_eq!(pool.active_recovery_checkpoint(), Err(PoolError::Genesis));
    assert_eq!(pool.state.summary(), committed);
    assert_eq!(pool.summary(), Err(PoolError::Unavailable));
    drop(pool);
    assert_eq!(fs::read(source.join("genesis")).unwrap(), changed);
}

#[test]
fn repinned_headers_are_bounded_inside_the_physical_genesis_file() {
    let d = Dir::new();
    let (pin, original) = fixture(&d.path("source"), 3);
    for (label, expected) in [
        ("borrow-segment-for-commitment", PoolError::Bounds),
        ("unbounded-commitment-count", PoolError::Bounds),
        ("extra-physical-header-bytes", PoolError::Corrupt),
        ("wrong-profile", PoolError::Genesis),
        ("wrong-network", PoolError::Genesis),
        ("zero-domain", PoolError::Domain),
        ("invalid-curve-point", PoolError::Genesis),
    ] {
        let mut changed = original.clone();
        let header = changed.get_mut("genesis").unwrap();
        match label {
            "borrow-segment-for-commitment" => header[72..76].copy_from_slice(&1u32.to_be_bytes()),
            "unbounded-commitment-count" => {
                header[72..76].copy_from_slice(&u32::MAX.to_be_bytes())
            }
            "extra-physical-header-bytes" => header.extend_from_slice(&[0; 32]),
            "wrong-profile" => header[..8].copy_from_slice(b"ZVOPOL02"),
            "wrong-network" => header[8] ^= 1,
            "zero-domain" => header[40..72].fill(0),
            "invalid-curve-point" => {
                header[72..76].copy_from_slice(&1u32.to_be_bytes());
                header.extend_from_slice(&[0xff; 32]);
            }
            _ => unreachable!(),
        }
        let changed_pin = repin(pin, &changed);
        ActiveRecoveryCheckpoint::from_bytes(&changed_pin.to_bytes()).unwrap();
        let path = d.path(label);
        write_directory(&path, &changed);
        assert!(
            matches!(ActiveArchive::open(&path, changed_pin), Err(error) if error == expected),
            "wrong rejection for {label}"
        );
        assert_eq!(directory_bytes(&path), changed);
    }
    ActiveArchive::open(&d.path("source"), pin).unwrap();
}

#[test]
fn repinned_layout_still_requires_complete_frames_canonical_rotation_and_real_state() {
    let d = Dir::new();
    let (pin, original) = fixture(&d.path("source"), 3);
    assert_eq!(original[SEGMENT].len(), 450);
    for (label, split) in [("early-rotation", 150), ("split-frame", 200)] {
        let records = &original[SEGMENT];
        let mut changed = original.clone();
        changed.insert(SEGMENT.into(), records[..split].to_vec());
        changed.insert(SECOND_SEGMENT.into(), records[split..].to_vec());
        let changed_pin = repin(pin, &changed);
        assert_eq!(changed_pin.length(), pin.length());
        assert_ne!(changed_pin.layout_hash, pin.layout_hash);
        ActiveRecoveryCheckpoint::from_bytes(&changed_pin.to_bytes()).unwrap();
        let path = d.path(label);
        write_directory(&path, &changed);
        assert_layout_pin_matches(&path, changed_pin);
        // Both physical parts meet the 150-byte minimum, every body/checksum
        // and the logical stream are unchanged, and the new layout hash matches.
        // Rejection therefore exercises per-record physical-frame validation.
        assert!(matches!(
            ActiveArchive::open(&path, changed_pin),
            Err(PoolError::Corrupt)
        ));
        assert_eq!(directory_bytes(&path), changed);
    }
    for label in ["wrong-record-checksum", "wrong-final-state", "trailing-byte"] {
        let mut changed = original.clone();
        let records = changed.get_mut(SEGMENT).unwrap();
        match label {
            "wrong-record-checksum" => records[449] ^= 1,
            "wrong-final-state" => {
                let body_start = 2 * 150 + 4;
                records[body_start + 80] ^= 1;
                let digest = Sha256::digest(&records[body_start..body_start + 114]);
                records[body_start + 114..body_start + 146].copy_from_slice(&digest);
            }
            "trailing-byte" => records.push(0),
            _ => unreachable!(),
        }
        let changed_pin = repin(pin, &changed);
        ActiveRecoveryCheckpoint::from_bytes(&changed_pin.to_bytes()).unwrap();
        let path = d.path(label);
        write_directory(&path, &changed);
        assert_layout_pin_matches(&path, changed_pin);
        assert!(
            matches!(
                ActiveArchive::open(&path, changed_pin),
                Err(PoolError::Corrupt)
            ),
            "{label}"
        );
        assert_eq!(directory_bytes(&path), changed);
    }
    let mut wrong_genesis = pin;
    wrong_genesis.genesis[0] ^= 1;
    assert!(matches!(
        ActiveArchive::open(&d.path("source"), wrong_genesis),
        Err(PoolError::Genesis)
    ));
    let mut wrong_layout = pin;
    wrong_layout.layout_hash[0] ^= 1;
    assert!(matches!(
        ActiveArchive::open(&d.path("source"), wrong_layout),
        Err(PoolError::Corrupt)
    ));
    for wrong in [
        ActiveRecoveryCheckpoint { height: 2, ..pin },
        ActiveRecoveryCheckpoint {
            app_hash: [91; 32],
            ..pin
        },
    ] {
        assert!(matches!(
            ActiveArchive::open(&d.path("source"), wrong),
            Err(PoolError::Stale)
        ));
    }
}

#[test]
fn creating_a_target_is_exclusive_and_source_validation_precedes_creation() {
    let d = Dir::new();
    let source = d.path("source");
    let (pin, original) = fixture(&source, 2);
    let mut archive = ActiveArchive::open(&source, pin).unwrap();
    let existing_file = d.path("existing-file");
    fs::write(&existing_file, b"preserve-file").unwrap();
    let existing_dir = d.path("existing-directory");
    fs::create_dir(&existing_dir).unwrap();
    fs::write(existing_dir.join("preserve"), b"preserve-directory").unwrap();
    for path in [source.clone(), existing_file.clone(), existing_dir.clone()] {
        assert!(archive.copy_new(&path).is_err());
    }
    assert_eq!(fs::read(&existing_file).unwrap(), b"preserve-file");
    assert_eq!(
        fs::read(existing_dir.join("preserve")).unwrap(),
        b"preserve-directory"
    );
    assert!(matches!(
        archive.copy_new(Path::new("relative")),
        Err(PoolError::Bounds)
    ));
    let missing_parent = d.path("missing/target");
    assert!(archive.copy_new(&missing_parent).is_err());
    assert!(!d.path("missing").exists());
    let nested = source.join("must-not-create");
    assert!(matches!(archive.copy_new(&nested), Err(PoolError::Bounds)));
    assert!(!nested.exists());
    assert_eq!(directory_bytes(&source), original);

    // Once an archive is open, a persistently modified segment must be checked
    // again before creating output. Segments do not own the root's byte lock.
    let mut changed = original[SEGMENT].clone();
    *changed.last_mut().unwrap() ^= 1;
    fs::write(source.join(SEGMENT), &changed).unwrap();
    let absent = d.path("bad-source-must-not-create");
    assert!(matches!(archive.copy_new(&absent), Err(PoolError::Corrupt)));
    assert!(!absent.exists());
    assert_eq!(fs::read(source.join(SEGMENT)).unwrap(), changed);
}

#[test]
fn partial_copies_and_lost_acknowledgements_preserve_targets_without_retry_or_repair() {
    let d = Dir::new();
    let source = d.path("source");
    let (pin, original) = fixture(&source, 3);
    let mut archive = ActiveArchive::open(&source, pin).unwrap();
    for fault in 1..=4 {
        let target = d.path(&format!("fault-{fault}"));
        archive.fault = fault;
        assert_eq!(archive.copy_new(&target), Err(PoolError::Storage));
        assert!(target.is_dir());
        assert_eq!(directory_bytes(&source), original);
        let partial = directory_bytes(&target);
        match fault {
            1 => {
                assert!(partial["genesis"].len() < original["genesis"].len());
                assert!(!partial.contains_key(SEGMENT));
            }
            2 => {
                assert_eq!(partial["genesis"], original["genesis"]);
                assert!(!partial[SEGMENT].is_empty());
                assert!(partial[SEGMENT].len() < original[SEGMENT].len());
            }
            3 | 4 => assert_eq!(partial, original),
            _ => unreachable!(),
        }
        let checked = ActiveArchive::open(&target, pin);
        assert_eq!(checked.is_ok(), fault >= 3);
        drop(checked);
        // Fault 3 proves only process-visible full bytes, not persistence. Fault
        // 4 occurs after sync but still makes no actual power-loss guarantee.
        archive.fault = 0;
        assert!(archive.copy_new(&target).is_err());
        assert_eq!(directory_bytes(&target), partial);
        archive.verify().unwrap();
    }
    assert_eq!(
        archive.copy_new(&d.path("explicit-new-target")).unwrap(),
        pin
    );
}

#[test]
fn final_source_and_target_namespace_changes_cannot_return_success() {
    let d = Dir::new();
    for fault in [5, 6] {
        let source = d.path(&format!("source-{fault}"));
        let target = d.path(&format!("target-{fault}"));
        let (pin, original) = fixture(&source, 3);
        let mut archive = ActiveArchive::open(&source, pin).unwrap();
        archive.fault = fault;
        assert_eq!(archive.copy_new(&target), Err(PoolError::Corrupt));
        assert!(target.is_dir());
        let mut source_after = directory_bytes(&source);
        let mut target_after = directory_bytes(&target);
        if fault == 5 {
            // This injection deliberately adds an external namespace entry. It
            // changes that directory, while retaining every original file byte.
            assert!(source_after.remove(".archive-final-source-fault").is_some());
            assert_eq!(source_after, original);
            assert_eq!(target_after, original);
            assert!(archive.verify().is_err());
            ActiveArchive::open(&target, pin).unwrap().verify().unwrap();
        } else {
            assert_eq!(source_after, original);
            assert!(target_after.remove(".archive-final-target-fault").is_some());
            assert_eq!(target_after, original);
            assert!(ActiveArchive::open(&target, pin).is_err());
            archive.verify().unwrap();
        }
    }
}

#[path = "namespace_tests.rs"]
mod namespace_tests;
