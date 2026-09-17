//! Local, bounded, read-only wallet history authenticated against an already
//! open journal's committed state. Not a remote-peer or finality certificate.
use super::*;
use std::io::Seek;

pub struct WalletHistory {
    pub(crate) genesis: Hash,
    pub(crate) signing_domain: Option<Hash>,
    pub(crate) initial: Vec<Hash>,
    #[cfg(feature = "local-funding-lab")]
    pub(crate) genesis_notes: Vec<orchard::Note>,
    origin: Summary,
    pub(crate) blocks: Vec<WalletBlock>,
}
pub(crate) struct WalletBlock {
    pub(crate) result: Summary,
    pub(crate) transactions: Vec<Vec<u8>>,
}
impl WalletHistory {
    pub fn tip(&self) -> &Summary {
        self.blocks
            .last()
            .map(|b| &b.result)
            .unwrap_or(&self.origin)
    }
    pub(crate) fn checkpoint(&self, height: u64) -> Option<&Summary> {
        if height == 0 {
            Some(&self.origin)
        } else {
            self.blocks
                .get(usize::try_from(height - 1).ok()?)
                .map(|b| &b.result)
        }
    }
}

impl PoolStore {
    /// Export only public signed records after full cryptographic replay. A
    /// caller must trust this local full-node store; checksum alone is not trust.
    /// Replays all blocks; state summaries still traverse cumulative sets.
    pub fn wallet_history(&mut self) -> Result<WalletHistory, PoolError> {
        let committed = self.summary()?;
        let result = self.read_wallet_history(&committed);
        if result.is_err() {
            self.available = false;
        }
        result
    }
    fn read_wallet_history(&mut self, committed: &Summary) -> Result<WalletHistory, PoolError> {
        let mut blocks = Vec::new();
        let origin = self.replay_history(committed, |block| {
            blocks.try_reserve(1).map_err(|_| PoolError::Storage)?;
            #[cfg(test)]
            replay::HISTORY_BLOCKS_COLLECTED.with(|n| n.set(n.get() + 1));
            blocks.push(WalletBlock {
                result: block.result,
                transactions: block.transactions,
            });
            Ok(())
        })?;
        Ok(WalletHistory {
            #[cfg(feature = "local-funding-lab")]
            genesis_notes: Vec::new(),
            genesis: origin.genesis,
            signing_domain: origin.signing_domain,
            initial: origin.initial,
            origin: origin.summary,
            blocks,
        })
    }

    // Verify the entire committed file without retaining every transaction for
    // wallet scanning. This is still full authorization replay, not a checkpoint
    // shortcut. Only recovery checkpoint export calls this discard mode.
    pub(super) fn verify_committed_history(&mut self) -> Result<(), PoolError> {
        let committed = self.summary()?;
        let result = self.replay_history(&committed, |_| Ok(())).map(|_| ());
        if result.is_err() {
            self.available = false;
        }
        result
    }

    // The visitor is private and must only collect into unpublished local
    // storage or discard blocks. Failed replay drops everything before return.
    fn replay_history(
        &mut self,
        committed: &Summary,
        visit: impl FnMut(replay::ReplayedBlock) -> Result<(), PoolError>,
    ) -> Result<HistoryOrigin, PoolError> {
        if let Some(active) = &self.active {
            if active.length() != self.length {
                return Err(PoolError::Corrupt);
            }
            active.check(&self.file)?;
            let reader = active.reader(&self.file)?;
            let origin = self.replay_history_stream(reader, committed, visit)?;
            active.check(&self.file)?;
            return Ok(origin);
        }
        if self.file.metadata().map_err(|_| PoolError::Storage)?.len() != self.length
            || self.length > MAX_JOURNAL_BYTES
        {
            return Err(PoolError::Corrupt);
        }
        self.file.rewind().map_err(|_| PoolError::Storage)?;
        // The owning file and lock remain held. A clone only supplies the Read
        // implementation without aliasing the mutable PoolStore borrow.
        let reader = self.file.try_clone().map_err(|_| PoolError::Storage)?;
        self.replay_history_stream(reader, committed, visit)
    }

    fn replay_history_stream(
        &self,
        mut reader: impl Read,
        committed: &Summary,
        mut visit: impl FnMut(replay::ReplayedBlock) -> Result<(), PoolError>,
    ) -> Result<HistoryOrigin, PoolError> {
        let header =
            replay::read_header_profile(&mut reader, self.length, self.state.profile)?;
        let signing_domain = header.signing_domain;
        if signing_domain != self.state.signing_domain {
            return Err(PoolError::Domain);
        }
        let initial = header.initial;
        let state = State::from_storage_policy(&initial, signing_domain, self.state.profile)?;
        if state.genesis != self.state.genesis {
            return Err(PoolError::Genesis);
        }
        let origin = state.summary();
        let mut replay = replay::Replay::new(reader, self.length, header.length, state)?;
        let mut start = header.length;
        while let Some(block) = replay.next_block(&self.verifier)? {
            let end = replay.byte_position()?;
            if let Some(active) = &self.active {
                active.validate_frame(start, end)?;
            }
            start = end;
            visit(block)?;
        }
        let (state, final_summary) = replay.finish()?;
        if &final_summary != committed {
            return Err(PoolError::Corrupt);
        }
        Ok(HistoryOrigin {
            genesis: state.genesis,
            signing_domain,
            initial,
            summary: origin,
        })
    }
}

// Initial policy metadata only; never contains a purported final tip or a
// partial history. The final tip was checked before constructing this value.
struct HistoryOrigin {
    genesis: Hash,
    signing_domain: Option<Hash>,
    initial: Vec<Hash>,
    summary: Summary,
}
