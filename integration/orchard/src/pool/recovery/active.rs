//! Independently pinned, exact copies of PUBLIC ActiveSegmentsV1 directories.
//! Full replay, not snapshots, pruning, latest-tip authentication or validator
//! recovery. No wallet, signer state, consensus database or key is copied.
use super::super::active::ActiveJournal;
use super::*;

const MAGIC: &[u8; 8] = b"ZVARCP01";
pub const ACTIVE_CHECKPOINT_BYTES: usize = 128;
const MIN_HEADER: u64 = 76;
const MIN_FRAME: u64 = 150;

/// A pin must be retained independently from untrusted directory bytes. Its
/// hashes bind exact bytes and layout; they do not establish origin or finality.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ActiveRecoveryCheckpoint {
    genesis: Hash,
    height: u64,
    app_hash: Hash,
    length: u64,
    header_length: u32,
    segment_count: u32,
    layout_hash: Hash,
}

impl ActiveRecoveryCheckpoint {
    pub fn height(&self) -> u64 {
        self.height
    }
    pub fn app_hash(&self) -> Hash {
        self.app_hash
    }
    pub fn length(&self) -> u64 {
        self.length
    }
    pub fn header_length(&self) -> u32 {
        self.header_length
    }
    pub fn segment_count(&self) -> u32 {
        self.segment_count
    }
    pub fn to_bytes(&self) -> [u8; ACTIVE_CHECKPOINT_BYTES] {
        let mut raw = [0; ACTIVE_CHECKPOINT_BYTES];
        raw[..8].copy_from_slice(MAGIC);
        raw[8..40].copy_from_slice(&self.genesis);
        raw[40..48].copy_from_slice(&self.height.to_be_bytes());
        raw[48..80].copy_from_slice(&self.app_hash);
        raw[80..88].copy_from_slice(&self.length.to_be_bytes());
        raw[88..92].copy_from_slice(&self.header_length.to_be_bytes());
        raw[92..96].copy_from_slice(&self.segment_count.to_be_bytes());
        raw[96..128].copy_from_slice(&self.layout_hash);
        raw
    }
    pub fn from_bytes(raw: &[u8]) -> Result<Self, PoolError> {
        if raw.len() != ACTIVE_CHECKPOINT_BYTES || &raw[..8] != MAGIC {
            return Err(PoolError::Bounds);
        }
        let pin = Self {
            genesis: raw[8..40].try_into().map_err(|_| PoolError::Bounds)?,
            height: u64::from_be_bytes(raw[40..48].try_into().map_err(|_| PoolError::Bounds)?),
            app_hash: raw[48..80].try_into().map_err(|_| PoolError::Bounds)?,
            length: u64::from_be_bytes(raw[80..88].try_into().map_err(|_| PoolError::Bounds)?),
            header_length: u32::from_be_bytes(
                raw[88..92].try_into().map_err(|_| PoolError::Bounds)?,
            ),
            segment_count: u32::from_be_bytes(
                raw[92..96].try_into().map_err(|_| PoolError::Bounds)?,
            ),
            layout_hash: raw[96..128].try_into().map_err(|_| PoolError::Bounds)?,
        };
        pin.check_bounds()?;
        Ok(pin)
    }

    fn check_bounds(&self) -> Result<(), PoolError> {
        let profile = StorageProfile::ActiveSegmentsV1;
        let header = u64::from(self.header_length);
        let segments = u64::from(self.segment_count);
        let max_header = MIN_HEADER
            .checked_add(32 * MAX_COMMITMENTS as u64)
            .ok_or(PoolError::Bounds)?;
        if self.genesis == [0; 32]
            || self.app_hash == [0; 32]
            || self.layout_hash == [0; 32]
            || self.height > profile.max_records()
            || self.length > profile.max_journal_bytes()
            || segments > super::super::active::MAX_SEGMENTS as u64
            || !(MIN_HEADER..=max_header).contains(&header)
            || !(header - MIN_HEADER).is_multiple_of(32)
        {
            return Err(PoolError::Bounds);
        }
        let records = self.length.checked_sub(header).ok_or(PoolError::Bounds)?;
        if self.height == 0 {
            if segments != 0 || records != 0 {
                return Err(PoolError::Bounds);
            }
        } else if segments == 0
            || segments > self.height
            || records
                < MIN_FRAME
                    .checked_mul(self.height)
                    .ok_or(PoolError::Bounds)?
            || records
                > segments
                    .checked_mul(super::super::active::SEGMENT_BYTES)
                    .ok_or(PoolError::Bounds)?
        {
            return Err(PoolError::Bounds);
        }
        Ok(())
    }
}

