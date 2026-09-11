//! Bounded encrypted single-owner wallet journal. NO REAL FUNDS.
//!
//! A payment is returned only after its reservation AND exact signed bytes have
//! been synchronized. No network calls, automatic rebroadcast, repair or fallback.
//! File locks assume a trusted private directory and cooperative local processes;
//! this is not an OS sandbox, malicious-filesystem defense or rollback oracle.
use std::fs::{self, File, OpenOptions, TryLockError};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;

use orchard::Address;
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

use super::super::{Payment, Wallet, WalletError, WalletProver};
use super::{decrypt_payload, encrypt_payload, restore, snapshot, HEADER, MAX_PAYLOAD, PLAIN};
use crate::pool::history::WalletHistory;
use crate::wire::{decode, AuthorizationVerifier, MAX_ENVELOPE_SIZE};
use crate::NETWORK;

const MAGIC: &[u8; 8] = b"ZVWJNL01";
const FILE_HEADER: usize = 72;
const PREFIX: usize = 40;
const SEALED: usize = HEADER + MAX_PAYLOAD + 16;
const RECORD: usize = PREFIX + SEALED + 32;
pub const MAX_RECORDS: u64 = 256;
pub const MAX_FILE_BYTES: u64 = FILE_HEADER as u64 + MAX_RECORDS * RECORD as u64;
type Hash = [u8; 32];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StoreError {
    Io,
    Locked,
    Corrupt,
    Capacity,
    Unavailable,
    Rollback,
    MissingOutbox,
    Wallet(WalletError),
}
impl std::fmt::Display for StoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "wallet storage failed: {self:?}")
    }
}
impl std::error::Error for StoreError {}
impl From<WalletError> for StoreError {
    fn from(value: WalletError) -> Self {
        Self::Wallet(value)
    }
}

/// Local journal ancestry pin, NOT blockchain finality or a secret key. It only
/// detects rollback when retained independently of the file being checked.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StoreReceipt {
    pub journal_id: Hash,
    pub generation: u64,
    pub digest: Hash,
}

/// No Debug, Clone, mutable-wallet accessor, or password export.
/// Keeping this object unlocked retains a password buffer until drop. Zeroizing
/// covers owned buffers, not upstream copies, swap, core dumps or a compromised OS.
pub struct WalletStore {
    file: File,
    header: [u8; FILE_HEADER],
    receipt: StoreReceipt,
    password: Zeroizing<Vec<u8>>,
    wallet: Wallet,
    outbox: Option<Vec<u8>>,
    healthy: bool,
    #[cfg(test)]
    fault: u8,
}

struct Chain {
    header: [u8; FILE_HEADER],
    receipt: StoreReceipt,
    binding: Vec<u8>,
    sealed: Vec<u8>,
}

