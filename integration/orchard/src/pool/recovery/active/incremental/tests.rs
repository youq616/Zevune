//! Public API tests with ordinarily committed empty blocks. Genuine payments,
//! production-size rotation and restored onward spends remain in active_flow_tests.
use super::*;
use crate::pool::{PoolStore, StorageProfile};
use rand::{rngs::OsRng, RngCore};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

const DOMAIN: [u8; 32] = [47; 32];
const SEGMENT: &str = "00000000.journal";
type DirectoryBytes = BTreeMap<String, Vec<u8>>;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let suffix: String = nonce.iter().map(|byte| format!("{byte:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-incremental-archive-{suffix}"));
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

fn fixture(path: &Path, height: u64, variant: u8, domain: [u8; 32]) -> ActiveRecoveryCheckpoint {
    let mut store =
        PoolStore::create_with_profile(path, &[], Some(domain), StorageProfile::ActiveSegmentsV1)
            .unwrap();
    for height in 1..=height {
        let mut id = [variant; 32];
        id[..8].copy_from_slice(&height.to_be_bytes());
        let prepared = store.prepare(height, id, &[]).unwrap();
        let expected = prepared.result().clone();
        assert_eq!(store.commit(prepared).unwrap(), expected);
    }
    store.active_recovery_checkpoint().unwrap()
}

// Fixtures have already dropped the exclusive writer. Archive shared locks
// permit these independent inspection reads on both native operating systems.
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

fn copy_directory(path: &Path, original: &DirectoryBytes) {
    fs::create_dir(path).unwrap();
    for (name, bytes) in original {
        fs::write(path.join(name), bytes).unwrap();
    }
}

fn overwrite(path: &Path, bytes: &[u8]) {
    let mut outside = OpenOptions::new().write(true).open(path).unwrap();
    outside.write_all(bytes).unwrap();
    outside.sync_all().unwrap();
}

// Called only by the private cfg(test) late-change injection. This simulates an
// uncooperative outside writer after both replays and the full prefix comparison.
// Its changed byte is retained on failure; production has no mutation branch.
pub(super) fn change_tail(path: &Path) -> Result<(), PoolError> {
    let mut outside = OpenOptions::new()
        .read(true)
        .write(true)
        .open(path.join(SEGMENT))
        .map_err(|_| PoolError::Storage)?;
    outside
        .seek(SeekFrom::End(-1))
        .map_err(|_| PoolError::Storage)?;
    let mut byte = [0];
    outside
        .read_exact(&mut byte)
        .map_err(|_| PoolError::Storage)?;
    byte[0] ^= 0x80;
    outside
        .seek(SeekFrom::End(-1))
        .map_err(|_| PoolError::Storage)?;
    outside.write_all(&byte).map_err(|_| PoolError::Storage)?;
    outside.sync_all().map_err(|_| PoolError::Storage)
}

#[test]
fn real_empty_commits_produce_exact_appended_bytes_and_immutable_checkpoints() {
    let d = Dir::new();
    for (base_height, height) in [(0, 0), (0, 3), (2, 2), (2, 5)] {
        let base_path = d.path(&format!("base-{base_height}-{height}"));
        let later_path = d.path(&format!("later-{base_height}-{height}"));
        let base_pin = fixture(&base_path, base_height, 0, DOMAIN);
        let later_pin = fixture(&later_path, height, 0, DOMAIN);
        let before_base = directory_bytes(&base_path);
        let before_later = directory_bytes(&later_path);
        let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
        let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
        let plan = base.incremental_plan(&mut later).unwrap();
        assert_eq!(plan.base_checkpoint(), base_pin);
        assert_eq!(plan.checkpoint(), later_pin);
        assert_eq!(plan.reused_bytes(), base_pin.length());
        assert_eq!(plan.appended_bytes(), (height - base_height) * 150);
        assert_eq!(
            plan.new_segment_count(),
            u32::from(base_height == 0 && height != 0)
        );
        assert_eq!(
            plan.unchanged_segment_count(),
            u32::from(base_height != 0 && base_height == height)
        );
        let mut expected = before_base.clone();
        if base_height == height {
            assert!(plan.ranges().is_empty());
        } else {
            assert_eq!(plan.ranges().len(), 1);
            let range = plan.ranges()[0];
            assert_eq!(range.segment_index(), 0);
            assert_eq!(u64::from(range.offset()), base_height * 150);
            assert_eq!(u64::from(range.length()), (height - base_height) * 150);
            let offset = usize::try_from(range.offset()).unwrap();
            let end = offset + usize::try_from(range.length()).unwrap();
            assert_eq!(end, before_later[SEGMENT].len());
            expected
                .entry(SEGMENT.into())
                .or_default()
                .extend_from_slice(&before_later[SEGMENT][offset..end]);
        }
        assert_eq!(expected, before_later);
        assert_eq!(base.incremental_plan(&mut later).unwrap(), plan);
        assert_eq!(directory_bytes(&base_path), before_base);
        assert_eq!(directory_bytes(&later_path), before_later);
    }
}

