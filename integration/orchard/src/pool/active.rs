//! Bounded active journal segments for the explicitly selected LAB2 v3 profile.
//! This layer binds names, lengths, framing and durability, never authorization.
//! A caller must replay every record and validate every returned physical frame
//! before publishing any state. Trusted parents, OS and filesystem are required.
use super::recovery::segments::namespace;
use super::{PoolError, MAX_COMMITMENTS, MAX_RECORD_BYTES};
use std::fs::{self, File, Metadata, OpenOptions};
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

pub(super) const SEGMENT_BYTES: u64 = 1024 * 1024;
pub(super) const MAX_SEGMENTS: usize = 2048;
const TOTAL_BYTES: u64 = 1024 * 1024 * 1024;
const GENESIS: &str = "genesis";
const MIN_FRAME_BYTES: u64 = 4 + 114 + 32;
const MAX_FRAME_BYTES: u64 = 4 + MAX_RECORD_BYTES as u64 + 32;
const MAX_HEADER_BYTES: u64 = 76 + 32 * MAX_COMMITMENTS as u64;

struct Segment {
    file: File,
    length: u64,
}

/// Owns retained segment/directory handles. The separate returned `genesis`
/// handle owns the exclusive lock and must remain owned by the enclosing store.
/// Keeping at most MAX_SEGMENTS handles can exceed a host's descriptor limit;
/// that is a fail-closed storage error, never permission to omit a segment.
pub(super) struct ActiveJournal {
    path: PathBuf,
    location: namespace::Directory,
    header_length: u64,
    segments: Vec<Segment>,
    length: u64,
    /// Test-only interruption points: 1=new empty segment; 2=partial write;
    /// 3=full write before sync; 4=durable write with lost acknowledgement.
    #[cfg(test)]
    pub(super) fault: u8,
}

fn name(index: usize) -> String {
    format!("{index:08}.journal")
}

fn regular(meta: &Metadata) -> bool {
    if !meta.is_file() || meta.file_type().is_symlink() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if meta.nlink() != 1 {
            return false;
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if meta.file_attributes() & 0x400 != 0 {
            return false;
        }
    }
    true
}

fn check_file(path: &Path, file: &File, length: u64) -> Result<(), PoolError> {
    namespace::check_file(path, file, length)?;
    if !regular(&fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?)
        || !regular(&file.metadata().map_err(|_| PoolError::Storage)?)
    {
        return Err(PoolError::Corrupt);
    }
    Ok(())
}

fn open_file(path: &Path, expected: Option<u64>) -> Result<Segment, PoolError> {
    let before = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
    let length = before.len();
    if !regular(&before)
        || match expected {
            Some(n) => length != n,
            None => !(MIN_FRAME_BYTES..=SEGMENT_BYTES).contains(&length),
        }
    {
        return Err(PoolError::Corrupt);
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    namespace::retain_name(&mut options);
    let file = options.open(path).map_err(|_| PoolError::Storage)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let opened = file.metadata().map_err(|_| PoolError::Storage)?;
        if before.dev() != opened.dev() || before.ino() != opened.ino() {
            return Err(PoolError::Corrupt);
        }
    }
    check_file(path, &file, length)?;
    Ok(Segment { file, length })
}

fn create_file(path: &Path) -> Result<File, PoolError> {
    let mut options = OpenOptions::new();
    options.create_new(true).read(true).write(true);
    namespace::retain_name(&mut options);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(path).map_err(|_| PoolError::Storage)?;
    check_file(path, &file, 0)?;
    Ok(file)
}

/// Bounded name inventory. No manifest-supplied paths, recursive search, ignored
/// extras, gaps, or alternate spelling of a segment number are accepted.
fn inventory(path: &Path) -> Result<usize, PoolError> {
    let mut found = [false; MAX_SEGMENTS];
    let mut genesis = false;
    let mut count = 0;
    for entry in fs::read_dir(path).map_err(|_| PoolError::Storage)? {
        let entry = entry.map_err(|_| PoolError::Storage)?;
        let value = entry.file_name();
        if value == GENESIS {
            if genesis {
                return Err(PoolError::Corrupt);
            }
            genesis = true;
            continue;
        }
        let value = value.to_str().ok_or(PoolError::Corrupt)?;
        if value.len() != 16
            || !value.as_bytes()[..8].iter().all(u8::is_ascii_digit)
            || &value.as_bytes()[8..] != b".journal"
        {
            return Err(PoolError::Corrupt);
        }
        let index = value[..8].parse::<usize>().map_err(|_| PoolError::Corrupt)?;
        if index >= MAX_SEGMENTS || found[index] {
            return Err(PoolError::Bounds);
        }
        found[index] = true;
        count += 1;
    }
    if !genesis || found[..count].iter().any(|present| !present) {
        return Err(PoolError::Corrupt);
    }
    Ok(count)
}

