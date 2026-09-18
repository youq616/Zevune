//! Immutable packages of exact PUBLIC append bytes. Two independently trusted
//! pins and a complete base are mandatory; the package never imports state or
//! replaces genuine replay with its metadata, hashes, or a previous result.
use super::incremental::{check_pins, ActiveAppendRange, ActiveIncrementalPlan};
use super::{ActiveArchive, ActiveRecoveryCheckpoint, PoolError};
use crate::pool::active::package::{JoinedJournal, NewTarget, RangeSpec, RetainedPackage};
use crate::pool::active::MAX_SEGMENTS;
use crate::pool::replay::{read_header_profile, Replay};
use crate::pool::{State, StorageProfile};
use crate::wire::AuthorizationVerifier;
use std::path::Path;

const MAGIC: &[u8; 8] = b"ZVAIPK01";
const FIXED_BYTES: usize = 268;
const RANGE_BYTES: usize = 12;
const MAX_METADATA: usize = FIXED_BYTES + MAX_SEGMENTS * RANGE_BYTES;

fn metadata_length(count: usize) -> Result<usize, PoolError> {
    if count > MAX_SEGMENTS {
        return Err(PoolError::Bounds);
    }
    let length = FIXED_BYTES
        .checked_add(count.checked_mul(RANGE_BYTES).ok_or(PoolError::Bounds)?)
        .ok_or(PoolError::Bounds)?;
    if length > MAX_METADATA {
        return Err(PoolError::Bounds);
    }
    Ok(length)
}

fn encode(plan: &ActiveIncrementalPlan) -> Result<Vec<u8>, PoolError> {
    let length = metadata_length(plan.ranges().len())?;
    let mut raw = Vec::new();
    raw.try_reserve_exact(length)
        .map_err(|_| PoolError::Storage)?;
    raw.extend_from_slice(MAGIC);
    raw.extend_from_slice(&plan.base_checkpoint().to_bytes());
    raw.extend_from_slice(&plan.checkpoint().to_bytes());
    raw.extend_from_slice(
        &u32::try_from(plan.ranges().len())
            .map_err(|_| PoolError::Bounds)?
            .to_be_bytes(),
    );
    for range in plan.ranges() {
        raw.extend_from_slice(&range.segment_index().to_be_bytes());
        raw.extend_from_slice(&range.offset().to_be_bytes());
        raw.extend_from_slice(&range.length().to_be_bytes());
    }
    if raw.len() != length {
        return Err(PoolError::Corrupt);
    }
    Ok(raw)
}

fn physical_ranges(plan: &ActiveIncrementalPlan) -> Result<Vec<RangeSpec>, PoolError> {
    if plan.ranges().len() > MAX_SEGMENTS {
        return Err(PoolError::Bounds);
    }
    let mut ranges = Vec::new();
    ranges
        .try_reserve_exact(plan.ranges().len())
        .map_err(|_| PoolError::Storage)?;
    for range in plan.ranges() {
        ranges.push(RangeSpec {
            segment_index: range.segment_index(),
            offset: range.offset(),
            length: range.length(),
        });
    }
    Ok(ranges)
}

// A decoded tail offset is checked against the actual retained base length,
// not merely against an unauthenticated range table or a nominal segment size.
fn checked_plan(
    base: &ActiveArchive,
    later: ActiveRecoveryCheckpoint,
    ranges: &[RangeSpec],
) -> Result<ActiveIncrementalPlan, PoolError> {
    check_pins(base.pin, later)?;
    let (length, count, tail) = base.journal.capacity();
    if length != base.pin.length || count != base.pin.segment_count {
        return Err(PoolError::Stale);
    }
    if ranges.len() > MAX_SEGMENTS {
        return Err(PoolError::Bounds);
    }
    let mut unchanged = count;
    let mut decoded = Vec::new();
    decoded
        .try_reserve_exact(ranges.len())
        .map_err(|_| PoolError::Storage)?;
    for range in ranges {
        if range.segment_index < count {
            if range
                .segment_index
                .checked_add(1)
                .ok_or(PoolError::Bounds)?
                != count
                || range.offset != tail
                || tail == 0
            {
                return Err(PoolError::Corrupt);
            }
            unchanged = unchanged.checked_sub(1).ok_or(PoolError::Bounds)?;
        }
        decoded.push(ActiveAppendRange::from_parts(
            range.segment_index,
            range.offset,
            range.length,
        ));
    }
    ActiveIncrementalPlan::checked(base.pin, later, unchanged, decoded)
}

/// Retains the exact package file and its lock, never a writable chain state.
/// `plan()` describes a past successful full verification, not future contents,
/// origin, freshness, consensus finality, or permission to omit another replay.
pub struct ActiveIncrementalPackage {
    file: RetainedPackage,
    metadata: Vec<u8>,
    ranges: Vec<RangeSpec>,
    plan: ActiveIncrementalPlan,
    #[cfg(test)]
    fault: u8,
}

