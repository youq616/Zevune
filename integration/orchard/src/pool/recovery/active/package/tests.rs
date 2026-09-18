//! Public package gates over ordinary, genuinely replayed empty-block commits.
//! Real payments, default-size rotation and restored onward spending are in
//! active_flow_tests. The encoders below do not call production package code.
use super::*;
use crate::pool::{PoolStore, Summary};
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::PathBuf;

const DOMAIN: [u8; 32] = [61; 32];
const SEGMENT: &str = "00000000.journal";
type DirectoryBytes = BTreeMap<String, Vec<u8>>;
type Range = (u32, u32, u32);

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let suffix: String = nonce.iter().map(|byte| format!("{byte:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-package-api-{suffix}"));
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

fn open_store(path: &Path) -> Result<PoolStore, PoolError> {
    PoolStore::open_with_profile(path, &[], Some(DOMAIN), StorageProfile::ActiveSegmentsV1)
}

fn fixture(path: &Path, height: u64, variant: u8, domain: [u8; 32]) -> ActiveRecoveryCheckpoint {
    let mut pool =
        PoolStore::create_with_profile(path, &[], Some(domain), StorageProfile::ActiveSegmentsV1)
            .unwrap();
    for height in 1..=height {
        let mut id = [variant; 32];
        id[..8].copy_from_slice(&height.to_be_bytes());
        let block = pool.prepare(height, id, &[]).unwrap();
        let expected = block.result().clone();
        assert_eq!(pool.commit(block).unwrap(), expected);
    }
    let summary = pool.summary().unwrap();
    let pin = pool.active_recovery_checkpoint().unwrap();
    drop(pool);
    assert_eq!(physical_pin(&directory_bytes(path), &summary), pin);
    pin
}

fn physical_pin(files: &DirectoryBytes, state: &Summary) -> ActiveRecoveryCheckpoint {
    let header = &files["genesis"];
    let count = u32::try_from(files.len() - 1).unwrap();
    let mut hash = Sha256::new();
    hash.update(b"ZVARLY01");
    hash.update(u32::try_from(header.len()).unwrap().to_be_bytes());
    hash.update(header);
    hash.update(count.to_be_bytes());
    let mut length = header.len() as u64;
    for index in 0..count {
        let bytes = &files[&format!("{index:08}.journal")];
        hash.update(index.to_be_bytes());
        hash.update(u32::try_from(bytes.len()).unwrap().to_be_bytes());
        hash.update(bytes);
        length += bytes.len() as u64;
    }
    let mut raw = b"ZVARCP01".to_vec();
    raw.extend_from_slice(&Sha256::digest(header));
    raw.extend_from_slice(&state.height.to_be_bytes());
    raw.extend_from_slice(&state.app_hash);
    raw.extend_from_slice(&length.to_be_bytes());
    raw.extend_from_slice(&u32::try_from(header.len()).unwrap().to_be_bytes());
    raw.extend_from_slice(&count.to_be_bytes());
    raw.extend_from_slice(&hash.finalize());
    ActiveRecoveryCheckpoint::from_bytes(&raw).unwrap()
}

fn encode_fixture(
    base: ActiveRecoveryCheckpoint,
    later: ActiveRecoveryCheckpoint,
    ranges: &[Range],
    payload: &[u8],
) -> Vec<u8> {
    let mut raw = b"ZVAIPK01".to_vec();
    raw.extend_from_slice(&base.to_bytes());
    raw.extend_from_slice(&later.to_bytes());
    raw.extend_from_slice(&u32::try_from(ranges.len()).unwrap().to_be_bytes());
    for &(index, offset, length) in ranges {
        raw.extend_from_slice(&index.to_be_bytes());
        raw.extend_from_slice(&offset.to_be_bytes());
        raw.extend_from_slice(&length.to_be_bytes());
    }
    raw.extend_from_slice(payload);
    raw
}

fn expected_ranges(base: &DirectoryBytes, later: &DirectoryBytes) -> Vec<Range> {
    let mut ranges = Vec::new();
    for index in 0..later.len() - 1 {
        let name = format!("{index:08}.journal");
        let offset = base.get(&name).map_or(0, Vec::len);
        let bytes = &later[&name];
        if bytes.len() > offset {
            ranges.push((
                u32::try_from(index).unwrap(),
                u32::try_from(offset).unwrap(),
                u32::try_from(bytes.len() - offset).unwrap(),
            ));
        }
    }
    ranges
}

