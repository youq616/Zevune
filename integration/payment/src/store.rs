//! Bounded append-only journal with OS lock, revalidation, and fail-closed writes.
use crate::chain::{Block, Ledger, Summary, Verifier, MAX_BLOCK_TXS};
use crate::wire::{Reader, MAX_TX};
use crate::{Error, Result};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;

const HEADER: &[u8; 4] = b"ZVJ1";
const MAX_JOURNAL: u64 = 64 * 1024 * 1024;
const MAX_FRAME: usize = MAX_BLOCK_TXS * MAX_TX * 2 + 4096;

pub struct Store {
    file: File,
    pub ledger: Ledger,
    pub verifier: Verifier,
    pending: Option<(Block, Ledger)>,
    poisoned: bool,
}
impl Store {
    pub fn open(home: &Path, genesis: &[u8]) -> Result<Self> {
        fs::create_dir_all(home).map_err(|_| Error::Storage)?;
        let meta = fs::symlink_metadata(home).map_err(|_| Error::Storage)?;
        if !meta.is_dir() || meta.file_type().is_symlink() {
            return Err(Error::Storage);
        }
        let path = home.join("payment.journal");
        if let Ok(meta) = fs::symlink_metadata(&path) {
            if !meta.is_file() || meta.file_type().is_symlink() {
                return Err(Error::Storage);
            }
        }
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(path).map_err(|_| Error::Storage)?;
        file.try_lock().map_err(|_| Error::Storage)?;
        let verifier = Verifier::new();
        let mut ledger = Ledger::genesis(genesis, &verifier)?;
        let len = file.metadata().map_err(|_| Error::Storage)?.len();
        if len > MAX_JOURNAL {
            return Err(Error::Limit);
        }
        if len == 0 {
            // The owner must also ensure existing consensus data never pairs with a new journal.
            let mut header = HEADER.to_vec();
            header.extend_from_slice(&ledger.genesis_id);
            file.write_all(&header)
                .and_then(|_| file.sync_all())
                .map_err(|_| Error::Storage)?;
        } else {
            let mut data = Vec::with_capacity(len as usize);
            file.read_to_end(&mut data).map_err(|_| Error::Storage)?;
            let mut reader = Reader::new(&data);
            if &reader.array::<4>()? != HEADER || reader.array::<32>()? != ledger.genesis_id {
                return Err(Error::Storage);
            }
            let mut cursor = 36;
            while cursor < data.len() {
                let mut r = Reader::new(&data[cursor..]);
                let n = r.u32()? as usize;
                if n > MAX_FRAME {
                    return Err(Error::Limit);
                }
                let bytes = r.take(n)?;
                let checksum = r.array::<32>()?;
                if <[u8; 32]>::from(Sha256::digest(bytes)) != checksum {
                    return Err(Error::Storage);
                }
                let block: Block = serde_json::from_slice(bytes).map_err(|_| Error::Storage)?;
                ledger = ledger.preview(&block, &verifier)?;
                cursor = cursor.checked_add(4 + n + 32).ok_or(Error::Limit)?;
            }
            if cursor != data.len() {
                return Err(Error::Storage);
            }
        }
        file.seek(SeekFrom::End(0)).map_err(|_| Error::Storage)?;
        Ok(Self {
            file,
            ledger,
            verifier,
            pending: None,
            poisoned: false,
        })
    }
    pub fn preview(&self, block: &Block) -> Result<Summary> {
        if self.poisoned {
            return Err(Error::Storage);
        }
        Ok(self.ledger.preview(block, &self.verifier)?.summary())
    }
    pub fn stage(&mut self, block: Block) -> Result<Summary> {
        if self.poisoned {
            return Err(Error::Storage);
        }
        if let Some((prior, state)) = &self.pending {
            if prior == &block {
                return Ok(state.summary());
            }
            return Err(Error::State);
        }
        let candidate = self.ledger.preview(&block, &self.verifier)?;
        let summary = candidate.summary();
        self.pending = Some((block, candidate));
        Ok(summary)
    }
    pub fn commit(&mut self, height: u64, hash: &str) -> Result<Summary> {
        if self.poisoned {
            return Err(Error::Storage);
        }
        if self.pending.is_none()
            && self.ledger.height == height
            && hex::encode(self.ledger.last_block) == hash
        {
            return Ok(self.ledger.summary());
        }
        let (block, state) = self.pending.as_ref().ok_or(Error::State)?;
        if block.height != height || block.hash != hash {
            return Err(Error::State);
        }
        let bytes = serde_json::to_vec(block).map_err(|_| Error::Storage)?;
        if bytes.len() > MAX_FRAME {
            return Err(Error::Limit);
        }
        let mut frame = (bytes.len() as u32).to_be_bytes().to_vec();
        frame.extend_from_slice(&bytes);
        frame.extend_from_slice(&Sha256::digest(&bytes));
        let len = self.file.metadata().map_err(|_| Error::Storage)?.len();
        if len.checked_add(frame.len() as u64).ok_or(Error::Limit)? > MAX_JOURNAL {
            return Err(Error::Limit);
        }
        // An uncertain write is terminal. Do not keep executing after partial I/O.
        if self
            .file
            .write_all(&frame)
            .and_then(|_| self.file.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(Error::Storage);
        }
        self.ledger = state.clone();
        self.pending = None;
        Ok(self.ledger.summary())
    }
}
