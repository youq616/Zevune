//! Deterministic, bounded public state for the local payment experiment.
use std::collections::BTreeSet;
use incrementalmerkletree::{frontier::Frontier, Hashable, Level};
use orchard::circuit::VerifyingKey;
use orchard::tree::{MerkleHashOrchard, MerklePath};
use orchard::{Anchor, Note};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use zevune_orchard_lab::{CIRCUIT, VERSION};
use crate::wire::{Transaction, MAX_TX};
use crate::{Error, Result, CHAIN, FEE, SUPPLY};

pub const MAX_BLOCK_TXS: usize = 8;
pub const MAX_BLOCKS: usize = 4096;
pub const MAX_NOTES: usize = 32768;
pub const MAX_EXPORT: usize = 32 * 1024 * 1024;

pub struct Verifier { key: VerifyingKey }
impl Default for Verifier { fn default() -> Self { Self::new() } }
impl Verifier {
    pub fn new() -> Self { Self { key: VerifyingKey::build(CIRCUIT) } }
    // Individual signature and proof verification, not randomized signature batches.
    fn authorize(&self, tx: &Transaction) -> Result<()> {
        let digest = tx.digest()?;
        for a in tx.bundle.actions().iter() { a.rk().verify(&digest, a.authorization()).map_err(|_| Error::Authorization)?; }
        tx.bundle.binding_validating_key().verify(&digest, tx.bundle.authorization().binding_signature()).map_err(|_| Error::Authorization)?;
        tx.bundle.verify_proof(&self.key).map_err(|_| Error::Authorization)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Block { pub height: u64, pub hash: String, pub txs: Vec<String> }
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Summary {
    pub chain_id: String, pub genesis_id: String, pub height: u64,
    pub app_hash: String, pub note_root: String, pub note_count: usize,
    pub spent_count: usize, pub burned_fees: u64, pub test_asset_payments: bool,
    pub real_funds_allowed: bool,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Export { pub format: u32, pub genesis: String, pub blocks: Vec<Block>, pub summary: Summary }

#[derive(Clone)]
pub struct Ledger {
    genesis_bytes: Vec<u8>, pub genesis_id: [u8; 32], pub height: u64,
    pub last_block: [u8; 32], pub leaves: Vec<MerkleHashOrchard>,
    frontier: Frontier<MerkleHashOrchard, 32>, pub spent: BTreeSet<[u8; 32]>,
    outputs: BTreeSet<[u8; 32]>, anchors: Vec<[u8; 32]>,
    burned: u64, history: Vec<Block>,
}
impl Ledger {
    pub fn genesis(bytes: &[u8], verifier: &Verifier) -> Result<Self> {
        let tx = Transaction::decode(bytes)?;
        if tx.kind != 0 || tx.genesis != [0;32] || tx.expiry != 0 || tx.fee != 0 || tx.bundle.flags().spends_enabled() || !tx.bundle.flags().outputs_enabled() || *tx.bundle.value_balance() != -(SUPPLY as i64) || *tx.bundle.anchor() != Anchor::empty_tree() { return Err(Error::Context); }
        verifier.authorize(&tx)?;
        let mut s = Self { genesis_bytes: bytes.to_vec(), genesis_id: Sha256::digest(bytes).into(), height: 0, last_block: [0;32], leaves: vec![], frontier: Frontier::empty(), spent: BTreeSet::new(), outputs: BTreeSet::new(), anchors: vec![], burned: 0, history: vec![] };
        s.add_effects(&tx)?; s.anchors.push(s.root()); Ok(s)
    }
    pub fn root(&self) -> [u8;32] { self.frontier.root().to_bytes() }
    pub fn check(&self, bytes: &[u8], at: u64, verifier: &Verifier) -> Result<Transaction> {
        let tx = Transaction::decode(bytes)?;
        if tx.kind != 1 || tx.genesis != self.genesis_id || tx.bundle.flags() != &VERSION.default_flags() || tx.bundle.actions().len() < 2 || tx.expiry < at || at == 0 { return Err(Error::Context); }
        if tx.fee != FEE || *tx.bundle.value_balance() != FEE as i64 { return Err(Error::Funds); }
        if !self.anchors.contains(&tx.bundle.anchor().to_bytes()) { return Err(Error::State); }
        self.check_effects(&tx)?;
        verifier.authorize(&tx)?; Ok(tx)
    }
    fn check_effects(&self, tx: &Transaction) -> Result<()> {
        if self.leaves.len().checked_add(tx.bundle.actions().len()).ok_or(Error::Limit)? > MAX_NOTES { return Err(Error::Limit); }
        let mut nfs = BTreeSet::new(); let mut cms = BTreeSet::new();
        for a in tx.bundle.actions().iter() {
            let nf = a.nullifier().to_bytes(); let cm = a.cmx().to_bytes();
            if self.spent.contains(&nf) || !nfs.insert(nf) || self.outputs.contains(&cm) || !cms.insert(cm) { return Err(Error::State); }
        } Ok(())
    }
    fn add_effects(&mut self, tx: &Transaction) -> Result<()> {
        self.check_effects(tx)?;
        for a in tx.bundle.actions().iter() {
            let leaf = MerkleHashOrchard::from_cmx(a.cmx());
            if !self.frontier.append(leaf) { return Err(Error::Limit); }
            self.leaves.push(leaf); self.outputs.insert(a.cmx().to_bytes()); self.spent.insert(a.nullifier().to_bytes());
        } Ok(())
    }
    pub fn preview(&self, block: &Block, verifier: &Verifier) -> Result<Self> {
        if self.height.checked_add(1) != Some(block.height) || self.history.len() >= MAX_BLOCKS || block.txs.len() > MAX_BLOCK_TXS { return Err(Error::Limit); }
        let hash = decode_hash(&block.hash)?;
        let mut candidate = self.clone();
        for bytes in &block.txs {
            let raw = decode_tx_hex(bytes)?;
            // Anchors are from preceding committed blocks; never trust caller roots.
            let tx = candidate.check(&raw, block.height, verifier)?;
            candidate.add_effects(&tx)?;
            candidate.burned = candidate.burned.checked_add(tx.fee).filter(|v| *v <= SUPPLY).ok_or(Error::Funds)?;
        }
        let root = candidate.root();
        if candidate.anchors.last() != Some(&root) { candidate.anchors.push(root); }
        if candidate.anchors.len() > 64 { candidate.anchors.remove(0); }
        candidate.height = block.height; candidate.last_block = hash; candidate.history.push(block.clone()); Ok(candidate)
    }
    pub fn summary(&self) -> Summary {
        let mut h = Sha256::new(); h.update(b"ZEVUNE-PAYMENT-LAB-STATE\0\x01"); h.update(self.genesis_id); h.update(self.height.to_be_bytes()); h.update(self.last_block); h.update(self.root());
        h.update((self.leaves.len() as u64).to_be_bytes()); h.update((self.spent.len() as u64).to_be_bytes());
        for nf in &self.spent { h.update(nf); }
        h.update(self.burned.to_be_bytes());
        h.update((self.anchors.len() as u64).to_be_bytes()); for root in &self.anchors { h.update(root); }
        Summary { chain_id: CHAIN.into(), genesis_id: hex::encode(self.genesis_id), height: self.height, app_hash: hex::encode(h.finalize()), note_root: hex::encode(self.root()), note_count: self.leaves.len(), spent_count: self.spent.len(), burned_fees: self.burned, test_asset_payments: true, real_funds_allowed: false }
    }
    pub fn export(&self) -> Export { Export { format: 1, genesis: hex::encode(&self.genesis_bytes), blocks: self.history.clone(), summary: self.summary() } }
    pub fn from_export(export: &Export, expected_genesis: &[u8], verifier: &Verifier) -> Result<Self> {
        if export.format != 1 || export.blocks.len() > MAX_BLOCKS || decode_tx_hex(&export.genesis)? != expected_genesis { return Err(Error::Context); }
        let mut s = Self::genesis(expected_genesis, verifier)?;
        for block in &export.blocks { s = s.preview(block, verifier)?; }
        if s.summary() != export.summary { return Err(Error::State); } Ok(s)
    }
    pub fn transactions(&self) -> Result<Vec<Transaction>> {
        let mut txs = vec![Transaction::decode(&self.genesis_bytes)?];
        for block in &self.history { for raw in &block.txs { txs.push(Transaction::decode(&decode_tx_hex(raw)?)?); } } Ok(txs)
    }
    pub fn witness(&self, position: usize, note: &Note) -> Result<MerklePath> {
        if position >= self.leaves.len() || self.leaves[position] != MerkleHashOrchard::from_cmx(&note.commitment().into()) { return Err(Error::State); }
        let mut nodes = self.leaves.clone(); let mut index = position;
        let mut path = [MerkleHashOrchard::empty_leaf();32];
        for (level, sibling) in path.iter_mut().enumerate() {
            let l = Level::from(level as u8);
            *sibling = nodes.get(index ^ 1).copied().unwrap_or_else(|| MerkleHashOrchard::empty_root(l));
            nodes = nodes.chunks(2).map(|pair| MerkleHashOrchard::combine(l, &pair[0], &pair.get(1).copied().unwrap_or_else(|| MerkleHashOrchard::empty_root(l)))).collect(); index >>= 1;
        }
        let path = MerklePath::from_parts(position as u32, path);
        if path.root(note.commitment().into()).to_bytes() != self.root() { return Err(Error::State); } Ok(path)
    }
}
pub fn decode_hash(value: &str) -> Result<[u8;32]> {
    if value.len() != 64 || value.bytes().any(|b| !b.is_ascii_hexdigit() || b.is_ascii_uppercase()) { return Err(Error::Encoding); }
    hex::decode(value).map_err(|_| Error::Encoding)?.try_into().map_err(|_| Error::Encoding)
}
pub fn decode_tx_hex(value: &str) -> Result<Vec<u8>> {
    if value.len() > MAX_TX*2 || value.bytes().any(|b| !b.is_ascii_hexdigit() || b.is_ascii_uppercase()) { return Err(Error::Limit); }
    hex::decode(value).map_err(|_| Error::Encoding)
}
