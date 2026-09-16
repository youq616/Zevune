//! Replay-derived navigation for one exact, independently pinned public archive.
//! No deserializer, imported state, proof shortcut, or on-disk format change.
use super::*;
use crate::pool::{Summary, MAX_RECORD_BYTES};

/// One full original journal frame, including its prefix and checksum. Its
/// bytes may cross segment boundaries. App hashes refer to BLOCK boundaries,
/// never to a partly stored record or to a segment boundary in the middle of it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecordLocation {
    height: u64,
    offset: u64,
    length: u64,
    before_app_hash: Hash,
    after_app_hash: Hash,
}
impl RecordLocation {
    pub fn height(&self) -> u64 {
        self.height
    }
    pub fn offset(&self) -> u64 {
        self.offset
    }
    pub fn length(&self) -> u64 {
        self.length
    }
    pub fn before_app_hash(&self) -> Hash {
        self.before_app_hash
    }
    pub fn after_app_hash(&self) -> Hash {
        self.after_app_hash
    }
    /// Zero-based segment indices; the last byte belongs to last_segment.
    pub fn first_segment(&self) -> u32 {
        (self.offset / SEGMENT_BYTES) as u32
    }
    pub fn last_segment(&self) -> u32 {
        ((self.offset + self.length - 1) / SEGMENT_BYTES) as u32
    }
    pub fn first_segment_offset(&self) -> u32 {
        (self.offset % SEGMENT_BYTES) as u32
    }
    /// Exclusive end within last_segment, in 1..=SEGMENT_BYTES. An exact segment
    /// end is SEGMENT_BYTES, not zero in a non-existent following segment.
    pub fn last_segment_end(&self) -> u32 {
        ((self.offset + self.length - 1) % SEGMENT_BYTES + 1) as u32
    }
}

/// Immutable navigation metadata published only after full genuine replay,
/// pinned final-state comparison and the final file/namespace checks succeed.
/// This is historical metadata, not a claim that disk paths remain unchanged
/// after return. It is never accepted as input to recovery or live state APIs.
/// Every new archive operation must still perform its normal verification.
#[derive(Debug)]
pub struct VerifiedIndex {
    checkpoint: RecoveryCheckpoint,
    header_bytes: u64,
    records: Vec<RecordLocation>,
}
impl VerifiedIndex {
    pub fn checkpoint(&self) -> RecoveryCheckpoint {
        self.checkpoint
    }
    pub fn header_bytes(&self) -> u64 {
        self.header_bytes
    }
    pub fn records(&self) -> &[RecordLocation] {
        &self.records
    }
    /// O(1) lookup after validation, since accepted journal heights are exactly
    /// 1..=tip. Height zero is the genesis header, not a block/record location.
    /// Lookup performs no I/O and does not authorize reads of changed paths.
    pub fn locate_height(&self, height: u64) -> Result<&RecordLocation, PoolError> {
        let position = height.checked_sub(1).ok_or(PoolError::Height)?;
        let record = self
            .records
            .get(usize::try_from(position).map_err(|_| PoolError::Height)?)
            .ok_or(PoolError::Height)?;
        if record.height != height {
            return Err(PoolError::Corrupt);
        }
        Ok(record)
    }
}

// Only the replay visitor populates this builder. No serialized index is trusted
// or accepted. A visitor error discards the entire local builder at the caller.
struct Builder {
    pin: RecoveryCheckpoint,
    next_offset: Option<u64>,
    previous_hash: Option<Hash>,
    records: Vec<RecordLocation>,
}
impl Builder {
    fn new(pin: RecoveryCheckpoint) -> Result<Self, PoolError> {
        if pin.height > MAX_RECORDS || !(44..=MAX_JOURNAL_BYTES).contains(&pin.length) {
            return Err(PoolError::Bounds);
        }
        let mut records = Vec::new();
        records
            .try_reserve_exact(usize::try_from(pin.height).map_err(|_| PoolError::Bounds)?)
            .map_err(|_| PoolError::Storage)?;
        Ok(Self {
            pin,
            next_offset: None,
            previous_hash: None,
            records,
        })
    }
    fn push(
        &mut self,
        start: u64,
        end: u64,
        before: &Summary,
        after: &Summary,
    ) -> Result<(), PoolError> {
        let height = self.records.len() as u64 + 1;
        let length = end.checked_sub(start).ok_or(PoolError::Bounds)?;
        if height > self.pin.height
            || height > MAX_RECORDS
            || after.height != height
            || before.height != height - 1
            || start < 44
            || end > self.pin.length
            || !(150..=MAX_RECORD_BYTES as u64 + 36).contains(&length)
            || self.next_offset.is_some_and(|offset| offset != start)
            || self
                .previous_hash
                .is_some_and(|hash| hash != before.app_hash)
        {
            return Err(PoolError::Corrupt);
        }
        self.records.push(RecordLocation {
            height,
            offset: start,
            length,
            before_app_hash: before.app_hash,
            after_app_hash: after.app_hash,
        });
        self.next_offset = Some(end);
        self.previous_hash = Some(after.app_hash);
        Ok(())
    }
    fn finish(self, header_bytes: u64) -> Result<VerifiedIndex, PoolError> {
        if self.records.len() as u64 != self.pin.height
            || header_bytes < 44
            || header_bytes > self.pin.length
            || self
                .records
                .first()
                .is_some_and(|record| record.offset != header_bytes)
            || self.next_offset.unwrap_or(header_bytes) != self.pin.length
            || self
                .previous_hash
                .is_some_and(|hash| hash != self.pin.app_hash)
        {
            return Err(PoolError::Corrupt);
        }
        Ok(VerifiedIndex {
            checkpoint: self.pin,
            header_bytes,
            records: self.records,
        })
    }
}

impl SegmentedArchive {
    /// Open and build navigation using ONE full validation pass, not an open
    /// validation followed by another replay. The unchecked opener is private.
    pub fn open_indexed(
        path: &Path,
        pin: RecoveryCheckpoint,
    ) -> Result<(Self, VerifiedIndex), PoolError> {
        let mut archive = Self::open_unverified(path, pin)?;
        let index = archive.build_index()?;
        Ok((archive, index))
    }
    /// Revalidates even a previously opened archive. No cached file verdict is
    /// reused; corrupt later records cannot leave a successful prefix index.
    pub fn build_index(&mut self) -> Result<VerifiedIndex, PoolError> {
        let mut builder = Builder::new(self.pin)?;
        let header_bytes = self
            .replay_checked(|start, end, before, after| builder.push(start, end, before, after))?;
        builder.finish(header_bytes)
    }
}

#[cfg(test)]
mod tests;