fn check_namespace(
    path: &Path,
    location: &namespace::Directory,
    genesis: &File,
    header_length: u64,
    segments: &[Segment],
) -> Result<(), PoolError> {
    location.check(path)?;
    if inventory(path)? != segments.len() {
        return Err(PoolError::Corrupt);
    }
    check_file(&path.join(GENESIS), genesis, header_length)?;
    for (index, segment) in segments.iter().enumerate() {
        check_file(&path.join(name(index)), &segment.file, segment.length)?;
    }
    location.check(path)
}

fn header_length(header: &[u8]) -> Result<u64, PoolError> {
    let length = u64::try_from(header.len()).map_err(|_| PoolError::Bounds)?;
    if !(76..=MAX_HEADER_BYTES).contains(&length) {
        return Err(PoolError::Bounds);
    }
    Ok(length)
}

fn frame_size(length: u64) -> Result<(), PoolError> {
    if !(MIN_FRAME_BYTES..=MAX_FRAME_BYTES.min(SEGMENT_BYTES)).contains(&length) {
        return Err(PoolError::Bounds);
    }
    Ok(())
}

/// Return whether the next complete frame needs a new segment. This pure budget
/// check is shared by prepare and commit; it never reserves or creates a file.
fn frame_budget(
    length: u64,
    segments: usize,
    tail: u64,
    frame_length: u64,
) -> Result<bool, PoolError> {
    frame_size(frame_length)?;
    if segments > MAX_SEGMENTS
        || tail > SEGMENT_BYTES
        || (segments == 0) != (tail == 0)
        || length.checked_add(frame_length).ok_or(PoolError::Bounds)? > TOTAL_BYTES
    {
        return Err(PoolError::Bounds);
    }
    let rotate = segments == 0 || tail + frame_length > SEGMENT_BYTES;
    if rotate && segments == MAX_SEGMENTS {
        return Err(PoolError::Bounds);
    }
    Ok(rotate)
}

// Explicit offsets make each read independent of a cloned handle's cursor.
// Windows seek_read still updates that shared cursor: current callers finish
// reading before mutating the store, and append explicitly seeks to its tail.
// Retained handles do not provide concurrent read/write snapshot semantics.
fn read_at(file: &File, bytes: &mut [u8], offset: u64) -> io::Result<usize> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::FileExt;
        file.read_at(bytes, offset)
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::FileExt;
        file.seek_read(bytes, offset)
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = (file, bytes, offset);
        Err(io::Error::new(io::ErrorKind::Unsupported, "unsupported filesystem"))
    }
}