#[test]
fn same_path_and_distinct_copy_empty_plans_keep_shared_locks_until_drop() {
    let d = Dir::new();
    let path = d.path("source");
    let pin = fixture(&path, 3, 0, DOMAIN);
    let original = directory_bytes(&path);
    let copied_path = d.path("copy");
    copy_directory(&copied_path, &original);
    let mut first = ActiveArchive::open(&path, pin).unwrap();
    let mut second = ActiveArchive::open(&path, pin).unwrap();
    let mut copy = ActiveArchive::open(&copied_path, pin).unwrap();
    let same = first.incremental_plan(&mut second).unwrap();
    assert_eq!(same, first.incremental_plan(&mut copy).unwrap());
    assert_eq!(same.reused_bytes(), pin.length());
    assert_eq!(same.appended_bytes(), 0);
    assert_eq!(same.unchanged_segment_count(), 1);
    assert_eq!(same.new_segment_count(), 0);
    assert!(same.ranges().is_empty());
    assert!(matches!(
        PoolStore::open_with_profile(&path, &[], Some(DOMAIN), StorageProfile::ActiveSegmentsV1),
        Err(PoolError::Locked)
    ));
    drop(first);
    assert!(matches!(
        PoolStore::open_with_profile(&path, &[], Some(DOMAIN), StorageProfile::ActiveSegmentsV1),
        Err(PoolError::Locked)
    ));
    drop(second);
    let mut writer =
        PoolStore::open_with_profile(&path, &[], Some(DOMAIN), StorageProfile::ActiveSegmentsV1)
            .unwrap();
    assert_eq!(writer.active_recovery_checkpoint().unwrap(), pin);
    drop(writer);
    assert_eq!(directory_bytes(&path), original);
    assert_eq!(directory_bytes(&copied_path), original);
}

#[test]
fn separately_verified_same_height_and_higher_forks_and_rollback_are_stale() {
    let d = Dir::new();
    let base_path = d.path("base");
    let base_pin = fixture(&base_path, 2, 0, DOMAIN);
    let original = directory_bytes(&base_path);
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    for (label, height, variant) in [
        ("same-height-fork", 2, 11),
        ("higher-fork", 4, 11),
        ("rollback", 1, 0),
    ] {
        let path = d.path(label);
        let pin = fixture(&path, height, variant, DOMAIN);
        let bytes = directory_bytes(&path);
        let mut other = ActiveArchive::open(&path, pin).unwrap();
        base.verify().unwrap();
        other.verify().unwrap();
        assert_eq!(base_pin.genesis, pin.genesis);
        if height > base_pin.height() {
            // Both pins and complete histories pass independently, and the
            // growth metadata clears every early relation check. This reaches
            // the actual retained-byte prefix comparison, not a stale hash.
            assert!(pin.length() > base_pin.length());
            assert!(pin.segment_count() >= base_pin.segment_count());
            assert_eq!(
                base.journal.visit_append_ranges(
                    &base.file,
                    &other.journal,
                    &other.file,
                    |_, _, _| Ok(()),
                ),
                Err(PoolError::Stale)
            );
        }
        assert_eq!(base.incremental_plan(&mut other), Err(PoolError::Stale));
        assert_eq!(directory_bytes(&path), bytes);
        assert_eq!(directory_bytes(&base_path), original);
    }
}

