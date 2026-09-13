//! Greedy proposal selection over one disposable state. Accepted prefixes are
//! NOT reexecuted for each candidate. Finalize/Commit still independently check
//! the complete block. No selection state or spend permission is persisted.
use super::*;

pub const MAX_CANDIDATES: usize = 64;
pub const MAX_PROPOSAL_BYTES: usize = MAX_BLOCK_TRANSACTIONS * MAX_ENVELOPE_SIZE;

#[derive(Debug)]
pub struct Selection {
    pub result: Summary,
    /// Bit i refers to candidate i; selected bytes stay in their original order.
    pub mask: u64,
}

impl PoolStore {
    pub fn select_proposal(
        &self,
        height: u64,
        block_id: Hash,
        max_bytes: usize,
        candidates: &[Vec<u8>],
    ) -> Result<Selection, PoolError> {
        let base = self.summary()?;
        if height != base.height.checked_add(1).ok_or(PoolError::Height)?
            || height > MAX_RECORDS
            || block_id == [0; 32]
        {
            return Err(PoolError::Height);
        }
        if candidates.len() > MAX_CANDIDATES
            || max_bytes > MAX_PROPOSAL_BYTES
            || candidates.iter().any(|tx| tx.len() > MAX_ENVELOPE_SIZE)
        {
            return Err(PoolError::Bounds);
        }
        let mut next = self.state.clone();
        let mut remaining = max_bytes;
        let mut count = 0;
        let mut mask = 0;
        for (i, raw) in candidates.iter().enumerate() {
            if count == MAX_BLOCK_TRANSACTIONS {
                break;
            }
            if raw.is_empty() || raw.len() > remaining {
                continue;
            }
            match next.apply_transaction(height, &self.state.anchors, raw, &self.verifier) {
                Ok(()) => {
                    remaining -= raw.len();
                    count += 1;
                    mask |= 1u64 << i;
                }
                // Invalid candidates are skipped, not cached as future valid
                // spends. Operational/storage faults must never become votes.
                Err(
                    PoolError::Bounds
                    | PoolError::Domain
                    | PoolError::Anchor
                    | PoolError::DoubleSpend
                    | PoolError::DuplicateOutput
                    | PoolError::Authorization
                    | PoolError::Expired
                    | PoolError::FeeOverflow,
                ) => {}
                Err(err) => return Err(err),
            }
        }
        next.finish_block(height, block_id);
        Ok(Selection {
            result: next.summary(),
            mask,
        })
    }
}

#[cfg(test)]
thread_local! {
    pub(super) static ATTEMPTS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

#[cfg(all(test, feature = "local-funding-lab"))]
mod tests;
