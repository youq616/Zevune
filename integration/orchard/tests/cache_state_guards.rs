#![cfg(feature = "local-funding-lab")]

//! A successful cached authorization must never become cached state permission.
use rand::{rngs::OsRng, RngCore};
use std::fs;
use std::path::PathBuf;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::pool::PoolError;
use zevune_orchard_lab::wallet::{Wallet, WalletProver};

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let name: String = random.iter().map(|b| format!("{b:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-cache-state-{name}"));
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
fn warm_authorization_still_checks_atomicity_spends_expiry_and_roots() {
    let dir = Dir::new();
    let mut sender = Wallet::create().unwrap();
    let receiver = Wallet::create().unwrap().receive_address(0).unwrap();
    let destination = sender.receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(destination, TEST_SUPPLY)]).unwrap();
    let path = dir.0.join("state.journal");
    let mut pool = genesis.create_pool(&path).unwrap();
    sender
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let tx = sender
        .build_payment(receiver, 10_000, 1_000, 3, &WalletProver::new())
        .unwrap();
    let raw = tx.bytes().to_vec();
    let before = pool.summary().unwrap();
    let length = fs::metadata(&path).unwrap().len();
    let prepared = pool
        .prepare(1, [1; 32], std::slice::from_ref(&raw))
        .unwrap();
    // The first preview has warmed the actual authorization cache.
    assert!(matches!(
        pool.prepare(1, [2; 32], &[raw.clone(), raw.clone()]),
        Err(PoolError::DoubleSpend)
    ));
    assert_eq!(pool.summary().unwrap(), before);
    assert_eq!(fs::metadata(&path).unwrap().len(), length);
    pool.commit(prepared).unwrap();
    assert!(matches!(
        pool.prepare(2, [2; 32], std::slice::from_ref(&raw)),
        Err(PoolError::DoubleSpend)
    ));
    drop(pool);
    let reopened = genesis.open_pool(&path).unwrap();
    assert!(matches!(
        reopened.prepare(2, [2; 32], std::slice::from_ref(&raw)),
        Err(PoolError::DoubleSpend)
    ));
    let mut expired = genesis.create_pool(&dir.0.join("expired.journal")).unwrap();
    // Warm another cache, but do not commit the payment.
    expired
        .prepare(1, [1; 32], std::slice::from_ref(&raw))
        .unwrap();
    for height in 1..=3 {
        let prepared = expired.prepare(height, [height as u8; 32], &[]).unwrap();
        expired.commit(prepared).unwrap();
    }
    assert!(matches!(
        expired.prepare(4, [4; 32], std::slice::from_ref(&raw)),
        Err(PoolError::Expired)
    ));
    let other = TestGenesis::generate(&[(destination, TEST_SUPPLY)]).unwrap();
    let foreign = other.create_pool(&dir.0.join("foreign.journal")).unwrap();
    assert!(matches!(
        foreign.prepare(1, [1; 32], std::slice::from_ref(&raw)),
        Err(PoolError::Domain)
    ));
}