fn payload(files: &DirectoryBytes, ranges: &[Range]) -> Vec<u8> {
    let mut raw = Vec::new();
    for &(index, offset, length) in ranges {
        let file = &files[&format!("{index:08}.journal")];
        let end = offset.checked_add(length).unwrap();
        raw.extend_from_slice(&file[offset as usize..end as usize]);
    }
    raw
}

fn assert_plan(
    package: &ActiveIncrementalPackage,
    base: ActiveRecoveryCheckpoint,
    later: ActiveRecoveryCheckpoint,
    ranges: &[Range],
) {
    let plan = package.plan();
    assert_eq!(plan.base_checkpoint(), base);
    assert_eq!(plan.checkpoint(), later);
    assert_eq!(plan.reused_bytes(), base.length());
    assert_eq!(plan.appended_bytes(), later.length() - base.length());
    assert_eq!(
        plan.new_segment_count(),
        later.segment_count() - base.segment_count()
    );
    let changed_old = ranges
        .iter()
        .filter(|range| range.0 < base.segment_count())
        .count();
    assert_eq!(
        plan.unchanged_segment_count(),
        base.segment_count() - u32::try_from(changed_old).unwrap()
    );
    let actual: Vec<_> = plan
        .ranges()
        .iter()
        .map(|range| (range.segment_index(), range.offset(), range.length()))
        .collect();
    assert_eq!(actual, ranges);
    assert_eq!(
        package.package_bytes(),
        268 + 12 * ranges.len() as u64 + later.length() - base.length()
    );
}

// Private, test-only simulation of a late noncooperating journal write. The
// ordinary archive root lock is retained, and the changed byte remains visible.
pub(super) fn change_tail(path: &Path) -> Result<(), PoolError> {
    let mut paths = Vec::new();
    for entry in fs::read_dir(path).map_err(|_| PoolError::Storage)? {
        let path = entry.map_err(|_| PoolError::Storage)?.path();
        if path
            .extension()
            .is_some_and(|extension| extension == "journal")
        {
            paths.push(path);
        }
    }
    paths.sort();
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(paths.last().ok_or(PoolError::Corrupt)?)
        .map_err(|_| PoolError::Storage)?;
    file.seek(SeekFrom::End(-1))
        .map_err(|_| PoolError::Storage)?;
    let mut byte = [0];
    file.read_exact(&mut byte).map_err(|_| PoolError::Storage)?;
    byte[0] ^= 0x80;
    file.seek(SeekFrom::End(-1))
        .map_err(|_| PoolError::Storage)?;
    file.write_all(&byte).map_err(|_| PoolError::Storage)?;
    file.sync_all().map_err(|_| PoolError::Storage)
}

#[test]
fn independently_encoded_packages_restore_exact_bytes_without_a_later_directory() {
    let d = Dir::new();
    for (number, (base_height, later_height)) in
        [(0, 0), (0, 3), (2, 2), (2, 5)].into_iter().enumerate()
    {
        let base_path = d.path(&format!("base-{number}"));
        let later_path = d.path(&format!("later-{number}"));
        let base_pin = fixture(&base_path, base_height, 0, DOMAIN);
        let later_pin = fixture(&later_path, later_height, 0, DOMAIN);
        let original_base = directory_bytes(&base_path);
        let original_later = directory_bytes(&later_path);
        let ranges = expected_ranges(&original_base, &original_later);
        let expected = encode_fixture(
            base_pin,
            later_pin,
            &ranges,
            &payload(&original_later, &ranges),
        );
        let path = d.path(&format!("created-{number}.incremental"));
        let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
        let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
        let package = base.pack_incremental_new(&mut later, &path).unwrap();
        assert_plan(&package, base_pin, later_pin, &ranges);
        drop(package);
        drop(later);
        assert_eq!(fs::read(&path).unwrap(), expected);
        // The completed writer has been dropped. Subsequent public operations
        // receive only the base, package, and independently retained later pin.
        fs::remove_dir_all(&later_path).unwrap();
        let mut package = ActiveIncrementalPackage::open(&path, &mut base, later_pin).unwrap();
        assert_plan(&package, base_pin, later_pin, &ranges);
        package.verify(&mut base).unwrap();
        let restored = d.path(&format!("restored-{number}"));
        assert_eq!(
            package.restore_new(&mut base, &restored).unwrap(),
            later_pin
        );
        assert_eq!(directory_bytes(&restored), original_later);
        // restore_new returns no owning writer or hidden pending reservation.
        let mut pool = open_store(&restored).unwrap();
        pool.check_checkpoint(later_pin.height(), later_pin.app_hash())
            .unwrap();
        let block = pool.prepare(later_height + 1, [93; 32], &[]).unwrap();
        assert_eq!(pool.commit(block).unwrap().height, later_height + 1);
        drop(pool);
        package.verify(&mut base).unwrap();
        assert_eq!(directory_bytes(&base_path), original_base);
        assert_eq!(fs::read(&path).unwrap(), expected);
    }
}

