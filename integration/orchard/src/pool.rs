//! NO-FUNDS Orchard state machine and bounded journal. Not connected to consensus.
//! Public constructors only support empty genesis. Nonempty bootstrap is test-only.
//! Every replay and commit rechecks actual authorization; hashes are not finality.
use std::collections::{BTreeSet, VecDeque};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;

use incrementalmerkletree::frontier::Frontier;
use orchard::note::ExtractedNoteCommitment;
use orchard::tree::MerkleHashOrchard;
use sha2::{Digest, Sha256};

use crate::wire::{decode, AuthorizationVerifier, MAX_ENVELOPE_SIZE};
use crate::{MAX_ANCHORS, NETWORK};

type Hash = [u8; 32];
const FILE_MAGIC: &[u8; 8] = b"ZVOPOL01";
const RECORD_MAGIC: &[u8; 8] = b"ZVOBLK01";
pub const MAX_BLOCK_TRANSACTIONS: usize = 16;
pub const MAX_COMMITMENTS: usize = 65_536;
pub const MAX_RECORDS: u64 = 10_000;
pub const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_RECORD_BYTES: usize = 114 + MAX_BLOCK_TRANSACTIONS * (4 + MAX_ENVELOPE_SIZE);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PoolError {
    Bounds,
    Height,
    Genesis,
    Anchor,
    DoubleSpend,
    DuplicateOutput,
    Authorization,
    Expired,
    FeeOverflow,
    Stale,
    Corrupt,
    Locked,
    Storage,
    Unavailable,
}
impl std::fmt::Display for PoolError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Orchard pool failure: {self:?}")
    }
}
impl std::error::Error for PoolError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Summary {
    pub height: u64,
    pub app_hash: Hash,
    pub root: Hash,
    pub commitments: u64,
    pub nullifiers: u64,
    pub fees: u64,
}

#[derive(Clone)]
struct State {
    height: u64,
    head: Hash,
    genesis: Hash,
    fees: u64,
    frontier: Frontier<MerkleHashOrchard, 32>,
    spent: BTreeSet<Hash>,
    outputs: BTreeSet<Hash>,
    anchors: VecDeque<Hash>,
}
impl State {
    fn from_genesis(commitments: &[Hash]) -> Result<Self, PoolError> {
        if commitments.len() > MAX_COMMITMENTS { return Err(PoolError::Bounds); }
        let mut frontier = Frontier::empty();
        let mut outputs = BTreeSet::new();
        for cm in commitments {
            let cmx = Option::<ExtractedNoteCommitment>::from(ExtractedNoteCommitment::from_bytes(cm)).ok_or(PoolError::Genesis)?;
            if !outputs.insert(*cm) || !frontier.append(MerkleHashOrchard::from_cmx(&cmx)) {
                return Err(PoolError::Genesis);
            }
        }
        let root = frontier.root().to_bytes();
        let genesis = Sha256::digest(genesis_bytes(commitments)?).into();
        Ok(Self { height: 0, head: [0; 32], genesis, fees: 0, frontier, spent: BTreeSet::new(), outputs, anchors: VecDeque::from([root]) })
    }
    fn summary(&self) -> Summary {
        let mut h = Sha256::new();
        h.update(b"ZEVUNE-ORCHARD-POOL-STATE\0\x01");
        h.update(self.genesis);
        h.update(self.height.to_be_bytes()); h.update(self.head);
        h.update(self.fees.to_be_bytes());
        h.update(self.frontier.tree_size().to_be_bytes());
        let root = self.frontier.root().to_bytes(); h.update(root);
        h.update((self.spent.len() as u64).to_be_bytes());
        for nf in &self.spent { h.update(nf); }
        h.update((self.outputs.len() as u64).to_be_bytes());
        for cm in &self.outputs { h.update(cm); }
        h.update((self.anchors.len() as u64).to_be_bytes());
        for anchor in &self.anchors { h.update(anchor); }
        Summary { height: self.height, app_hash: h.finalize().into(), root, commitments: self.frontier.tree_size(), nullifiers: self.spent.len() as u64, fees: self.fees }
    }
    fn execute(&self, height: u64, block_id: Hash, transactions: &[Vec<u8>], verifier: &AuthorizationVerifier) -> Result<State, PoolError> {
        if height != self.height.checked_add(1).ok_or(PoolError::Height)? || height > MAX_RECORDS || block_id == [0; 32] {
            return Err(PoolError::Height);
        }
        if transactions.len() > MAX_BLOCK_TRANSACTIONS || transactions.iter().any(|tx| tx.len() > MAX_ENVELOPE_SIZE) {
            return Err(PoolError::Bounds);
        }
        let mut next = self.clone();
        for raw in transactions {
            let decoded = decode(raw).map_err(|_| PoolError::Authorization)?;
            if decoded.context.expiry_height < height { return Err(PoolError::Expired); }
            // Only roots committed before this block are spend anchors. Never
            // expose roots of partially executed candidate blocks as trusted.
            if !self.anchors.contains(&decoded.bundle.anchor().to_bytes()) { return Err(PoolError::Anchor); }
            if next.outputs.len().checked_add(decoded.bundle.actions().len()).ok_or(PoolError::Bounds)? > MAX_COMMITMENTS {
                return Err(PoolError::Bounds);
            }
            for a in decoded.bundle.actions().iter() {
                if next.spent.contains(&a.nullifier().to_bytes()) { return Err(PoolError::DoubleSpend); }
                if next.outputs.contains(&a.cmx().to_bytes()) { return Err(PoolError::DuplicateOutput); }
            }
            verifier.verify(raw).map_err(|_| PoolError::Authorization)?;
            next.fees = next.fees.checked_add(decoded.context.fee).ok_or(PoolError::FeeOverflow)?;
            for a in decoded.bundle.actions().iter() {
                next.spent.insert(a.nullifier().to_bytes());
                next.outputs.insert(a.cmx().to_bytes());
                if !next.frontier.append(MerkleHashOrchard::from_cmx(a.cmx())) { return Err(PoolError::Bounds); }
            }
        }
        next.height = height; next.head = block_id;
        let root = next.frontier.root().to_bytes();
        if next.anchors.back() != Some(&root) {
            next.anchors.push_back(root);
            if next.anchors.len() > MAX_ANCHORS { next.anchors.pop_front(); }
        }
        Ok(next)
    }
}

