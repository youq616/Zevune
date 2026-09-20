//! NO-FUNDS Orchard state machine and bounded journal used by the lab adapter.
//! Public default constructors support empty genesis. Funded bootstrap is opt-in.
//! Every replay and commit rechecks actual authorization; hashes are not finality.
use std::collections::{BTreeSet, VecDeque};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, Write};
use std::path::Path;

use incrementalmerkletree::frontier::Frontier;
use orchard::note::ExtractedNoteCommitment;
use orchard::tree::MerkleHashOrchard;
use sha2::{Digest, Sha256};

use crate::wire::{decode, AuthorizationVerifier, MAX_ENVELOPE_SIZE};
use crate::{MAX_ANCHORS, NETWORK};

type Hash = [u8; 32];
const FILE_MAGIC: &[u8; 8] = b"ZVOPOL01";
const BOUND_FILE_MAGIC: &[u8; 8] = b"ZVOPOL02";
const ACTIVE_FILE_MAGIC: &[u8; 8] = b"ZVOPOL03";
const RECORD_MAGIC: &[u8; 8] = b"ZVOBLK01";
pub const MAX_BLOCK_TRANSACTIONS: usize = 16;
pub const MAX_COMMITMENTS: usize = 65_536;
pub const MAX_RECORDS: u64 = 10_000;
pub const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_RECORD_BYTES: usize = 114 + MAX_BLOCK_TRANSACTIONS * (4 + MAX_ENVELOPE_SIZE);