#[test]
fn strict_package_metadata_pins_offsets_lengths_and_eof_reject_without_writing() {
    let d = Dir::new();
    let base_path = d.path("base");
    let later_path = d.path("later");
    let base_pin = fixture(&base_path, 2, 0, DOMAIN);
    let later_pin = fixture(&later_path, 5, 0, DOMAIN);
    let original_base = directory_bytes(&base_path);
    let original_later = directory_bytes(&later_path);
    let suffix = &original_later[SEGMENT][300..];
    let good = encode_fixture(base_pin, later_pin, &[(0, 300, 450)], suffix);
    let mut cases = Vec::new();
    for (label, offset) in [
        ("magic", 0),
        ("version", 7),
        ("base-pin", 8),
        ("later-pin", 136),
    ] {
        let mut raw = good.clone();
        raw[offset] ^= 1;
        cases.push((label, raw));
    }
    for (label, count) in [("range-bound", 2049u32), ("count-overflow", u32::MAX)] {
        let mut raw = good.clone();
        raw[264..268].copy_from_slice(&count.to_be_bytes());
        cases.push((label, raw));
    }
    for (label, ranges) in [
        ("wrong-tail-before", vec![(0, 299, 450)]),
        ("wrong-tail-after", vec![(0, 301, 450)]),
        ("old-tail-zero", vec![(0, 0, 450)]),
        ("zero-length", vec![(0, 300, 0)]),
        ("missing-range", vec![]),
        ("duplicate", vec![(0, 300, 150), (0, 450, 300)]),
        ("new-gap", vec![(2, 0, 450)]),
        ("offset-overflow", vec![(0, u32::MAX, 450)]),
        ("length-overflow", vec![(0, 300, u32::MAX)]),
        ("wrong-sum", vec![(0, 300, 449)]),
    ] {
        cases.push((label, encode_fixture(base_pin, later_pin, &ranges, suffix)));
    }
    for end in [0, 7, 135, 263, 267, 279, good.len() - 1] {
        cases.push(("truncated", good[..end].to_vec()));
    }
    let mut extra = good.clone();
    extra.push(0);
    cases.push(("trailing", extra));
    let mut damaged = good.clone();
    *damaged.last_mut().unwrap() ^= 1;
    cases.push(("payload", damaged));
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    for (index, (label, bytes)) in cases.iter().enumerate() {
        let path = d.path(&format!("bad-{index}.incremental"));
        fs::write(&path, bytes).unwrap();
        assert!(
            ActiveIncrementalPackage::open(&path, &mut base, later_pin).is_err(),
            "{label}"
        );
        assert_eq!(&fs::read(&path).unwrap(), bytes);
        // A failed open must release its acquired package file lock.
        let probe = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .unwrap();
        probe.try_lock().unwrap();
        drop(probe);
        base.verify().unwrap();
    }
    let path = d.path("good.incremental");
    fs::write(&path, &good).unwrap();
    ActiveIncrementalPackage::open(&path, &mut base, later_pin).unwrap();
    assert_eq!(directory_bytes(&base_path), original_base);
    assert_eq!(directory_bytes(&later_path), original_later);
}

