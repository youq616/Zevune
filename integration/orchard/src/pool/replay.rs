//! Shared, bounded replay of the existing journal format. The entire state here
//! is unpublished: a failure consumes it, and only exact EOF permits finish().
//! Frame checksums detect damage; every record still executes real authorization.
use super::{
    Hash, PoolError, Record, State, Summary, MAX_JOURNAL_BYTES, MAX_RECORDS, MAX_RECORD_BYTES,
};
use crate::wire::AuthorizationVerifier;
use sha2::{Digest, Sha256};
use std::io::{ErrorKind, Read};

#[cfg(test)]
std::thread_local! {
    // Counts the original copying execution path, not proof invocations or time.
    pub(super) static HISTORY_BLOCKS_COLLECTED: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
    pub(super) static COPYING_EXECUTIONS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

struct Records<R> {
    reader: R,
    length: u64,
    consumed: u64,
    count: u64,
    exhausted: bool,
    body: Vec<u8>,
}
impl<R: Read> Records<R> {
    fn new(reader: R, length: u64, consumed: u64) -> Result<Self, PoolError> {
        if consumed > length || length > MAX_JOURNAL_BYTES {
            return Err(PoolError::Bounds);
        }
        Ok(Self {
            reader,
            length,
            consumed,
            count: 0,
            exhausted: false,
            body: Vec::new(),
        })
    }

    fn next(&mut self) -> Result<Option<Record>, PoolError> {
        if self.exhausted {
            return Ok(None);
        }
        if self.consumed == self.length {
            // Do not treat reaching the captured length as EOF: appended data
            // must be rejected. Retry Interrupted just as read_exact does.
            let mut byte = [0; 1];
            loop {
                match self.reader.read(&mut byte) {
                    Ok(0) => {
                        self.exhausted = true;
                        return Ok(None);
                    }
                    Ok(_) => return Err(PoolError::Corrupt),
                    Err(e) if e.kind() == ErrorKind::Interrupted => continue,
                    Err(_) => return Err(PoolError::Storage),
                }
            }
        }
        if self.count >= MAX_RECORDS {
            return Err(PoolError::Bounds);
        }
        if self.length - self.consumed < 4 {
            return Err(PoolError::Corrupt);
        }
        let mut prefix = [0; 4];
        self.reader
            .read_exact(&mut prefix)
            .map_err(|_| PoolError::Corrupt)?;
        let size = u32::from_be_bytes(prefix) as usize;
        if !(114..=MAX_RECORD_BYTES).contains(&size) {
            return Err(PoolError::Bounds);
        }
        let end = self
            .consumed
            .checked_add(size as u64 + 36)
            .ok_or(PoolError::Bounds)?;
        if end > self.length {
            return Err(PoolError::Corrupt);
        }
        // Validate the frame size and remaining captured bytes BEFORE allocation.
        // Reuse one bounded body buffer; decoded transactions live for one block
        // unless the wallet-history caller explicitly collects the history.
        if size > self.body.len() {
            self.body
                .try_reserve_exact(size - self.body.len())
                .map_err(|_| PoolError::Storage)?;
        }
        self.body.resize(size, 0);
        let mut checksum = [0; 32];
        self.reader
            .read_exact(&mut self.body)
            .map_err(|_| PoolError::Corrupt)?;
        self.reader
            .read_exact(&mut checksum)
            .map_err(|_| PoolError::Corrupt)?;
        if checksum != Hash::from(Sha256::digest(&self.body)) {
            return Err(PoolError::Corrupt);
        }
        let record = Record::decode(&self.body)?;
        self.consumed = end;
        self.count += 1;
        Ok(Some(record))
    }
}

pub(super) struct ReplayedBlock {
    pub(super) result: Summary,
    pub(super) transactions: Vec<Vec<u8>>,
}

/// Owns an isolated reconstruction, never a live PoolStore's committed state.
/// Returned blocks are for internal collection only; they must not be published
/// as authenticated history until finish succeeds and the caller checks its tip.
pub(super) struct Replay<R> {
    records: Records<R>,
    state: Option<State>,
    summary: Summary,
}
impl<R: Read> Replay<R> {
    pub(super) fn new(
        reader: R,
        length: u64,
        header_size: u64,
        state: State,
    ) -> Result<Self, PoolError> {
        let records = Records::new(reader, length, header_size)?;
        let summary = state.summary();
        Ok(Self {
            records,
            state: Some(state),
            summary,
        })
    }

    pub(super) fn next_block(
        &mut self,
        verifier: &AuthorizationVerifier,
    ) -> Result<Option<ReplayedBlock>, PoolError> {
        // Any failure after take() drops the unpublished reconstruction. A caller
        // cannot catch an error and resume past an invalid or partly applied block.
        let mut state = self.state.take().ok_or(PoolError::Unavailable)?;
        let Some(record) = self.records.next()? else {
            self.state = Some(state);
            return Ok(None);
        };
        if record.base_hash != self.summary.app_hash {
            return Err(PoolError::Corrupt);
        }
        state.execute_unpublished(
            record.height,
            record.block_id,
            &record.transactions,
            verifier,
        )?;
        let result = state.summary();
        if result.app_hash != record.result_hash {
            return Err(PoolError::Corrupt);
        }
        self.summary = result.clone();
        self.state = Some(state);
        Ok(Some(ReplayedBlock {
            result,
            transactions: record.transactions,
        }))
    }

    pub(super) fn finish(self) -> Result<(State, Summary), PoolError> {
        if !self.records.exhausted {
            return Err(PoolError::Unavailable);
        }
        Ok((self.state.ok_or(PoolError::Unavailable)?, self.summary))
    }
}

#[cfg(test)]
#[path = "replay_tests.rs"]
mod tests;
