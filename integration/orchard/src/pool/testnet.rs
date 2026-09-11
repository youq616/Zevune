//! Opt-in, fixed-supply, NO-FUNDS local test genesis. Not a mainnet issuance rule.
//! Initial allocations (addresses, amounts and note openings) are PUBLIC. Ordinary
//! payments still use the unchanged real Orchard verifier; no later mint exists.
use super::{history::WalletHistory, Hash, PoolError, PoolStore, State, Summary};
use orchard::note::{ExtractedNoteCommitment, RandomSeed, Rho};
use orchard::value::NoteValue;
use orchard::{Address, Note, NoteVersion};
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;

const MAGIC: &[u8; 8] = b"ZVTGEN01";
const HEADER: usize = 50;
const ENTRY: usize = 115;
pub const TEST_SUPPLY: u64 = 100_000;
pub const MAX_ALLOCATIONS: usize = 16;
pub const MAX_GENESIS_BYTES: usize = HEADER + ENTRY * MAX_ALLOCATIONS;

/// No mutable fields or arbitrary commitment constructor. Every accepted note
/// opening is public and checked, so all validators independently verify supply.
pub struct TestGenesis {
    notes: Vec<Note>,
    bytes: Vec<u8>,
}
impl TestGenesis {
    pub fn generate(allocations: &[(Address, u64)]) -> Result<Self, PoolError> {
        if allocations.is_empty() || allocations.len() > MAX_ALLOCATIONS {
            return Err(PoolError::Genesis);
        }
        let mut total = 0u64;
        for (_, value) in allocations {
            if *value == 0 || *value > TEST_SUPPLY {
                return Err(PoolError::Genesis);
            }
            total = total.checked_add(*value).ok_or(PoolError::Genesis)?;
        }
        if total != TEST_SUPPLY {
            return Err(PoolError::Genesis);
        }
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(&Sha256::digest(crate::NETWORK.as_bytes()));
        bytes.extend_from_slice(&TEST_SUPPLY.to_be_bytes());
        bytes.extend_from_slice(&(allocations.len() as u16).to_be_bytes());
        for (address, value) in allocations {
            let mut produced = None;
            for _ in 0..128 {
                let mut raw_rho = [0; 32];
                let mut raw_seed = [0; 32];
                OsRng.try_fill_bytes(&mut raw_rho).map_err(|_| PoolError::Genesis)?;
                OsRng.try_fill_bytes(&mut raw_seed).map_err(|_| PoolError::Genesis)?;
                let Some(rho) = Option::<Rho>::from(Rho::from_bytes(&raw_rho)) else { continue; };
                let Some(seed) = Option::<RandomSeed>::from(RandomSeed::from_bytes(raw_seed, &rho)) else { continue; };
                // This is an explicit PUBLIC genesis opening, never a substitute
                // for authenticated decryption of an ordinary received output.
                if let Some(note) = Option::<Note>::from(Note::from_parts(*address, NoteValue::from_raw(*value), rho, seed, NoteVersion::V2)) {
                    produced = Some(note);
                    break;
                }
            }
            let note = produced.ok_or(PoolError::Genesis)?;
            bytes.extend_from_slice(&note.recipient().to_raw_address_bytes());
            bytes.extend_from_slice(&note.value().inner().to_be_bytes());
            bytes.extend_from_slice(&note.rho().to_bytes());
            bytes.extend_from_slice(note.rseed().as_bytes());
        }
        Self::decode(&bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, PoolError> {
        if !(HEADER + ENTRY..=MAX_GENESIS_BYTES).contains(&bytes.len())
            || &bytes[..8] != MAGIC
            || bytes[8..40] != Sha256::digest(crate::NETWORK.as_bytes())[..]
            || bytes[40..48] != TEST_SUPPLY.to_be_bytes()
        {
            return Err(PoolError::Genesis);
        }
        let count = u16::from_be_bytes(bytes[48..50].try_into().map_err(|_| PoolError::Genesis)?) as usize;
        if !(1..=MAX_ALLOCATIONS).contains(&count) || bytes.len() != HEADER + count * ENTRY {
            return Err(PoolError::Genesis);
        }
        let mut notes = Vec::with_capacity(count);
        let mut rhos = BTreeSet::new();
        let mut commitments = BTreeSet::new();
        let mut total = 0u64;
        for entry in bytes[HEADER..].as_chunks::<ENTRY>().0 {
            let address = Option::<Address>::from(Address::from_raw_address_bytes(&entry[..43].try_into().map_err(|_| PoolError::Genesis)?)).ok_or(PoolError::Genesis)?;
            let value = u64::from_be_bytes(entry[43..51].try_into().map_err(|_| PoolError::Genesis)?);
            if value == 0 || value > TEST_SUPPLY { return Err(PoolError::Genesis); }
            total = total.checked_add(value).ok_or(PoolError::Genesis)?;
            if total > TEST_SUPPLY { return Err(PoolError::Genesis); }
            let rho_bytes = entry[51..83].try_into().map_err(|_| PoolError::Genesis)?;
            let rho = Option::<Rho>::from(Rho::from_bytes(&rho_bytes)).ok_or(PoolError::Genesis)?;
            if !rhos.insert(rho_bytes) { return Err(PoolError::Genesis); }
            let seed = Option::<RandomSeed>::from(RandomSeed::from_bytes(entry[83..115].try_into().map_err(|_| PoolError::Genesis)?, &rho)).ok_or(PoolError::Genesis)?;
            let note = Option::<Note>::from(Note::from_parts(address, NoteValue::from_raw(value), rho, seed, NoteVersion::V2)).ok_or(PoolError::Genesis)?;
            let cm = ExtractedNoteCommitment::from(note.commitment()).to_bytes();
            if !commitments.insert(cm) { return Err(PoolError::Genesis); }
            notes.push(note);
        }
        if total != TEST_SUPPLY { return Err(PoolError::Genesis); }
        Ok(Self { notes, bytes: bytes.to_vec() })
    }
    pub fn bytes(&self) -> &[u8] { &self.bytes }
    pub fn digest(&self) -> Hash { Sha256::digest(&self.bytes).into() }
    fn commitments(&self) -> Vec<Hash> {
        self.notes.iter().map(|n| ExtractedNoteCommitment::from(n.commitment()).to_bytes()).collect()
    }
    pub fn initial_summary(&self) -> Result<Summary, PoolError> { Ok(State::from_genesis(&self.commitments())?.summary()) }
    pub fn create_pool(&self, path: &Path) -> Result<PoolStore, PoolError> { PoolStore::create_with_genesis(path, &self.commitments()) }
    pub fn open_pool(&self, path: &Path) -> Result<PoolStore, PoolError> { PoolStore::open_with_genesis(path, &self.commitments()) }
    /// Attach public genesis allocations ONLY after full journal authorization
    /// replay and exact commitment-order comparison. No remote peer is trusted.
    pub fn wallet_history(&self, pool: &mut PoolStore) -> Result<WalletHistory, PoolError> {
        let mut history = pool.wallet_history()?;
        if history.initial != self.commitments() { return Err(PoolError::Genesis); }
        history.genesis_notes = self.notes.clone();
        Ok(history)
    }
    pub fn write_new(&self, path: &Path) -> Result<(), PoolError> {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)] { use std::os::unix::fs::OpenOptionsExt; options.mode(0o600); }
        let mut file = options.open(path).map_err(|_| PoolError::Storage)?;
        file.write_all(&self.bytes).map_err(|_| PoolError::Storage)?;
        file.sync_all().map_err(|_| PoolError::Storage)
    }
    pub fn read_pinned(path: &Path, expected: Hash) -> Result<Self, PoolError> {
        let info = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
        if !info.file_type().is_file() || info.len() > MAX_GENESIS_BYTES as u64 || expected == [0; 32] { return Err(PoolError::Genesis); }
        let file = OpenOptions::new().read(true).open(path).map_err(|_| PoolError::Storage)?;
        if !file.metadata().map_err(|_| PoolError::Storage)?.is_file() { return Err(PoolError::Genesis); }
        let mut bytes = Vec::with_capacity(MAX_GENESIS_BYTES);
        file.take(MAX_GENESIS_BYTES as u64 + 1).read_to_end(&mut bytes).map_err(|_| PoolError::Storage)?;
        if Hash::from(Sha256::digest(&bytes)) != expected { return Err(PoolError::Genesis); }
        Self::decode(&bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wallet::Wallet;
    #[test]
    fn fixed_supply_and_canonical_openings() {
        let wallet = Wallet::create().unwrap();
        let addr = wallet.receive_address(0).unwrap();
        let g = TestGenesis::generate(&[(addr, 50_000), (addr, 50_000)]).unwrap();
        assert_eq!(g.initial_summary().unwrap().commitments, 2);
        assert_eq!(TestGenesis::decode(g.bytes()).unwrap().digest(), g.digest());
        for n in 0..g.bytes().len() { assert!(TestGenesis::decode(&g.bytes()[..n]).is_err()); }
        let mut trailing = g.bytes().to_vec(); trailing.push(0);
        assert!(TestGenesis::decode(&trailing).is_err());
        for offset in [0, 8, 40, 48] {
            let mut bad = g.bytes().to_vec(); bad[offset] ^= 128;
            assert!(TestGenesis::decode(&bad).is_err());
        }
        let mut bad = g.bytes().to_vec();
        bad[HEADER + 43..HEADER + 51].copy_from_slice(&50_001u64.to_be_bytes());
        assert!(TestGenesis::decode(&bad).is_err());
        bad[HEADER + 43..HEADER + 51].copy_from_slice(&49_999u64.to_be_bytes());
        assert!(TestGenesis::decode(&bad).is_err());
        bad[HEADER + 43..HEADER + 51].copy_from_slice(&0u64.to_be_bytes());
        assert!(TestGenesis::decode(&bad).is_err());
        let mut duplicate = g.bytes().to_vec();
        let entry = duplicate[HEADER..HEADER + ENTRY].to_vec();
        duplicate[HEADER + ENTRY..].copy_from_slice(&entry);
        assert!(TestGenesis::decode(&duplicate).is_err());
        for values in [vec![], vec![(addr, 0)], vec![(addr, 99_999)], vec![(addr, 100_001)], vec![(addr, u64::MAX)]] {
            assert!(TestGenesis::generate(&values).is_err());
        }
    }
    #[test]
    fn different_manifests_bind_different_initial_states() {
        let addr = Wallet::create().unwrap().receive_address(0).unwrap();
        let a = TestGenesis::generate(&[(addr, TEST_SUPPLY)]).unwrap();
        let b = TestGenesis::generate(&[(addr, TEST_SUPPLY)]).unwrap();
        assert_ne!(a.digest(), b.digest());
        assert_ne!(a.initial_summary().unwrap().app_hash, b.initial_summary().unwrap().app_hash);
    }
}
