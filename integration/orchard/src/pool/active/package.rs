//! Private physical transport for ZVAIPK01. This module never authenticates a
//! record or returns state. Its caller must replay the base and reconstruction,
//! bind both trusted pins, and repeat complete byte/namespace checks at the end.
use super::{
    check_file, create_file, name, namespace, open_file_access, read_at, regular,
    validate_physical_frame, visit_file, ActiveJournal, File, Hash, PoolError, Segment,
    COPY_CHUNK, GENESIS, MAX_SEGMENTS, MIN_FRAME_BYTES, SEGMENT_BYTES, TOTAL_BYTES,
};
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

const FIXED_BYTES: usize = 268;
const RANGE_BYTES: usize = 12;
const MAX_METADATA: usize = FIXED_BYTES + RANGE_BYTES * MAX_SEGMENTS;
const MAX_PACKAGE: u64 = TOTAL_BYTES + MAX_METADATA as u64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(in crate::pool) struct RangeSpec {
    pub(in crate::pool) segment_index: u32,
    pub(in crate::pool) offset: u32,
    pub(in crate::pool) length: u32,
}

fn metadata_length(count: usize) -> Result<usize, PoolError> {
    if count > MAX_SEGMENTS {
        return Err(PoolError::Bounds);
    }
    FIXED_BYTES
        .checked_add(count.checked_mul(RANGE_BYTES).ok_or(PoolError::Bounds)?)
        .ok_or(PoolError::Bounds)
}

fn range_end(range: RangeSpec) -> Result<u64, PoolError> {
    let end = u64::from(range.offset)
        .checked_add(u64::from(range.length))
        .ok_or(PoolError::Bounds)?;
    if range.segment_index as usize >= MAX_SEGMENTS || range.length == 0 || end > SEGMENT_BYTES {
        return Err(PoolError::Bounds);
    }
    Ok(end)
}

