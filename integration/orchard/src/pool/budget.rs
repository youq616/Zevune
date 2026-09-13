//! Exact byte budget for the EXISTING bounded journal format, not free-disk
//! measurement or a promise that a later write/fsync will succeed.
use super::{PoolError, MAX_BLOCK_TRANSACTIONS, MAX_ENVELOPE_SIZE};

// ZVOBLK01 + height + block ID + base/result hashes + transaction count.
const RECORD_BODY_FIXED_BYTES: u64 = 8 + 8 + 32 + 32 + 32 + 2;
// u32 body length, then body, then SHA-256 checksum.
const FRAME_FIXED_BYTES: u64 = 4 + RECORD_BODY_FIXED_BYTES + 32;
const TRANSACTION_LENGTH_BYTES: u64 = 4;

#[derive(Clone, Copy)]
pub(super) struct JournalBudget {
    remaining: u64,
}
impl JournalBudget {
    pub(super) fn new(current_length: u64, limit: u64) -> Result<Self, PoolError> {
        // Even the empty candidate must be persistable under the configured
        // laboratory limit. Subtract first to avoid addition overflow.
        let remaining = limit
            .checked_sub(current_length)
            .and_then(|n| n.checked_sub(FRAME_FIXED_BYTES))
            .ok_or(PoolError::Bounds)?;
        Ok(Self { remaining })
    }

    pub(super) fn after_transaction(self, length: usize) -> Option<Self> {
        if length > MAX_ENVELOPE_SIZE {
            return None;
        }
        let cost = u64::try_from(length)
            .ok()?
            .checked_add(TRANSACTION_LENGTH_BYTES)?;
        Some(Self {
            remaining: self.remaining.checked_sub(cost)?,
        })
    }
}

pub(super) fn record_end(
    current_length: u64,
    limit: u64,
    transactions: &[Vec<u8>],
) -> Result<u64, PoolError> {
    if transactions.len() > MAX_BLOCK_TRANSACTIONS {
        return Err(PoolError::Bounds);
    }
    let mut budget = JournalBudget::new(current_length, limit)?;
    for tx in transactions {
        budget = budget
            .after_transaction(tx.len())
            .ok_or(PoolError::Bounds)?;
    }
    // remaining never exceeds limit, even when current_length == u64::MAX.
    Ok(limit - budget.remaining)
}