#[test]
fn repinned_early_rotation_and_split_frames_reach_the_joined_replay_gate() {
    let d = Dir::new();
    let base_path = d.path("base");
    let later_path = d.path("later");
    let base_pin = fixture(&base_path, 1, 0, DOMAIN);
    let later_pin = fixture(&later_path, 3, 0, DOMAIN);
    let state = open_store(&later_path).unwrap().summary().unwrap();
    let original_base = directory_bytes(&base_path);
    let original_later = directory_bytes(&later_path);
    assert_eq!(original_later[SEGMENT].len(), 450);
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    for (label, split, ranges) in [
        ("early-rotation", 150, vec![(1, 0, 300)]),
        ("split-frame", 225, vec![(0, 150, 75), (1, 0, 225)]),
    ] {
        let mut changed = original_later.clone();
        changed.insert(SEGMENT.into(), original_later[SEGMENT][..split].to_vec());
        changed.insert(
            "00000001.journal".into(),
            original_later[SEGMENT][split..].to_vec(),
        );
        let pin = physical_pin(&changed, &state);
        assert_eq!(pin.length(), later_pin.length());
        assert_eq!(pin.height(), later_pin.height());
        assert_eq!(pin.app_hash(), later_pin.app_hash());
        assert_ne!(pin, later_pin);
        let raw = encode_fixture(base_pin, pin, &ranges, &payload(&changed, &ranges));
        assert_eq!(raw.len(), 268 + 12 * ranges.len() + 300);
        let path = d.path(&format!("{label}.incremental"));
        fs::write(&path, &raw).unwrap();
        // These PRIVATE calls cannot publish an object to production callers.
        // Prove the genuine base, strict metadata, complete payload and repinned
        // combined layout all pass before exercising the actual replay gate.
        let mut unchecked = ActiveIncrementalPackage::open_unverified(&path, &base, pin).unwrap();
        unchecked.check_bytes(&base).unwrap();
        if ranges.len() > 1 {
            // Both segment indices and individual offsets remain in bounds.
            // Reorder payload with its descriptors so this specifically tests
            // strict table ordering rather than an out-of-range segment index.
            let mut reversed = ranges.clone();
            reversed.reverse();
            let reordered = encode_fixture(base_pin, pin, &reversed, &payload(&changed, &reversed));
            let reordered_path = d.path("out-of-order.incremental");
            fs::write(&reordered_path, &reordered).unwrap();
            assert!(matches!(
                ActiveIncrementalPackage::open_unverified(&reordered_path, &base, pin),
                Err(PoolError::Corrupt)
            ));
            assert_eq!(fs::read(reordered_path).unwrap(), reordered);
        }
        assert_eq!(unchecked.verify(&mut base), Err(PoolError::Corrupt));
        let target = d.path(&format!("must-not-create-{label}"));
        assert_eq!(
            unchecked.restore_new(&mut base, &target),
            Err(PoolError::Corrupt)
        );
        assert!(!target.exists());
        drop(unchecked);
        assert!(matches!(
            ActiveIncrementalPackage::open(&path, &mut base, pin),
            Err(PoolError::Corrupt)
        ));
        assert_eq!(fs::read(path).unwrap(), raw);
        assert_eq!(directory_bytes(&base_path), original_base);
    }
    let ranges = [(0, 150, 300)];
    let good = encode_fixture(
        base_pin,
        later_pin,
        &ranges,
        &payload(&original_later, &ranges),
    );
    let path = d.path("canonical-control.incremental");
    fs::write(&path, &good).unwrap();
    ActiveIncrementalPackage::open(&path, &mut base, later_pin).unwrap();
    assert_eq!(directory_bytes(&later_path), original_later);
}

