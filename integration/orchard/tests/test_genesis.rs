#![cfg(feature = "local-funding-lab")]

use rand::{rngs::OsRng, RngCore};
use std::fs;
use std::path::PathBuf;
use zevune_orchard_lab::pool::testnet::{TestGenesis, MAX_GENESIS_BYTES, TEST_SUPPLY};
use zevune_orchard_lab::pool::PoolStore;
use zevune_orchard_lab::wallet::Wallet;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let name: String = random.iter().map(|b| format!("{b:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-genesis-{name}"));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn pinned_manifest_storage_and_foreign_genesis_rejection() {
    let dir = Dir::new();
    let addr = Wallet::create().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(addr, TEST_SUPPLY)]).unwrap();
    let other = TestGenesis::generate(&[(addr, TEST_SUPPLY)]).unwrap();
    let manifest = dir.0.join("public-genesis.bin");
    genesis.write_new(&manifest).unwrap();
    assert!(genesis.write_new(&manifest).is_err());
    let loaded = TestGenesis::read_pinned(&manifest, genesis.digest()).unwrap();
    assert_eq!(loaded.bytes(), genesis.bytes());
    assert!(TestGenesis::read_pinned(&manifest, other.digest()).is_err());
    let path = dir.0.join("state.journal");
    let pool = loaded.create_pool(&path).unwrap();
    let initial = pool.summary().unwrap();
    assert!(loaded.create_pool(&path).is_err());
    drop(pool);
    assert!(other.open_pool(&path).is_err());
    assert!(PoolStore::open(&path).is_err());
    assert_eq!(loaded.open_pool(&path).unwrap().summary().unwrap(), initial);
    fs::write(&manifest, vec![0; MAX_GENESIS_BYTES + 1]).unwrap();
    assert!(TestGenesis::read_pinned(&manifest, genesis.digest()).is_err());
}

#[test]
fn wallet_identifies_only_its_public_genesis_allocations() {
    let dir = Dir::new();
    let mut owner = Wallet::create().unwrap();
    let mut stranger = Wallet::create().unwrap();
    let first = owner.receive_address(0).unwrap();
    let second = owner.receive_address(17).unwrap();
    let encoded = TestGenesis::generate(&[(first, 30_000), (second, 70_000)]).unwrap();
    let genesis = TestGenesis::decode(encoded.bytes()).unwrap();
    let mut pool = genesis.create_pool(&dir.0.join("state.journal")).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    owner.sync(&history).unwrap();
    stranger.sync(&history).unwrap();
    assert_eq!(owner.balance().unwrap(), TEST_SUPPLY);
    assert_eq!(owner.available_balance().unwrap(), TEST_SUPPLY);
    assert_eq!(stranger.balance().unwrap(), 0);
    assert_eq!(owner.height(), Some(0));
    let other = TestGenesis::generate(&[(first, TEST_SUPPLY)]).unwrap();
    assert!(other.wallet_history(&mut pool).is_err());
}

#[test]
fn genesis_cannot_be_submitted_as_a_later_mint_transaction() {
    let dir = Dir::new();
    let addr = Wallet::create().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(addr, TEST_SUPPLY)]).unwrap();
    let mut pool = genesis.create_pool(&dir.0.join("state.journal")).unwrap();
    let initial = pool.summary().unwrap();
    assert!(pool.prepare(1, [1; 32], &[genesis.bytes().to_vec()]).is_err());
    assert_eq!(pool.summary().unwrap(), initial);
    let next = pool.prepare(1, [2; 32], &[]).unwrap();
    pool.commit(next).unwrap();
    assert!(pool.prepare(2, [3; 32], &[genesis.bytes().to_vec()]).is_err());
    assert_eq!(pool.summary().unwrap().height, 1);
}