// The caller cannot edit prepared contents. It is still a pre-commit result,
// NOT a signed block, finality certificate, or authorization to bypass replay.
pub struct PreparedBlock {
    base: Summary,
    result: Summary,
    block_id: Hash,
    transactions: Vec<Vec<u8>>,
}
impl PreparedBlock {
    pub fn result(&self) -> &Summary { &self.result }
}

/// A bounded single-writer laboratory journal. No account secrets are stored.
/// A successful write followed by lost acknowledgement may be present on replay.
/// No automatic truncation, reset, state repair or signer reset is performed.
pub struct PoolStore {
    file: File,
    state: State,
    verifier: AuthorizationVerifier,
    available: bool,
    length: u64,
    #[cfg(test)]
    fault: u8,
}
impl PoolStore {
    /// Create an empty pool. Does not issue assets or overwrite any existing file.
    pub fn create(path: &Path) -> Result<Self, PoolError> { Self::create_with_genesis(path, &[]) }
    /// Reopen only an empty-genesis pool, revalidating every persisted transaction.
    pub fn open(path: &Path) -> Result<Self, PoolError> { Self::open_with_genesis(path, &[]) }
    fn create_with_genesis(path: &Path, initial: &[Hash]) -> Result<Self, PoolError> {
        let state = State::from_genesis(initial)?;
        let header = genesis_bytes(initial)?;
        let mut options = OpenOptions::new();
        options.create_new(true).read(true).append(true);
        #[cfg(unix)] {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(path).map_err(|_| PoolError::Storage)?;
        file.try_lock().map_err(|_| PoolError::Locked)?;
        file.write_all(&header).map_err(|_| PoolError::Storage)?;
        file.sync_all().map_err(|_| PoolError::Storage)?;
        // Directory durability is platform/filesystem dependent, explicitly not
        // a promise of zero-loss recovery after every power failure.
        Ok(Self { file, state, verifier: AuthorizationVerifier::new(), available: true, length: header.len() as u64, #[cfg(test)] fault: 0 })
    }
    fn open_with_genesis(path: &Path, initial: &[Hash]) -> Result<Self, PoolError> {
        let info = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
        if !info.file_type().is_file() || info.len() > MAX_JOURNAL_BYTES { return Err(PoolError::Bounds); }
        let mut file = OpenOptions::new().read(true).append(true).open(path).map_err(|_| PoolError::Storage)?;
        file.try_lock().map_err(|_| PoolError::Locked)?;
        let length = file.metadata().map_err(|_| PoolError::Storage)?.len();
        if length > MAX_JOURNAL_BYTES { return Err(PoolError::Bounds); }
        let expected_header = genesis_bytes(initial)?;
        let mut actual_header = vec![0; expected_header.len()];
        file.read_exact(&mut actual_header).map_err(|_| PoolError::Corrupt)?;
        if actual_header != expected_header { return Err(PoolError::Genesis); }
        let verifier = AuthorizationVerifier::new();
        let mut state = State::from_genesis(initial)?;
        let mut read_length = actual_header.len() as u64;
        loop {
            let mut prefix = [0; 4];
            if !read_prefix(&mut file, &mut prefix)? { break; }
            let n = u32::from_be_bytes(prefix) as usize;
            if !(114..=MAX_RECORD_BYTES).contains(&n) { return Err(PoolError::Bounds); }
            read_length = read_length.checked_add(n as u64 + 36).ok_or(PoolError::Bounds)?;
            if read_length > length { return Err(PoolError::Corrupt); }
            let mut body = vec![0; n]; let mut checksum = [0; 32];
            file.read_exact(&mut body).map_err(|_| PoolError::Corrupt)?;
            file.read_exact(&mut checksum).map_err(|_| PoolError::Corrupt)?;
            if checksum != Hash::from(Sha256::digest(&body)) { return Err(PoolError::Corrupt); }
            let record = Record::decode(&body)?;
            if record.base_hash != state.summary().app_hash { return Err(PoolError::Corrupt); }
            let next = state.execute(record.height, record.block_id, &record.transactions, &verifier)?;
            if next.summary().app_hash != record.result_hash { return Err(PoolError::Corrupt); }
            state = next;
        }
        if read_length != length { return Err(PoolError::Corrupt); }
        Ok(Self { file, state, verifier, available: true, length, #[cfg(test)] fault: 0 })
    }
    pub fn summary(&self) -> Result<Summary, PoolError> {
        if !self.available { return Err(PoolError::Unavailable); }
        Ok(self.state.summary())
    }
    /// Compare against an independently trusted checkpoint. This does not make
    /// an untrusted hash authentic and is not a consensus light-client proof.
    pub fn check_checkpoint(&self, height: u64, app_hash: Hash) -> Result<(), PoolError> {
        let s = self.summary()?;
        if s.height != height || s.app_hash != app_hash { return Err(PoolError::Stale); }
        Ok(())
    }
    pub fn prepare(&self, height: u64, block_id: Hash, transactions: &[Vec<u8>]) -> Result<PreparedBlock, PoolError> {
        let base = self.summary()?;
        let next = self.state.execute(height, block_id, transactions, &self.verifier)?;
        Ok(PreparedBlock { base, result: next.summary(), block_id, transactions: transactions.to_vec() })
    }
    pub fn commit(&mut self, prepared: PreparedBlock) -> Result<Summary, PoolError> {
        let base = self.summary()?;
        if base != prepared.base { return Err(PoolError::Stale); }
        let next = self.state.execute(prepared.result.height, prepared.block_id, &prepared.transactions, &self.verifier)?;
        let result = next.summary();
        if result != prepared.result { return Err(PoolError::Stale); }
        let body = Record { height: result.height, block_id: prepared.block_id, base_hash: base.app_hash, result_hash: result.app_hash, transactions: prepared.transactions }.encode()?;
        let new_length = self.length.checked_add(body.len() as u64 + 36).ok_or(PoolError::Bounds)?;
        if new_length > MAX_JOURNAL_BYTES { return Err(PoolError::Bounds); }
        let file_length = match self.file.metadata() {
            Ok(meta) => meta.len(),
            Err(_) => { self.available = false; return Err(PoolError::Storage); }
        };
        if file_length != self.length {
            self.available = false; return Err(PoolError::Corrupt);
        }
        let mut frame = (body.len() as u32).to_be_bytes().to_vec();
        frame.extend_from_slice(&body); frame.extend_from_slice(&Sha256::digest(&body));
        if self.append(&frame).is_err() { self.available = false; return Err(PoolError::Storage); }
        self.state = next; self.length = new_length;
        Ok(result)
    }
    fn append(&mut self, frame: &[u8]) -> std::io::Result<()> {
        #[cfg(test)] {
            if self.fault == 1 {
                self.fault = 0; self.file.write_all(&frame[..5])?;
                return Err(std::io::Error::other("test-only partial write"));
            }
        }
        self.file.write_all(frame)?;
        #[cfg(test)] {
            if self.fault == 2 { self.fault = 0; return Err(std::io::Error::other("test-only sync failure")); }
        }
        self.file.sync_all()
    }
}

fn genesis_bytes(initial: &[Hash]) -> Result<Vec<u8>, PoolError> {
    if initial.len() > MAX_COMMITMENTS { return Err(PoolError::Bounds); }
    let mut out = FILE_MAGIC.to_vec();
    out.extend_from_slice(&Sha256::digest(NETWORK.as_bytes()));
    out.extend_from_slice(&(initial.len() as u32).to_be_bytes());
    for cm in initial { out.extend_from_slice(cm); }
    Ok(out)
}
fn read_prefix(file: &mut File, prefix: &mut [u8; 4]) -> Result<bool, PoolError> {
    loop {
        match file.read(&mut prefix[..1]) {
            Ok(0) => return Ok(false),
            Ok(_) => break,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(PoolError::Storage),
        }
    }
    file.read_exact(&mut prefix[1..]).map_err(|_| PoolError::Corrupt)?;
    Ok(true)
}
struct Record {
    height: u64,
    block_id: Hash,
    base_hash: Hash,
    result_hash: Hash,
    transactions: Vec<Vec<u8>>,
}
impl Record {
    fn encode(&self) -> Result<Vec<u8>, PoolError> {
        if self.transactions.len() > MAX_BLOCK_TRANSACTIONS { return Err(PoolError::Bounds); }
        let mut b = RECORD_MAGIC.to_vec();
        b.extend_from_slice(&self.height.to_be_bytes()); b.extend_from_slice(&self.block_id);
        b.extend_from_slice(&self.base_hash); b.extend_from_slice(&self.result_hash);
        b.extend_from_slice(&(self.transactions.len() as u16).to_be_bytes());
        for tx in &self.transactions {
            if tx.len() > MAX_ENVELOPE_SIZE { return Err(PoolError::Bounds); }
            b.extend_from_slice(&(tx.len() as u32).to_be_bytes()); b.extend_from_slice(tx);
        }
        Ok(b)
    }
    fn decode(raw: &[u8]) -> Result<Self, PoolError> {
        if !(114..=MAX_RECORD_BYTES).contains(&raw.len()) || &raw[..8] != RECORD_MAGIC { return Err(PoolError::Corrupt); }
        let height = u64::from_be_bytes(raw[8..16].try_into().map_err(|_| PoolError::Corrupt)?);
        let block_id = raw[16..48].try_into().map_err(|_| PoolError::Corrupt)?;
        let base_hash = raw[48..80].try_into().map_err(|_| PoolError::Corrupt)?;
        let result_hash = raw[80..112].try_into().map_err(|_| PoolError::Corrupt)?;
        let count = u16::from_be_bytes(raw[112..114].try_into().map_err(|_| PoolError::Corrupt)?) as usize;
        if count > MAX_BLOCK_TRANSACTIONS { return Err(PoolError::Bounds); }
        let mut transactions = Vec::with_capacity(count); let mut p = 114usize;
        for _ in 0..count {
            let n = u32::from_be_bytes(raw.get(p..p+4).ok_or(PoolError::Corrupt)?.try_into().map_err(|_| PoolError::Corrupt)?) as usize;
            p += 4;
            if n > MAX_ENVELOPE_SIZE { return Err(PoolError::Bounds); }
            let end = p.checked_add(n).ok_or(PoolError::Bounds)?;
            transactions.push(raw.get(p..end).ok_or(PoolError::Corrupt)?.to_vec()); p = end;
        }
        if p != raw.len() { return Err(PoolError::Corrupt); }
        Ok(Self { height, block_id, base_hash, result_hash, transactions })
    }
}

#[cfg(test)]
#[path = "pool_tests.rs"]
mod tests;