#[test]
fn independently_valid_forks_rollback_networks_and_wrong_base_cannot_authorize_output() {
    let d = Dir::new();
    let base_path = d.path("base");
    let later_path = d.path("later");
    let base_pin = fixture(&base_path, 2, 0, DOMAIN);
    let later_pin = fixture(&later_path, 4, 0, DOMAIN);
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
    let package_path = d.path("good.incremental");
    let mut package = base
        .pack_incremental_new(&mut later, &package_path)
        .unwrap();
    for (index, (height, variant, domain)) in [
        (2, 1, DOMAIN),
        (4, 1, DOMAIN),
        (1, 0, DOMAIN),
        (4, 0, [62; 32]),
    ]
    .into_iter()
    .enumerate()
    {
        let path = d.path(&format!("candidate-{index}"));
        let pin = fixture(&path, height, variant, domain);
        let original = directory_bytes(&path);
        let mut candidate = ActiveArchive::open(&path, pin).unwrap();
        candidate.verify().unwrap();
        let output = d.path(&format!("refused-{index}.incremental"));
        assert!(base.pack_incremental_new(&mut candidate, &output).is_err());
        assert!(!output.exists());
        assert_eq!(package.verify(&mut candidate), Err(PoolError::Stale));
        let target = d.path(&format!("refused-restore-{index}"));
        assert_eq!(
            package.restore_new(&mut candidate, &target),
            Err(PoolError::Stale)
        );
        assert!(!target.exists());
        assert_eq!(directory_bytes(&path), original);
    }
    package.verify(&mut base).unwrap();
    let mut same_base = ActiveArchive::open(&base_path, base_pin).unwrap();
    let same_path = d.path("same-path.incremental");
    let same = base
        .pack_incremental_new(&mut same_base, &same_path)
        .unwrap();
    assert_plan(&same, base_pin, base_pin, &[]);
}

#[test]
fn new_outputs_are_exclusive_and_changed_inputs_are_rechecked_before_creation() {
    let d = Dir::new();
    let base_path = d.path("base");
    let later_path = d.path("later");
    let base_pin = fixture(&base_path, 1, 0, DOMAIN);
    let later_pin = fixture(&later_path, 3, 0, DOMAIN);
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
    let package_path = d.path("package.incremental");
    let package = base
        .pack_incremental_new(&mut later, &package_path)
        .unwrap();
    drop(package);
    let original_package = fs::read(&package_path).unwrap();
    let mut package = ActiveIncrementalPackage::open(&package_path, &mut base, later_pin).unwrap();
    let file = d.path("existing-file");
    fs::write(&file, b"keep file").unwrap();
    let directory = d.path("existing-directory");
    fs::create_dir(&directory).unwrap();
    fs::write(directory.join("keep"), b"keep directory").unwrap();
    for target in [&base_path, &later_path, &package_path, &file, &directory] {
        assert!(base.pack_incremental_new(&mut later, target).is_err());
        assert!(package.restore_new(&mut base, target).is_err());
    }
    for target in [
        base_path.join("nested"),
        later_path.join("nested"),
        d.path("missing-parent/new"),
        PathBuf::from("relative"),
    ] {
        assert!(base.pack_incremental_new(&mut later, &target).is_err());
        assert!(!target.exists());
    }
    for target in [
        base_path.join("nested"),
        d.path("missing-parent/new"),
        PathBuf::from("relative"),
    ] {
        assert!(package.restore_new(&mut base, &target).is_err());
        assert!(!target.exists());
    }
    assert_eq!(fs::read(&file).unwrap(), b"keep file");
    assert_eq!(fs::read(directory.join("keep")).unwrap(), b"keep directory");
    assert_eq!(fs::read(&package_path).unwrap(), original_package);
    // A prior successful open and plan cannot authorize future base contents.
    change_tail(&base_path).unwrap();
    let changed = directory_bytes(&base_path);
    let target = d.path("changed-base-must-not-create");
    assert!(package.restore_new(&mut base, &target).is_err());
    assert!(!target.exists());
    assert!(base.pack_incremental_new(&mut later, &target).is_err());
    assert!(!target.exists());
    assert_eq!(directory_bytes(&base_path), changed);
    assert_eq!(fs::read(package_path).unwrap(), original_package);
}

