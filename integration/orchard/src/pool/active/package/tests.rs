//! Physical transport tests only. The synthetic headers/frames here never enter
//! State or PoolStore and do not represent genuine authorization or recovery.
use super::*;
use crate::pool::active::MAX_FRAME_BYTES;
use rand::{rngs::OsRng, RngCore};
use std::collections::BTreeMap;

struct Dir(PathBuf);

impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-package-physical-{suffix}"));
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

fn ranges(
    base: &ActiveJournal,
    genesis: &File,
    later: &ActiveJournal,
    later_genesis: &File,
) -> Vec<RangeSpec> {
    let mut ranges = Vec::new();
    base.visit_append_ranges(genesis, later, later_genesis, |index, offset, length| {
        ranges.push(RangeSpec {
            segment_index: index,
            offset,
            length,
        });
        Ok(())
    })
    .unwrap();
    ranges
}

fn metadata(ranges: &[RangeSpec]) -> Vec<u8> {
    // Deliberately not valid pins. Only the higher recovery layer interprets
    // them; these independently encoded bytes test the physical transport.
    let mut raw = vec![0; FIXED_BYTES];
    raw[..8].copy_from_slice(b"ZVAIPK01");
    raw[264..268].copy_from_slice(&u32::try_from(ranges.len()).unwrap().to_be_bytes());
    for range in ranges {
        raw.extend_from_slice(&range.segment_index.to_be_bytes());
        raw.extend_from_slice(&range.offset.to_be_bytes());
        raw.extend_from_slice(&range.length.to_be_bytes());
    }
    raw
}

fn logical(journal: &ActiveJournal, genesis: &File) -> Vec<u8> {
    let mut raw = Vec::new();
    journal
        .reader(genesis)
        .unwrap()
        .read_to_end(&mut raw)
        .unwrap();
    raw
}

fn package_bytes(package: &RetainedPackage) -> Vec<u8> {
    let mut raw = vec![0; usize::try_from(package.length()).unwrap()];
    package.read_exact_at(&mut raw, 0).unwrap();
    raw
}

fn file_bytes(file: &File, length: u64) -> Vec<u8> {
    let mut raw = vec![0; usize::try_from(length).unwrap()];
    fill_at(&mut raw, 0, |bytes, offset| read_at(file, bytes, offset)).unwrap();
    raw
}

fn output_bytes(path: &Path) -> BTreeMap<String, Vec<u8>> {
    fs::read_dir(path)
        .unwrap()
        .map(|entry| {
            let entry = entry.unwrap();
            (
                entry.file_name().into_string().unwrap(),
                fs::read(entry.path()).unwrap(),
            )
        })
        .collect()
}