impl PoolStore {
    /// Export the exact committed directory only after fresh genuine replay,
    /// bracketed by full bytes and retained-name checks. Prepared blocks are not
    /// included, consumed or changed. Unsupported legacy stores remain usable.
    pub fn active_recovery_checkpoint(&mut self) -> Result<ActiveRecoveryCheckpoint, PoolError> {
        if self.active.is_none() {
            return Err(PoolError::Bounds);
        }
        let committed = self.summary()?;
        let result = (|| {
            let journal = self.active.as_ref().ok_or(PoolError::Bounds)?;
            let before = journal.layout_hash(&self.file)?;
            let (state, _) = Self::replay_active_handles(&self.file, journal, self.state.genesis)?;
            if state.genesis != self.state.genesis
                || state.summary() != committed
                || journal.length() != self.length
            {
                return Err(PoolError::Corrupt);
            }
            if journal.layout_hash(&self.file)? != before {
                return Err(PoolError::Corrupt);
            }
            let (_, segments, _) = journal.capacity();
            let pin = ActiveRecoveryCheckpoint {
                genesis: state.genesis,
                height: committed.height,
                app_hash: committed.app_hash,
                length: self.length,
                header_length: u32::try_from(journal.header_length())
                    .map_err(|_| PoolError::Bounds)?,
                segment_count: segments,
                layout_hash: before,
            };
            pin.check_bounds()?;
            Ok(pin)
        })();
        if result.is_err() {
            self.available = false;
        }
        result
    }
}

/// Read-only source ownership, with the root shared lock and all directory/file
/// names retained. No writable state or partly authenticated history escapes.
pub struct ActiveArchive {
    file: File,
    journal: ActiveJournal,
    pin: ActiveRecoveryCheckpoint,
    #[cfg(test)]
    fault: u8,
}

impl ActiveArchive {
    pub fn open(path: &Path, pin: ActiveRecoveryCheckpoint) -> Result<Self, PoolError> {
        pin.check_bounds()?;
        let (file, journal) = ActiveJournal::open_readonly(path, pin.header_length)?;
        let mut archive = Self {
            file,
            journal,
            pin,
            #[cfg(test)]
            fault: 0,
        };
        archive.verify()?;
        Ok(archive)
    }

    pub fn checkpoint(&self) -> ActiveRecoveryCheckpoint {
        self.pin
    }

    fn check_bytes(&self) -> Result<(), PoolError> {
        let (length, count, _) = self.journal.capacity();
        if length != self.pin.length
            || count != self.pin.segment_count
            || self.journal.header_length() != u64::from(self.pin.header_length)
        {
            return Err(PoolError::Stale);
        }
        if self.journal.layout_hash(&self.file)? != self.pin.layout_hash {
            return Err(PoolError::Corrupt);
        }
        Ok(())
    }

    /// Reconstructs the complete state with a NEW authorization verifier on
    /// every call; layout hashes and previous successful checks cannot replace
    /// replay, physical frame boundaries or the independently retained tip.
    pub fn verify(&mut self) -> Result<(), PoolError> {
        self.check_bytes()?;
        let (state, _) =
            PoolStore::replay_active_handles(&self.file, &self.journal, self.pin.genesis)?;
        if state.genesis != self.pin.genesis {
            return Err(PoolError::Genesis);
        }
        let summary = state.summary();
        if summary.height != self.pin.height || summary.app_hash != self.pin.app_hash {
            return Err(PoolError::Stale);
        }
        self.check_bytes()
    }

    /// Copy every original file into a NEW directory, retain all owning handles,
    /// and authenticate the exact target before return. Failure may leave a
    /// partial OR complete target; it never removes, overwrites, repairs or retries.
    pub fn copy_new(&mut self, target: &Path) -> Result<ActiveRecoveryCheckpoint, PoolError> {
        self.journal.check(&self.file)?;
        if !target.is_absolute() {
            return Err(PoolError::Bounds);
        }
        let parent = fs::canonicalize(target.parent().ok_or(PoolError::Bounds)?)
            .map_err(|_| PoolError::Storage)?;
        let source = fs::canonicalize(self.journal.path()).map_err(|_| PoolError::Storage)?;
        if parent.starts_with(&source) {
            return Err(PoolError::Bounds);
        }
        match fs::symlink_metadata(target) {
            Ok(_) => return Err(PoolError::Storage),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err(PoolError::Storage),
        }
        self.verify()?;
        #[cfg(test)]
        {
            // Physical test points 1..4 are private and never select a weaker
            // production copy. Points 5/6 below simulate late outside changes.
            self.journal.fault = self.fault;
        }
        let (file, journal) = self.journal.copy_new(&self.file, target)?;
        let mut checked = Self {
            file,
            journal,
            pin: self.pin,
            #[cfg(test)]
            fault: 0,
        };
        checked.verify()?; // Original creation handles: no unlock/reopen window.
        #[cfg(test)]
        if self.fault == 5 {
            fault_entry(self.journal.path(), ".archive-final-source-fault")?;
        }
        self.verify()?;
        #[cfg(test)]
        if self.fault == 6 {
            fault_entry(target, ".archive-final-target-fault")?;
        }
        checked.check_bytes()?;
        Ok(self.pin)
    }
}

#[cfg(test)]
fn fault_entry(path: &Path, name: &str) -> Result<(), PoolError> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path.join(name))
        .map_err(|_| PoolError::Storage)?;
    file.write_all(b"test-only late namespace change")
        .map_err(|_| PoolError::Storage)
}

#[cfg(test)]
mod tests;
