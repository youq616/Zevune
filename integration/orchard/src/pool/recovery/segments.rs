//! Immutable, bounded segmented backups of the ORIGINAL public journal bytes.
//! Not the live journal format, snapshots, pruning, fast sync, or node recovery.
use super::*;
use crate::pool::replay::{read_header, require_eof, Replay};
use std::io;

pub(in crate::pool) mod namespace;

/// Full-replay-derived historical record navigation; not a state import format.
pub mod index;

const MAGIC: &[u8; 8] = b"ZVPSEG01";
const MANIFEST: &str = "MANIFEST";
pub const SEGMENT_BYTES: u64 = 1024 * 1024;
const MAX_SEGMENTS: usize = (MAX_JOURNAL_BYTES / SEGMENT_BYTES) as usize;
const FIXED_BYTES: usize = 8 + CHECKPOINT_BYTES + 8;
const MAX_MANIFEST: usize = FIXED_BYTES + MAX_SEGMENTS * 36;

#[derive(Clone)]
struct Entry {
    length: u32,
    hash: Hash,
}
fn name(index: usize) -> String {
    format!("segment-{index:06}.bin")
}
fn count(pin: RecoveryCheckpoint) -> usize {
    pin.length.div_ceil(SEGMENT_BYTES) as usize
}
fn segment_length(pin: RecoveryCheckpoint, index: usize) -> u32 {
    (pin.length - index as u64 * SEGMENT_BYTES).min(SEGMENT_BYTES) as u32
}
fn encode(pin: RecoveryCheckpoint, entries: &[Entry]) -> Result<Vec<u8>, PoolError> {
    if entries.len() != count(pin) {
        return Err(PoolError::Bounds);
    }
    let mut raw = MAGIC.to_vec();
    raw.extend_from_slice(&pin.to_bytes());
    raw.extend_from_slice(&(SEGMENT_BYTES as u32).to_be_bytes());
    raw.extend_from_slice(&(entries.len() as u32).to_be_bytes());
    for (i, entry) in entries.iter().enumerate() {
        if entry.length != segment_length(pin, i) {
            return Err(PoolError::Bounds);
        }
        raw.extend_from_slice(&entry.length.to_be_bytes());
        raw.extend_from_slice(&entry.hash);
    }
    Ok(raw)
}
fn decode(raw: &[u8], pin: RecoveryCheckpoint) -> Result<Vec<Entry>, PoolError> {
    let n = count(pin);
    if n == 0 || n > MAX_SEGMENTS || raw.len() != FIXED_BYTES + n * 36 {
        return Err(PoolError::Bounds);
    }
    if &raw[..8] != MAGIC
        || raw[8..128] != pin.to_bytes()
        || raw[128..132] != (SEGMENT_BYTES as u32).to_be_bytes()
        || raw[132..136] != (n as u32).to_be_bytes()
    {
        return Err(PoolError::Corrupt);
    }
    let mut entries = Vec::new();
    entries
        .try_reserve_exact(n)
        .map_err(|_| PoolError::Storage)?;
    for (i, bytes) in raw[FIXED_BYTES..].as_chunks::<36>().0.iter().enumerate() {
        let length = u32::from_be_bytes(bytes[..4].try_into().map_err(|_| PoolError::Corrupt)?);
        if length != segment_length(pin, i) {
            return Err(PoolError::Bounds);
        }
        entries.push(Entry {
            length,
            hash: bytes[4..].try_into().map_err(|_| PoolError::Corrupt)?,
        });
    }
    Ok(entries)
}
fn directory(path: &Path, n: usize) -> Result<(), PoolError> {
    let info = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
    if !path.is_absolute() || !info.is_dir() || info.file_type().is_symlink() {
        return Err(PoolError::Bounds);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if info.file_attributes() & 0x400 != 0 {
            return Err(PoolError::Bounds);
        }
    }
    let mut seen = 0;
    for entry in fs::read_dir(path).map_err(|_| PoolError::Storage)? {
        let entry = entry.map_err(|_| PoolError::Storage)?;
        seen += 1;
        if seen > n + 1
            || (entry.file_name() != MANIFEST
                && !(0..n).any(|i| entry.file_name() == name(i).as_str()))
        {
            return Err(PoolError::Corrupt);
        }
    }
    if seen != n + 1 {
        return Err(PoolError::Corrupt);
    }
    Ok(())
}
fn open_read(path: &Path, length: u64) -> Result<File, PoolError> {
    let before = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
    if !regular(&before) || before.len() != length {
        return Err(PoolError::Bounds);
    }
    let mut options = OpenOptions::new();
    options.read(true);
    namespace::retain_name(&mut options);
    let file = options.open(path).map_err(|_| PoolError::Storage)?;
    file.try_lock_shared().map_err(|_| PoolError::Locked)?;
    let after = file.metadata().map_err(|_| PoolError::Storage)?;
    if !regular(&after) || after.len() != length {
        return Err(PoolError::Corrupt);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.dev() != after.dev() || before.ino() != after.ino() {
            return Err(PoolError::Corrupt);
        }
    }
    namespace::check_file(path, &file, length)?;
    Ok(file)
}
fn create_file(path: &Path) -> Result<File, PoolError> {
    let mut opts = OpenOptions::new();
    opts.create_new(true).read(true).write(true);
    namespace::retain_name(&mut opts);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    let file = opts.open(path).map_err(|_| PoolError::Storage)?;
    file.try_lock().map_err(|_| PoolError::Locked)?;
    Ok(file)
}

