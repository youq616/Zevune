//! A read-only description of an exact physical append between independently
//! trusted pins. This is not an incremental package, snapshot, or reusable proof.
use super::{ActiveArchive, ActiveRecoveryCheckpoint, PoolError};
use crate::pool::active::{MAX_SEGMENTS, SEGMENT_BYTES};

/// Public journal bytes from one later segment. No path or writable capability
/// is retained, and the fields cannot be modified or constructed by a caller.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ActiveAppendRange {
    segment_index: u32,
    offset: u32,
    length: u32,
}

impl ActiveAppendRange {
    pub fn segment_index(&self) -> u32 {
        self.segment_index
    }
    pub fn offset(&self) -> u32 {
        self.offset
    }
    pub fn length(&self) -> u32 {
        self.length
    }
}

/// An immutable, bounded observation of two fully replayed archives. Retaining
/// this value does not authenticate future file contents, origin, or finality.
#[derive(Debug, Eq, PartialEq)]
pub struct ActiveIncrementalPlan {
    base_checkpoint: ActiveRecoveryCheckpoint,
    checkpoint: ActiveRecoveryCheckpoint,
    reused_bytes: u64,
    appended_bytes: u64,
    unchanged_segment_count: u32,
    new_segment_count: u32,
    ranges: Vec<ActiveAppendRange>,
}

impl ActiveIncrementalPlan {
    pub fn base_checkpoint(&self) -> ActiveRecoveryCheckpoint {
        self.base_checkpoint
    }
    pub fn checkpoint(&self) -> ActiveRecoveryCheckpoint {
        self.checkpoint
    }
    pub fn reused_bytes(&self) -> u64 {
        self.reused_bytes
    }
    pub fn appended_bytes(&self) -> u64 {
        self.appended_bytes
    }
    pub fn unchanged_segment_count(&self) -> u32 {
        self.unchanged_segment_count
    }
    pub fn new_segment_count(&self) -> u32 {
        self.new_segment_count
    }
    pub fn ranges(&self) -> &[ActiveAppendRange] {
        &self.ranges
    }

    fn checked(
        base: ActiveRecoveryCheckpoint,
        later: ActiveRecoveryCheckpoint,
        unchanged: u32,
        ranges: Vec<ActiveAppendRange>,
    ) -> Result<Self, PoolError> {
        let new_count = later
            .segment_count
            .checked_sub(base.segment_count)
            .ok_or(PoolError::Stale)?;
        if ranges.len() > MAX_SEGMENTS || unchanged > base.segment_count {
            return Err(PoolError::Bounds);
        }
        let mut sum = 0u64;
        let mut previous = None;
        let mut next_new = base.segment_count;
        for range in &ranges {
            let index = range.segment_index;
            if range.length == 0
                || index >= later.segment_count
                || previous.is_some_and(|prior| index <= prior)
                || u64::from(range.offset)
                    .checked_add(u64::from(range.length))
                    .ok_or(PoolError::Bounds)?
                    > SEGMENT_BYTES
            {
                return Err(PoolError::Corrupt);
            }
            if index < base.segment_count {
                if index.checked_add(1).ok_or(PoolError::Bounds)? != base.segment_count
                    || range.offset == 0
                {
                    return Err(PoolError::Corrupt);
                }
            } else {
                if range.offset != 0 || index != next_new {
                    return Err(PoolError::Corrupt);
                }
                next_new = next_new.checked_add(1).ok_or(PoolError::Bounds)?;
            }
            previous = Some(index);
            sum = sum
                .checked_add(u64::from(range.length))
                .ok_or(PoolError::Bounds)?;
        }
        if next_new != later.segment_count
            || unchanged
                .checked_add(u32::try_from(ranges.len()).map_err(|_| PoolError::Bounds)?)
                .ok_or(PoolError::Bounds)?
                != later.segment_count
            || base.length.checked_add(sum).ok_or(PoolError::Bounds)? != later.length
        {
            return Err(PoolError::Corrupt);
        }
        Ok(Self {
            base_checkpoint: base,
            checkpoint: later,
            reused_bytes: base.length,
            appended_bytes: sum,
            unchanged_segment_count: unchanged,
            new_segment_count: new_count,
            ranges,
        })
    }
}

impl ActiveArchive {
    /// Fully replay BOTH retained archives on every call, compare every reused
    /// physical byte, and recheck both entire layouts before returning any plan.
    /// Two independently trusted pins are required; neither proves the other's
    /// origin, a latest height, or consensus finality. No archive file is written.
    pub fn incremental_plan(
        &mut self,
        later: &mut ActiveArchive,
    ) -> Result<ActiveIncrementalPlan, PoolError> {
        self.pin.check_bounds()?;
        later.pin.check_bounds()?;
        if self.pin.genesis != later.pin.genesis
            || self.pin.header_length != later.pin.header_length
        {
            return Err(PoolError::Genesis);
        }
        if later.pin.height < self.pin.height
            || (later.pin.height == self.pin.height && later.pin != self.pin)
            || (later.pin.height > self.pin.height && later.pin.length <= self.pin.length)
            || later.pin.segment_count < self.pin.segment_count
        {
            return Err(PoolError::Stale);
        }
        self.verify()?;
        later.verify()?;
        let capacity = usize::try_from(later.pin.segment_count).map_err(|_| PoolError::Bounds)?;
        if capacity > MAX_SEGMENTS {
            return Err(PoolError::Bounds);
        }
        let mut ranges = Vec::new();
        ranges
            .try_reserve_exact(capacity)
            .map_err(|_| PoolError::Storage)?;
        let unchanged = self.journal.visit_append_ranges(
            &self.file,
            &later.journal,
            &later.file,
            |segment_index, offset, length| {
                if ranges.len() >= capacity {
                    return Err(PoolError::Bounds);
                }
                ranges.push(ActiveAppendRange {
                    segment_index,
                    offset,
                    length,
                });
                Ok(())
            },
        )?;
        #[cfg(test)]
        {
            // Test-only simulations of late OUTSIDE modifications. Unlike
            // production, these deliberately change files and leave them so.
            // Existing copy_new fault numbers 1..6 retain their own semantics.
            if self.fault == 7 {
                super::fault_entry(self.journal.path(), ".incremental-base-fault")?;
            }
            if later.fault == 8 {
                super::fault_entry(later.journal.path(), ".incremental-later-fault")?;
            }
            if self.fault == 9 {
                tests::change_tail(self.journal.path())?;
            }
            if later.fault == 10 {
                tests::change_tail(later.journal.path())?;
            }
        }
        self.check_bytes()?;
        later.check_bytes()?;
        ActiveIncrementalPlan::checked(self.pin, later.pin, unchanged, ranges)
    }
}

#[cfg(test)]
mod tests;
