//! Bounded, checkpoint-pinned copies of PUBLIC journal bytes. Never copies a
//! validator signer, consensus database, wallet, or key. This is full replay,
//! not fast/state sync, compaction, a finality proof, or a latest-tip oracle.
use super::*;
use std::fs::Metadata;

const MAGIC: &[u8; 8] = b"ZVPRCP01";
pub const CHECKPOINT_BYTES: usize = 120;
const CHUNK: usize = 64 * 1024;

/// An independently retained pin for one exact committed journal. A pin obtained
/// together with untrusted bytes does not authenticate their origin/freshness.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RecoveryCheckpoint {
    genesis: Hash,
    height: u64,
    app_hash: Hash,
    length: u64,
    journal_hash: Hash,
}
impl RecoveryCheckpoint {
    pub fn height(&self) -> u64 {
        self.height
    }
    pub fn app_hash(&self) -> Hash {
        self.app_hash
    }
    pub fn length(&self) -> u64 {
        self.length
    }
    pub fn to_bytes(&self) -> [u8; CHECKPOINT_BYTES] {
        let mut out = [0; CHECKPOINT_BYTES];
        out[..8].copy_from_slice(MAGIC);
        out[8..40].copy_from_slice(&self.genesis);
        out[40..48].copy_from_slice(&self.height.to_be_bytes());
        out[48..80].copy_from_slice(&self.app_hash);
        out[80..88].copy_from_slice(&self.length.to_be_bytes());
        out[88..120].copy_from_slice(&self.journal_hash);
        out
    }
    pub fn from_bytes(raw: &[u8]) -> Result<Self, PoolError> {
        if raw.len() != CHECKPOINT_BYTES || &raw[..8] != MAGIC {
            return Err(PoolError::Bounds);
        }
        // Fixed length has been checked before every bounded array conversion.
        let result = Self {
            genesis: raw[8..40].try_into().map_err(|_| PoolError::Bounds)?,
            height: u64::from_be_bytes(raw[40..48].try_into().map_err(|_| PoolError::Bounds)?),
            app_hash: raw[48..80].try_into().map_err(|_| PoolError::Bounds)?,
            length: u64::from_be_bytes(raw[80..88].try_into().map_err(|_| PoolError::Bounds)?),
            journal_hash: raw[88..120].try_into().map_err(|_| PoolError::Bounds)?,
        };
        if result.genesis == [0; 32]
            || result.app_hash == [0; 32]
            || result.journal_hash == [0; 32]
            || result.height > MAX_RECORDS
            || !(44..=MAX_JOURNAL_BYTES).contains(&result.length)
        {
            return Err(PoolError::Bounds);
        }
        Ok(result)
    }
    fn matches(&self, store: &PoolStore) -> Result<(), PoolError> {
        if store.state.genesis != self.genesis || store.length != self.length {
            return Err(PoolError::Stale);
        }
        store.check_checkpoint(self.height, self.app_hash)
    }
}

impl PoolStore {
    /// Export an exact pin only after revalidating this owned store's full
    /// history and checking the file bytes before AND after replay. Does not
    /// include uncommitted candidates or prove that a peer disclosed its tip.
    pub fn recovery_checkpoint(&mut self) -> Result<RecoveryCheckpoint, PoolError> {
        let summary = self.summary()?;
        let result = (|| {
            let before = fingerprint(&mut self.file, self.length)?;
            self.verify_committed_history()?;
            if fingerprint(&mut self.file, self.length)? != before {
                return Err(PoolError::Corrupt);
            }
            Ok(RecoveryCheckpoint {
                genesis: self.state.genesis,
                height: summary.height,
                app_hash: summary.app_hash,
                length: self.length,
                journal_hash: before,
            })
        })();
        if result.is_err() {
            self.available = false;
        }
        result
    }
}

