use super::*;
use crate::pool::testnet::{TestGenesis, TEST_SUPPLY};
use crate::pool::{PoolError, PoolStore};
use crate::wallet::address::Recipient;
use std::fs;
use std::path::{Path, PathBuf};
use zeroize::Zeroizing;

struct Home(PathBuf);
impl Home {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "zevune-checked-pending-{:032x}",
            rand::random::<u128>()
        ));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
}
impl Drop for Home {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn files(path: &Path) -> Vec<(PathBuf, Vec<u8>)> {
    if path.is_file() {
        return vec![(path.to_owned(), fs::read(path).unwrap())];
    }
    let mut children = fs::read_dir(path)
        .unwrap()
        .map(|e| e.unwrap().path())
        .collect::<Vec<_>>();
    children.sort();
    children.iter().flat_map(|p| files(p)).collect()
}
fn setup(
    home: &Home,
    password: &[u8],
    active: bool,
) -> (WalletStore, TestGenesis, PoolStore, Payment) {
    let mut wallet = WalletStore::create(&home.0.join("wallet"), password).unwrap();
    let owner = wallet.view().unwrap().receive_address(0).unwrap();
    let genesis = if active {
        TestGenesis::generate_active(&[(owner, TEST_SUPPLY)]).unwrap()
    } else {
        TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap()
    };
    let mut pool = genesis.create_pool(&home.0.join("pool")).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    assert!(matches!(
        wallet.pending_payment_from_history(&history),
        Err(StoreError::MissingOutbox)
    ));
    let recipient = Recipient::new(owner, genesis.signing_domain()).unwrap();
    // Only fixture setup signs a valueless payment, using the existing real
    // proof path. The recovery method itself never creates proving parameters.
    let payment = wallet
        .prepare_payment_from_history(&history, &recipient, 1_000, 1, 10)
        .unwrap();
    (wallet, genesis, pool, payment)
}
fn unchanged(wallet: &WalletStore, pin: super::super::StoreReceipt, txid: Hash) {
    assert_eq!(wallet.receipt().unwrap(), pin);
    assert_eq!(wallet.view().unwrap().pending_id(), Some(txid));
    assert_eq!(
        wallet.view().unwrap().balance(),
        Err(WalletError::NotSynced)
    );
    assert_eq!(
        wallet.view().unwrap().available_balance(),
        Err(WalletError::NotSynced)
    );
    assert!(matches!(
        wallet.pending_payment(),
        Err(StoreError::Wallet(WalletError::NotSynced))
    ));
}

#[test]
fn both_profiles_recover_exact_bytes_without_publishing_new_history() {
    for active in [false, true] {
        let home = Home::new();
        let password = Zeroizing::new(rand::random::<[u8; 32]>());
        let (wallet, genesis, mut pool, payment) = setup(&home, password.as_ref(), active);
        let pin = wallet.receipt().unwrap();
        let empty = pool.prepare(1, [0x41; 32], &[]).unwrap();
        pool.commit(empty).unwrap();
        drop(wallet);
        drop(pool);
        let source = home.0.join("wallet");
        let journal = home.0.join("pool");
        let before = files(&source);
        let reference = files(&journal);
        pool = genesis.open_pool(&journal).unwrap();
        let history = genesis.wallet_history(&mut pool).unwrap();
        let mut wallet = WalletStore::open(&source, password.as_ref(), Some(pin)).unwrap();
        for _ in 0..2 {
            let recovered = wallet.pending_payment_from_history(&history).unwrap();
            assert!(recovered.bytes() == payment.bytes());
            assert_eq!(recovered.id(), payment.id());
            unchanged(&wallet, pin, payment.id());
            assert_eq!(wallet.view().unwrap().height(), Some(0));
            assert!(matches!(
                genesis.open_pool(&journal),
                Err(PoolError::Locked)
            ));
            assert!(matches!(
                WalletStore::open(&source, password.as_ref(), Some(pin)),
                Err(StoreError::Locked)
            ));
        }
        drop(wallet);
        drop(pool);
        assert!(files(&source) == before);
        assert!(files(&journal) == reference);
        let reopened = WalletStore::open(&source, password.as_ref(), Some(pin)).unwrap();
        unchanged(&reopened, pin, payment.id());
        drop(reopened);
        assert!(files(&source) == before);
    }
}

#[test]
fn consumed_and_expired_history_refuse_without_clearing_durable_pending() {
    for active in [false, true] {
        let home = Home::new();
        let password = Zeroizing::new(rand::random::<[u8; 32]>());
        let (wallet, genesis, mut pool, payment) = setup(&home, password.as_ref(), active);
        let pin = wallet.receipt().unwrap();
        let consumed = pool
            .prepare(1, [0x42; 32], &[payment.bytes().to_vec()])
            .unwrap();
        pool.commit(consumed).unwrap();
        let consumed_history = genesis.wallet_history(&mut pool).unwrap();
        let expired_path = home.0.join("expired-pool");
        let mut expired = genesis.create_pool(&expired_path).unwrap();
        for height in 1..=11 {
            let block = expired.prepare(height, [0x43; 32], &[]).unwrap();
            expired.commit(block).unwrap();
        }
        let expired_history = genesis.wallet_history(&mut expired).unwrap();
        drop(wallet);
        drop(pool);
        drop(expired);
        let source = home.0.join("wallet");
        let before = files(&source);
        let reference = files(&home.0.join("pool"));
        let expiry_reference = files(&expired_path);
        let mut wallet = WalletStore::open(&source, password.as_ref(), Some(pin)).unwrap();
        for history in [&consumed_history, &expired_history] {
            assert!(matches!(
                wallet.pending_payment_from_history(history),
                Err(StoreError::Wallet(WalletError::History))
            ));
            unchanged(&wallet, pin, payment.id());
            assert_eq!(wallet.view().unwrap().height(), Some(0));
        }
        drop(wallet);
        assert!(files(&source) == before);
        assert!(files(&home.0.join("pool")) == reference);
        assert!(files(&expired_path) == expiry_reference);
    }
}

#[test]
fn rollback_wrong_domain_missing_outbox_and_unhealthy_are_not_recovery_authority() {
    let home = Home::new();
    let password = Zeroizing::new(rand::random::<[u8; 32]>());
    let (mut wallet, genesis, mut pool, payment) = setup(&home, password.as_ref(), false);
    let old = genesis.wallet_history(&mut pool).unwrap();
    let block = pool.prepare(1, [0x44; 32], &[]).unwrap();
    pool.commit(block).unwrap();
    let current = genesis.wallet_history(&mut pool).unwrap();
    wallet.sync(&current).unwrap(); // explicit fixture advance, before evidence
    let pin = wallet.receipt().unwrap();
    let owner = wallet.view().unwrap().receive_address(0).unwrap();
    let wrong = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    assert_ne!(wrong.signing_domain(), genesis.signing_domain());
    let mut other = wrong.create_pool(&home.0.join("wrong-pool")).unwrap();
    let wrong_history = wrong.wallet_history(&mut other).unwrap();
    drop(other);
    drop(pool);
    drop(wallet);
    let source = home.0.join("wallet");
    let before = files(&source);
    wallet = WalletStore::open(&source, password.as_ref(), Some(pin)).unwrap();
    for history in [&old, &wrong_history] {
        assert!(wallet.pending_payment_from_history(history).is_err());
        unchanged(&wallet, pin, payment.id());
        assert_eq!(wallet.view().unwrap().height(), Some(1));
    }
    // Test-only representation of an M8 import with reservations but no outbox;
    // never persisted and no accepting backend or production failure switch.
    let original = wallet.outbox.take();
    assert!(matches!(
        wallet.pending_payment_from_history(&current),
        Err(StoreError::MissingOutbox)
    ));
    assert_eq!(wallet.receipt().unwrap(), pin);
    wallet.outbox = original;
    unchanged(&wallet, pin, payment.id());
    wallet.healthy = false;
    assert!(matches!(
        wallet.pending_payment_from_history(&current),
        Err(StoreError::Unavailable)
    ));
    drop(wallet);
    assert!(files(&source) == before);
}

#[test]
fn full_real_journal_can_recover_without_room_or_a_new_record() {
    let home = Home::new();
    let password = Zeroizing::new(rand::random::<[u8; 32]>());
    let (mut wallet, genesis, mut pool, payment) = setup(&home, password.as_ref(), false);
    while wallet.receipt().unwrap().generation < super::super::MAX_RECORDS {
        wallet.persist().unwrap(); // real records in synthetic private fixture
    }
    let history = genesis.wallet_history(&mut pool).unwrap();
    let pin = wallet.receipt().unwrap();
    assert!(matches!(wallet.room(), Err(StoreError::Capacity)));
    drop(wallet);
    drop(pool);
    let source = home.0.join("wallet");
    let before = files(&source);
    wallet = WalletStore::open(&source, password.as_ref(), Some(pin)).unwrap();
    let recovered = wallet.pending_payment_from_history(&history).unwrap();
    assert!(recovered.bytes() == payment.bytes());
    assert_eq!(recovered.id(), payment.id());
    unchanged(&wallet, pin, payment.id());
    assert_eq!(wallet.storage_status().unwrap().records_remaining, 0);
    drop(wallet);
    assert!(files(&source) == before);
}

#[test]
fn expiry_minus_one_recovers_but_equality_and_after_refuse_on_both_profiles() {
    for active in [false, true] {
        let home = Home::new();
        let password = Zeroizing::new(rand::random::<[u8; 32]>());
        let (wallet, genesis, mut pool, payment) = setup(&home, password.as_ref(), active);
        let pin = wallet.receipt().unwrap();
        let source = home.0.join("wallet");
        let journal = home.0.join("pool");
        drop(wallet);
        drop(pool);
        let before = files(&source);
        for height in 1..=11 {
            pool = genesis.open_pool(&journal).unwrap();
            let block = pool.prepare(height, [0x47; 32], &[]).unwrap();
            pool.commit(block).unwrap();
            drop(pool);
            if height < 9 {
                continue;
            }
            let reference = files(&journal);
            pool = genesis.open_pool(&journal).unwrap();
            let history = genesis.wallet_history(&mut pool).unwrap();
            let mut wallet = WalletStore::open(&source, password.as_ref(), Some(pin)).unwrap();
            let original = snapshot(&wallet.wallet).unwrap();
            let mut temporary = restore(original.as_ref()).unwrap();
            temporary.sync(&history).unwrap();
            assert_eq!(temporary.height(), Some(height));
            // Demonstrate equality is NOT a pending-clear by the old sync rule.
            assert_eq!(temporary.pending_id(), (height <= 10).then_some(payment.id()));
            if height == 9 {
                let recovered = wallet.pending_payment_from_history(&history).unwrap();
                assert_eq!(recovered.id(), payment.id());
                assert!(recovered.bytes() == payment.bytes());
            } else {
                assert!(matches!(
                    wallet.pending_payment_from_history(&history),
                    Err(StoreError::Wallet(WalletError::History))
                ));
            }
            unchanged(&wallet, pin, payment.id());
            assert_eq!(wallet.view().unwrap().height(), Some(0));
            assert!(wallet.outbox.as_deref().unwrap() == payment.bytes());
            drop(wallet);
            drop(pool);
            assert!(files(&source) == before);
            assert!(files(&journal) == reference);
        }
    }
}