#[test]
fn wrong_network_legacy_and_wrong_pin_are_rejected_without_changes() {
    let d = Dir::new();
    let base_path = d.path("base");
    let other_path = d.path("other-network");
    let base_pin = fixture(&base_path, 2, 0, DOMAIN);
    let other_pin = fixture(&other_path, 3, 0, [48; 32]);
    let base_bytes = directory_bytes(&base_path);
    let other_bytes = directory_bytes(&other_path);
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    let mut other = ActiveArchive::open(&other_path, other_pin).unwrap();
    base.verify().unwrap();
    other.verify().unwrap();
    assert_eq!(base.incremental_plan(&mut other), Err(PoolError::Genesis));
    let mut wrong_pin = base_pin;
    wrong_pin.app_hash[0] ^= 1;
    assert!(matches!(
        ActiveArchive::open(&base_path, wrong_pin),
        Err(PoolError::Stale)
    ));
    wrong_pin = base_pin;
    wrong_pin.layout_hash[0] ^= 1;
    assert!(matches!(
        ActiveArchive::open(&base_path, wrong_pin),
        Err(PoolError::Corrupt)
    ));
    let legacy_path = d.path("legacy");
    let mut legacy = PoolStore::create(&legacy_path).unwrap();
    let old_pin = legacy.recovery_checkpoint().unwrap();
    drop(legacy);
    let legacy_bytes = fs::read(&legacy_path).unwrap();
    assert_eq!(
        ActiveRecoveryCheckpoint::from_bytes(&old_pin.to_bytes()),
        Err(PoolError::Bounds)
    );
    assert!(ActiveArchive::open(&legacy_path, base_pin).is_err());
    assert_eq!(fs::read(&legacy_path).unwrap(), legacy_bytes);
    assert_eq!(directory_bytes(&base_path), base_bytes);
    assert_eq!(directory_bytes(&other_path), other_bytes);
}

#[test]
fn every_call_rechecks_both_open_archives_after_successful_planning() {
    let d = Dir::new();
    for change_base in [false, true] {
        for mode in ["namespace", "same-length", "truncate", "append"] {
            let base_path = d.path(&format!("base-{change_base}-{mode}"));
            let later_path = d.path(&format!("later-{change_base}-{mode}"));
            let base_pin = fixture(&base_path, 2, 0, DOMAIN);
            let later_pin = fixture(&later_path, 4, 0, DOMAIN);
            let original_base = directory_bytes(&base_path);
            let original_later = directory_bytes(&later_path);
            let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
            let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
            base.incremental_plan(&mut later).unwrap();
            let changed_path = if change_base { &base_path } else { &later_path };
            match mode {
                "namespace" => {
                    fs::write(changed_path.join("unexpected"), b"retain outside entry").unwrap();
                }
                "same-length" => change_tail(changed_path).unwrap(),
                "truncate" => {
                    let outside = OpenOptions::new()
                        .write(true)
                        .open(changed_path.join(SEGMENT))
                        .unwrap();
                    outside
                        .set_len(outside.metadata().unwrap().len() - 1)
                        .unwrap();
                }
                "append" => {
                    let mut outside = OpenOptions::new()
                        .append(true)
                        .open(changed_path.join(SEGMENT))
                        .unwrap();
                    outside.write_all(&[0]).unwrap();
                    outside.sync_all().unwrap();
                }
                _ => unreachable!(),
            }
            let changed = directory_bytes(changed_path);
            assert_eq!(base.incremental_plan(&mut later), Err(PoolError::Corrupt));
            assert_eq!(directory_bytes(changed_path), changed);
            assert_eq!(
                directory_bytes(if change_base { &later_path } else { &base_path }),
                if change_base { original_later } else { original_base }
            );
        }
    }
}