#[test]
fn final_verify_byte_changes_do_not_reuse_previous_success_or_repair_inputs() {
    let d = Dir::new();
    for fault in 1..=3 {
        let base_path = d.path(&format!("base-{fault}"));
        let later_path = d.path(&format!("later-{fault}"));
        let base_pin = fixture(&base_path, 2, 0, DOMAIN);
        let later_pin = fixture(&later_path, 4, 0, DOMAIN);
        let before_base = directory_bytes(&base_path);
        let before_later = directory_bytes(&later_path);
        let ranges = [(0, 300, 300)];
        let mut expected = encode_fixture(
            base_pin,
            later_pin,
            &ranges,
            &payload(&before_later, &ranges),
        );
        let path = d.path(&format!("fault-{fault}.incremental"));
        let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
        let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
        let mut package = base.pack_incremental_new(&mut later, &path).unwrap();
        package.verify(&mut base).unwrap();
        package.fault = fault;
        assert_eq!(package.verify(&mut base), Err(PoolError::Corrupt));
        package.fault = 0;
        assert_eq!(package.verify(&mut base), Err(PoolError::Corrupt));
        // Faults 2/3 change the retained ORIGINAL writable creation handle.
        // They do not claim an outside writer bypassed Windows package locks.
        drop(package);
        let mut expected_base = before_base;
        match fault {
            1 => *expected_base.get_mut(SEGMENT).unwrap().last_mut().unwrap() ^= 0x80,
            2 => expected[0] ^= 1,
            3 => expected[280] ^= 1,
            _ => unreachable!(),
        }
        assert_eq!(directory_bytes(&base_path), expected_base);
        assert_eq!(directory_bytes(&later_path), before_later);
        assert_eq!(fs::read(&path).unwrap(), expected);
    }
}

#[test]
fn partial_package_and_restore_failures_keep_exact_targets_and_release_creation_handles() {
    let d = Dir::new();
    let base_path = d.path("base");
    let later_path = d.path("later");
    let base_pin = fixture(&base_path, 2, 0, DOMAIN);
    let later_pin = fixture(&later_path, 4, 0, DOMAIN);
    let original_base = directory_bytes(&base_path);
    let original_later = directory_bytes(&later_path);
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
    for fault in 20..=23 {
        let path = d.path(&format!("partial-{fault}.incremental"));
        base.fault = fault;
        assert!(matches!(
            base.pack_incremental_new(&mut later, &path),
            Err(PoolError::Storage)
        ));
        base.fault = 0;
        assert!(path.is_file());
        let bytes = fs::read(&path).unwrap();
        let result = ActiveIncrementalPackage::open(&path, &mut base, later_pin);
        assert_eq!(result.is_ok(), fault >= 22);
        drop(result);
        assert!(base.pack_incremental_new(&mut later, &path).is_err());
        assert_eq!(fs::read(&path).unwrap(), bytes);
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .unwrap();
        file.try_lock().unwrap();
        drop(file);
    }
    let package_path = d.path("complete.incremental");
    let mut package = base
        .pack_incremental_new(&mut later, &package_path)
        .unwrap();
    for fault in 11..=14 {
        let target = d.path(&format!("partial-restore-{fault}"));
        package.fault = fault;
        assert_eq!(
            package.restore_new(&mut base, &target),
            Err(PoolError::Storage)
        );
        package.fault = 0;
        assert!(target.is_dir());
        let bytes = directory_bytes(&target);
        let result = ActiveArchive::open(&target, later_pin);
        assert_eq!(result.is_ok(), fault >= 13);
        drop(result);
        assert!(package.restore_new(&mut base, &target).is_err());
        assert_eq!(directory_bytes(&target), bytes);
        let moved = d.path(&format!("released-{fault}"));
        fs::rename(&target, &moved).unwrap();
        fs::rename(&moved, &target).unwrap();
        if fault >= 13 {
            assert_eq!(bytes, original_later);
        }
    }
    // Full bytes seen before sync or after a lost acknowledgement are process
    // observations only; these hooks do not simulate actual physical power loss.
    package.verify(&mut base).unwrap();
    let good = d.path("explicit-new-target");
    assert_eq!(package.restore_new(&mut base, &good).unwrap(), later_pin);
    assert_eq!(directory_bytes(&good), original_later);
    assert_eq!(directory_bytes(&base_path), original_base);
    assert_eq!(directory_bytes(&later_path), original_later);
}