/// Read-only archive ownership. Its inner replayed store is private: callers
/// cannot use an archive verifier as a writable pool or alter its trusted pin.
/// Cooperating live writers hold exclusive locks and block opening this reader.
pub struct RecoveryArchive {
    store: PoolStore,
    checkpoint: RecoveryCheckpoint,
    #[cfg(test)]
    fault: u8,
}
impl RecoveryArchive {
    pub fn open(path: &Path, checkpoint: RecoveryCheckpoint) -> Result<Self, PoolError> {
        if !path.is_absolute() {
            return Err(PoolError::Bounds);
        }
        let before = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
        if !regular(&before) || before.len() != checkpoint.length {
            return Err(PoolError::Bounds);
        }
        let file = File::open(path).map_err(|_| PoolError::Storage)?;
        file.try_lock_shared().map_err(|_| PoolError::Locked)?;
        let opened = file.metadata().map_err(|_| PoolError::Storage)?;
        if !regular(&opened) || opened.len() != before.len() {
            return Err(PoolError::Corrupt);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if before.dev() != opened.dev() || before.ino() != opened.ino() {
                return Err(PoolError::Corrupt);
            }
        }
        let store = verify_locked(file, checkpoint)?;
        Ok(Self {
            store,
            checkpoint,
            #[cfg(test)]
            fault: 0,
        })
    }
    pub fn checkpoint(&self) -> RecoveryCheckpoint {
        self.checkpoint
    }
    /// Copies to an atomic create-new file, syncs it, then independently replays
    /// it THROUGH THE OWNING HANDLE. No unlock/reopen gap or Windows lock clash.
    /// Failure can leave a partial OR complete target. Never auto-retry, delete,
    /// truncate, or reset signer files. A successful copy still is not a complete
    /// validator backup; consensus and signing state must be reconciled separately.
    pub fn copy_new(&mut self, path: &Path) -> Result<RecoveryCheckpoint, PoolError> {
        if !path.is_absolute() {
            return Err(PoolError::Bounds);
        }
        if fingerprint(&mut self.store.file, self.checkpoint.length)?
            != self.checkpoint.journal_hash
        {
            return Err(PoolError::Corrupt);
        }
        let mut opts = OpenOptions::new();
        opts.create_new(true).read(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            opts.mode(0o600);
        }
        let mut target = opts.open(path).map_err(|_| PoolError::Storage)?;
        target.try_lock().map_err(|_| PoolError::Locked)?;
        self.store.file.rewind().map_err(|_| PoolError::Storage)?;
        let mut left = self.checkpoint.length;
        let mut buffer = [0; CHUNK];
        while left != 0 {
            let take = usize::try_from(left.min(CHUNK as u64)).map_err(|_| PoolError::Bounds)?;
            self.store
                .file
                .read_exact(&mut buffer[..take])
                .map_err(|_| PoolError::Corrupt)?;
            #[cfg(test)]
            if self.fault == 1 {
                target
                    .write_all(&buffer[..take / 2])
                    .map_err(|_| PoolError::Storage)?;
                return Err(PoolError::Storage);
            }
            target
                .write_all(&buffer[..take])
                .map_err(|_| PoolError::Storage)?;
            left -= take as u64;
        }
        target.sync_all().map_err(|_| PoolError::Storage)?;
        sync_parent(path)?;
        #[cfg(test)]
        if self.fault == 2 {
            return Err(PoolError::Storage);
        }
        // Checksums are only damage pins, so do not replace real replay with
        // equality of the streamed hash or previously computed state summary.
        let checked = verify_locked(target, self.checkpoint)?;
        self.checkpoint.matches(&checked)?;
        if fingerprint(&mut self.store.file, self.checkpoint.length)?
            != self.checkpoint.journal_hash
        {
            return Err(PoolError::Corrupt);
        }
        Ok(self.checkpoint)
    }
}