/// Holds the verified files and their locks, not an editable chain state.
/// Opening uses shared read-only handles; a newly packed object retains the
/// writer handles until dropped. Trusted local parent directories/OS are required.
pub struct SegmentedArchive {
    path: std::path::PathBuf,
    location: namespace::Directory,
    manifest: File,
    raw_manifest: Vec<u8>,
    entries: Vec<Entry>,
    files: Vec<File>,
    pin: RecoveryCheckpoint,
    #[cfg(test)]
    fault: u8,
}
impl SegmentedArchive {
    /// `pin` must be independently authenticated. Manifest hashes are NOT a
    /// substitute for this pin, genuine journal replay, or consensus finality.
    pub fn open(path: &Path, pin: RecoveryCheckpoint) -> Result<Self, PoolError> {
        let mut archive = Self::open_unverified(path, pin)?;
        archive.verify()?;
        Ok(archive)
    }
    // Private construction only. No caller may publish this before full replay.
    // open() and open_indexed() both apply that same verification gate.
    fn open_unverified(path: &Path, pin: RecoveryCheckpoint) -> Result<Self, PoolError> {
        if !path.is_absolute() {
            return Err(PoolError::Bounds);
        }
        let n = count(pin);
        let location = namespace::Directory::open(path)?;
        directory(path, n)?;
        let size = FIXED_BYTES + n * 36;
        if n == 0 || n > MAX_SEGMENTS || size > MAX_MANIFEST {
            return Err(PoolError::Bounds);
        }
        let mut manifest = open_read(&path.join(MANIFEST), size as u64)?;
        let mut raw = vec![0; size];
        manifest
            .read_exact(&mut raw)
            .map_err(|_| PoolError::Corrupt)?;
        require_eof(&mut manifest)?;
        let entries = decode(&raw, pin)?;
        let mut files = Vec::new();
        files.try_reserve_exact(n).map_err(|_| PoolError::Storage)?;
        for (i, entry) in entries.iter().enumerate() {
            files.push(open_read(&path.join(name(i)), entry.length as u64)?);
        }
        let archive = Self {
            path: path.to_path_buf(),
            location,
            manifest,
            raw_manifest: raw,
            entries,
            files,
            pin,
            #[cfg(test)]
            fault: 0,
        };
        Ok(archive)
    }
    pub fn checkpoint(&self) -> RecoveryCheckpoint {
        self.pin
    }