fn verify_header(file: &File, expected: &[u8]) -> Result<(), PoolError> {
    let mut position = 0;
    let mut buffer = [0; 8192];
    while position < expected.len() {
        let take = (expected.len() - position).min(buffer.len());
        match read_at(file, &mut buffer[..take], position as u64) {
            Ok(0) => return Err(PoolError::Corrupt),
            Ok(n) => {
                if buffer[..n] != expected[position..position + n] {
                    return Err(PoolError::Genesis);
                }
                position += n;
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(PoolError::Storage),
        }
    }
    let mut extra = [0];
    loop {
        match read_at(file, &mut extra, expected.len() as u64) {
            Ok(0) => return Ok(()),
            Ok(_) => return Err(PoolError::Corrupt),
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(PoolError::Storage),
        }
    }
}

impl ActiveJournal {
    pub(super) fn create(path: &Path, header: &[u8]) -> Result<(File, Self), PoolError> {
        if !path.is_absolute() {
            return Err(PoolError::Bounds);
        }
        let header_length = header_length(header)?;
        let mut builder = fs::DirBuilder::new();
        builder.recursive(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder.create(path).map_err(|_| PoolError::Storage)?;
        let location = namespace::Directory::open(path)?;
        let mut genesis = create_file(&path.join(GENESIS))?;
        genesis.try_lock().map_err(|_| PoolError::Locked)?;
        genesis.write_all(header).map_err(|_| PoolError::Storage)?;
        genesis.sync_all().map_err(|_| PoolError::Storage)?;
        location.sync()?;
        #[cfg(unix)]
        namespace::Directory::open(path.parent().ok_or(PoolError::Bounds)?)?.sync()?;
        let journal = Self {
            path: path.to_path_buf(),
            location,
            header_length,
            segments: Vec::new(),
            length: header_length,
            #[cfg(test)]
            fault: 0,
        };
        journal.check(&genesis)?;
        Ok((genesis, journal))
    }

    /// Opens a bounded candidate under the root lock. The caller must perform
    /// genuine replay and validate_frame for EVERY decoded record before use.
    pub(super) fn open(path: &Path, expected_header: &[u8]) -> Result<(File, Self), PoolError> {
        let header_length = header_length(expected_header)?;
        let location = namespace::Directory::open(path)?;
        let genesis = open_file(&path.join(GENESIS), Some(header_length))?.file;
        genesis.try_lock().map_err(|_| PoolError::Locked)?;
        verify_header(&genesis, expected_header)?;
        let count = inventory(path)?;
        let mut segments = Vec::new();
        segments.try_reserve_exact(count).map_err(|_| PoolError::Storage)?;
        let mut length = header_length;
        for index in 0..count {
            let segment = open_file(&path.join(name(index)), None)?;
            length = length.checked_add(segment.length).ok_or(PoolError::Bounds)?;
            if length > TOTAL_BYTES {
                return Err(PoolError::Bounds);
            }
            segments.push(segment);
        }
        let journal = Self {
            path: path.to_path_buf(),
            location,
            header_length,
            segments,
            length,
            #[cfg(test)]
            fault: 0,
        };
        journal.check(&genesis)?;
        Ok((genesis, journal))
    }

    pub(super) fn length(&self) -> u64 {
        self.length
    }

    pub(super) fn check(&self, genesis: &File) -> Result<(), PoolError> {
        check_namespace(
            &self.path,
            &self.location,
            genesis,
            self.header_length,
            &self.segments,
        )
    }

    fn check_tail(&self, genesis: &File) -> Result<(), PoolError> {
        self.location.check(&self.path)?;
        check_file(&self.path.join(GENESIS), genesis, self.header_length)?;
        if let Some(segment) = self.segments.last() {
            check_file(
                &self.path.join(name(self.segments.len() - 1)),
                &segment.file,
                segment.length,
            )?;
        }
        Ok(())
    }

    pub(super) fn reader(&self, genesis: &File) -> Result<ActiveReader, PoolError> {
        self.check(genesis)?;
        let mut segments = Vec::new();
        segments
            .try_reserve_exact(self.segments.len())
            .map_err(|_| PoolError::Storage)?;
        for segment in &self.segments {
            segments.push(Segment {
                file: segment.file.try_clone().map_err(|_| PoolError::Storage)?,
                length: segment.length,
            });
        }
        let reader = ActiveReader {
            path: self.path.clone(),
            location: self.location.try_clone()?,
            genesis: genesis.try_clone().map_err(|_| PoolError::Storage)?,
            header_length: self.header_length,
            segments,
            index: 0,
            offset: 0,
            failed: false,
            finished: false,
        };
        self.check(genesis)?;
        Ok(reader)
    }

    /// `start` and `end` are the actual logical positions bracketing one full
    /// Replay record. Reject split physical frames and noncanonical early rolls.
    pub(super) fn validate_frame(&self, start: u64, end: u64) -> Result<(), PoolError> {
        let frame_length = end.checked_sub(start).ok_or(PoolError::Corrupt)?;
        frame_size(frame_length)?;
        if start < self.header_length || end > self.length {
            return Err(PoolError::Corrupt);
        }
        let mut begin = self.header_length;
        for (index, segment) in self.segments.iter().enumerate() {
            let limit = begin + segment.length;
            if start < limit {
                if end > limit
                    || (start == begin
                        && index != 0
                        && self.segments[index - 1].length + frame_length <= SEGMENT_BYTES)
                {
                    return Err(PoolError::Corrupt);
                }
                return Ok(());
            }
            begin = limit;
        }
        Err(PoolError::Corrupt)
    }

    pub(super) fn check_frame(&self, frame_length: u64) -> Result<(), PoolError> {
        frame_budget(
            self.length,
            self.segments.len(),
            self.segments.last().map_or(0, |segment| segment.length),
            frame_length,
        )?;
        Ok(())
    }

    /// The enclosing store must become unavailable after an I/O/identity error;
    /// disk bytes may contain an incomplete frame OR a complete durable frame.
    /// There is no truncate, deletion, rollback, retry, or production fault flag.
    pub(super) fn append(&mut self, genesis: &File, frame: &[u8]) -> Result<(), PoolError> {
        let frame_length = u64::try_from(frame.len()).map_err(|_| PoolError::Bounds)?;
        self.check_frame(frame_length)?;
        let body_length = u32::from_be_bytes(frame[..4].try_into().map_err(|_| PoolError::Bounds)?);
        if u64::from(body_length) + 36 != frame_length {
            return Err(PoolError::Corrupt);
        }
        self.check_tail(genesis)?;
        let rotate = frame_budget(
            self.length,
            self.segments.len(),
            self.segments.last().map_or(0, |segment| segment.length),
            frame_length,
        )?;
        let mut created = if rotate {
            self.check(genesis)?;
            self.segments.try_reserve(1).map_err(|_| PoolError::Storage)?;
            Some(create_file(&self.path.join(name(self.segments.len())))?)
        } else {
            None
        };
        #[cfg(test)]
        if rotate && self.fault == 1 {
            return Err(PoolError::Storage);
        }
        let index = if rotate { self.segments.len() } else { self.segments.len() - 1 };
        let previous = if rotate { 0 } else { self.segments.last().ok_or(PoolError::Corrupt)?.length };
        let file = match created.as_mut() {
            Some(file) => file,
            None => &mut self.segments.last_mut().ok_or(PoolError::Corrupt)?.file,
        };
        file.seek(SeekFrom::Start(previous)).map_err(|_| PoolError::Storage)?;
        #[cfg(test)]
        if self.fault == 2 {
            file.write_all(&frame[..frame.len() / 2]).map_err(|_| PoolError::Storage)?;
            return Err(PoolError::Storage);
        }
        file.write_all(frame).map_err(|_| PoolError::Storage)?;
        #[cfg(test)]
        if self.fault == 3 {
            return Err(PoolError::Storage);
        }
        file.sync_all().map_err(|_| PoolError::Storage)?;
        if rotate {
            self.location.sync()?;
        }
        #[cfg(test)]
        if self.fault == 4 {
            return Err(PoolError::Storage);
        }
        let next_length = previous + frame_length;
        check_file(&self.path.join(name(index)), file, next_length)?;
        self.location.check(&self.path)?;
        check_file(&self.path.join(GENESIS), genesis, self.header_length)?;
        if rotate && inventory(&self.path)? != self.segments.len() + 1 {
            return Err(PoolError::Corrupt);
        }
        // No committed metadata changes occur before every write/sync/check.
        if let Some(file) = created {
            self.segments.push(Segment { file, length: next_length });
        } else {
            self.segments.last_mut().ok_or(PoolError::Corrupt)?.length = next_length;
        }
        self.length += frame_length;
        Ok(())
    }

    pub(super) fn capacity(&self) -> (u64, u32, u32) {
        (
            self.length,
            self.segments.len() as u32,
            self.segments.last().map_or(0, |segment| segment.length as u32),
        )
    }
}

/// Owned, bounded logical stream. Cloned handles retain the genesis lock and
/// pathname protections even if the original store is dropped. Each individual
/// file must reach its captured length AND actual EOF; joining streams cannot
/// conceal extra bytes. validate_frame additionally enforces record boundaries.
pub(super) struct ActiveReader {
    path: PathBuf,
    location: namespace::Directory,
    genesis: File,
    header_length: u64,
    segments: Vec<Segment>,
    index: usize,
    offset: u64,
    failed: bool,
    finished: bool,
}

impl ActiveReader {
    fn read_next(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        loop {
            let (file, length) = if self.index == 0 {
                (&self.genesis, self.header_length)
            } else if let Some(segment) = self.segments.get(self.index - 1) {
                (&segment.file, segment.length)
            } else {
                check_namespace(
                    &self.path,
                    &self.location,
                    &self.genesis,
                    self.header_length,
                    &self.segments,
                )
                .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "active journal changed"))?;
                self.finished = true;
                return Ok(0);
            };
            if self.offset == length {
                let mut extra = [0];
                match read_at(file, &mut extra, length) {
                    Ok(0) => {
                        self.index += 1;
                        self.offset = 0;
                        continue;
                    }
                    Ok(_) => return Err(io::Error::new(io::ErrorKind::InvalidData, "extra journal bytes")),
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    Err(error) => return Err(error),
                }
            }
            let take = (length - self.offset).min(bytes.len() as u64) as usize;
            match read_at(file, &mut bytes[..take], self.offset) {
                Ok(0) => return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "truncated journal")),
                Ok(n) => {
                    self.offset += n as u64;
                    return Ok(n);
                }
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(error) => return Err(error),
            }
        }
    }
}

impl Read for ActiveReader {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        if self.failed {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "failed journal reader"));
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