// Fill independently of any shared cursor. A malicious test double returning
// more than requested is rejected instead of causing an out-of-bounds slice.
fn fill_at(
    mut bytes: &mut [u8],
    mut offset: u64,
    mut read: impl FnMut(&mut [u8], u64) -> io::Result<usize>,
) -> Result<(), PoolError> {
    while !bytes.is_empty() {
        match read(bytes, offset) {
            Ok(0) => return Err(PoolError::Corrupt),
            Ok(count) => {
                if count > bytes.len() {
                    return Err(PoolError::Corrupt);
                }
                offset = offset
                    .checked_add(u64::try_from(count).map_err(|_| PoolError::Bounds)?)
                    .ok_or(PoolError::Bounds)?;
                bytes = &mut bytes[count..];
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(PoolError::Storage),
        }
    }
    Ok(())
}

fn write_all_checked(writer: &mut impl Write, mut bytes: &[u8]) -> Result<(), PoolError> {
    while !bytes.is_empty() {
        match writer.write(bytes) {
            Ok(0) => return Err(PoolError::Storage),
            Ok(count) => {
                if count > bytes.len() {
                    return Err(PoolError::Corrupt);
                }
                bytes = &bytes[count..];
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(PoolError::Storage),
        }
    }
    Ok(())
}

fn exact_file_end(file: &File, length: u64) -> Result<(), PoolError> {
    let mut byte = [0];
    loop {
        match read_at(file, &mut byte, length) {
            Ok(0) => break,
            Ok(_) => return Err(PoolError::Corrupt),
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(PoolError::Storage),
        }
    }
    let metadata = file.metadata().map_err(|_| PoolError::Storage)?;
    if !regular(&metadata) || metadata.len() != length {
        return Err(PoolError::Corrupt);
    }
    Ok(())
}

// A package range ends inside a file. Only the enclosing package, not each
// payload range, has an EOF; whole base files use visit_file instead.
fn visit_span(
    file: &File,
    offset: u64,
    length: u64,
    mut consume: impl FnMut(&[u8]) -> Result<(), PoolError>,
) -> Result<(), PoolError> {
    let end = offset.checked_add(length).ok_or(PoolError::Bounds)?;
    let mut position = offset;
    let mut buffer = [0; COPY_CHUNK];
    while position < end {
        let take = usize::try_from((end - position).min(COPY_CHUNK as u64))
            .map_err(|_| PoolError::Bounds)?;
        fill_at(&mut buffer[..take], position, |bytes, at| read_at(file, bytes, at))?;
        consume(&buffer[..take])?;
        position = position
            .checked_add(u64::try_from(take).map_err(|_| PoolError::Bounds)?)
            .ok_or(PoolError::Bounds)?;
    }
    Ok(())
}

/// Retains the actual parent across potentially lengthy replay before writing.
/// Sibling files are allowed: this is parent identity, not a directory archive.
pub(in crate::pool) struct NewTarget {
    path: PathBuf,
    parent_path: PathBuf,
    parent: namespace::Directory,
    /// Private transport interruptions only; never a production option.
    #[cfg(test)]
    pub(in crate::pool) fault: u8,
}

impl NewTarget {
    pub(in crate::pool) fn prepare(path: &Path, forbidden: &[&Path]) -> Result<Self, PoolError> {
        if !path.is_absolute() || path.file_name().is_none() {
            return Err(PoolError::Bounds);
        }
        let parent_path = path.parent().ok_or(PoolError::Bounds)?.to_path_buf();
        let parent = namespace::Directory::open(&parent_path)?;
        let target = Self {
            path: path.to_path_buf(),
            parent_path,
            parent,
            #[cfg(test)]
            fault: 0,
        };
        for source in forbidden {
            target.reject_inside(source)?;
        }
        target.check_absent()?;
        Ok(target)
    }

    pub(in crate::pool) fn path(&self) -> &Path {
        &self.path
    }

    pub(in crate::pool) fn check_parent(&self) -> Result<(), PoolError> {
        self.parent.check(&self.parent_path)
    }

    pub(in crate::pool) fn check_absent(&self) -> Result<(), PoolError> {
        self.check_parent()?;
        match fs::symlink_metadata(&self.path) {
            Ok(_) => return Err(PoolError::Storage),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(_) => return Err(PoolError::Storage),
        }
        self.check_parent()
    }

    fn reject_inside(&self, source: &Path) -> Result<(), PoolError> {
        self.check_parent()?;
        let parent = fs::canonicalize(&self.parent_path).map_err(|_| PoolError::Storage)?;
        let source = fs::canonicalize(source).map_err(|_| PoolError::Storage)?;
        if parent.starts_with(source) {
            return Err(PoolError::Bounds);
        }
        self.check_parent()
    }
}

/// A retained transport file, not a verified public package. Read access and
/// original creation access both retain their own parent and file identities.
pub(in crate::pool) struct RetainedPackage {
    target: NewTarget,
    file: File,
    length: u64,
}

impl RetainedPackage {
    pub(in crate::pool) fn open(path: &Path) -> Result<Self, PoolError> {
        if !path.is_absolute() || path.file_name().is_none() {
            return Err(PoolError::Bounds);
        }
        let parent_path = path.parent().ok_or(PoolError::Bounds)?.to_path_buf();
        let parent = namespace::Directory::open(&parent_path)?;
        let before = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
        let length = before.len();
        if !regular(&before) || !(FIXED_BYTES as u64..=MAX_PACKAGE).contains(&length) {
            return Err(PoolError::Bounds);
        }
        // This active-specific helper also enforces Unix nlink == 1, unlike
        // the legacy recovery regular-file predicate used by namespace alone.
        let file = open_file_access(path, Some(length), false)?.file;
        file.try_lock_shared().map_err(|_| PoolError::Locked)?;
        let package = Self {
            target: NewTarget {
                path: path.to_path_buf(),
                parent_path,
                parent,
                #[cfg(test)]
                fault: 0,
            },
            file,
            length,
        };
        package.check()?;
        Ok(package)
    }

    pub(in crate::pool) fn create_new(
        target: NewTarget,
        metadata: &[u8],
        ranges: &[RangeSpec],
        later: &ActiveJournal,
        later_genesis: &File,
    ) -> Result<Self, PoolError> {
        if metadata.len() != metadata_length(ranges.len())? {
            return Err(PoolError::Bounds);
        }
        later.check(later_genesis)?;
        target.reject_inside(later.path())?;
        let mut length = u64::try_from(metadata.len()).map_err(|_| PoolError::Bounds)?;
        let mut previous = None;
        for range in ranges {
            let segment = later
                .segments
                .get(range.segment_index as usize)
                .ok_or(PoolError::Bounds)?;
            if range_end(*range)? != segment.length
                || previous.is_some_and(|prior| range.segment_index <= prior)
            {
                return Err(PoolError::Corrupt);
            }
            length = length
                .checked_add(u64::from(range.length))
                .ok_or(PoolError::Bounds)?;
            previous = Some(range.segment_index);
        }
        if length > MAX_PACKAGE {
            return Err(PoolError::Bounds);
        }
        target.check_absent()?;
        let mut file = create_file(target.path())?;
        file.try_lock().map_err(|_| PoolError::Locked)?;
        #[cfg(test)]
        if target.fault == 1 {
            write_all_checked(&mut file, &metadata[..metadata.len() / 2])?;
            return Err(PoolError::Storage);
        }
        write_all_checked(&mut file, metadata)?;
        for (index, range) in ranges.iter().enumerate() {
            #[cfg(not(test))]
            let _ = index;
            let source = &later.segments[range.segment_index as usize];
            visit_span(
                &source.file,
                u64::from(range.offset),
                u64::from(range.length),
                |bytes| {
                    #[cfg(test)]
                    if target.fault == 2 && index == 0 {
                        write_all_checked(&mut file, &bytes[..bytes.len() / 2])?;
                        return Err(PoolError::Storage);
                    }
                    write_all_checked(&mut file, bytes)
                },
            )?;
            exact_file_end(&source.file, source.length)?;
        }
        #[cfg(test)]
        if target.fault == 3 {
            return Err(PoolError::Storage);
        }
        file.sync_all().map_err(|_| PoolError::Storage)?;
        target.parent.sync()?;
        target.check_parent()?;
        #[cfg(test)]
        if target.fault == 4 {
            return Err(PoolError::Storage);
        }
        let package = Self {
            target,
            file,
            length,
        };
        package.check()?;
        later.check(later_genesis)?;
        Ok(package)
    }

    pub(in crate::pool) fn length(&self) -> u64 {
        self.length
    }

    pub(in crate::pool) fn path(&self) -> &Path {
        self.target.path()
    }

    pub(in crate::pool) fn read_exact_at(
        &self,
        bytes: &mut [u8],
        offset: u64,
    ) -> Result<(), PoolError> {
        let end = offset
            .checked_add(u64::try_from(bytes.len()).map_err(|_| PoolError::Bounds)?)
            .ok_or(PoolError::Bounds)?;
        if end > self.length {
            return Err(PoolError::Bounds);
        }
        fill_at(bytes, offset, |bytes, at| read_at(&self.file, bytes, at))
    }

    pub(in crate::pool) fn check(&self) -> Result<(), PoolError> {
        self.target.check_parent()?;
        check_file(self.path(), &self.file, self.length)?;
        exact_file_end(&self.file, self.length)?;
        check_file(self.path(), &self.file, self.length)?;
        self.target.check_parent()
    }

    fn check_metadata(&self, metadata: &[u8]) -> Result<(), PoolError> {
        if !(FIXED_BYTES..=MAX_METADATA).contains(&metadata.len())
            || metadata.len() as u64 > self.length
        {
            return Err(PoolError::Bounds);
        }
        let mut offset = 0usize;
        visit_span(&self.file, 0, metadata.len() as u64, |bytes| {
            let end = offset.checked_add(bytes.len()).ok_or(PoolError::Bounds)?;
            if bytes != metadata.get(offset..end).ok_or(PoolError::Corrupt)? {
                return Err(PoolError::Corrupt);
            }
            offset = end;
            Ok(())
        })
    }

    #[cfg(test)]
    pub(in crate::pool) fn fault_change_byte(&self, offset: u64) -> Result<(), PoolError> {
        use std::io::{Seek, SeekFrom};
        let mut byte = [0];
        self.read_exact_at(&mut byte, offset)?;
        byte[0] ^= 1;
        let mut writer = self.file.try_clone().map_err(|_| PoolError::Storage)?;
        writer
            .seek(SeekFrom::Start(offset))
            .map_err(|_| PoolError::Storage)?;
        write_all_checked(&mut writer, &byte)?;
        writer.sync_all().map_err(|_| PoolError::Storage)
    }
}

struct JoinedSegment {
    base_length: u64,
    payload_offset: u64,
    payload_length: u64,
    length: u64,
}

/// Only bounded physical metadata is allocated. All payload and reused bytes
/// remain behind the original owning handles and are read with explicit offsets.
pub(in crate::pool) struct JoinedJournal<'a> {
    base: &'a ActiveJournal,
    genesis: &'a File,
    package: &'a RetainedPackage,
    metadata: &'a [u8],
    segments: Vec<JoinedSegment>,
    length: u64,
}

impl<'a> JoinedJournal<'a> {
    pub(in crate::pool) fn new(
        base: &'a ActiveJournal,
        genesis: &'a File,
        package: &'a RetainedPackage,
        metadata: &'a [u8],
        ranges: &[RangeSpec],
        later_count: u32,
        later_length: u64,
    ) -> Result<Self, PoolError> {
        base.check(genesis)?;
        package.check()?;
        let count = usize::try_from(later_count).map_err(|_| PoolError::Bounds)?;
        if count > MAX_SEGMENTS || count < base.segments.len() || later_length > TOTAL_BYTES {
            return Err(PoolError::Bounds);
        }
        let appended = later_length
            .checked_sub(base.length)
            .ok_or(PoolError::Stale)?;
        let metadata_size = metadata_length(ranges.len())?;
        if metadata.len() != metadata_size
            || (metadata_size as u64)
                .checked_add(appended)
                .ok_or(PoolError::Bounds)?
                != package.length
        {
            return Err(PoolError::Corrupt);
        }
        let mut segments = Vec::new();
        segments
            .try_reserve_exact(count)
            .map_err(|_| PoolError::Storage)?;
        for index in 0..count {
            let base_length = base.segments.get(index).map_or(0, |segment| segment.length);
            segments.push(JoinedSegment {
                base_length,
                payload_offset: 0,
                payload_length: 0,
                length: base_length,
            });
        }
        let mut previous = None;
        let mut next_new = base.segments.len();
        let mut payload_offset = metadata_size as u64;
        for range in ranges {
            let index = usize::try_from(range.segment_index).map_err(|_| PoolError::Bounds)?;
            let end = range_end(*range)?;
            if index >= count || previous.is_some_and(|prior| index <= prior) {
                return Err(PoolError::Corrupt);
            }
            if index < base.segments.len() {
                if index.checked_add(1).ok_or(PoolError::Bounds)? != base.segments.len()
                    || u64::from(range.offset) != base.segments[index].length
                {
                    return Err(PoolError::Corrupt);
                }
            } else {
                if index != next_new || range.offset != 0 {
                    return Err(PoolError::Corrupt);
                }
                next_new = next_new.checked_add(1).ok_or(PoolError::Bounds)?;
            }
            let segment = &mut segments[index];
            segment.payload_offset = payload_offset;
            segment.payload_length = u64::from(range.length);
            segment.length = end;
            payload_offset = payload_offset
                .checked_add(segment.payload_length)
                .ok_or(PoolError::Bounds)?;
            previous = Some(index);
        }
        if next_new != count || payload_offset != package.length {
            return Err(PoolError::Corrupt);
        }
        let mut length = base.header_length;
        for segment in &segments {
            if !(MIN_FRAME_BYTES..=SEGMENT_BYTES).contains(&segment.length) {
                return Err(PoolError::Bounds);
            }
            length = length
                .checked_add(segment.length)
                .ok_or(PoolError::Bounds)?;
        }
        if length != later_length {
            return Err(PoolError::Corrupt);
        }
        let joined = Self {
            base,
            genesis,
            package,
            metadata,
            segments,
            length,
        };
        joined.check()?;
        Ok(joined)
    }

    pub(in crate::pool) fn check(&self) -> Result<(), PoolError> {
        self.base.check(self.genesis)?;
        self.package.check()?;
        self.package.check_metadata(self.metadata)?;
        self.package.check()?;
        self.base.check(self.genesis)
    }

    pub(in crate::pool) fn reader(&self) -> Result<JoinedReader<'_, 'a>, PoolError> {
        self.check()?;
        Ok(JoinedReader {
            joined: self,
            piece: 0,
            offset: 0,
            failed: false,
            finished: false,
        })
    }

    fn visit_segment(
        &self,
        index: usize,
        mut consume: impl FnMut(&[u8]) -> Result<(), PoolError>,
    ) -> Result<(), PoolError> {
        let segment = self.segments.get(index).ok_or(PoolError::Bounds)?;
        if segment.base_length != 0 {
            let source = self.base.segments.get(index).ok_or(PoolError::Corrupt)?;
            visit_file(&source.file, segment.base_length, &mut consume)?;
        }
        if segment.payload_length != 0 {
            visit_span(
                &self.package.file,
                segment.payload_offset,
                segment.payload_length,
                consume,
            )?;
        }
        Ok(())
    }

    pub(in crate::pool) fn layout_hash(&self) -> Result<Hash, PoolError> {
        self.check()?;
        let mut hash = Sha256::new();
        hash.update(b"ZVARLY01");
        hash.update(
            u32::try_from(self.base.header_length)
                .map_err(|_| PoolError::Bounds)?
                .to_be_bytes(),
        );
        visit_file(self.genesis, self.base.header_length, |bytes| {
            hash.update(bytes);
            Ok(())
        })?;
        hash.update(
            u32::try_from(self.segments.len())
                .map_err(|_| PoolError::Bounds)?
                .to_be_bytes(),
        );
        for (index, segment) in self.segments.iter().enumerate() {
            hash.update((index as u32).to_be_bytes());
            hash.update((segment.length as u32).to_be_bytes());
            self.visit_segment(index, |bytes| {
                hash.update(bytes);
                Ok(())
            })?;
        }
        self.check()?;
        Ok(hash.finalize().into())
    }

    pub(in crate::pool) fn validate_frame(&self, start: u64, end: u64) -> Result<(), PoolError> {
        validate_physical_frame(
            self.base.header_length,
            self.length,
            self.segments.iter().map(|segment| segment.length),
            start,
            end,
        )
    }

    pub(in crate::pool) fn copy_new(
        &self,
        target: &NewTarget,
    ) -> Result<(File, ActiveJournal), PoolError> {
        self.check()?;
        target.reject_inside(self.base.path())?;
        target.check_absent()?;
        let mut builder = fs::DirBuilder::new();
        builder.recursive(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder.create(target.path()).map_err(|_| PoolError::Storage)?;
        let location = namespace::Directory::open(target.path())?;
        let mut genesis = create_file(&target.path().join(GENESIS))?;
        genesis.try_lock().map_err(|_| PoolError::Locked)?;
        visit_file(self.genesis, self.base.header_length, |bytes| {
            #[cfg(test)]
            if target.fault == 11 {
                write_all_checked(&mut genesis, &bytes[..bytes.len() / 2])?;
                return Err(PoolError::Storage);
            }
            write_all_checked(&mut genesis, bytes)
        })?;
        #[cfg(test)]
        if target.fault == 13 && self.segments.is_empty() {
            return Err(PoolError::Storage);
        }
        genesis.sync_all().map_err(|_| PoolError::Storage)?;
        let mut segments = Vec::new();
        segments
            .try_reserve_exact(self.segments.len())
            .map_err(|_| PoolError::Storage)?;
        for (index, segment) in self.segments.iter().enumerate() {
            let mut file = create_file(&target.path().join(name(index)))?;
            self.visit_segment(index, |bytes| {
                #[cfg(test)]
                if target.fault == 12 && index == 0 {
                    write_all_checked(&mut file, &bytes[..bytes.len() / 2])?;
                    return Err(PoolError::Storage);
                }
                write_all_checked(&mut file, bytes)
            })?;
            #[cfg(test)]
            if target.fault == 13 && index + 1 == self.segments.len() {
                return Err(PoolError::Storage);
            }
            file.sync_all().map_err(|_| PoolError::Storage)?;
            segments.push(Segment {
                file,
                length: segment.length,
            });
        }
        location.sync()?;
        target.parent.sync()?;
        target.check_parent()?;
        #[cfg(test)]
        if target.fault == 14 {
            return Err(PoolError::Storage);
        }
        let journal = ActiveJournal {
            path: target.path().to_path_buf(),
            location,
            header_length: self.base.header_length,
            segments,
            length: self.length,
            #[cfg(test)]
            fault: 0,
        };
        journal.check(&genesis)?;
        self.check()?;
        target.check_parent()?;
        Ok((genesis, journal))
    }

    fn piece(&self, index: usize) -> Result<Option<ReadPiece<'a>>, PoolError> {
        if index == 0 {
            return Ok(Some(ReadPiece {
                file: self.genesis,
                start: 0,
                length: self.base.header_length,
                whole_file: true,
            }));
        }
        let segment_index = (index - 1) / 2;
        let Some(segment) = self.segments.get(segment_index) else {
            return Ok(None);
        };
        if (index - 1).is_multiple_of(2) {
            // A zero-length base part of a new segment is skipped without
            // inventing a source file or a physical EOF at a payload boundary.
            if segment.base_length == 0 {
                return Ok(Some(ReadPiece {
                    file: &self.package.file,
                    start: 0,
                    length: 0,
                    whole_file: false,
                }));
            }
            let source = self
                .base
                .segments
                .get(segment_index)
                .ok_or(PoolError::Corrupt)?;
            Ok(Some(ReadPiece {
                file: &source.file,
                start: 0,
                length: segment.base_length,
                whole_file: true,
            }))
        } else {
            Ok(Some(ReadPiece {
                file: &self.package.file,
                start: segment.payload_offset,
                length: segment.payload_length,
                whole_file: false,
            }))
        }
    }
}

struct ReadPiece<'a> {
    file: &'a File,
    start: u64,
    length: u64,
    whole_file: bool,
}