fn io<T>(result: std::io::Result<T>) -> Result<T, StoreError> {
    result.map_err(|_| StoreError::Io)
}
fn lock(file: &File) -> Result<(), StoreError> {
    file.try_lock().map_err(|e| match e {
        TryLockError::WouldBlock => StoreError::Locked,
        TryLockError::Error(_) => StoreError::Io,
    })
}
fn create_file(path: &Path) -> Result<File, StoreError> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = io(options.open(path))?;
    lock(&file)?;
    Ok(file)
}
fn sync_parent(path: &Path) -> Result<(), StoreError> {
    #[cfg(unix)]
    {
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        io(io(File::open(parent))?.sync_all())?;
    }
    // Portable std does not provide equivalent directory fsync on Windows.
    // File sync is checked there; directory durability is NOT claimed.
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}
fn new_header() -> Result<[u8; FILE_HEADER], StoreError> {
    let mut header = [0; FILE_HEADER];
    header[..8].copy_from_slice(MAGIC);
    header[8..40].copy_from_slice(&Sha256::digest(NETWORK.as_bytes()));
    OsRng
        .try_fill_bytes(&mut header[40..])
        .map_err(|_| StoreError::Wallet(WalletError::Entropy))?;
    Ok(header)
}
fn binding(header: &[u8; FILE_HEADER], prefix: &[u8]) -> Vec<u8> {
    let mut result = header.to_vec();
    result.extend_from_slice(prefix);
    result
}
fn payload(wallet: &Wallet, outbox: Option<&[u8]>) -> Result<Zeroizing<Vec<u8>>, StoreError> {
    let bytes = outbox.unwrap_or(&[]);
    if bytes.len() > MAX_ENVELOPE_SIZE || PLAIN + 4 + bytes.len() > MAX_PAYLOAD {
        return Err(StoreError::Corrupt);
    }
    let mut result = Zeroizing::new(vec![0; MAX_PAYLOAD]);
    result[..PLAIN].copy_from_slice(snapshot(wallet)?.as_ref());
    result[PLAIN..PLAIN + 4].copy_from_slice(&(bytes.len() as u32).to_be_bytes());
    result[PLAIN + 4..PLAIN + 4 + bytes.len()].copy_from_slice(bytes);
    Ok(result)
}
fn decode_payload(raw: &[u8]) -> Result<(Wallet, Option<Vec<u8>>), StoreError> {
    if raw.len() != MAX_PAYLOAD {
        return Err(StoreError::Corrupt);
    }
    let wallet = restore(&raw[..PLAIN])?;
    let n = u32::from_be_bytes(raw[PLAIN..PLAIN + 4].try_into().unwrap()) as usize;
    if n > MAX_ENVELOPE_SIZE
        || PLAIN + 4 + n > raw.len()
        || raw[PLAIN + 4 + n..].iter().any(|v| *v != 0)
    {
        return Err(StoreError::Corrupt);
    }
    let outbox = if n == 0 {
        None
    } else {
        let bytes = raw[PLAIN + 4..PLAIN + 4 + n].to_vec();
        let pending = wallet.pending.as_ref().ok_or(StoreError::Corrupt)?;
        let tx = decode(&bytes).map_err(|_| StoreError::Corrupt)?;
        if pending.txid != <Hash>::from(Sha256::digest(&bytes))
            || pending.expiry != tx.context.expiry_height
            || pending.nullifiers.iter().any(|nf| {
                !tx.bundle
                    .actions()
                    .iter()
                    .any(|a| a.nullifier().to_bytes() == *nf)
            })
        {
            return Err(StoreError::Corrupt);
        }
        AuthorizationVerifier::new()
            .verify(&bytes)
            .map_err(|_| StoreError::Corrupt)?;
        Some(bytes)
    };
    Ok((wallet, outbox))
}
fn record(
    header: &[u8; FILE_HEADER],
    generation: u64,
    previous: Hash,
    wallet: &Wallet,
    outbox: Option<&[u8]>,
    password: &[u8],
) -> Result<Vec<u8>, StoreError> {
    let mut out = Vec::with_capacity(RECORD);
    out.extend_from_slice(&generation.to_be_bytes());
    out.extend_from_slice(&previous);
    let sealed = encrypt_payload(
        payload(wallet, outbox)?.as_ref(),
        password,
        &binding(header, &out),
    )?;
    if sealed.len() != SEALED {
        return Err(StoreError::Corrupt);
    }
    out.extend_from_slice(&sealed);
    let digest = Sha256::digest(&out);
    out.extend_from_slice(&digest);
    Ok(out)
}

// Hash all fixed-size records, but perform one KDF/AEAD open on the final record.
// Its authenticated predecessor hash recursively commits to the entire prefix.
// The checksum itself is NOT an authentication tag.
fn scan(file: &mut File, expected: Option<StoreReceipt>) -> Result<Chain, StoreError> {
    let meta = io(file.metadata())?;
    let length = meta.len();
    if !meta.is_file()
        || !(FILE_HEADER as u64 + RECORD as u64..=MAX_FILE_BYTES).contains(&length)
        || !(length - FILE_HEADER as u64).is_multiple_of(RECORD as u64)
    {
        return Err(StoreError::Corrupt);
    }
    io(file.seek(SeekFrom::Start(0)))?;
    let mut header = [0; FILE_HEADER];
    io(file.read_exact(&mut header))?;
    if &header[..8] != MAGIC || header[8..40] != Sha256::digest(NETWORK.as_bytes())[..] {
        return Err(StoreError::Corrupt);
    }
    let id: Hash = Sha256::digest(header).into();
    let mut previous = id;
    let mut matched = expected.is_none();
    let count = (length - FILE_HEADER as u64) / RECORD as u64;
    let mut last = vec![0; RECORD];
    for generation in 1..=count {
        io(file.read_exact(&mut last))?;
        let digest: Hash = Sha256::digest(&last[..RECORD - 32]).into();
        if last[..8] != generation.to_be_bytes()
            || last[8..PREFIX] != previous
            || last[RECORD - 32..] != digest
        {
            return Err(StoreError::Corrupt);
        }
        if expected
            .is_some_and(|e| e.journal_id == id && e.generation == generation && e.digest == digest)
        {
            matched = true;
        }
        previous = digest;
    }
    let mut extra = [0];
    if io(file.read(&mut extra))? != 0 {
        return Err(StoreError::Corrupt);
    }
    if !matched {
        return Err(StoreError::Rollback);
    }
    Ok(Chain {
        header,
        receipt: StoreReceipt {
            journal_id: id,
            generation: count,
            digest: previous,
        },
        binding: binding(&header, &last[..PREFIX]),
        sealed: last[PREFIX..RECORD - 32].to_vec(),
    })
}