    fn check_namespace(&self) -> Result<(), PoolError> {
        self.location.check(&self.path)?;
        directory(&self.path, self.entries.len())?;
        namespace::check_file(
            &self.path.join(MANIFEST),
            &self.manifest,
            self.raw_manifest.len() as u64,
        )?;
        for (i, (file, entry)) in self.files.iter().zip(&self.entries).enumerate() {
            namespace::check_file(&self.path.join(name(i)), file, entry.length as u64)?;
        }
        Ok(())
    }

    fn check_bytes(&mut self) -> Result<(), PoolError> {
        self.check_namespace()?;
        let meta = self.manifest.metadata().map_err(|_| PoolError::Storage)?;
        if !regular(&meta) || meta.len() != self.raw_manifest.len() as u64 {
            return Err(PoolError::Corrupt);
        }
        self.manifest.rewind().map_err(|_| PoolError::Storage)?;
        let mut raw = vec![0; self.raw_manifest.len()];
        self.manifest
            .read_exact(&mut raw)
            .map_err(|_| PoolError::Corrupt)?;
        require_eof(&mut self.manifest)?;
        if raw != self.raw_manifest {
            return Err(PoolError::Corrupt);
        }
        let mut total = Sha256::new();
        let mut buffer = [0; CHUNK];
        for (file, entry) in self.files.iter_mut().zip(&self.entries) {
            let meta = file.metadata().map_err(|_| PoolError::Storage)?;
            if !regular(&meta) || meta.len() != entry.length as u64 {
                return Err(PoolError::Corrupt);
            }
            file.rewind().map_err(|_| PoolError::Storage)?;
            let mut left = entry.length as usize;
            let mut hash = Sha256::new();
            while left != 0 {
                let take = left.min(buffer.len());
                file.read_exact(&mut buffer[..take])
                    .map_err(|_| PoolError::Corrupt)?;
                hash.update(&buffer[..take]);
                total.update(&buffer[..take]);
                left -= take;
            }
            require_eof(file)?;
            if Hash::from(hash.finalize()) != entry.hash
                || file.metadata().map_err(|_| PoolError::Storage)?.len() != entry.length as u64
            {
                return Err(PoolError::Corrupt);
            }
        }
        if Hash::from(total.finalize()) != self.pin.journal_hash {
            return Err(PoolError::Corrupt);
        }
        self.check_namespace()
    }
    fn reader(&mut self) -> Result<SegmentReader<'_>, PoolError> {
        for file in &mut self.files {
            file.rewind().map_err(|_| PoolError::Storage)?;
        }
        Ok(SegmentReader {
            files: &mut self.files,
            entries: &self.entries,
            index: 0,
            position: 0,
            failed: false,
        })
    }
    /// Revalidates every original record using the same genuine state machine.
    /// Nothing is accepted on segment checksums alone and no partial tip escapes.
    pub fn verify(&mut self) -> Result<(), PoolError> {
        self.replay_checked(|_, _, _, _| Ok(())).map(|_| ())
    }
    // Private visitors only discard metadata or build an UNPUBLISHED index.
    // Both paths verify the complete archive, including final bytes/namespace.
    fn replay_checked(
        &mut self,
        mut visit: impl FnMut(u64, u64, &Summary, &Summary) -> Result<(), PoolError>,
    ) -> Result<u64, PoolError> {
        self.check_bytes()?;
        let pin = self.pin;
        let mut reader = self.reader()?;
        let header = read_header(&mut reader, pin.length)?;
        let state = State::from_policy(&header.initial, header.signing_domain)?;
        if state.genesis != pin.genesis {
            return Err(PoolError::Genesis);
        }
        let mut before = state.summary();
        let mut start = header.length;
        let verifier = AuthorizationVerifier::new();
        let mut replay = Replay::new(&mut reader, pin.length, header.length, state)?;
        while let Some(block) = replay.next_block(&verifier)? {
            let end = replay.byte_position()?;
            visit(start, end, &before, &block.result)?;
            before = block.result;
            start = end;
        }
        let (_, summary) = replay.finish()?;
        if summary.height != pin.height || summary.app_hash != pin.app_hash {
            return Err(PoolError::Stale);
        }
        self.check_bytes()?;
        Ok(header.length)
    }
    /// Restores the original flat journal ONLY to a new file. Neither the
    /// archive nor any existing target is overwritten or automatically repaired.
    pub fn restore_new(&mut self, target: &Path) -> Result<RecoveryCheckpoint, PoolError> {
        if !target.is_absolute() {
            return Err(PoolError::Bounds);
        }
        // Detect a persistently replaced source path before destination checks
        // or creating output. Never validate detached old handles as new names.
        self.check_namespace()?;
        // A new output INSIDE this archive would change its exact file set and
        // invalidate the source. Resolve trusted parent aliases before writing.
        let parent = fs::canonicalize(target.parent().ok_or(PoolError::Bounds)?)
            .map_err(|_| PoolError::Storage)?;
        let archive = fs::canonicalize(&self.path).map_err(|_| PoolError::Storage)?;
        if parent.starts_with(&archive) {
            return Err(PoolError::Bounds);
        }
        self.verify()?;
        let pin = self.pin;
        #[cfg(test)]
        let fault = self.fault;
        let mut file = create_file(target)?;
        let mut reader = self.reader()?;
        let mut left = pin.length;
        let mut buffer = [0; CHUNK];
        while left != 0 {
            let n = left.min(CHUNK as u64) as usize;
            reader
                .read_exact(&mut buffer[..n])
                .map_err(|_| PoolError::Corrupt)?;
            #[cfg(test)]
            if fault == 1 {
                file.write_all(&buffer[..n / 2])
                    .map_err(|_| PoolError::Storage)?;
                return Err(PoolError::Storage);
            }
            file.write_all(&buffer[..n])
                .map_err(|_| PoolError::Storage)?;
            left -= n as u64;
        }
        require_eof(&mut reader)?;
        file.sync_all().map_err(|_| PoolError::Storage)?;
        sync_parent(target)?;
        #[cfg(test)]
        if fault == 2 {
            return Err(PoolError::Storage);
        }
        let checked = verify_locked(file, pin)?;
        pin.matches(&checked)?;
        self.verify()?;
        Ok(pin)
    }
}