pub(in crate::pool) struct JoinedReader<'view, 'source> {
    joined: &'view JoinedJournal<'source>,
    piece: usize,
    offset: u64,
    failed: bool,
    finished: bool,
}

fn reader_error(error: PoolError) -> io::Error {
    let _ = error;
    io::Error::new(io::ErrorKind::InvalidData, "incremental input changed")
}

impl JoinedReader<'_, '_> {
    fn read_next(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        loop {
            let Some(piece) = self.joined.piece(self.piece).map_err(reader_error)? else {
                self.joined.check().map_err(reader_error)?;
                self.finished = true;
                return Ok(0);
            };
            if self.offset == piece.length {
                if piece.whole_file {
                    exact_file_end(piece.file, piece.length).map_err(reader_error)?;
                }
                self.piece = self
                    .piece
                    .checked_add(1)
                    .ok_or_else(|| reader_error(PoolError::Bounds))?;
                self.offset = 0;
                continue;
            }
            let remaining = piece
                .length
                .checked_sub(self.offset)
                .ok_or_else(|| reader_error(PoolError::Corrupt))?;
            let take = usize::try_from(remaining.min(bytes.len() as u64))
                .map_err(|_| reader_error(PoolError::Bounds))?;
            let offset = piece
                .start
                .checked_add(self.offset)
                .ok_or_else(|| reader_error(PoolError::Bounds))?;
            match read_at(piece.file, &mut bytes[..take], offset) {
                Ok(0) => {
                    return Err(io::Error::new(
                        io::ErrorKind::UnexpectedEof,
                        "truncated incremental input",
                    ));
                }
                Ok(count) => {
                    if count > take {
                        return Err(reader_error(PoolError::Corrupt));
                    }
                    self.offset = self
                        .offset
                        .checked_add(count as u64)
                        .ok_or_else(|| reader_error(PoolError::Bounds))?;
                    return Ok(count);
                }
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(error) => return Err(error),
            }
        }
    }
}

impl Read for JoinedReader<'_, '_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        if self.failed {
            return Err(reader_error(PoolError::Unavailable));
        }
        if bytes.is_empty() || self.finished {
            return Ok(0);
        }
        let result = self.read_next(bytes);
        if result.is_err() {
            self.failed = true;
        }
        result
    }
}

#[cfg(test)]
mod tests;