impl ActiveIncrementalPackage {
    /// Both pins originate outside the package: the base owns its independent
    /// pin, and the later pin is supplied separately. Nothing is returned before
    /// the complete base and joined history have each genuinely replayed.
    pub fn open(
        path: &Path,
        base: &mut ActiveArchive,
        later: ActiveRecoveryCheckpoint,
    ) -> Result<Self, PoolError> {
        let mut package = Self::open_unverified(path, base, later)?;
        package.verify(base)?;
        Ok(package)
    }

    // Private construction only. The public open gate immediately verifies the
    // complete history; tests may use this boundary to prove a hostile layout
    // clears metadata/hash checks before the real frame or authorization gate.
    fn open_unverified(
        path: &Path,
        base: &ActiveArchive,
        later: ActiveRecoveryCheckpoint,
    ) -> Result<Self, PoolError> {
        check_pins(base.pin, later)?;
        let file = RetainedPackage::open(path)?;
        let mut fixed = [0; FIXED_BYTES];
        file.read_exact_at(&mut fixed, 0)?;
        if &fixed[..8] != MAGIC {
            return Err(PoolError::Corrupt);
        }
        if fixed[8..136] != base.pin.to_bytes() || fixed[136..264] != later.to_bytes() {
            return Err(PoolError::Stale);
        }
        let count = usize::try_from(u32::from_be_bytes(
            fixed[264..268].try_into().map_err(|_| PoolError::Corrupt)?,
        ))
        .map_err(|_| PoolError::Bounds)?;
        let size = metadata_length(count)?;
        let payload = later
            .length
            .checked_sub(base.pin.length)
            .ok_or(PoolError::Stale)?;
        let length = u64::try_from(size)
            .map_err(|_| PoolError::Bounds)?
            .checked_add(payload)
            .ok_or(PoolError::Bounds)?;
        if file.length() != length {
            return Err(PoolError::Corrupt);
        }
        let mut metadata = Vec::new();
        metadata
            .try_reserve_exact(size)
            .map_err(|_| PoolError::Storage)?;
        metadata.resize(size, 0);
        metadata[..FIXED_BYTES].copy_from_slice(&fixed);
        file.read_exact_at(&mut metadata[FIXED_BYTES..], FIXED_BYTES as u64)?;
        let mut ranges = Vec::new();
        ranges
            .try_reserve_exact(count)
            .map_err(|_| PoolError::Storage)?;
        for bytes in metadata[FIXED_BYTES..].as_chunks::<RANGE_BYTES>().0 {
            ranges.push(RangeSpec {
                segment_index: u32::from_be_bytes(
                    bytes[..4].try_into().map_err(|_| PoolError::Corrupt)?,
                ),
                offset: u32::from_be_bytes(bytes[4..8].try_into().map_err(|_| PoolError::Corrupt)?),
                length: u32::from_be_bytes(
                    bytes[8..12].try_into().map_err(|_| PoolError::Corrupt)?,
                ),
            });
        }
        let plan = checked_plan(base, later, &ranges)?;
        Ok(Self {
            file,
            metadata,
            ranges,
            plan,
            #[cfg(test)]
            fault: 0,
        })
    }

    pub fn plan(&self) -> &ActiveIncrementalPlan {
        &self.plan
    }

    pub fn package_bytes(&self) -> u64 {
        self.file.length()
    }

    fn check_identity(&self, base: &ActiveArchive) -> Result<(), PoolError> {
        if base.pin != self.plan.base_checkpoint() {
            return Err(PoolError::Stale);
        }
        if checked_plan(base, self.plan.checkpoint(), &self.ranges)? != self.plan {
            return Err(PoolError::Corrupt);
        }
        Ok(())
    }

    fn joined<'a>(&'a self, base: &'a ActiveArchive) -> Result<JoinedJournal<'a>, PoolError> {
        self.check_identity(base)?;
        JoinedJournal::new(
            &base.journal,
            &base.file,
            &self.file,
            &self.metadata,
            &self.ranges,
            self.plan.checkpoint().segment_count,
            self.plan.checkpoint().length,
        )
    }

    fn check_bytes(&self, base: &ActiveArchive) -> Result<(), PoolError> {
        base.check_bytes()?;
        let joined = self.joined(base)?;
        if joined.layout_hash()? != self.plan.checkpoint().layout_hash {
            return Err(PoolError::Corrupt);
        }
        Ok(())
    }

