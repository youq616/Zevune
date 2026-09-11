//! Bounded, local NO-FUNDS wallet core. No networking, telemetry or master key.
//! History is supplied by a locally revalidated PoolStore, not by an RPC peer.
//! This is not a light client, production wallet or finalized address standard.
use std::collections::{BTreeMap, BTreeSet};

use incrementalmerkletree::{Hashable, Level};
use orchard::builder::{Builder, BundleType};
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, Scope, SpendAuthorizingKey, SpendingKey};
use orchard::tree::{MerkleHashOrchard, MerklePath};
use orchard::value::NoteValue;
use orchard::{Address, Note};
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

use crate::pool::history::WalletHistory;
use crate::pool::MAX_COMMITMENTS;
use crate::wire::{decode, encode, AuthorizationVerifier};
use crate::{signing_digest, Context, CIRCUIT, MAX_ACTIONS, NETWORK, VERSION};

pub mod vault;
type Hash = [u8; 32];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WalletError {
    Entropy,
    Key,
    Bounds,
    NotSynced,
    History,
    Rollback,
    InsufficientFunds,
    Pending,
    Proof,
    Backup,
    Authentication,
    Storage,
}
impl std::fmt::Display for WalletError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "wallet operation failed: {self:?}")
    }
}
impl std::error::Error for WalletError {}

#[derive(Clone, Copy, Eq, PartialEq)]
struct Checkpoint {
    genesis: Hash,
    height: u64,
    app_hash: Hash,
}
struct OwnedNote {
    note: Note,
    position: usize,
}
struct Scanned {
    leaves: Vec<MerkleHashOrchard>,
    notes: BTreeMap<Hash, OwnedNote>,
}
#[derive(Clone)]
struct Pending {
    expiry: u64,
    txid: Hash,
    nullifiers: Vec<Hash>,
}

/// Secret-bearing type: intentionally no Debug, Clone or serialization derive.
/// Only our seed buffer is zeroized. Upstream key/note copies and the operating
/// system are not covered by a secure-memory-erasure guarantee.
pub struct Wallet {
    seed: Zeroizing<[u8; 32]>,
    checkpoint: Option<Checkpoint>,
    scanned: Option<Scanned>,
    pending: Option<Pending>,
}

/// Cache public proving/verification parameters between local payments.
pub struct WalletProver {
    key: ProvingKey,
    verifier: AuthorizationVerifier,
}
impl Default for WalletProver {
    fn default() -> Self {
        Self::new()
    }
}
impl WalletProver {
    pub fn new() -> Self {
        Self {
            key: ProvingKey::build(CIRCUIT),
            verifier: AuthorizationVerifier::new(),
        }
    }
}

/// Public signed transaction, not a receipt or confirmation certificate.
pub struct Payment {
    bytes: Vec<u8>,
    txid: Hash,
}
impl Payment {
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn id(&self) -> Hash {
        self.txid
    }
}

impl Wallet {
    pub fn create() -> Result<Self, WalletError> {
        let mut seed = Zeroizing::new([0; 32]);
        OsRng.try_fill_bytes(seed.as_mut()).map_err(|_| WalletError::Entropy)?;
        let result = Self { seed, checkpoint: None, scanned: None, pending: None };
        result.spending_key()?;
        Ok(result)
    }
    fn spending_key(&self) -> Result<SpendingKey, WalletError> {
        // Test coin type 1, account 0. NOT an allocated Zevune mainnet coin type.
        let account = zip32::AccountId::try_from(0u32).map_err(|_| WalletError::Key)?;
        SpendingKey::from_zip32_seed(self.seed.as_ref(), 1, account)
            .map_err(|_| WalletError::Key)
    }
    pub fn receive_address(&self, index: u32) -> Result<Address, WalletError> {
        Ok(FullViewingKey::from(&self.spending_key()?).address_at(index, Scope::External))
    }
    pub fn height(&self) -> Option<u64> {
        self.checkpoint.map(|c| c.height)
    }
    pub fn pending_id(&self) -> Option<Hash> {
        self.pending.as_ref().map(|p| p.txid)
    }
    pub fn balance(&self) -> Result<u64, WalletError> {
        self.scanned.as_ref().ok_or(WalletError::NotSynced)?.notes.values()
            .try_fold(0u64, |v, n| v.checked_add(n.note.value().inner()).ok_or(WalletError::Bounds))
    }
    pub fn available_balance(&self) -> Result<u64, WalletError> {
        self.scanned.as_ref().ok_or(WalletError::NotSynced)?.notes.iter()
            .filter(|(nf, _)| !self.pending.as_ref().is_some_and(|p| p.nullifiers.contains(nf)))
            .try_fold(0u64, |v, (_, n)| v.checked_add(n.note.value().inner()).ok_or(WalletError::Bounds))
    }