fn regular(meta: &Metadata) -> bool {
    if !meta.file_type().is_file() {
        return false;
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
fn sync_parent(path: &Path) -> Result<(), PoolError> {
    #[cfg(unix)]
    {
        File::open(path.parent().ok_or(PoolError::Bounds)?)
            .and_then(|f| f.sync_all())
            .map_err(|_| PoolError::Storage)?;
    }
    #[cfg(not(unix))]
    let _ = path; // No portable directory-fsync promise on Windows.
    Ok(())
}
fn fingerprint(file: &mut File, length: u64) -> Result<Hash, PoolError> {
    if !(44..=MAX_JOURNAL_BYTES).contains(&length) {
        return Err(PoolError::Bounds);
    }
    let meta = file.metadata().map_err(|_| PoolError::Storage)?;
    if !regular(&meta) || meta.len() != length {
        return Err(PoolError::Corrupt);
    }
    file.rewind().map_err(|_| PoolError::Storage)?;
    let mut hash = Sha256::new();
    let mut buffer = [0; CHUNK];
    let mut left = length;
    while left != 0 {
        let take = usize::try_from(left.min(CHUNK as u64)).map_err(|_| PoolError::Bounds)?;
        file.read_exact(&mut buffer[..take])
            .map_err(|_| PoolError::Corrupt)?;
        hash.update(&buffer[..take]);
        left -= take as u64;
    }
    if file
        .read(&mut buffer[..1])
        .map_err(|_| PoolError::Storage)?
        != 0
        || file.metadata().map_err(|_| PoolError::Storage)?.len() != length
    {
        return Err(PoolError::Corrupt);
    }
    Ok(hash.finalize().into())
}
fn verify_locked(mut file: File, checkpoint: RecoveryCheckpoint) -> Result<PoolStore, PoolError> {
    if fingerprint(&mut file, checkpoint.length)? != checkpoint.journal_hash {
        return Err(PoolError::Corrupt);
    }
    file.rewind().map_err(|_| PoolError::Storage)?;
    let mut fixed = [0; 40];
    file.read_exact(&mut fixed)
        .map_err(|_| PoolError::Corrupt)?;
    if fixed[8..] != Sha256::digest(NETWORK.as_bytes())[..] {
        return Err(PoolError::Genesis);
    }
    let domain = match &fixed[..8] {
        bytes if bytes == FILE_MAGIC => None,
        bytes if bytes == BOUND_FILE_MAGIC => {
            let mut hash = [0; 32];
            file.read_exact(&mut hash).map_err(|_| PoolError::Corrupt)?;
            if hash == [0; 32] {
                return Err(PoolError::Domain);
            }
            Some(hash)
        }
        _ => return Err(PoolError::Genesis),
    };
    let mut encoded_count = [0; 4];
    file.read_exact(&mut encoded_count)
        .map_err(|_| PoolError::Corrupt)?;
    let count = u32::from_be_bytes(encoded_count) as usize;
    let header_size = if domain.is_some() { 76 } else { 44 };
    if count > MAX_COMMITMENTS || header_size + count as u64 * 32 > checkpoint.length {
        return Err(PoolError::Bounds);
    }
    let mut initial = Vec::with_capacity(count);
    for _ in 0..count {
        let mut cm = [0; 32];
        file.read_exact(&mut cm).map_err(|_| PoolError::Corrupt)?;
        initial.push(cm);
    }
    let genesis: Hash = Sha256::digest(genesis_bytes_policy(&initial, domain)?).into();
    if genesis != checkpoint.genesis {
        return Err(PoolError::Genesis);
    }
    // Reuse the same isolated bounded replay as writable startup; ownership
    // of this handle and its existing lock is retained throughout.
    let mut store = PoolStore::replay_locked_file(file, &initial, domain)?;
    checkpoint.matches(&store)?;
    if fingerprint(&mut store.file, checkpoint.length)? != checkpoint.journal_hash {
        return Err(PoolError::Corrupt);
    }
    Ok(store)
}

#[cfg(test)]
mod tests;