    /// Every successful call performs two full real replays with independent
    /// fresh authorization caches, and brackets them with exact byte checks.
    /// Neither an earlier success nor the immutable plan authorizes new bytes.
    pub fn verify(&mut self, base: &mut ActiveArchive) -> Result<(), PoolError> {
        self.check_identity(base)?;
        self.file.check()?;
        base.verify()?;
        self.check_bytes(base)?;
        {
            let joined = self.joined(base)?;
            let physical_header = base.journal.read_header(&base.file)?;
            let profile = StorageProfile::ActiveSegmentsV1;
            let pin = self.plan.checkpoint();
            let mut reader = joined.reader()?;
            let header = read_header_profile(&mut reader, pin.length, profile)?;
            if header.length != physical_header.length
                || header.initial != physical_header.initial
                || header.signing_domain != physical_header.signing_domain
            {
                return Err(PoolError::Genesis);
            }
            let state =
                State::from_storage_policy(&header.initial, header.signing_domain, profile)?;
            if state.genesis != pin.genesis {
                return Err(PoolError::Genesis);
            }
            let verifier = AuthorizationVerifier::new();
            let mut replay = Replay::new(reader, pin.length, header.length, state)?;
            let mut start = header.length;
            while replay.next_block(&verifier)?.is_some() {
                let end = replay.byte_position()?;
                joined.validate_frame(start, end)?;
                start = end;
            }
            let (state, summary) = replay.finish()?;
            if state.genesis != pin.genesis {
                return Err(PoolError::Genesis);
            }
            if summary.height != pin.height || summary.app_hash != pin.app_hash {
                return Err(PoolError::Stale);
            }
        }
        #[cfg(test)]
        match self.fault {
            1 => tests::change_tail(base.journal.path())?,
            2 => self.file.fault_change_byte(0)?,
            3 => self.file.fault_change_byte(
                u64::try_from(self.metadata.len()).map_err(|_| PoolError::Bounds)?,
            )?,
            _ => {}
        }
        self.check_bytes(base)
    }

    /// Restores exact original bytes ONLY to a new directory. The complete
    /// package/base pair is replayed before writing and again after the target
    /// has independently replayed through its original creation handles.
    /// Failure leaves the partial or complete new target as written, never
    /// deletes, truncates, repairs, retries, or exposes a writable PoolStore.
    pub fn restore_new(
        &mut self,
        base: &mut ActiveArchive,
        path: &Path,
    ) -> Result<ActiveRecoveryCheckpoint, PoolError> {
        self.check_identity(base)?;
        base.journal.check(&base.file)?;
        self.file.check()?;
        let target = NewTarget::prepare(path, &[base.journal.path()])?;
        #[cfg(test)]
        let target = {
            let mut target = target;
            if (11..=14).contains(&self.fault) {
                target.fault = self.fault;
            }
            target
        };
        self.verify(base)?;
        let pin = self.plan.checkpoint();
        let (file, journal) = self.joined(base)?.copy_new(&target)?;
        let mut checked = ActiveArchive {
            file,
            journal,
            pin,
            #[cfg(test)]
            fault: 0,
        };
        checked.verify()?;
        self.verify(base)?;
        #[cfg(test)]
        match self.fault {
            4 => super::fault_entry(path, ".incremental-package-target-fault")?,
            5 => tests::change_tail(path)?,
            _ => {}
        }
        checked.check_bytes()?;
        target.check_parent()?;
        Ok(pin)
    }
}

impl ActiveArchive {
    /// Writes only exact append bytes to a new immutable package file. The
    /// existing dual-pin plan performs two full replays, then the package gate
    /// performs two more. Final complete source/package byte checks precede
    /// publication; the original new-file handle and exclusive lock are kept.
    pub fn pack_incremental_new(
        &mut self,
        later: &mut ActiveArchive,
        path: &Path,
    ) -> Result<ActiveIncrementalPackage, PoolError> {
        check_pins(self.pin, later.pin)?;
        self.journal.check(&self.file)?;
        later.journal.check(&later.file)?;
        let target = NewTarget::prepare(path, &[self.journal.path(), later.journal.path()])?;
        #[cfg(test)]
        let target = {
            let mut target = target;
            if (20..=23).contains(&self.fault) {
                target.fault = self.fault - 19;
            }
            target
        };
        let plan = self.incremental_plan(later)?;
        let metadata = encode(&plan)?;
        let ranges = physical_ranges(&plan)?;
        let file =
            RetainedPackage::create_new(target, &metadata, &ranges, &later.journal, &later.file)?;
        let mut package = ActiveIncrementalPackage {
            file,
            metadata,
            ranges,
            plan,
            #[cfg(test)]
            fault: 0,
        };
        package.verify(self)?;
        #[cfg(test)]
        match self.fault {
            30 => super::fault_entry(self.journal.path(), ".incremental-package-base-fault")?,
            31 => super::fault_entry(later.journal.path(), ".incremental-package-later-fault")?,
            32 => package.file.fault_change_byte(0)?,
            _ => {}
        }
        self.check_bytes()?;
        later.check_bytes()?;
        package.check_bytes(self)?;
        Ok(package)
    }
}

#[cfg(test)]
mod tests;