    /// Full bounded rescan. The input can only be produced by a locally locked,
    /// cryptographically replayed journal. This is NOT authentication of a remote
    /// peer's tip. Existing checkpoint ancestry must be present, even on restore.
    pub fn sync(&mut self, history: &WalletHistory) -> Result<(), WalletError> {
        if let Some(c) = self.checkpoint {
            if c.genesis != history.genesis || history.tip().height < c.height {
                return Err(WalletError::Rollback);
            }
            if history.checkpoint(c.height).map(|s| s.app_hash) != Some(c.app_hash) {
                return Err(WalletError::Rollback);
            }
        }
        let fvk = FullViewingKey::from(&self.spending_key()?);
        let keys = [fvk.to_ivk(Scope::External), fvk.to_ivk(Scope::Internal)];
        let mut leaves = history.initial.iter().map(|cm| {
            let cmx = Option::<orchard::note::ExtractedNoteCommitment>::from(
                orchard::note::ExtractedNoteCommitment::from_bytes(cm))
                .ok_or(WalletError::History)?;
            Ok(MerkleHashOrchard::from_cmx(&cmx))
        }).collect::<Result<Vec<_>, WalletError>>()?;
        let mut notes = BTreeMap::new();
        let mut spent = BTreeSet::new();
        for block in &history.blocks {
            for raw in &block.transactions {
                let tx = decode(raw).map_err(|_| WalletError::History)?;
                let start = leaves.len();
                if start.checked_add(tx.bundle.actions().len()).ok_or(WalletError::Bounds)? > MAX_COMMITMENTS {
                    return Err(WalletError::Bounds);
                }
                for a in tx.bundle.actions().iter() {
                    let nf = a.nullifier().to_bytes();
                    spent.insert(nf);
                    notes.remove(&nf);
                    leaves.push(MerkleHashOrchard::from_cmx(a.cmx()));
                }
                for (action, _, note, _, _) in tx.bundle.decrypt_outputs_with_keys(&keys) {
                    if note.value().inner() == 0 {
                        continue;
                    }
                    let nf = note.nullifier(&fvk).to_bytes();
                    if action >= tx.bundle.actions().len() || spent.contains(&nf)
                        || notes.insert(nf, OwnedNote { note, position: start + action }).is_some() {
                        return Err(WalletError::History);
                    }
                }
            }
        }
        let tip = history.tip();
        if leaves.len() as u64 != tip.commitments || tree_root(&leaves)? != tip.root {
            return Err(WalletError::History);
        }
        // Construct everything before changing the live wallet, including pending
        // reservations. A spend conflict releases only still-unspent inputs.
        let pending = self.pending.clone().filter(|p| {
            tip.height <= p.expiry && !p.nullifiers.iter().any(|nf| spent.contains(nf))
        });
        self.scanned = Some(Scanned { leaves, notes });
        self.checkpoint = Some(Checkpoint { genesis: history.genesis, height: tip.height, app_hash: tip.app_hash });
        self.pending = pending;
        Ok(())
    }

