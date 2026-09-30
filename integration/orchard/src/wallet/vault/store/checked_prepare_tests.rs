use super::*;
use crate::pool::testnet::{TestGenesis, TEST_SUPPLY};
use crate::pool::{PoolError, PoolStore};
use crate::wallet::Wallet;
use std::fs;
use std::path::PathBuf;

struct Home(PathBuf);
impl Home {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "zevune-checked-prepare-{:032x}",
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

fn setup(
    home: &Home,
    password: &[u8],
    active: bool,
) -> (WalletStore, TestGenesis, PoolStore, Recipient) {
    let wallet = WalletStore::create(&home.0.join("wallet"), password).unwrap();
    let owner = wallet.view().unwrap().receive_address(0).unwrap();
    let genesis = if active {
        TestGenesis::generate_active(&[(owner, TEST_SUPPLY)]).unwrap()
    } else {
        TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap()
    };
    let pool = genesis.create_pool(&home.0.join("pool")).unwrap();
    let recipient = Recipient::new(owner, genesis.signing_domain()).unwrap();
    (wallet, genesis, pool, recipient)
}

#[test]
fn fee_guard_is_deterministic_at_each_boundary() {
    for amount in [1, 99, 100, 199, 200, 9_999, 10_000, 10_100, u64::MAX] {
        let cap = (amount / 100).clamp(1, 100);
        assert!(WalletStore::check_preparation_fee(amount, 1).is_ok());
        assert!(WalletStore::check_preparation_fee(amount, cap).is_ok());
        assert_eq!(
            WalletStore::check_preparation_fee(amount, cap + 1),
            Err(StoreError::Wallet(WalletError::Bounds))
        );
        assert!(WalletStore::check_preparation_fee(amount, 0).is_err());
    }
    assert!(WalletStore::check_preparation_fee(0, 1).is_err());
    assert!(WalletStore::check_preparation_fee(1, 99_999).is_err());
}

#[test]
fn rejected_intents_do_not_initialize_prover_or_publish_rescan() {
    for active in [false, true] {
        let home = Home::new();
        let password = zeroize::Zeroizing::new(rand::random::<[u8; 32]>());
        let (wallet, genesis, mut pool, recipient) = setup(&home, password.as_ref(), active);
        let pin = wallet.receipt().unwrap();
        drop(wallet);
        let before = fs::read(home.0.join("wallet")).unwrap();
        let history = genesis.wallet_history(&mut pool).unwrap();
        let mut wallet =
            WalletStore::open(&home.0.join("wallet"), password.as_ref(), Some(pin)).unwrap();
        let initial = snapshot(wallet.view().unwrap()).unwrap();
        for (amount, fee, expiry, expected) in [
            (0, 1, 10, WalletError::Bounds),
            (1, 0, 10, WalletError::Bounds),
            (1, 99_999, 10, WalletError::Bounds),
            (100, 2, 10, WalletError::Bounds),
            (200, 3, 10, WalletError::Bounds),
            (10_100, 101, 10, WalletError::Bounds),
            (1, 1, 0, WalletError::Bounds),
            (1, 1, 101, WalletError::Bounds),
            (TEST_SUPPLY, 1, 10, WalletError::InsufficientFunds),
        ] {
            let result =
                wallet.prepare_from_history_with(&history, &recipient, amount, fee, expiry, || {
                    panic!("rejected intent constructed prover")
                });
            assert!(matches!(result, Err(StoreError::Wallet(e)) if e == expected));
            assert_eq!(wallet.receipt().unwrap(), pin);
            assert!(snapshot(wallet.view().unwrap()).unwrap().as_ref() == initial.as_ref());
            assert!(wallet.view().unwrap().pending_id().is_none());
            assert_eq!(wallet.view().unwrap().height(), None);
            assert_eq!(
                wallet.view().unwrap().balance(),
                Err(WalletError::NotSynced)
            );
        }
        let wrong = Recipient::new(
            Wallet::create().unwrap().receive_address(0).unwrap(),
            Some([0x7f; 32]),
        )
        .unwrap();
        let result = wallet.prepare_from_history_with(&history, &wrong, 1, 1, 10, || {
            panic!("wrong domain constructed prover")
        });
        assert!(matches!(
            result,
            Err(StoreError::Wallet(WalletError::History))
        ));
        assert_eq!(wallet.receipt().unwrap(), pin);
        assert!(snapshot(wallet.view().unwrap()).unwrap().as_ref() == initial.as_ref());
        drop(wallet);
        drop(pool);
        assert!(fs::read(home.0.join("wallet")).unwrap() == before);
    }
}

#[test]
fn both_profiles_save_one_record_and_reject_existing_pending_without_replacing_bytes() {
    for active in [false, true] {
        let home = Home::new();
        let password = zeroize::Zeroizing::new(rand::random::<[u8; 32]>());
        let (mut wallet, genesis, mut pool, recipient) = setup(&home, password.as_ref(), active);
        let initial_pin = wallet.receipt().unwrap();
        let history = genesis.wallet_history(&mut pool).unwrap();
        let payment = wallet
            .prepare_from_history_with(&history, &recipient, 1_000, 1, 10, || {
                assert!(matches!(
                    genesis.open_pool(&home.0.join("pool")),
                    Err(PoolError::Locked)
                ));
                WalletProver::new()
            })
            .unwrap();
        let bytes = payment.bytes().to_vec();
        let id = payment.id();
        let pin = wallet.receipt().unwrap();
        assert_eq!(pin.generation, initial_pin.generation + 1);
        assert_eq!(wallet.view().unwrap().height(), Some(0));
        assert_eq!(wallet.view().unwrap().pending_id(), Some(id));
        assert_eq!(wallet.view().unwrap().available_balance(), Ok(0));
        assert!(wallet.pending_payment().unwrap().unwrap().bytes() == bytes.as_slice());
        // The original PoolStore is the actual authorization verifier here.
        let prepared = pool
            .prepare(1, [0x31; 32], std::slice::from_ref(&bytes))
            .unwrap();
        pool.commit(prepared).unwrap();
        let committed_history = genesis.wallet_history(&mut pool).unwrap();
        drop(wallet);
        let saved = fs::read(home.0.join("wallet")).unwrap();
        let mut wallet =
            WalletStore::open(&home.0.join("wallet"), password.as_ref(), Some(pin)).unwrap();
        assert_eq!(wallet.view().unwrap().pending_id(), Some(id));
        assert_eq!(
            wallet.view().unwrap().balance(),
            Err(WalletError::NotSynced)
        );
        // Even CONFIRMING history may not silently clear pending in new prepare.
        let result =
            wallet.prepare_from_history_with(&committed_history, &recipient, 1, 1, 10, || {
                panic!("existing pending constructed prover")
            });
        assert!(matches!(
            result,
            Err(StoreError::Wallet(WalletError::Pending))
        ));
        assert_eq!(wallet.receipt().unwrap(), pin);
        assert_eq!(wallet.view().unwrap().pending_id(), Some(id));
        // Explicit old history rescan restores access to EXACT saved signed bytes.
        wallet.sync(&history).unwrap();
        assert!(wallet.pending_payment().unwrap().unwrap().bytes() == bytes.as_slice());
        assert_eq!(wallet.receipt().unwrap(), pin);
        drop(wallet);
        assert!(fs::read(home.0.join("wallet")).unwrap() == saved);
        let mut wallet =
            WalletStore::open(&home.0.join("wallet"), password.as_ref(), Some(pin)).unwrap();
        wallet.sync(&committed_history).unwrap();
        assert!(wallet.view().unwrap().pending_id().is_none());
        assert_eq!(wallet.view().unwrap().balance(), Ok(TEST_SUPPLY - 1));
        drop(wallet);
        drop(pool);
    }
}

#[test]
fn actual_full_wallet_refuses_before_proving_without_mutation() {
    let home = Home::new();
    let password = zeroize::Zeroizing::new(rand::random::<[u8; 32]>());
    let (mut wallet, genesis, mut pool, recipient) = setup(&home, password.as_ref(), false);
    // Real bounded records, not a fake generation counter or enlarged limit.
    while wallet.receipt().unwrap().generation < super::super::MAX_RECORDS {
        wallet.persist().unwrap();
    }
    let pin = wallet.receipt().unwrap();
    drop(wallet);
    let before = fs::read(home.0.join("wallet")).unwrap();
    let mut wallet =
        WalletStore::open(&home.0.join("wallet"), password.as_ref(), Some(pin)).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    let result = wallet.prepare_from_history_with(&history, &recipient, 1, 1, 10, || {
        panic!("capacity rejection constructed prover")
    });
    assert!(matches!(result, Err(StoreError::Capacity)));
    assert_eq!(wallet.receipt().unwrap(), pin);
    assert!(wallet.view().unwrap().pending_id().is_none());
    drop(wallet);
    drop(pool);
    assert!(fs::read(home.0.join("wallet")).unwrap() == before);
}

#[test]
fn persist_failures_never_return_payment_and_require_explicit_recovery() {
    for fault in [1, 2] {
        let home = Home::new();
        let password = zeroize::Zeroizing::new(rand::random::<[u8; 32]>());
        let (mut wallet, genesis, mut pool, recipient) = setup(&home, password.as_ref(), false);
        let pin = wallet.receipt().unwrap();
        wallet.backup_new(&home.0.join("backup")).unwrap();
        let history = genesis.wallet_history(&mut pool).unwrap();
        wallet.fault = fault;
        assert!(matches!(
            wallet.prepare_payment_from_history(&history, &recipient, 1, 1, 10),
            Err(StoreError::Io)
        ));
        assert!(matches!(wallet.view(), Err(StoreError::Unavailable)));
        assert_eq!(wallet.receipt(), Err(StoreError::Unavailable));
        drop(wallet);
        let source = WalletStore::open(&home.0.join("wallet"), password.as_ref(), Some(pin));
        if fault == 1 {
            assert!(matches!(source, Err(StoreError::Corrupt)));
        } else {
            let mut restored = source.unwrap();
            let id = restored.view().unwrap().pending_id().unwrap();
            assert_eq!(restored.receipt().unwrap().generation, pin.generation + 1);
            restored.sync(&history).unwrap();
            let saved = restored.pending_payment().unwrap().unwrap();
            assert_eq!(saved.id(), id);
            // Recovery reads and verifies the old signed bytes, never re-signs.
            let prepared = pool
                .prepare(1, [0x41; 32], &[saved.bytes().to_vec()])
                .unwrap();
            pool.commit(prepared).unwrap();
            drop(restored);
        }
        let backup =
            WalletStore::open(&home.0.join("backup"), password.as_ref(), Some(pin)).unwrap();
        assert_eq!(backup.receipt().unwrap(), pin);
        assert!(backup.view().unwrap().pending_id().is_none());
        drop(backup);
        drop(pool);
    }
}