impl WalletStore {
    #[cfg(test)]
    pub(crate) fn lose_next_sync_acknowledgement_for_test(&mut self) {
        self.fault = 2;
    }

    pub fn create(path: &Path, password: &[u8]) -> Result<Self, StoreError> {
        Self::create_wallet(path, password, Wallet::create()?)
    }
    /// Import an existing authenticated M8 snapshot into a NEW journal. A pending
    /// legacy snapshot preserves reservations but contains no signed outbox; it
    /// cannot be rebroadcast from this API until its bytes are separately recovered.
    pub fn import_snapshot_new(
        path: &Path,
        snapshot_bytes: &[u8],
        password: &[u8],
    ) -> Result<Self, StoreError> {
        Self::create_wallet(path, password, super::open(snapshot_bytes, password)?)
    }
    fn create_wallet(path: &Path, password: &[u8], wallet: Wallet) -> Result<Self, StoreError> {
        let header = new_header()?;
        let id: Hash = Sha256::digest(header).into();
        let bytes = record(&header, 1, id, &wallet, None, password)?;
        let receipt = StoreReceipt {
            journal_id: id,
            generation: 1,
            digest: bytes[RECORD - 32..].try_into().unwrap(),
        };
        let mut file = create_file(path)?;
        io(file.write_all(&header))?;
        io(file.write_all(&bytes))?;
        io(file.sync_all())?;
        sync_parent(path)?;
        Ok(Self {
            file,
            header,
            receipt,
            password: Zeroizing::new(password.to_vec()),
            wallet,
            outbox: None,
            healthy: true,
            #[cfg(test)]
            fault: 0,
        })
    }
    /// Existing file only. Optional receipt must occur in the authenticated
    /// ancestry. Without an independently retained receipt a complete old valid
    /// prefix cannot be distinguished from the latest wallet state.
    pub fn open(
        path: &Path,
        password: &[u8],
        expected: Option<StoreReceipt>,
    ) -> Result<Self, StoreError> {
        if !io(fs::symlink_metadata(path))?.file_type().is_file() {
            return Err(StoreError::Corrupt);
        }
        let mut file = io(OpenOptions::new().read(true).write(true).open(path))?;
        lock(&file)?;
        let chain = scan(&mut file, expected)?;
        let plain = decrypt_payload(&chain.sealed, password, &chain.binding)?;
        let (wallet, outbox) = decode_payload(&plain)?;
        Ok(Self {
            file,
            header: chain.header,
            receipt: chain.receipt,
            password: Zeroizing::new(password.to_vec()),
            wallet,
            outbox,
            healthy: true,
            #[cfg(test)]
            fault: 0,
        })
    }
    fn ensure(&self) -> Result<(), StoreError> {
        if self.healthy {
            Ok(())
        } else {
            Err(StoreError::Unavailable)
        }
    }
    fn validate_storage(&mut self) -> Result<(), StoreError> {
        self.ensure()?;
        let result = scan(&mut self.file, Some(self.receipt));
        match result {
            Ok(c) if c.header == self.header && c.receipt == self.receipt => Ok(()),
            _ => {
                self.healthy = false;
                Err(StoreError::Corrupt)
            }
        }
    }
    fn room(&self) -> Result<(), StoreError> {
        self.ensure()?;
        if self.receipt.generation >= MAX_RECORDS {
            return Err(StoreError::Capacity);
        }
        Ok(())
    }
    /// Read-only view. Restored balances remain NotSynced until validated history
    /// is supplied; decrypting a file is not confirmation of ledger freshness.
    pub fn view(&self) -> Result<&Wallet, StoreError> {
        self.ensure()?;
        Ok(&self.wallet)
    }
    pub fn receipt(&self) -> Result<StoreReceipt, StoreError> {
        self.ensure()?;
        Ok(self.receipt)
    }
    pub fn sync(&mut self, history: &WalletHistory) -> Result<(), StoreError> {
        self.room()?;
        self.validate_storage()?;
        let before = snapshot(&self.wallet)?;
        self.wallet.sync(history)?;
        let cleared = self.wallet.pending_id().is_none() && self.outbox.is_some();
        if cleared {
            self.outbox = None;
        }
        if before.as_ref() != snapshot(&self.wallet)?.as_ref() || cleared {
            self.persist()?;
        }
        Ok(())
    }
    /// Transaction bytes do not escape on write/sync failure. Success means the
    /// local reservation was saved, NOT that the network accepted this payment.
    pub fn prepare_payment(
        &mut self,
        destination: Address,
        amount: u64,
        fee: u64,
        expiry: u64,
        prover: &WalletProver,
    ) -> Result<Payment, StoreError> {
        self.room()?;
        self.validate_storage()?;
        let payment = self
            .wallet
            .build_payment(destination, amount, fee, expiry, prover)?;
        self.outbox = Some(payment.bytes().to_vec());
        self.persist()?;
        Ok(payment)
    }
    /// Explicitly retrieve the SAME signed bytes after a rescan. Never rebuilds
    /// or broadcasts automatically, and never clears reservations on a timeout.
    pub fn pending_payment(&self) -> Result<Option<Payment>, StoreError> {
        self.ensure()?;
        self.wallet.balance()?;
        match (&self.wallet.pending, &self.outbox) {
            (None, None) => Ok(None),
            (Some(p), Some(raw)) => Ok(Some(Payment {
                bytes: raw.clone(),
                txid: p.txid,
            })),
            (Some(_), None) => Err(StoreError::MissingOutbox),
            _ => Err(StoreError::Corrupt),
        }
    }
    fn persist(&mut self) -> Result<(), StoreError> {
        let result = self.persist_inner();
        if result.is_err() {
            self.healthy = false;
        }
        result
    }
    fn persist_inner(&mut self) -> Result<(), StoreError> {
        self.room()?;
        self.validate_storage()?;
        let generation = self.receipt.generation + 1;
        let bytes = record(
            &self.header,
            generation,
            self.receipt.digest,
            &self.wallet,
            self.outbox.as_deref(),
            self.password.as_ref(),
        )?;
        let length = FILE_HEADER as u64 + self.receipt.generation * RECORD as u64;
        io(self.file.seek(SeekFrom::Start(length)))?;
        #[cfg(test)]
        if self.fault == 1 {
            io(self.file.write_all(&bytes[..RECORD / 2]))?;
            return Err(StoreError::Io);
        }
        io(self.file.write_all(&bytes))?;
        io(self.file.sync_all())?;
        #[cfg(test)]
        if self.fault == 2 {
            return Err(StoreError::Io);
        }
        self.receipt.generation = generation;
        self.receipt.digest = bytes[RECORD - 32..].try_into().unwrap();
        Ok(())
    }
    /// Create-only, byte-identical encrypted backup including the pending outbox.
    /// Failure never deletes/truncates the live file. Do not run multiple restored
    /// copies as concurrent wallets: file locks do not coordinate across copies.
    pub fn backup_new(&mut self, path: &Path) -> Result<StoreReceipt, StoreError> {
        self.validate_storage()?;
        let mut target = create_file(path)?;
        io(self.file.seek(SeekFrom::Start(0)))?;
        let length = FILE_HEADER as u64 + self.receipt.generation * RECORD as u64;
        let n = io(std::io::copy(
            &mut std::io::Read::by_ref(&mut self.file).take(length),
            &mut target,
        ))?;
        if n != length {
            return Err(StoreError::Io);
        }
        io(target.sync_all())?;
        sync_parent(path)?;
        Ok(self.receipt)
    }
}

#[cfg(test)]
mod tests;