#[test]
fn final_pack_and_restored_target_changes_cannot_publish_success() {
    let d = Dir::new();
    for fault in 30..=32 {
        let base_path = d.path(&format!("base-{fault}"));
        let later_path = d.path(&format!("later-{fault}"));
        let base_pin = fixture(&base_path, 2, 0, DOMAIN);
        let later_pin = fixture(&later_path, 4, 0, DOMAIN);
        let mut before_base = directory_bytes(&base_path);
        let mut before_later = directory_bytes(&later_path);
        let mut expected = encode_fixture(
            base_pin,
            later_pin,
            &[(0, 300, 300)],
            &before_later[SEGMENT][300..],
        );
        let path = d.path(&format!("late-{fault}.incremental"));
        let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
        let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
        base.fault = fault;
        assert!(matches!(
            base.pack_incremental_new(&mut later, &path),
            Err(PoolError::Corrupt)
        ));
        match fault {
            30 => {
                before_base.insert(
                    ".incremental-package-base-fault".into(),
                    b"test-only late namespace change".to_vec(),
                );
            }
            31 => {
                before_later.insert(
                    ".incremental-package-later-fault".into(),
                    b"test-only late namespace change".to_vec(),
                );
            }
            32 => expected[0] ^= 1,
            _ => unreachable!(),
        }
        assert_eq!(directory_bytes(&base_path), before_base);
        assert_eq!(directory_bytes(&later_path), before_later);
        assert_eq!(fs::read(&path).unwrap(), expected);
    }
    for fault in [4, 5] {
        let base_path = d.path(&format!("base-{fault}"));
        let later_path = d.path(&format!("later-{fault}"));
        let base_pin = fixture(&base_path, 2, 0, DOMAIN);
        let later_pin = fixture(&later_path, 4, 0, DOMAIN);
        let original_base = directory_bytes(&base_path);
        let original_later = directory_bytes(&later_path);
        let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
        let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
        let path = d.path(&format!("complete-{fault}.incremental"));
        let mut package = base.pack_incremental_new(&mut later, &path).unwrap();
        package.fault = fault;
        let target = d.path(&format!("late-target-{fault}"));
        assert_eq!(
            package.restore_new(&mut base, &target),
            Err(PoolError::Corrupt)
        );
        let mut expected = original_later.clone();
        if fault == 4 {
            expected.insert(
                ".incremental-package-target-fault".into(),
                b"test-only late namespace change".to_vec(),
            );
        } else {
            *expected.get_mut(SEGMENT).unwrap().last_mut().unwrap() ^= 0x80;
        }
        assert_eq!(directory_bytes(&target), expected);
        assert!(ActiveArchive::open(&target, later_pin).is_err());
        package.fault = 0;
        package.verify(&mut base).unwrap();
        assert_eq!(directory_bytes(&base_path), original_base);
        assert_eq!(directory_bytes(&later_path), original_later);
    }
}

#[test]
fn shared_package_readers_keep_locks_until_last_drop_and_allow_sibling_restores() {
    let d = Dir::new();
    let base_path = d.path("base");
    let later_path = d.path("later");
    let base_pin = fixture(&base_path, 1, 0, DOMAIN);
    let later_pin = fixture(&later_path, 3, 0, DOMAIN);
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
    let path = d.path("package.incremental");
    let created = base.pack_incremental_new(&mut later, &path).unwrap();
    assert!(matches!(
        ActiveIncrementalPackage::open(&path, &mut base, later_pin),
        Err(PoolError::Locked)
    ));
    drop(created);
    let first = ActiveIncrementalPackage::open(&path, &mut base, later_pin).unwrap();
    let mut second = ActiveIncrementalPackage::open(&path, &mut base, later_pin).unwrap();
    let file = File::open(&path).unwrap();
    assert!(file.try_lock().is_err());
    drop(first);
    assert!(file.try_lock().is_err());
    let target = d.path("sibling-target");
    second.restore_new(&mut base, &target).unwrap();
    assert_eq!(directory_bytes(&target), directory_bytes(&later_path));
    second.verify(&mut base).unwrap();
    assert!(matches!(open_store(&base_path), Err(PoolError::Locked)));
    drop(second);
    file.try_lock().unwrap();
    drop(file);
    drop(base);
    open_store(&base_path).unwrap();
}