#[test]
fn checked_io_retries_short_reads_writes_and_interruptions_without_skipping_bytes() {
    let source: Vec<u8> = (0u8..100).collect();
    for chunk in [1, 3, 17] {
        let mut calls = 0usize;
        let mut offsets = Vec::new();
        let mut output = [0; 71];
        fill_at(&mut output, 13, |bytes, offset| {
            calls += 1;
            offsets.push(offset);
            if calls.is_multiple_of(3) {
                return Err(io::ErrorKind::Interrupted.into());
            }
            let offset = usize::try_from(offset).unwrap();
            let take = bytes.len().min(chunk).min(source.len() - offset);
            bytes[..take].copy_from_slice(&source[offset..offset + take]);
            Ok(take)
        })
        .unwrap();
        assert_eq!(&output, &source[13..84]);
        assert!(offsets.windows(2).all(|pair| pair[0] <= pair[1]));
        assert!(offsets.windows(2).any(|pair| pair[0] == pair[1]));
    }
    assert_eq!(fill_at(&mut [0], 0, |_, _| Ok(0)), Err(PoolError::Corrupt));
    assert_eq!(fill_at(&mut [0], 0, |_, _| Ok(2)), Err(PoolError::Corrupt));
    assert_eq!(
        fill_at(&mut [0], u64::MAX, |_, _| Ok(1)),
        Err(PoolError::Bounds)
    );
    let mut partial = [0; 10];
    assert_eq!(
        fill_at(&mut partial, 0, |bytes, offset| {
            if offset != 0 {
                return Err(io::ErrorKind::PermissionDenied.into());
            }
            bytes[..5].copy_from_slice(&[7; 5]);
            Ok(5)
        }),
        Err(PoolError::Storage)
    );
    assert_eq!(partial, [7, 7, 7, 7, 7, 0, 0, 0, 0, 0]);

    struct Writer {
        raw: Vec<u8>,
        calls: usize,
        chunk: usize,
        limit: usize,
        fault: u8,
    }
    impl Write for Writer {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.calls += 1;
            if self.calls.is_multiple_of(3) {
                return Err(io::ErrorKind::Interrupted.into());
            }
            match self.fault {
                1 => return Ok(0),
                2 => return Ok(bytes.len() + 1),
                _ => {}
            }
            if self.raw.len() >= self.limit {
                return Err(io::ErrorKind::PermissionDenied.into());
            }
            let count = bytes.len().min(self.chunk).min(self.limit - self.raw.len());
            self.raw.extend_from_slice(&bytes[..count]);
            Ok(count)
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    for chunk in [1, 3, 17] {
        let mut writer = Writer {
            raw: Vec::new(),
            calls: 0,
            chunk,
            limit: usize::MAX,
            fault: 0,
        };
        write_all_checked(&mut writer, &source).unwrap();
        assert_eq!(writer.raw, source);
        assert!(writer.calls > source.len().div_ceil(chunk));
    }
    for (fault, limit, error, retained) in [
        (1, usize::MAX, PoolError::Storage, 0),
        (2, usize::MAX, PoolError::Corrupt, 0),
        (0, 23, PoolError::Storage, 23),
    ] {
        let mut writer = Writer {
            raw: Vec::new(),
            calls: 0,
            chunk: 7,
            limit,
            fault,
        };
        assert_eq!(write_all_checked(&mut writer, &source), Err(error));
        assert_eq!(writer.raw, source[..retained]);
    }
}

#[test]
fn transport_view_and_original_creation_handles_preserve_exact_physical_layouts() {
    let full = vec![
        MAX_FRAME_BYTES,
        MAX_FRAME_BYTES,
        SEGMENT_BYTES - 2 * MAX_FRAME_BYTES,
    ];
    let mut multiple = full.clone();
    multiple.extend_from_slice(&full);
    multiple.extend_from_slice(&full);
    multiple.push(150);
    let cases = [
        (vec![], vec![]),
        (vec![], vec![400]),
        (vec![400], vec![400, 65_700]),
        (full, multiple.clone()),
        (vec![MAX_FRAME_BYTES], multiple),
    ];
    let d = Dir::new();
    for (index, (base_frames, later_frames)) in cases.iter().enumerate() {
        let base_path = d.path(&format!("base-{index}"));
        let later_path = d.path(&format!("later-{index}"));
        let (base_genesis, base) = journal(&base_path, base_frames);
        let (later_genesis, later) = journal(&later_path, later_frames);
        let before_base = logical(&base, &base_genesis);
        let expected = logical(&later, &later_genesis);
        let ranges = ranges(&base, &base_genesis, &later, &later_genesis);
        if index >= 3 {
            let mut exact = Vec::new();
            if index == 4 {
                exact.push(RangeSpec {
                    segment_index: 0,
                    offset: MAX_FRAME_BYTES as u32,
                    length: (SEGMENT_BYTES - MAX_FRAME_BYTES) as u32,
                });
            }
            exact.extend_from_slice(&[
                RangeSpec {
                    segment_index: 1,
                    offset: 0,
                    length: SEGMENT_BYTES as u32,
                },
                RangeSpec {
                    segment_index: 2,
                    offset: 0,
                    length: SEGMENT_BYTES as u32,
                },
                RangeSpec {
                    segment_index: 3,
                    offset: 0,
                    length: 150,
                },
            ]);
            assert_eq!(ranges, exact);
        }
        let metadata = metadata(&ranges);
        let package_path = d.path(&format!("package-{index}"));
        let target = NewTarget::prepare(&package_path, &[&base_path, &later_path]).unwrap();
        let package =
            RetainedPackage::create_new(target, &metadata, &ranges, &later, &later_genesis)
                .unwrap();
        let mut encoded = metadata.clone();
        for range in &ranges {
            let segment = &later.segments[range.segment_index as usize];
            let mut bytes = vec![0; range.length as usize];
            fill_at(&mut bytes, u64::from(range.offset), |bytes, offset| {
                read_at(&segment.file, bytes, offset)
            })
            .unwrap();
            encoded.extend_from_slice(&bytes);
        }
        assert_eq!(package_bytes(&package), encoded);
        assert_eq!(
            package.length(),
            metadata.len() as u64 + later.length() - base.length()
        );
        let joined = JoinedJournal::new(
            &base,
            &base_genesis,
            &package,
            &metadata,
            &ranges,
            later.capacity().1,
            later.length(),
        )
        .unwrap();
        assert_eq!(
            joined.layout_hash().unwrap(),
            later.layout_hash(&later_genesis).unwrap()
        );
        let mut reader = joined.reader().unwrap();
        let mut actual = Vec::new();
        let mut buffer = [0; 8191];
        loop {
            let count = reader.read(&mut buffer).unwrap();
            if count == 0 {
                break;
            }
            actual.extend_from_slice(&buffer[..count]);
        }
        assert_eq!(actual, expected);
        assert_eq!(reader.read(&mut [0]).unwrap(), 0);
        let mut start = 76;
        for length in later_frames {
            joined.validate_frame(start, start + length).unwrap();
            start += length;
        }
        assert_eq!(start, later.length());
        fs::write(d.path(&format!("allowed-sibling-{index}")), b"unrelated").unwrap();
        package.check().unwrap();
        let restored_path = d.path(&format!("restored-{index}"));
        let output = NewTarget::prepare(&restored_path, &[&base_path]).unwrap();
        let (restored_genesis, restored) = joined.copy_new(&output).unwrap();
        assert_eq!(
            file_bytes(&restored_genesis, restored.header_length),
            file_bytes(&later_genesis, later.header_length)
        );
        for (index, segment) in restored.segments.iter().enumerate() {
            assert_eq!(segment.length, later.segments[index].length);
            assert_eq!(
                file_bytes(&segment.file, segment.length),
                file_bytes(&later.segments[index].file, later.segments[index].length)
            );
        }
        assert_eq!(logical(&restored, &restored_genesis), expected);
        assert_eq!(
            restored.layout_hash(&restored_genesis).unwrap(),
            joined.layout_hash().unwrap()
        );
        assert!(matches!(
            ActiveJournal::open(&restored_path, &[0; 76]),
            Err(PoolError::Locked)
        ));
        assert!(NewTarget::prepare(&restored_path, &[]).is_err());
        assert!(NewTarget::prepare(&package_path, &[]).is_err());
        assert_eq!(logical(&base, &base_genesis), before_base);
        assert_eq!(logical(&later, &later_genesis), expected);
        assert_eq!(package_bytes(&package), encoded);
        drop(restored);
        drop(restored_genesis);
        let (genesis_again, restored_again) =
            ActiveJournal::open(&restored_path, &[0; 76]).unwrap();
        assert_eq!(logical(&restored_again, &genesis_again), expected);
        drop(joined);
        drop(package);
        let reopened = RetainedPackage::open(&package_path).unwrap();
        assert_eq!(package_bytes(&reopened), encoded);
    }
}

#[test]
fn low_level_shape_binds_real_tail_and_source_range_end_before_creating_output() {
    let d = Dir::new();
    let (base_genesis, base) = journal(&d.path("base"), &[400]);
    let (later_genesis, later) = journal(&d.path("later"), &[400, 600]);
    let ranges = ranges(&base, &base_genesis, &later, &later_genesis);
    let metadata = metadata(&ranges);
    let target = NewTarget::prepare(&d.path("package"), &[]).unwrap();
    let package =
        RetainedPackage::create_new(target, &metadata, &ranges, &later, &later_genesis).unwrap();
    for (index, offset, length) in [
        (0, 399, 600),
        (0, 401, 600),
        (0, 0, 600),
        (1, 0, 600),
        (0, 400, 0),
    ] {
        let changed = [RangeSpec {
            segment_index: index,
            offset,
            length,
        }];
        assert!(JoinedJournal::new(
            &base,
            &base_genesis,
            &package,
            &metadata,
            &changed,
            1,
            later.length(),
        )
        .is_err());
        let path = d.path(&format!("must-not-create-{index}-{offset}-{length}"));
        let target = NewTarget::prepare(&path, &[]).unwrap();
        assert!(
            RetainedPackage::create_new(target, &metadata, &changed, &later, &later_genesis)
                .is_err()
        );
        assert!(!path.exists());
    }
    for count in [0, 2, MAX_SEGMENTS as u32 + 1] {
        assert!(JoinedJournal::new(
            &base,
            &base_genesis,
            &package,
            &metadata,
            &ranges,
            count,
            later.length(),
        )
        .is_err());
    }
    assert_eq!(metadata_length(MAX_SEGMENTS).unwrap(), 24844);
    assert_eq!(metadata_length(MAX_SEGMENTS + 1), Err(PoolError::Bounds));
    assert_eq!(metadata_length(usize::MAX), Err(PoolError::Bounds));
    assert_eq!(package_bytes(&package)[..metadata.len()], metadata);
}

#[test]
fn mutations_are_detected_and_a_failed_joined_reader_cannot_resume() {
    let d = Dir::new();
    let (base_genesis, base) = journal(&d.path("base"), &[400]);
    let (later_genesis, later) = journal(&d.path("later"), &[400, 70_000]);
    let ranges = ranges(&base, &base_genesis, &later, &later_genesis);
    let metadata = metadata(&ranges);
    for mode in ["metadata", "payload", "truncated", "extra"] {
        let target = NewTarget::prepare(&d.path(mode), &[]).unwrap();
        let package =
            RetainedPackage::create_new(target, &metadata, &ranges, &later, &later_genesis)
                .unwrap();
        let joined = JoinedJournal::new(
            &base,
            &base_genesis,
            &package,
            &metadata,
            &ranges,
            1,
            later.length(),
        )
        .unwrap();
        let before = joined.layout_hash().unwrap();
        match mode {
            "metadata" => {
                package.fault_change_byte(0).unwrap();
                assert!(joined.check().is_err());
                assert!(joined.layout_hash().is_err());
                assert!(joined.reader().is_err());
            }
            "payload" => {
                package.fault_change_byte(package.length() - 1).unwrap();
                // A length/identity check is not payload authentication. The
                // actual changed layout must fail the higher trusted-pin check.
                assert_ne!(joined.layout_hash().unwrap(), before);
            }
            "truncated" => {
                let mut reader = joined.reader().unwrap();
                let mut prefix = [0; 476];
                reader.read_exact(&mut prefix).unwrap();
                package.file.set_len(metadata.len() as u64 + 5).unwrap();
                let mut remainder = Vec::new();
                assert!(reader.read_to_end(&mut remainder).is_err());
                assert_eq!(remainder.len(), 5);
                assert!(joined.check().is_err());
                package.file.set_len(package.length()).unwrap();
                assert!(reader.read(&mut [0]).is_err());
                assert!(reader.read(&mut []).is_err());
                assert_ne!(joined.layout_hash().unwrap(), before);
            }
            "extra" => {
                package.file.set_len(package.length() + 1).unwrap();
                assert!(package.check().is_err());
                assert!(joined.layout_hash().is_err());
            }
            _ => unreachable!(),
        }
    }
}

#[test]
fn interrupted_package_writes_retain_partial_or_complete_new_files_without_retry() {
    let d = Dir::new();
    let (base_genesis, base) = journal(&d.path("base"), &[400]);
    let (later_genesis, later) = journal(&d.path("later"), &[400, 600]);
    let before_base = logical(&base, &base_genesis);
    let before_later = logical(&later, &later_genesis);
    let ranges = ranges(&base, &base_genesis, &later, &later_genesis);
    let metadata = metadata(&ranges);
    let good = RetainedPackage::create_new(
        NewTarget::prepare(&d.path("good"), &[]).unwrap(),
        &metadata,
        &ranges,
        &later,
        &later_genesis,
    )
    .unwrap();
    let expected = package_bytes(&good);
    for fault in 1..=4 {
        let path = d.path(&format!("fault-{fault}"));
        let mut target = NewTarget::prepare(&path, &[]).unwrap();
        target.fault = fault;
        assert!(matches!(
            RetainedPackage::create_new(target, &metadata, &ranges, &later, &later_genesis),
            Err(PoolError::Storage)
        ));
        let retained = fs::read(&path).unwrap();
        let length = match fault {
            1 => metadata.len() / 2,
            2 => metadata.len() + 300,
            _ => expected.len(),
        };
        assert_eq!(retained, expected[..length]);
        assert!(NewTarget::prepare(&path, &[]).is_err());
        assert_eq!(fs::read(&path).unwrap(), retained);
        if fault >= 3 {
            let package = RetainedPackage::open(&path).unwrap();
            let joined = JoinedJournal::new(
                &base,
                &base_genesis,
                &package,
                &metadata,
                &ranges,
                1,
                later.length(),
            )
            .unwrap();
            assert_eq!(
                joined.layout_hash().unwrap(),
                later.layout_hash(&later_genesis).unwrap()
            );
        }
    }
    assert_eq!(logical(&base, &base_genesis), before_base);
    assert_eq!(logical(&later, &later_genesis), before_later);
}

#[test]
fn interrupted_reconstruction_keeps_created_files_and_never_overwrites_them() {
    let d = Dir::new();
    let (base_genesis, base) = journal(&d.path("base"), &[400]);
    let (later_genesis, later) = journal(&d.path("later"), &[400, 600]);
    let before_base = logical(&base, &base_genesis);
    let before_later = logical(&later, &later_genesis);
    let ranges = ranges(&base, &base_genesis, &later, &later_genesis);
    let metadata = metadata(&ranges);
    let package = RetainedPackage::create_new(
        NewTarget::prepare(&d.path("package"), &[]).unwrap(),
        &metadata,
        &ranges,
        &later,
        &later_genesis,
    )
    .unwrap();
    let before_package = package_bytes(&package);
    let joined = JoinedJournal::new(
        &base,
        &base_genesis,
        &package,
        &metadata,
        &ranges,
        1,
        later.length(),
    )
    .unwrap();
    for fault in 11..=14 {
        let path = d.path(&format!("fault-{fault}"));
        let mut target = NewTarget::prepare(&path, &[]).unwrap();
        target.fault = fault;
        assert!(matches!(joined.copy_new(&target), Err(PoolError::Storage)));
        let retained = output_bytes(&path);
        assert_eq!(retained[GENESIS].len(), if fault == 11 { 38 } else { 76 });
        if fault == 11 {
            assert_eq!(retained.len(), 1);
        } else {
            assert_eq!(retained.len(), 2);
            assert_eq!(
                retained[&name(0)].len(),
                if fault == 12 { 200 } else { 1000 }
            );
        }
        assert!(joined.copy_new(&target).is_err());
        assert_eq!(output_bytes(&path), retained);
        if fault >= 13 {
            let (genesis, restored) = ActiveJournal::open(&path, &[0; 76]).unwrap();
            assert_eq!(logical(&restored, &genesis), before_later);
            assert_eq!(
                restored.layout_hash(&genesis).unwrap(),
                joined.layout_hash().unwrap()
            );
        }
    }
    assert_eq!(logical(&base, &base_genesis), before_base);
    assert_eq!(logical(&later, &later_genesis), before_later);
    assert_eq!(package_bytes(&package), before_package);
}

#[cfg(unix)]
#[test]
fn prepared_parent_replacement_is_rejected_before_any_output_creation() {
    let d = Dir::new();
    let parent = d.path("parent");
    let moved = d.path("moved");
    fs::create_dir(&parent).unwrap();
    let target = NewTarget::prepare(&parent.join("package"), &[]).unwrap();
    fs::rename(&parent, &moved).unwrap();
    fs::create_dir(&parent).unwrap();
    assert!(target.check_parent().is_err());
    assert!(target.check_absent().is_err());
    let (later_genesis, later) = journal(&d.path("later"), &[]);
    assert!(
        RetainedPackage::create_new(target, &metadata(&[]), &[], &later, &later_genesis).is_err()
    );
    assert_eq!(fs::read_dir(&parent).unwrap().count(), 0);
    assert_eq!(fs::read_dir(&moved).unwrap().count(), 0);
}

#[cfg(windows)]
#[test]
fn prepared_parent_cannot_be_renamed_before_the_retained_owner_drops() {
    let d = Dir::new();
    let parent = d.path("parent");
    let moved = d.path("moved");
    fs::create_dir(&parent).unwrap();
    let target = NewTarget::prepare(&parent.join("package"), &[]).unwrap();
    let error = fs::rename(&parent, &moved).unwrap_err();
    assert!(matches!(error.raw_os_error(), Some(5 | 32)), "{error}");
    target.check_absent().unwrap();
    drop(target);
    fs::rename(&parent, &moved).unwrap();
    assert_eq!(fs::read_dir(&moved).unwrap().count(), 0);
}