#[test]
fn same_length_valid_replacement_after_open_cannot_reuse_an_old_success() {
    let d = Dir::new();
    for change_base in [false, true] {
        let base_path = d.path(&format!("base-{change_base}"));
        let later_path = d.path(&format!("later-{change_base}"));
        let base_pin = fixture(&base_path, 2, 0, DOMAIN);
        let later_pin = fixture(&later_path, 4, 0, DOMAIN);
        let replacement_path = d.path(&format!("valid-replacement-{change_base}"));
        let replacement_pin = fixture(
            &replacement_path,
            if change_base { 2 } else { 4 },
            19,
            DOMAIN,
        );
        ActiveArchive::open(&replacement_path, replacement_pin)
            .unwrap()
            .verify()
            .unwrap();
        let replacement = directory_bytes(&replacement_path);
        let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
        let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
        base.incremental_plan(&mut later).unwrap();
        let path = if change_base { &base_path } else { &later_path };
        let original = directory_bytes(path);
        assert_eq!(original[SEGMENT].len(), replacement[SEGMENT].len());
        assert_ne!(original[SEGMENT], replacement[SEGMENT]);
        overwrite(&path.join(SEGMENT), &replacement[SEGMENT]);
        let replaced = directory_bytes(path);
        assert_eq!(replaced, replacement);
        assert_eq!(base.incremental_plan(&mut later), Err(PoolError::Corrupt));
        assert_eq!(directory_bytes(path), replaced);
    }
}

#[test]
fn final_full_digest_and_namespace_checks_reject_late_outside_modifications() {
    let d = Dir::new();
    for fault in 7..=10 {
        let base_path = d.path(&format!("base-{fault}"));
        let later_path = d.path(&format!("later-{fault}"));
        let base_pin = fixture(&base_path, 2, 0, DOMAIN);
        let later_pin = fixture(&later_path, 4, 0, DOMAIN);
        let base_bytes = directory_bytes(&base_path);
        let later_bytes = directory_bytes(&later_path);
        let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
        let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
        base.incremental_plan(&mut later).unwrap();
        if fault == 7 || fault == 9 {
            base.fault = fault;
        } else {
            later.fault = fault;
        }
        assert_eq!(base.incremental_plan(&mut later), Err(PoolError::Corrupt));
        let mut expected_base = base_bytes;
        let mut expected_later = later_bytes;
        match fault {
            7 => {
                expected_base.insert(
                    ".incremental-base-fault".into(),
                    b"test-only late namespace change".to_vec(),
                );
            }
            8 => {
                expected_later.insert(
                    ".incremental-later-fault".into(),
                    b"test-only late namespace change".to_vec(),
                );
            }
            9 => {
                *expected_base.get_mut(SEGMENT).unwrap().last_mut().unwrap() ^= 0x80;
            }
            10 => {
                *expected_later.get_mut(SEGMENT).unwrap().last_mut().unwrap() ^= 0x80;
            }
            _ => unreachable!(),
        }
        assert_eq!(directory_bytes(&base_path), expected_base);
        assert_eq!(directory_bytes(&later_path), expected_later);
    }
}

