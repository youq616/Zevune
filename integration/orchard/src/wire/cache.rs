//! Private, process-local memoization of successful authorization checks only.
//! An exact-byte hit says nothing about the current ledger, expiry or finality.
use std::collections::VecDeque;
use std::sync::Mutex;

use super::{WireError, MAX_ENVELOPE_SIZE};

pub(super) const CAPACITY: usize = 64;
struct Entry {
    digest: [u8; 32],
    raw: Vec<u8>,
}
#[derive(Default)]
pub(super) struct VerifiedCache {
    entries: Mutex<VecDeque<Entry>>,
}
impl VerifiedCache {
    pub(super) fn contains(&self, raw: &[u8], digest: [u8; 32]) -> Result<bool, WireError> {
        let entries = self.entries.lock().map_err(|_| WireError::Authorization)?;
        Ok(entries
            .iter()
            .any(|entry| entry.digest == digest && entry.raw.as_slice() == raw))
    }

    // Only the parent module may remember a result, AFTER its fixed upstream
    // proof and all signatures pass. No caller supplies a success flag or key.
    pub(super) fn remember(&self, raw: &[u8], digest: [u8; 32]) -> Result<(), WireError> {
        if raw.is_empty() || raw.len() > MAX_ENVELOPE_SIZE {
            return Err(WireError::Bounds);
        }
        let mut entries = self.entries.lock().map_err(|_| WireError::Authorization)?;
        if entries
            .iter()
            .any(|entry| entry.digest == digest && entry.raw.as_slice() == raw)
        {
            return Ok(());
        }
        if entries.len() == CAPACITY {
            entries.pop_front();
        }
        entries.push_back(Entry {
            digest,
            raw: raw.to_vec(),
        });
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // These test bookkeeping only; synthetic bytes are never passed off as
    // valid transactions and no insertion API is exported from the crate.
    #[test]
    fn exact_bytes_required_even_for_a_forced_digest_collision() {
        let cache = VerifiedCache::default();
        cache.remember(b"public-a", [7; 32]).unwrap();
        assert!(cache.contains(b"public-a", [7; 32]).unwrap());
        assert!(!cache.contains(b"public-b", [7; 32]).unwrap());
        assert!(!cache.contains(b"public-a", [8; 32]).unwrap());
    }

    #[test]
    fn fifo_capacity_and_duplicate_insert_are_bounded() {
        let cache = VerifiedCache::default();
        for i in 0..CAPACITY {
            let raw = (i as u64).to_be_bytes();
            cache.remember(&raw, [i as u8; 32]).unwrap();
        }
        cache.remember(&0u64.to_be_bytes(), [0; 32]).unwrap();
        assert_eq!(cache.entries.lock().unwrap().len(), CAPACITY);
        cache.remember(b"new-public-entry", [255; 32]).unwrap();
        assert!(!cache.contains(&0u64.to_be_bytes(), [0; 32]).unwrap());
        assert!(cache.contains(&1u64.to_be_bytes(), [1; 32]).unwrap());
        assert!(cache.contains(b"new-public-entry", [255; 32]).unwrap());
        assert_eq!(cache.entries.lock().unwrap().len(), CAPACITY);
        assert!(!VerifiedCache::default()
            .contains(b"new-public-entry", [255; 32])
            .unwrap());
    }

    #[test]
    fn invalid_sizes_cannot_fill_the_cache() {
        let cache = VerifiedCache::default();
        assert_eq!(cache.remember(&[], [0; 32]), Err(WireError::Bounds));
        assert_eq!(
            cache.remember(&vec![0; MAX_ENVELOPE_SIZE + 1], [0; 32]),
            Err(WireError::Bounds)
        );
        assert!(cache.entries.lock().unwrap().is_empty());
    }
}