impl RecoveryArchive {
    /// Create an immutable segmented backup. MANIFEST is written LAST, but its
    /// existence alone never establishes success. Failure leaves a partial or
    /// complete NEW directory for explicit verification; no deletion or retry.
    pub fn pack_new(&mut self, target: &Path) -> Result<SegmentedArchive, PoolError> {
        if !target.is_absolute() {
            return Err(PoolError::Bounds);
        }
        let pin = self.checkpoint;
        if fingerprint(&mut self.store.file, pin.length)? != pin.journal_hash {
            return Err(PoolError::Corrupt);
        }
        let builder = fs::DirBuilder::new();
        #[cfg(unix)]
        let builder = {
            use std::os::unix::fs::DirBuilderExt;
            let mut builder = builder;
            builder.mode(0o700);
            builder
        };
        builder.create(target).map_err(|_| PoolError::Storage)?;
        let location = namespace::Directory::open(target)?;
        let mut entries = Vec::new();
        let mut files = Vec::new();
        entries
            .try_reserve_exact(count(pin))
            .map_err(|_| PoolError::Storage)?;
        files
            .try_reserve_exact(count(pin))
            .map_err(|_| PoolError::Storage)?;
        self.store.file.rewind().map_err(|_| PoolError::Storage)?;
        let mut buffer = [0; CHUNK];
        for i in 0..count(pin) {
            let length = segment_length(pin, i);
            let mut file = create_file(&target.join(name(i)))?;
            let mut hash = Sha256::new();
            let mut left = length as usize;
            while left != 0 {
                let n = left.min(buffer.len());
                self.store
                    .file
                    .read_exact(&mut buffer[..n])
                    .map_err(|_| PoolError::Corrupt)?;
                #[cfg(test)]
                if self.fault == 3 {
                    file.write_all(&buffer[..n / 2])
                        .map_err(|_| PoolError::Storage)?;
                    return Err(PoolError::Storage);
                }
                file.write_all(&buffer[..n])
                    .map_err(|_| PoolError::Storage)?;
                hash.update(&buffer[..n]);
                left -= n;
            }
            file.sync_all().map_err(|_| PoolError::Storage)?;
            entries.push(Entry {
                length,
                hash: hash.finalize().into(),
            });
            files.push(file);
        }
        require_eof(&mut self.store.file)?;
        if fingerprint(&mut self.store.file, pin.length)? != pin.journal_hash {
            return Err(PoolError::Corrupt);
        }
        #[cfg(test)]
        if self.fault == 4 {
            return Err(PoolError::Storage);
        }
        let raw_manifest = encode(pin, &entries)?;
        let mut manifest = create_file(&target.join(MANIFEST))?;
        manifest
            .write_all(&raw_manifest)
            .map_err(|_| PoolError::Storage)?;
        manifest.sync_all().map_err(|_| PoolError::Storage)?;
        sync_parent(&target.join(MANIFEST))?;
        sync_parent(target)?;
        #[cfg(test)]
        if self.fault == 5 {
            return Err(PoolError::Storage);
        }
        let mut archive = SegmentedArchive {
            path: target.to_path_buf(),
            location,
            manifest,
            raw_manifest,
            entries,
            files,
            pin,
            #[cfg(test)]
            fault: 0,
        };
        archive.verify()?; // Through the owning locked handles, including on Windows.
        if fingerprint(&mut self.store.file, pin.length)? != pin.journal_hash {
            return Err(PoolError::Corrupt);
        }
        Ok(archive)
    }
}