#[cfg(unix)]
#[test]
fn package_symlinks_hardlinks_name_replacement_and_parent_replacement_are_rejected() {
    use std::os::unix::fs::{symlink, MetadataExt};
    let d = Dir::new();
    let base_path = d.path("base");
    let later_path = d.path("later");
    let base_pin = fixture(&base_path, 1, 0, DOMAIN);
    let later_pin = fixture(&later_path, 3, 0, DOMAIN);
    let bytes = directory_bytes(&later_path);
    let raw = encode_fixture(
        base_pin,
        later_pin,
        &[(0, 150, 300)],
        &bytes[SEGMENT][150..],
    );
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    for kind in ["symlink", "hardlink", "replacement", "late-hardlink"] {
        let path = d.path(&format!("{kind}.incremental"));
        let other = d.path(&format!("other-{kind}.incremental"));
        fs::write(&path, &raw).unwrap();
        if kind == "symlink" || kind == "hardlink" {
            fs::rename(&path, &other).unwrap();
            if kind == "symlink" {
                symlink(&other, &path).unwrap();
            } else {
                fs::hard_link(&other, &path).unwrap();
            }
            assert!(ActiveIncrementalPackage::open(&path, &mut base, later_pin).is_err());
        } else {
            let mut package = ActiveIncrementalPackage::open(&path, &mut base, later_pin).unwrap();
            if kind == "replacement" {
                fs::rename(&path, &other).unwrap();
                fs::write(&path, &raw).unwrap();
            } else {
                fs::hard_link(&path, &other).unwrap();
                assert_eq!(fs::metadata(&path).unwrap().nlink(), 2);
            }
            assert_eq!(package.verify(&mut base), Err(PoolError::Corrupt));
            let target = d.path(&format!("must-not-create-{kind}"));
            assert!(package.restore_new(&mut base, &target).is_err());
            assert!(!target.exists());
        }
        assert_eq!(fs::read(&path).unwrap(), raw);
        assert_eq!(fs::read(&other).unwrap(), raw);
    }
    let parent = d.path("package-parent");
    fs::create_dir(&parent).unwrap();
    let path = parent.join("package.incremental");
    fs::write(&path, &raw).unwrap();
    let mut package = ActiveIncrementalPackage::open(&path, &mut base, later_pin).unwrap();
    let moved = d.path("old-package-parent");
    fs::rename(&parent, &moved).unwrap();
    fs::create_dir(&parent).unwrap();
    fs::write(&path, &raw).unwrap();
    assert_eq!(package.verify(&mut base), Err(PoolError::Corrupt));
    assert_eq!(fs::read(&path).unwrap(), raw);
    assert_eq!(fs::read(moved.join("package.incremental")).unwrap(), raw);
}

#[cfg(windows)]
#[test]
fn windows_retained_package_and_parent_names_cannot_be_deleted_or_renamed() {
    let d = Dir::new();
    let base_path = d.path("base");
    let later_path = d.path("later");
    let base_pin = fixture(&base_path, 1, 0, DOMAIN);
    let later_pin = fixture(&later_path, 3, 0, DOMAIN);
    let parent = d.path("package-parent");
    fs::create_dir(&parent).unwrap();
    let path = parent.join("package.incremental");
    let moved = d.path("moved-package.incremental");
    let moved_parent = d.path("moved-parent");
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
    drop(base.pack_incremental_new(&mut later, &path).unwrap());
    let first = ActiveIncrementalPackage::open(&path, &mut base, later_pin).unwrap();
    let mut second = ActiveIncrementalPackage::open(&path, &mut base, later_pin).unwrap();
    let probe = || {
        for error in [
            fs::rename(&path, &moved).unwrap_err(),
            fs::remove_file(&path).unwrap_err(),
            fs::rename(&parent, &moved_parent).unwrap_err(),
        ] {
            assert!(matches!(error.raw_os_error(), Some(5 | 32)), "{error}");
        }
        assert!(path.is_file());
        assert!(!moved.exists());
        assert!(!moved_parent.exists());
    };
    probe();
    drop(first);
    probe();
    second.verify(&mut base).unwrap();
    drop(second);
    fs::rename(&path, &moved).unwrap();
    fs::rename(&moved, &path).unwrap();
    fs::rename(&parent, &moved_parent).unwrap();
    fs::remove_file(moved_parent.join("package.incremental")).unwrap();
    fs::remove_dir(&moved_parent).unwrap();
}