/// Fixed laboratory policies, selected only by an authenticated genesis format.
/// These are not operator-adjustable consensus limits or migration settings.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StorageProfile {
    LegacyJournal,
    ActiveSegmentsV1,
}
impl StorageProfile {
    pub fn max_records(self) -> u64 {
        match self {
            Self::LegacyJournal => MAX_RECORDS,
            Self::ActiveSegmentsV1 => 1_000_000,
        }
    }
    pub fn max_journal_bytes(self) -> u64 {
        match self {
            Self::LegacyJournal => MAX_JOURNAL_BYTES,
            Self::ActiveSegmentsV1 => 1024 * 1024 * 1024,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PoolError {
    Bounds,
    Height,
    Genesis,
    Domain,
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
    profile: StorageProfile,
    height: u64,
    head: Hash,
    genesis: Hash,
    signing_domain: Option<Hash>,
    fees: u64,
    frontier: Frontier<MerkleHashOrchard, 32>,
    // Derived only from this frontier; never imported or serialized. Updating
    // the frontier and this root is one unpublished transaction state change.
    commitment_root: Hash,
    spent: BTreeSet<Hash>,
    outputs: BTreeSet<Hash>,
    anchors: VecDeque<Hash>,
}
impl State {
    #[cfg(test)]
    fn from_genesis(commitments: &[Hash]) -> Result<Self, PoolError> {
        Self::from_policy(commitments, None)
    }
    fn from_policy(commitments: &[Hash], signing_domain: Option<Hash>) -> Result<Self, PoolError> {
        Self::from_storage_policy(commitments, signing_domain, StorageProfile::LegacyJournal)
    }
    fn from_storage_policy(
        commitments: &[Hash],
        signing_domain: Option<Hash>,
        profile: StorageProfile,
    ) -> Result<Self, PoolError> {
        if commitments.len() > MAX_COMMITMENTS {
            return Err(PoolError::Bounds);
        }
        let mut frontier = Frontier::empty();
        let mut outputs = BTreeSet::new();
        for cm in commitments {
            let cmx =
                Option::<ExtractedNoteCommitment>::from(ExtractedNoteCommitment::from_bytes(cm))
                    .ok_or(PoolError::Genesis)?;
            if !outputs.insert(*cm) || !frontier.append(MerkleHashOrchard::from_cmx(&cmx)) {
                return Err(PoolError::Genesis);
            }
        }
        let root = frontier.root().to_bytes();
        let genesis =
            Sha256::digest(genesis_bytes_profile(commitments, signing_domain, profile)?).into();
        Ok(Self {
            profile,
            height: 0,
            head: [0; 32],
            genesis,
            signing_domain,
            fees: 0,
            frontier,
            commitment_root: root,
            spent: BTreeSet::new(),
            outputs,
            anchors: VecDeque::from([root]),
        })
    }
    fn summary(&self) -> Summary {
        let mut h = Sha256::new();
        h.update(b"ZEVUNE-ORCHARD-POOL-STATE\0\x01");
        h.update(self.genesis);
        h.update(self.height.to_be_bytes());
        h.update(self.head);
        h.update(self.fees.to_be_bytes());
        h.update(self.frontier.tree_size().to_be_bytes());
        let root = self.commitment_root;
        h.update(root);
        h.update((self.spent.len() as u64).to_be_bytes());
        for nf in &self.spent {
            h.update(nf);
        }
        h.update((self.outputs.len() as u64).to_be_bytes());
        for cm in &self.outputs {
            h.update(cm);
        }
        h.update((self.anchors.len() as u64).to_be_bytes());
        for anchor in &self.anchors {
            h.update(anchor);
        }
        Summary {
            height: self.height,
            app_hash: h.finalize().into(),
            root,
            commitments: self.frontier.tree_size(),
            nullifiers: self.spent.len() as u64,
            fees: self.fees,
        }
    }
    fn execute(
        &self,
        height: u64,
        block_id: Hash,
        transactions: &[Vec<u8>],
        verifier: &AuthorizationVerifier,
    ) -> Result<State, PoolError> {
        self.validate_block(height, block_id, transactions)?;
        #[cfg(test)]
        replay::COPYING_EXECUTIONS.with(|count| count.set(count.get() + 1));
        let mut next = self.clone();
        next.execute_unpublished(height, block_id, transactions, verifier)?;
        Ok(next)
    }
    fn validate_block(
        &self,
        height: u64,
        block_id: Hash,
        transactions: &[Vec<u8>],
    ) -> Result<(), PoolError> {
        if height != self.height.checked_add(1).ok_or(PoolError::Height)?
            || height > self.profile.max_records()
            || block_id == [0; 32]
        {
            return Err(PoolError::Height);
        }
        if transactions.len() > MAX_BLOCK_TRANSACTIONS
            || transactions.iter().any(|tx| tx.len() > MAX_ENVELOPE_SIZE)
        {
            return Err(PoolError::Bounds);
        }
        Ok(())
    }
    // Only for a disposable, UNPUBLISHED state: a later transaction can fail
    // after earlier transactions have applied. execute() owns a clone; Replay
    // owns a reconstruction and discards it on ANY error. Never call on the
    // live PoolStore state or on the incremental proposal-selection state.
    fn execute_unpublished(
        &mut self,
        height: u64,
        block_id: Hash,
        transactions: &[Vec<u8>],
        verifier: &AuthorizationVerifier,
    ) -> Result<(), PoolError> {
        self.validate_block(height, block_id, transactions)?;
        let trusted_anchors = self.anchors.clone();
        for raw in transactions {
            self.apply_transaction(height, &trusted_anchors, raw, verifier)?;
        }
        self.finish_block(height, block_id);
        Ok(())
    }
    fn apply_transaction(
        &mut self,
        height: u64,
        trusted_anchors: &VecDeque<Hash>,
        raw: &[u8],
        verifier: &AuthorizationVerifier,
    ) -> Result<(), PoolError> {
        #[cfg(test)]
        selection::ATTEMPTS.with(|count| count.set(count.get() + 1));
        let decoded = decode(raw).map_err(|_| PoolError::Authorization)?;
        // Check the trusted genesis policy on EVERY execution, including
        // cache hits, replay and final commit. No legacy/domain fallback.
        if decoded.context.signing_domain != self.signing_domain {
            return Err(PoolError::Domain);
        }
        if decoded.context.expiry_height < height {
            return Err(PoolError::Expired);
        }
        // Only roots committed before this block are spend anchors. Never
        // expose roots of partially executed candidate blocks as trusted.
        if !trusted_anchors.contains(&decoded.bundle.anchor().to_bytes()) {
            return Err(PoolError::Anchor);
        }
        if self
            .outputs
            .len()
            .checked_add(decoded.bundle.actions().len())
            .ok_or(PoolError::Bounds)?
            > MAX_COMMITMENTS
        {
            return Err(PoolError::Bounds);
        }
        for a in decoded.bundle.actions().iter() {
            if self.spent.contains(&a.nullifier().to_bytes()) {
                return Err(PoolError::DoubleSpend);
            }
            if self.outputs.contains(&a.cmx().to_bytes()) {
                return Err(PoolError::DuplicateOutput);
            }
        }
        verifier.verify(raw).map_err(|_| PoolError::Authorization)?;
        let fees = self
            .fees
            .checked_add(decoded.context.fee)
            .ok_or(PoolError::FeeOverflow)?;
        let mut frontier = self.frontier.clone();
        for a in decoded.bundle.actions().iter() {
            if !frontier.append(MerkleHashOrchard::from_cmx(a.cmx())) {
                return Err(PoolError::Bounds);
            }
        }
        let commitment_root = frontier.root().to_bytes();
        // No fallible operation follows this point. A rejected candidate must
        // not leak partial fees, nullifiers or outputs into the next candidate.
        for a in decoded.bundle.actions().iter() {
            self.spent.insert(a.nullifier().to_bytes());
            self.outputs.insert(a.cmx().to_bytes());
        }
        self.fees = fees;
        self.frontier = frontier;
        self.commitment_root = commitment_root;
        Ok(())
    }
    fn finish_block(&mut self, height: u64, block_id: Hash) {
        self.height = height;
        self.head = block_id;
        let root = self.commitment_root;
        if self.anchors.back() != Some(&root) {
            self.anchors.push_back(root);
            if self.anchors.len() > MAX_ANCHORS {
                self.anchors.pop_front();
            }
        }
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
    pub fn result(&self) -> &Summary {
        &self.result
    }
}

/// A bounded single-writer laboratory journal. No account secrets are stored.
/// A successful write followed by lost acknowledgement may be present on replay.
/// No automatic truncation, reset, state repair or signer reset is performed.
pub struct PoolStore {
    file: File,
    active: Option<active::ActiveJournal>,
    state: State,
    verifier: AuthorizationVerifier,
    available: bool,
    length: u64,
    #[cfg(test)]
    fault: u8,
    #[cfg(test)]
    test_byte_limit: Option<u64>,
}
impl PoolStore {
    /// Create an empty pool. Does not issue assets or overwrite any existing file.
    pub fn create(path: &Path) -> Result<Self, PoolError> {
        Self::create_with_genesis(path, &[])
    }
    /// Reopen only an empty-genesis pool, revalidating every persisted transaction.
    pub fn open(path: &Path) -> Result<Self, PoolError> {
        Self::open_with_genesis(path, &[])
    }
    fn create_with_genesis(path: &Path, initial: &[Hash]) -> Result<Self, PoolError> {
        Self::create_with_policy(path, initial, None)
    }
    fn create_with_policy(
        path: &Path,
        initial: &[Hash],
        signing_domain: Option<Hash>,
    ) -> Result<Self, PoolError> {
        Self::create_with_profile(path, initial, signing_domain, StorageProfile::LegacyJournal)
    }
    fn create_with_profile(
        path: &Path,
        initial: &[Hash],
        signing_domain: Option<Hash>,
        profile: StorageProfile,
    ) -> Result<Self, PoolError> {
        let state = State::from_storage_policy(initial, signing_domain, profile)?;
        let header = genesis_bytes_profile(initial, signing_domain, profile)?;
        if profile == StorageProfile::ActiveSegmentsV1 {
            let (file, active) = active::ActiveJournal::create(path, &header)?;
            return Ok(Self {
                file,
                active: Some(active),
                state,
                verifier: AuthorizationVerifier::new(),
                available: true,
                length: header.len() as u64,
                #[cfg(test)]
                fault: 0,
                #[cfg(test)]
                test_byte_limit: None,
            });
        }
        let mut options = OpenOptions::new();
        options.create_new(true).read(true).append(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(path).map_err(|_| PoolError::Storage)?;
        file.try_lock().map_err(|_| PoolError::Locked)?;
        file.write_all(&header).map_err(|_| PoolError::Storage)?;
        file.sync_all().map_err(|_| PoolError::Storage)?;
        // Directory durability is platform/filesystem dependent, explicitly not
        // a promise of zero-loss recovery after every power failure.
        Ok(Self {
            file,
            active: None,
            state,
            verifier: AuthorizationVerifier::new(),
            available: true,
            length: header.len() as u64,
            #[cfg(test)]
            fault: 0,
            #[cfg(test)]
            test_byte_limit: None,
        })
    }
    fn open_with_genesis(path: &Path, initial: &[Hash]) -> Result<Self, PoolError> {
        Self::open_with_policy(path, initial, None)
    }
    fn open_with_policy(
        path: &Path,
        initial: &[Hash],
        signing_domain: Option<Hash>,
    ) -> Result<Self, PoolError> {
        Self::open_with_profile(path, initial, signing_domain, StorageProfile::LegacyJournal)
    }
    fn open_with_profile(
        path: &Path,
        initial: &[Hash],
        signing_domain: Option<Hash>,
        profile: StorageProfile,
    ) -> Result<Self, PoolError> {
        if profile == StorageProfile::ActiveSegmentsV1 {
            let expected_header = genesis_bytes_profile(initial, signing_domain, profile)?;
            let (file, active) = active::ActiveJournal::open(path, &expected_header)?;
            let length = active.length();
            let expected_genesis = Sha256::digest(&expected_header).into();
            let (state, verifier) = Self::replay_active_handles(&file, &active, expected_genesis)?;
            return Ok(Self {
                file,
                active: Some(active),
                state,
                verifier,
                available: true,
                length,
                #[cfg(test)]
                fault: 0,
                #[cfg(test)]
                test_byte_limit: None,
            });
        }
        let info = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
        if !info.file_type().is_file() || info.len() > MAX_JOURNAL_BYTES {
            return Err(PoolError::Bounds);
        }
        let file = OpenOptions::new()
            .read(true)
            .append(true)
            .open(path)
            .map_err(|_| PoolError::Storage)?;
        file.try_lock().map_err(|_| PoolError::Locked)?;
        Self::replay_locked_file(file, initial, signing_domain)
    }

    // Every caller keeps the original owning handles and their lock. Archives
    // discard the unpublished state; ordinary open publishes it only after this
    // complete replay. A fresh verifier prevents a previous verification result
    // from becoming an archive-authentication shortcut.
    fn replay_active_handles(
        file: &File,
        active: &active::ActiveJournal,
        expected_genesis: Hash,
    ) -> Result<(State, AuthorizationVerifier), PoolError> {
        let profile = StorageProfile::ActiveSegmentsV1;
        // Parse the physical genesis alone first. An oversized commitment count
        // must never borrow its alleged header bytes from the first journal.
        let physical_header = active.read_header(file)?;
        let length = active.length();
        let mut reader = active.reader(file)?;
        let header = replay::read_header_profile(&mut reader, length, profile)?;
        if header.length != physical_header.length
            || header.initial != physical_header.initial
            || header.signing_domain != physical_header.signing_domain
        {
            return Err(PoolError::Genesis);
        }
        let state = State::from_storage_policy(&header.initial, header.signing_domain, profile)?;
        // Bind the header actually replayed now to the caller's independent
        // policy/pin, not only to a header read earlier while opening names.
        if state.genesis != expected_genesis {
            return Err(PoolError::Genesis);
        }
        let verifier = AuthorizationVerifier::new();
        let mut replay = replay::Replay::new(reader, length, header.length, state)?;
        let mut start = header.length;
        while replay.next_block(&verifier)?.is_some() {
            let end = replay.byte_position()?;
            active.validate_frame(start, end)?;
            start = end;
        }
        let (state, _) = replay.finish()?;
        active.check(file)?;
        Ok((state, verifier))
    }
    // The caller owns the file and its lock for the entire replay. Recovery
    // readers keep the returned store private and never expose a write API.
    fn replay_locked_file(
        mut file: File,
        initial: &[Hash],
        signing_domain: Option<Hash>,
    ) -> Result<Self, PoolError> {
        file.rewind().map_err(|_| PoolError::Storage)?;
        let length = file.metadata().map_err(|_| PoolError::Storage)?.len();
        if length > MAX_JOURNAL_BYTES {
            return Err(PoolError::Bounds);
        }
        let header = replay::read_header(&mut file, length)?;
        if header.initial != initial || header.signing_domain != signing_domain {
            return Err(PoolError::Genesis);
        }
        let verifier = AuthorizationVerifier::new();
        let state = State::from_policy(initial, signing_domain)?;
        let mut replay = replay::Replay::new(&mut file, length, header.length, state)?;
        while replay.next_block(&verifier)?.is_some() {}
        let (state, _) = replay.finish()?;
        Ok(Self {
            file,
            active: None,
            state,
            verifier,
            available: true,
            length,
            #[cfg(test)]
            fault: 0,
            #[cfg(test)]
            test_byte_limit: None,
        })
    }
    pub fn summary(&self) -> Result<Summary, PoolError> {
        if !self.available {
            return Err(PoolError::Unavailable);
        }
        Ok(self.state.summary())
    }
    pub fn storage_profile(&self) -> StorageProfile {
        self.state.profile
    }
    /// Capacity of the same locked committed state, not a new authentication
    /// of every sealed transaction or a free-disk/power-loss guarantee.
    pub fn active_capacity(&mut self) -> Result<(Summary, u64, u32, u32), PoolError> {
        let summary = self.summary()?;
        let active = self.active.as_ref().ok_or(PoolError::Bounds)?;
        let result = (|| {
            active.check(&self.file)?;
            let (length, segments, tail) = active.capacity();
            if length != self.length {
                return Err(PoolError::Corrupt);
            }
            Ok((summary, length, segments, tail))
        })();
        if result.is_err() {
            self.available = false;
        }
        result
    }
    /// Compare against an independently trusted checkpoint. This does not make
    /// an untrusted hash authentic and is not a consensus light-client proof.
    pub fn check_checkpoint(&self, height: u64, app_hash: Hash) -> Result<(), PoolError> {
        let s = self.summary()?;
        if s.height != height || s.app_hash != app_hash {
            return Err(PoolError::Stale);
        }
        Ok(())
    }
    pub fn prepare(
        &self,
        height: u64,
        block_id: Hash,
        transactions: &[Vec<u8>],
    ) -> Result<PreparedBlock, PoolError> {
        let base = self.summary()?;
        // Reject a known-unpersistable candidate before cryptographic work or
        // reporting a successful preview. Commit repeats this same accounting.
        self.record_end(transactions)?;
        let next = self
            .state
            .execute(height, block_id, transactions, &self.verifier)?;
        Ok(PreparedBlock {
            base,
            result: next.summary(),
            block_id,
            transactions: transactions.to_vec(),
        })
    }
    pub fn commit(&mut self, prepared: PreparedBlock) -> Result<Summary, PoolError> {
        #[cfg(test)]
        let timing_attempt = commit_timing::Attempt::start(
            self.active.is_some(),
            prepared.result.height,
            !prepared.transactions.is_empty(),
        );
        #[cfg(test)]
        commit_timing::begin(commit_timing::Phase::Preflight);
        let base = self.summary()?;
        if base != prepared.base {
            return Err(PoolError::Stale);
        }
        let new_length = self.record_end(&prepared.transactions)?;
        #[cfg(test)]
        commit_timing::end();
        #[cfg(test)]
        commit_timing::begin(commit_timing::Phase::Reexecute);
        let next = self.state.execute(
            prepared.result.height,
            prepared.block_id,
            &prepared.transactions,
            &self.verifier,
        )?;
        let result = next.summary();
        if result != prepared.result {
            return Err(PoolError::Stale);
        }
        #[cfg(test)]
        commit_timing::end();
        #[cfg(test)]
        commit_timing::begin(commit_timing::Phase::EncodeFrame);
        let body = Record {
            height: result.height,
            block_id: prepared.block_id,
            base_hash: base.app_hash,
            result_hash: result.app_hash,
            transactions: prepared.transactions,
        }
        .encode()?;
        // Fail closed if the encoder and preflight ever diverge after a format
        // change. No bytes have been written and no committed state has changed.
        if self.length.checked_add(body.len() as u64 + 36) != Some(new_length) {
            return Err(PoolError::Corrupt);
        }
        if self.active.is_none() {
            let file_length = match self.file.metadata() {
                Ok(meta) => meta.len(),
                Err(_) => {
                    self.available = false;
                    return Err(PoolError::Storage);
                }
            };
            if file_length != self.length {
                self.available = false;
                return Err(PoolError::Corrupt);
            }
        }
        let mut frame = (body.len() as u32).to_be_bytes().to_vec();
        frame.extend_from_slice(&body);
        frame.extend_from_slice(&Sha256::digest(&body));
        #[cfg(test)]
        commit_timing::end();
        let written = if let Some(active) = self.active.as_mut() {
            active.append(&self.file, &frame)
        } else {
            self.append(&frame).map_err(|_| PoolError::Storage)
        };
        if let Err(error) = written {
            self.available = false;
            return Err(error);
        }
        #[cfg(test)]
        commit_timing::begin(commit_timing::Phase::StatePublish);
        self.state = next;
        self.length = new_length;
        #[cfg(test)]
        commit_timing::end();
        #[cfg(test)]
        timing_attempt.accept();
        Ok(result)
    }
    fn journal_byte_limit(&self) -> u64 {
        #[cfg(test)]
        if let Some(limit) = self.test_byte_limit {
            return limit.min(self.state.profile.max_journal_bytes());
        }
        self.state.profile.max_journal_bytes()
    }
    fn record_end(&self, transactions: &[Vec<u8>]) -> Result<u64, PoolError> {
        let end = budget::record_end(self.length, self.journal_byte_limit(), transactions)?;
        if let Some(active) = &self.active {
            active.check_frame(end - self.length)?;
        }
        Ok(end)
    }
    fn append(&mut self, frame: &[u8]) -> std::io::Result<()> {
        #[cfg(test)]
        {
            if self.fault == 1 {
                self.fault = 0;
                self.file.write_all(&frame[..5])?;
                return Err(std::io::Error::other("test-only partial write"));
            }
        }
        self.file.write_all(frame)?;
        #[cfg(test)]
        {
            if self.fault == 2 {
                self.fault = 0;
                return Err(std::io::Error::other("test-only sync failure"));
            }
        }
        self.file.sync_all()
    }
}

#[cfg(test)]
fn genesis_bytes(initial: &[Hash]) -> Result<Vec<u8>, PoolError> {
    genesis_bytes_policy(initial, None)
}
fn genesis_bytes_policy(
    initial: &[Hash],
    signing_domain: Option<Hash>,
) -> Result<Vec<u8>, PoolError> {
    genesis_bytes_profile(initial, signing_domain, StorageProfile::LegacyJournal)
}
fn genesis_bytes_profile(
    initial: &[Hash],
    signing_domain: Option<Hash>,
    profile: StorageProfile,
) -> Result<Vec<u8>, PoolError> {
    if initial.len() > MAX_COMMITMENTS {
        return Err(PoolError::Bounds);
    }
    if signing_domain == Some([0; 32])
        || (profile == StorageProfile::ActiveSegmentsV1 && signing_domain.is_none())
    {
        return Err(PoolError::Domain);
    }
    let mut out = if profile == StorageProfile::ActiveSegmentsV1 {
        ACTIVE_FILE_MAGIC.to_vec()
    } else if signing_domain.is_some() {
        BOUND_FILE_MAGIC.to_vec()
    } else {
        FILE_MAGIC.to_vec()
    };
    out.extend_from_slice(&Sha256::digest(NETWORK.as_bytes()));
    if let Some(domain) = signing_domain {
        out.extend_from_slice(&domain);
    }
    out.extend_from_slice(&(initial.len() as u32).to_be_bytes());
    for cm in initial {
        out.extend_from_slice(cm);
    }
    Ok(out)
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
        if self.transactions.len() > MAX_BLOCK_TRANSACTIONS {
            return Err(PoolError::Bounds);
        }
        let mut b = RECORD_MAGIC.to_vec();
        b.extend_from_slice(&self.height.to_be_bytes());
        b.extend_from_slice(&self.block_id);
        b.extend_from_slice(&self.base_hash);
        b.extend_from_slice(&self.result_hash);
        b.extend_from_slice(&(self.transactions.len() as u16).to_be_bytes());
        for tx in &self.transactions {
            if tx.len() > MAX_ENVELOPE_SIZE {
                return Err(PoolError::Bounds);
            }
            b.extend_from_slice(&(tx.len() as u32).to_be_bytes());
            b.extend_from_slice(tx);
        }
        Ok(b)
    }
    fn decode(raw: &[u8]) -> Result<Self, PoolError> {
        if !(114..=MAX_RECORD_BYTES).contains(&raw.len()) || &raw[..8] != RECORD_MAGIC {
            return Err(PoolError::Corrupt);
        }
        let height = u64::from_be_bytes(raw[8..16].try_into().map_err(|_| PoolError::Corrupt)?);
        let block_id = raw[16..48].try_into().map_err(|_| PoolError::Corrupt)?;
        let base_hash = raw[48..80].try_into().map_err(|_| PoolError::Corrupt)?;
        let result_hash = raw[80..112].try_into().map_err(|_| PoolError::Corrupt)?;
        let count =
            u16::from_be_bytes(raw[112..114].try_into().map_err(|_| PoolError::Corrupt)?) as usize;
        if count > MAX_BLOCK_TRANSACTIONS {
            return Err(PoolError::Bounds);
        }
        let mut transactions = Vec::with_capacity(count);
        let mut p = 114usize;
        for _ in 0..count {
            let n = u32::from_be_bytes(
                raw.get(p..p + 4)
                    .ok_or(PoolError::Corrupt)?
                    .try_into()
                    .map_err(|_| PoolError::Corrupt)?,
            ) as usize;
            p += 4;
            if n > MAX_ENVELOPE_SIZE {
                return Err(PoolError::Bounds);
            }
            let end = p.checked_add(n).ok_or(PoolError::Bounds)?;
            transactions.push(raw.get(p..end).ok_or(PoolError::Corrupt)?.to_vec());
            p = end;
        }
        if p != raw.len() {
            return Err(PoolError::Corrupt);
        }
        Ok(Self {
            height,
            block_id,
            base_hash,
            result_hash,
            transactions,
        })
    }
}

#[cfg(test)]
#[path = "pool_tests.rs"]
mod tests;

#[cfg(test)]
pub(crate) use tests::fixtures;

#[path = "wallet_history.rs"]
pub mod history;

#[cfg(test)]
#[path = "wallet_flow_tests.rs"]
mod wallet_flow_tests;

#[cfg(feature = "local-funding-lab")]
pub mod testnet;

/// Read-only, bounded proposal selection; never a commit or finality API.
pub mod selection;

#[cfg(test)]
#[path = "pool/capacity_tests.rs"]
mod capacity_tests;

mod budget;

/// Checkpoint-pinned, create-only recovery copies; not snapshots or finality.
pub mod recovery;

mod replay;

mod active;

#[cfg(all(test, feature = "local-funding-lab"))]
#[path = "pool/active_flow_tests.rs"]
mod active_flow_tests;

#[cfg(all(test, feature = "local-funding-lab"))]
#[path = "pool/root_cache_tests.rs"]
mod root_cache_tests;

#[cfg(test)]
mod commit_timing;

#[cfg(all(test, feature = "local-funding-lab"))]
mod commit_timing_tests;