#[cfg(unix)]
#[test]
fn retained_name_replacement_and_new_hard_link_reject_without_repair() {
    let d = Dir::new();
    for change_base in [false, true] {
        for mode in ["replacement", "hard-link"] {
            let base_path = d.path(&format!("base-{change_base}-{mode}"));
            let later_path = d.path(&format!("later-{change_base}-{mode}"));
            let base_pin = fixture(&base_path, 2, 0, DOMAIN);
            let later_pin = fixture(&later_path, 4, 0, DOMAIN);
            let base_bytes = directory_bytes(&base_path);
            let later_bytes = directory_bytes(&later_path);
            let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
            let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
            base.incremental_plan(&mut later).unwrap();
            let path = if change_base { &base_path } else { &later_path };
            let alias = d.path(&format!("outside-{change_base}-{mode}"));
            if mode == "replacement" {
                fs::rename(path.join(SEGMENT), &alias).unwrap();
                fs::copy(&alias, path.join(SEGMENT)).unwrap();
            } else {
                fs::hard_link(path.join(SEGMENT), &alias).unwrap();
            }
            assert_eq!(base.incremental_plan(&mut later), Err(PoolError::Corrupt));
            assert_eq!(directory_bytes(&base_path), base_bytes);
            assert_eq!(directory_bytes(&later_path), later_bytes);
            assert_eq!(fs::read(alias).unwrap(), fs::read(path.join(SEGMENT)).unwrap());
        }
    }
}

#[cfg(windows)]
#[test]
fn windows_planning_keeps_both_retained_names_protected_until_drop() {
    let d = Dir::new();
    let base_path = d.path("base");
    let later_path = d.path("later");
    let base_pin = fixture(&base_path, 2, 0, DOMAIN);
    let later_pin = fixture(&later_path, 4, 0, DOMAIN);
    let original_base = directory_bytes(&base_path);
    let original_later = directory_bytes(&later_path);
    let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
    let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
    base.incremental_plan(&mut later).unwrap();
    for (label, path) in [("base", &base_path), ("later", &later_path)] {
        let error = fs::rename(path.join(SEGMENT), d.path(&format!("moved-{label}"))).unwrap_err();
        assert!(matches!(error.raw_os_error(), Some(5 | 32)), "{error}");
    }
    base.incremental_plan(&mut later).unwrap();
    drop(base);
    drop(later);
    assert_eq!(directory_bytes(&base_path), original_base);
    assert_eq!(directory_bytes(&later_path), original_later);
    fs::rename(base_path.join(SEGMENT), d.path("moved-base-after-drop")).unwrap();
    fs::rename(later_path.join(SEGMENT), d.path("moved-later-after-drop")).unwrap();
}

#[cfg(unix)]
#[test]
fn missing_and_symlinked_retained_segments_fail_without_recreating_entries() {
    use std::os::unix::fs::symlink;
    let d = Dir::new();
    for change_base in [false, true] {
        for linked in [false, true] {
            let base_path = d.path(&format!("base-{change_base}-{linked}"));
            let later_path = d.path(&format!("later-{change_base}-{linked}"));
            let base_pin = fixture(&base_path, 2, 0, DOMAIN);
            let later_pin = fixture(&later_path, 4, 0, DOMAIN);
            let mut base = ActiveArchive::open(&base_path, base_pin).unwrap();
            let mut later = ActiveArchive::open(&later_path, later_pin).unwrap();
            base.incremental_plan(&mut later).unwrap();
            let path = if change_base { &base_path } else { &later_path };
            let original = directory_bytes(path);
            let outside = d.path(&format!("moved-{change_base}-{linked}"));
            fs::rename(path.join(SEGMENT), &outside).unwrap();
            if linked {
                symlink(&outside, path.join(SEGMENT)).unwrap();
            }
            assert_eq!(base.incremental_plan(&mut later), Err(PoolError::Corrupt));
            assert_eq!(fs::read(&outside).unwrap(), original[SEGMENT]);
            assert_eq!(fs::read(path.join("genesis")).unwrap(), original["genesis"]);
            if linked {
                assert!(fs::symlink_metadata(path.join(SEGMENT))
                    .unwrap()
                    .file_type()
                    .is_symlink());
                assert_eq!(fs::read_link(path.join(SEGMENT)).unwrap(), outside);
                assert_eq!(fs::read_dir(path).unwrap().count(), 2);
            } else {
                assert!(!path.join(SEGMENT).exists());
                assert_eq!(fs::read_dir(path).unwrap().count(), 1);
            }
        }
    }
}