    /// Build and locally validate a real payment. No network broadcast occurs.
    /// One pending payment at a time; save the encrypted wallet before handing
    /// bytes to a network broadcaster. Reserving funds is not chain confirmation.
    pub fn build_payment(&mut self, destination: Address, amount: u64, fee: u64,
        expiry: u64, prover: &WalletProver) -> Result<Payment, WalletError> {
        if self.pending.is_some() {
            return Err(WalletError::Pending);
        }
        let cp = self.checkpoint.ok_or(WalletError::NotSynced)?;
        let scanned = self.scanned.as_ref().ok_or(WalletError::NotSynced)?;
        let target = amount.checked_add(fee).ok_or(WalletError::Bounds)?;
        if amount == 0 || fee == 0 || target > i64::MAX as u64 || expiry <= cp.height
            || expiry > cp.height.checked_add(100).ok_or(WalletError::Bounds)? {
            return Err(WalletError::Bounds);
        }
        let mut ordered: Vec<_> = scanned.notes.iter().collect();
        ordered.sort_by_key(|(_, n)| n.position);
        let mut chosen = Vec::new();
        let mut total = 0u64;
        for (nf, n) in ordered.into_iter().take(MAX_ACTIONS) {
            total = total.checked_add(n.note.value().inner()).ok_or(WalletError::Bounds)?;
            if total > i64::MAX as u64 { return Err(WalletError::Bounds); }
            chosen.push((*nf, n));
            if total >= target { break; }
        }
        if total < target { return Err(WalletError::InsufficientFunds); }
        let sk = self.spending_key()?;
        let fvk = FullViewingKey::from(&sk);
        let first = chosen.first().ok_or(WalletError::InsufficientFunds)?.1;
        let path = witness(&scanned.leaves, first.position)?;
        let mut builder = Builder::new(BundleType::DEFAULT, VERSION, VERSION.default_flags(),
            path.root(first.note.commitment().into())).map_err(|_| WalletError::Proof)?;
        for (_, owned) in &chosen {
            builder.add_spend(fvk.clone(), owned.note, witness(&scanned.leaves, owned.position)?)
                .map_err(|_| WalletError::Proof)?;
        }
        builder.add_output(None, destination, NoteValue::from_raw(amount), [0; 512])
            .map_err(|_| WalletError::Proof)?;
        if total > target {
            builder.add_output(None, fvk.address_at(0u32, Scope::Internal),
                NoteValue::from_raw(total - target), [0; 512]).map_err(|_| WalletError::Proof)?;
        }
        let ctx = Context { network: NETWORK.into(), expiry_height: expiry, fee };
        let unsigned = builder.build::<i64>(OsRng).map_err(|_| WalletError::Proof)?
            .ok_or(WalletError::Proof)?.0;
        let digest = signing_digest(&unsigned, &ctx).map_err(|_| WalletError::Proof)?;
        let signed = unsigned.create_proof(&prover.key, OsRng).map_err(|_| WalletError::Proof)?
            .apply_signatures(OsRng, digest, &[SpendAuthorizingKey::from(&sk)])
            .map_err(|_| WalletError::Proof)?;
        let raw = encode(&signed, &ctx).map_err(|_| WalletError::Proof)?;
        prover.verifier.verify(&raw).map_err(|_| WalletError::Proof)?;
        let txid = Sha256::digest(&raw).into();
        self.pending = Some(Pending { expiry, txid, nullifiers: chosen.iter().map(|(nf, _)| *nf).collect() });
        Ok(Payment { bytes: raw, txid })
    }
}

fn tree_root(leaves: &[MerkleHashOrchard]) -> Result<Hash, WalletError> {
    let mut frontier = incrementalmerkletree::frontier::Frontier::<MerkleHashOrchard, 32>::empty();
    for leaf in leaves { if !frontier.append(*leaf) { return Err(WalletError::Bounds); } }
    Ok(frontier.root().to_bytes())
}
fn witness(leaves: &[MerkleHashOrchard], position: usize) -> Result<MerklePath, WalletError> {
    if position >= leaves.len() || leaves.len() > MAX_COMMITMENTS { return Err(WalletError::History); }
    let mut nodes = leaves.to_vec();
    let mut index = position;
    let mut path = [MerkleHashOrchard::empty_leaf(); 32];
    for (level, sibling) in path.iter_mut().enumerate() {
        let l = Level::from(level as u8);
        *sibling = nodes.get(index ^ 1).copied().unwrap_or_else(|| MerkleHashOrchard::empty_root(l));
        nodes = nodes.chunks(2).map(|p| MerkleHashOrchard::combine(l, &p[0],
            &p.get(1).copied().unwrap_or_else(|| MerkleHashOrchard::empty_root(l)))).collect();
        index >>= 1;
    }
    Ok(MerklePath::from_parts(position as u32, path))
}
