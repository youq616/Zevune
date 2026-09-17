//! These tests exercise physical bytes, offsets and file bounds only. Synthetic
//! frames never reach State/PoolStore and do not stand in for authorization.
use super::*;
use crate::pool::active::{MAX_FRAME_BYTES, MIN_FRAME_BYTES};
use rand::{rngs::OsRng, RngCore};
use std::fs::{self, OpenOptions};
use std::io::{Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-incremental-io-{suffix}"));
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

fn journal(path: &Path, lengths: &[u64]) -> (File, ActiveJournal) {
    let (genesis, mut journal) = ActiveJournal::create(path, &[0; 76]).unwrap();
    for (index, length) in lengths.iter().copied().enumerate() {
        assert!((MIN_FRAME_BYTES..=MAX_FRAME_BYTES).contains(&length));
        let mut frame = vec![u8::try_from(index + 1).unwrap(); usize::try_from(length).unwrap()];
        frame[..4].copy_from_slice(&u32::try_from(length - 36).unwrap().to_be_bytes());
        journal.append(&genesis, &frame).unwrap();
    }
    (genesis, journal)
}

#[test]
fn explicit_fill_handles_different_short_reads_and_interrupted_offsets() {
    let source: Vec<u8> = (0u8..100).collect();
    for chunk in [1, 3, 17] {
        let mut calls = 0usize;
        let mut offsets = Vec::new();
        let mut output = [0; 71];
        fill_at(&mut output, 13, |bytes, offset| {
            calls += 1;
            offsets.push(offset);
            if calls.is_multiple_of(3) {
                return Err(io::Error::from(io::ErrorKind::Interrupted));
            }
            let offset = usize::try_from(offset).unwrap();
            let take = bytes.len().min(chunk).min(source.len() - offset);
            bytes[..take].copy_from_slice(&source[offset..offset + take]);
            Ok(take)
        })
        .unwrap();
        assert_eq!(&output, &source[13..84]);
        assert!(offsets.windows(2).any(|pair| pair[0] == pair[1]));
        assert!(offsets.windows(2).all(|pair| pair[0] <= pair[1]));
    }
    assert_eq!(
        fill_at(&mut [0; 1], 0, |_, _| Ok(0)),
        Err(PoolError::Corrupt)
    );
    assert_eq!(
        fill_at(&mut [0; 1], 0, |_, _| Ok(2)),
        Err(PoolError::Corrupt)
    );
    assert_eq!(
        fill_at(&mut [0; 1], 0, |_, _| {
            Err(io::Error::from(io::ErrorKind::PermissionDenied))
        }),
        Err(PoolError::Storage)
    );
    assert_eq!(
        fill_at(&mut [0; 1], u64::MAX, |_, _| Ok(1)),
        Err(PoolError::Bounds)
    );
}

#[test]
fn physical_ranges_cover_empty_tail_growth_and_full_size_rotation() {
    let full = vec![
        MAX_FRAME_BYTES,
        MAX_FRAME_BYTES,
        SEGMENT_BYTES - 2 * MAX_FRAME_BYTES,
    ];
    let mut rotated = full.clone();
    rotated.push(MIN_FRAME_BYTES);
    let cases = [
        (vec![], vec![], vec![], 0),
        (vec![], vec![400], vec![(0, 0, 400)], 0),
        (vec![400], vec![400, 600], vec![(0, 400, 600)], 0),
        (full, rotated.clone(), vec![(1, 0, 150)], 1),
        (
            vec![MAX_FRAME_BYTES],
            rotated,
            vec![
                (
                    0,
                    u32::try_from(MAX_FRAME_BYTES).unwrap(),
                    u32::try_from(SEGMENT_BYTES - MAX_FRAME_BYTES).unwrap(),
                ),
                (1, 0, 150),
            ],
            0,
        ),
    ];
    let d = Dir::new();
    for (case, (base_frames, later_frames, expected, unchanged)) in cases.iter().enumerate() {
        let base_path = d.path(&format!("base-{case}"));
        let later_path = d.path(&format!("later-{case}"));
        let (base_genesis, base) = journal(&base_path, base_frames);
        let (later_genesis, later) = journal(&later_path, later_frames);
        let mut actual = Vec::new();
        assert_eq!(
            base.visit_append_ranges(
                &base_genesis,
                &later,
                &later_genesis,
                |index, offset, length| {
                    actual.push((index, offset, length));
                    Ok(())
                },
            )
            .unwrap(),
            *unchanged
        );
        assert_eq!(&actual, expected);
        let mut appended = Vec::new();
        for (index, offset, length) in actual {
            let bytes = fs::read(later_path.join(format!("{index:08}.journal"))).unwrap();
            let begin = usize::try_from(offset).unwrap();
            let end = begin + usize::try_from(length).unwrap();
            appended.extend_from_slice(&bytes[begin..end]);
        }
        assert_eq!(
            u64::try_from(appended.len()).unwrap(),
            later_frames.iter().sum::<u64>() - base_frames.iter().sum::<u64>()
        );
        assert_eq!(
            base.length() + u64::try_from(appended.len()).unwrap(),
            later.length()
        );
    }
}

#[test]
fn every_reused_byte_including_later_chunks_and_sealed_segments_is_compared() {
    let d = Dir::new();
    let full = [
        MAX_FRAME_BYTES,
        MAX_FRAME_BYTES,
        SEGMENT_BYTES - 2 * MAX_FRAME_BYTES,
        400,
    ];
    for (case, (index, offset)) in [(0, 65_537), (0, 1_048_575), (1, 399)]
        .into_iter()
        .enumerate()
    {
        let (base_genesis, base) = journal(&d.path(&format!("base-{case}")), &full);
        let later_path = d.path(&format!("later-{case}"));
        let mut longer = full.to_vec();
        longer.push(600);
        let (later_genesis, later) = journal(&later_path, &longer);
        let path = later_path.join(format!("{index:08}.journal"));
        let mut changed = fs::read(&path).unwrap();
        changed[offset] ^= 0x80;
        let mut outside = OpenOptions::new().write(true).open(&path).unwrap();
        outside.write_all(&changed).unwrap();
        outside.sync_all().unwrap();
        let mut visited = 0;
        assert_eq!(
            base.visit_append_ranges(&base_genesis, &later, &later_genesis, |_, _, _| {
                visited += 1;
                Ok(())
            }),
            Err(PoolError::Stale)
        );
        assert_eq!(visited, 0);
        assert_eq!(fs::read(path).unwrap(), changed);
    }
}

#[test]
fn physical_genesis_eof_and_retained_segment_lengths_fail_closed() {
    let d = Dir::new();
    let (base_genesis, base) = journal(&d.path("base"), &[400]);
    let (mut later_genesis, later) = journal(&d.path("different-genesis"), &[400, 600]);
    later_genesis.seek(SeekFrom::Start(75)).unwrap();
    later_genesis.write_all(&[1]).unwrap();
    later_genesis.sync_all().unwrap();
    assert_eq!(
        base.visit_append_ranges(&base_genesis, &later, &later_genesis, |_, _, _| Ok(())),
        Err(PoolError::Genesis)
    );
    for length in [399, 401] {
        let path = d.path(&format!("changed-length-{length}"));
        let (genesis, journal) = journal(&path, &[400]);
        let outside = OpenOptions::new()
            .write(true)
            .open(path.join("00000000.journal"))
            .unwrap();
        outside.set_len(length).unwrap();
        assert_eq!(
            base.visit_append_ranges(&base_genesis, &journal, &genesis, |_, _, _| Ok(())),
            Err(PoolError::Corrupt)
        );
        assert_eq!(outside.metadata().unwrap().len(), length);
    }
    let exact_path = d.path("exact-file");
    fs::write(&exact_path, [1; 5]).unwrap();
    let exact = File::open(exact_path).unwrap();
    assert_eq!(exact_file_end(&exact, 4), Err(PoolError::Corrupt));
    assert_eq!(exact_file_end(&exact, 6), Err(PoolError::Corrupt));
    exact_file_end(&exact, 5).unwrap();
}

#[test]
fn allocation_callback_failure_cannot_return_a_partial_physical_plan() {
    let d = Dir::new();
    let (base_genesis, base) = journal(&d.path("base"), &[400]);
    let (later_genesis, later) = journal(&d.path("later"), &[400, 600]);
    assert_eq!(
        base.visit_append_ranges(&base_genesis, &later, &later_genesis, |_, _, _| {
            Err(PoolError::Storage)
        }),
        Err(PoolError::Storage)
    );
    base.check(&base_genesis).unwrap();
    later.check(&later_genesis).unwrap();
}
