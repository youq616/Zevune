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
    /// This deliberately performs O(history) work for the bounded laboratory.
    pub fn wallet_history(&mut self) -> Result<WalletHistory, PoolError> {
        let committed = self.summary()?;
        let result = self.read_wallet_history(&committed);
        if result.is_err() {
            self.available = false;
        }
        result
    }
    fn read_wallet_history(&mut self, committed: &Summary) -> Result<WalletHistory, PoolError> {
        if self.file.metadata().map_err(|_| PoolError::Storage)?.len() != self.length
            || self.length > MAX_JOURNAL_BYTES
        {
            return Err(PoolError::Corrupt);
        }
        self.file.rewind().map_err(|_| PoolError::Storage)?;
        let mut fixed = [0; 40];
        self.file
            .read_exact(&mut fixed)
            .map_err(|_| PoolError::Corrupt)?;
        if fixed[8..40] != Sha256::digest(NETWORK.as_bytes())[..] {
            return Err(PoolError::Genesis);
        }
        let signing_domain = if &fixed[..8] == FILE_MAGIC {
            None
        } else if &fixed[..8] == BOUND_FILE_MAGIC {
            let mut domain = [0; 32];
            self.file
                .read_exact(&mut domain)
                .map_err(|_| PoolError::Corrupt)?;
            if domain == [0; 32] {
                return Err(PoolError::Domain);
            }
            Some(domain)
        } else {
            return Err(PoolError::Genesis);
        };
        if signing_domain != self.state.signing_domain {
            return Err(PoolError::Domain);
        }
        let mut raw_count = [0; 4];
        self.file
            .read_exact(&mut raw_count)
            .map_err(|_| PoolError::Corrupt)?;
        let count = u32::from_be_bytes(raw_count) as usize;
        let header_size = if signing_domain.is_some() { 76 } else { 44 };
        if count > MAX_COMMITMENTS || header_size + count as u64 * 32 > self.length {
            return Err(PoolError::Bounds);
        }
        let mut initial = Vec::with_capacity(count);
        for _ in 0..count {
            let mut cm = [0; 32];
            self.file
                .read_exact(&mut cm)
                .map_err(|_| PoolError::Corrupt)?;
            initial.push(cm);
        }
        let mut state = State::from_policy(&initial, signing_domain)?;
        if state.genesis != self.state.genesis {
            return Err(PoolError::Genesis);
        }
        let origin = state.summary();
        let mut consumed = header_size + count as u64 * 32;
        let mut blocks = Vec::new();
        while consumed < self.length {
            if blocks.len() >= MAX_RECORDS as usize {
                return Err(PoolError::Bounds);
            }
            let mut prefix = [0; 4];
            self.file
                .read_exact(&mut prefix)
                .map_err(|_| PoolError::Corrupt)?;
            let n = u32::from_be_bytes(prefix) as usize;
            if !(114..=MAX_RECORD_BYTES).contains(&n) {
                return Err(PoolError::Bounds);
            }
            consumed = consumed
                .checked_add(n as u64 + 36)
                .ok_or(PoolError::Bounds)?;
            if consumed > self.length {
                return Err(PoolError::Corrupt);
            }
            let mut body = vec![0; n];
            let mut checksum = [0; 32];
            self.file
                .read_exact(&mut body)
                .map_err(|_| PoolError::Corrupt)?;
            self.file
                .read_exact(&mut checksum)
                .map_err(|_| PoolError::Corrupt)?;
            if checksum != Hash::from(Sha256::digest(&body)) {
                return Err(PoolError::Corrupt);
            }
            let record = Record::decode(&body)?;
            if record.base_hash != state.summary().app_hash {
                return Err(PoolError::Corrupt);
            }
            state = state.execute(
                record.height,
                record.block_id,
                &record.transactions,
                &self.verifier,
            )?;
            let result = state.summary();
            if result.app_hash != record.result_hash {
                return Err(PoolError::Corrupt);
            }
            blocks.push(WalletBlock {
                result,
                transactions: record.transactions,
            });
        }
        let mut trailing = [0];
        if self
            .file
            .read(&mut trailing)
            .map_err(|_| PoolError::Storage)?
            != 0
            || &state.summary() != committed
        {
            return Err(PoolError::Corrupt);
        }
        Ok(WalletHistory {
            #[cfg(feature = "local-funding-lab")]
            genesis_notes: Vec::new(),
            genesis: state.genesis,
            signing_domain,
            initial,
            origin,
            blocks,
        })
    }
}
