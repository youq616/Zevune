use rand::{rngs::OsRng, RngCore};
use std::path::PathBuf;
use zevune_payment_lab::{
    chain::{Block, Ledger, Verifier},
    store::Store,
    wallet::{create_genesis, decode_address, encode_address, Wallet},
    wire::{Transaction, MAX_TX},
    Error, SUPPLY,
};
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        let mut id = [0; 16];
        OsRng.fill_bytes(&mut id);
        let path = std::env::temp_dir().join(format!("zevune-payment-test-{}", hex::encode(id)));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
#[test]
fn encrypted_seed_backup_and_corruption() {
    let dir = Temp::new();
    let path = dir.0.join("a.wallet");
    let backup = dir.0.join("backup.wallet");
    let pw = b"test-only-long-password";
    let wallet = Wallet::create(&path, pw).unwrap();
    let addr = encode_address(wallet.address()).unwrap();
    assert_eq!(decode_address(&addr).unwrap(), wallet.address());
    assert!(decode_address(&addr.to_uppercase()).is_err());
    assert!(Wallet::open(&path, b"wrong-password").is_err());
    assert!(Wallet::create(&path, pw).is_err());
    Wallet::backup(&path, &backup, pw).unwrap();
    assert_eq!(
        Wallet::open(&backup, pw).unwrap().address(),
        wallet.address()
    );
    let mut bytes = std::fs::read(&backup).unwrap();
    bytes[60] ^= 1;
    std::fs::write(&backup, bytes).unwrap();
    assert!(Wallet::open(&backup, pw).is_err());
}
#[test]
fn real_two_hop_atomic_journal_and_decoder_rejections() {
    let a = Wallet::generate();
    let b = Wallet::generate();
    let c = Wallet::generate();
    let unknown = Wallet::generate();
    let genesis = create_genesis(a.address()).unwrap();
    let verifier = Verifier::new();
    let state = Ledger::genesis(&genesis, &verifier).unwrap();
    assert_eq!(a.balance(&state).unwrap(), SUPPLY);
    assert_eq!(b.balance(&state).unwrap(), 0);
    let first = a.prepare(&state, b.address(), 600_000).unwrap();
    let decoded = Transaction::decode(&first).unwrap();
    assert_eq!(decoded.encode().unwrap(), first);
    for length in [0, 1, 4, 37, 95, 200, first.len() - 1] {
        assert!(Transaction::decode(&first[..length]).is_err());
    }
    let mut trailing = first.clone();
    trailing.push(0);
    assert!(Transaction::decode(&trailing).is_err());
    assert!(Transaction::decode(&vec![0; MAX_TX + 1]).is_err());
    let before = state.summary();
    let block = Block {
        height: 1,
        hash: hex::encode([1; 32]),
        txs: vec![hex::encode(&first)],
    };
    let candidate = state.preview(&block, &verifier).unwrap();
    assert_eq!(state.summary(), before);
    let mut bad = first.clone();
    let last = bad.len() - 1;
    bad[last] ^= 1;
    let mut failed = block.clone();
    failed.txs.push(hex::encode(&bad));
    assert!(state.preview(&failed, &verifier).is_err());
    assert_eq!(state.summary(), before);
    assert_eq!(a.balance(&candidate).unwrap(), 399_000);
    assert_eq!(b.balance(&candidate).unwrap(), 600_000);
    assert_eq!(unknown.balance(&candidate).unwrap(), 0);
    assert!(candidate.check(&first, 2, &verifier).is_err());
    let mut other = decoded.clone();
    other.genesis = [5; 32];
    assert!(state.check(&other.encode().unwrap(), 1, &verifier).is_err());
    let second = b.prepare(&candidate, c.address(), 250_000).unwrap();
    let next = Block {
        height: 2,
        hash: hex::encode([2; 32]),
        txs: vec![hex::encode(&second)],
    };
    let final_state = candidate.preview(&next, &verifier).unwrap();
    assert_eq!(b.balance(&final_state).unwrap(), 349_000);
    assert_eq!(c.balance(&final_state).unwrap(), 250_000);
    assert_eq!(final_state.summary().burned_fees, 2000);
    assert_eq!(
        Ledger::from_export(&final_state.export(), &genesis, &verifier)
            .unwrap()
            .summary(),
        final_state.summary()
    );
    assert!(matches!(
        a.prepare(&final_state, c.address(), SUPPLY),
        Err(Error::Funds)
    ));
    let dir = Temp::new();
    let db = dir.0.join("db");
    let mut store = Store::open(&db, &genesis).unwrap();
    assert!(Store::open(&db, &genesis).is_err());
    store.stage(block.clone()).unwrap();
    assert_eq!(store.ledger.height, 0);
    drop(store);
    let mut store = Store::open(&db, &genesis).unwrap();
    assert_eq!(store.ledger.height, 0);
    store.stage(block.clone()).unwrap();
    assert!(store.commit(1, &hex::encode([9; 32])).is_err());
    assert_eq!(store.ledger.height, 0);
    store.commit(1, &block.hash).unwrap();
    store.commit(1, &block.hash).unwrap();
    store.stage(next.clone()).unwrap();
    store.commit(2, &next.hash).unwrap();
    drop(store);
    let store = Store::open(&db, &genesis).unwrap();
    assert_eq!(store.ledger.summary(), final_state.summary());
    drop(store);
    let path = db.join("payment.journal");
    let mut bytes = std::fs::read(&path).unwrap();
    bytes.pop();
    std::fs::write(path, bytes).unwrap();
    assert!(Store::open(&db, &genesis).is_err());
    println!("M5 real proofs, two-hop receipt/spend, bounded codec, atomic state, encrypted recovery and journal replay passed");
}