// Only this private reader feeds replay/copy. Crossing a segment is not EOF;
// truncation and unexpected suffixes are errors, not skippable missing chunks.
struct SegmentReader<'a, R: Read = File> {
    files: &'a mut [R],
    entries: &'a [Entry],
    index: usize,
    position: u64,
    failed: bool,
}
impl<R: Read> Read for SegmentReader<'_, R> {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if out.is_empty() {
            return Ok(0);
        }
        if self.failed {
            return Err(io::Error::other(
                "segmented input unavailable after read failure",
            ));
        }
        let result = self.read_next(out);
        // Interrupted consumes no bytes and remains retryable. Every other
        // failure invalidates this reader, even if its source later recovers.
        // Replay already discards failed state; this is a second, lower boundary.
        if result
            .as_ref()
            .is_err_and(|err| err.kind() != io::ErrorKind::Interrupted)
        {
            self.failed = true;
        }
        result
    }
}
impl<R: Read> SegmentReader<'_, R> {
    fn read_next(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if self.files.len() != self.entries.len() {
            return Err(io::ErrorKind::InvalidData.into());
        }
        while self.index < self.files.len() {
            let size = self.entries[self.index].length as u64;
            if size == 0 || size > SEGMENT_BYTES || self.position > size {
                return Err(io::ErrorKind::InvalidData.into());
            }
            let file = &mut self.files[self.index];
            if self.position == size {
                require_eof(file).map_err(|_| io::Error::other("invalid segment EOF"))?;
                self.index += 1;
                self.position = 0;
                continue;
            }
            let n = out.len().min((size - self.position) as usize);
            let got = file.read(&mut out[..n])?;
            if got == 0 {
                return Err(io::ErrorKind::UnexpectedEof.into());
            }
            self.position += got as u64;
            return Ok(got);
        }
        Ok(0)
    }
}

#[cfg(test)]
mod tests;

#[cfg(test)]
mod reader_tests;
