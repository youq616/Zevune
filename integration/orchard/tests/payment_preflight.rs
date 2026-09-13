//! Real public genesis and wallet state, but no proving key is needed to preflight.
#![cfg(feature = "local-funding-lab")]
use std::{fs, path::PathBuf};
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::wallet::address::Recipient;
use zevune_orchard_lab::wallet::vault::store::{StoreError, WalletStore};
use zevune_orchard_lab::wallet::{Wallet, WalletError};

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let dir = Self(std::env::temp_dir().join(format!(
            "zevune-preflight-test-{:032x}",
            rand::random::<u128>()
        )));
        fs::create_dir(&dir.0).unwrap();
        dir
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn unsynced_preflight_never_infers_identity_from_recipient() {
    let wallet = Wallet::create().unwrap();
    let recipient = Recipient::new(wallet.receive_address(0).unwrap(), Some([1; 32])).unwrap();
    assert_eq!(
        wallet.check_payment_to(&recipient, 1, 1, 10),
        Err(WalletError::NotSynced)
    );
    assert!(wallet.pending_id().is_none());
}

#[test]
fn preflight_checks_domain_bounds_and_available_inputs_without_mutation() {
    let dir = Dir::new();
    let password = rand::random::<[u8; 32]>();
    let mut wallet = WalletStore::create(&dir.0.join("wallet"), &password).unwrap();
    let owner = wallet.view().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    let mut pool = genesis.create_pool(&dir.0.join("pool")).unwrap();
    wallet
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let recipient = Recipient::new(owner, genesis.signing_domain()).unwrap();
    let mut other = genesis.digest();
    other[0] ^= 1;
    other[1] |= 1;
    let wrong = Recipient::new(owner, Some(other)).unwrap();
    let legacy = Recipient::new(owner, None).unwrap();
    let before = dir.0.join("before");
    wallet.backup_new(&before).unwrap();
    let bytes = fs::read(before).unwrap();
    let receipt = wallet.receipt().unwrap();
    let state = pool.summary().unwrap();
    let cases = [
        (wrong, 1, 1, 10, WalletError::History),
        (legacy, 1, 1, 10, WalletError::History),
        (recipient, 0, 1, 10, WalletError::Bounds),
        (recipient, 1, 0, 10, WalletError::Bounds),
        (recipient, u64::MAX, 1, 10, WalletError::Bounds),
        (recipient, i64::MAX as u64, 1, 10, WalletError::Bounds),
        (
            recipient,
            TEST_SUPPLY,
            1,
            10,
            WalletError::InsufficientFunds,
        ),
        (recipient, 1, 1, 0, WalletError::Bounds),
        (recipient, 1, 1, 101, WalletError::Bounds),
    ];
    for (recipient, amount, fee, expiry, expected) in cases {
        assert_eq!(
            wallet.check_payment_to(&recipient, amount, fee, expiry),
            Err(StoreError::Wallet(expected))
        );
        assert_eq!(wallet.receipt().unwrap(), receipt);
        assert!(wallet.pending_payment().unwrap().is_none());
        assert_eq!(
            wallet.view().unwrap().available_balance().unwrap(),
            TEST_SUPPLY
        );
    }
    for (amount, fee, expiry) in [(1, 1, 1), (TEST_SUPPLY - 1, 1, 100)] {
        wallet
            .check_payment_to(&recipient, amount, fee, expiry)
            .unwrap();
        assert_eq!(wallet.receipt().unwrap(), receipt);
        assert!(wallet.pending_payment().unwrap().is_none());
    }
    let after = dir.0.join("after");
    wallet.backup_new(&after).unwrap();
    assert_eq!(fs::read(after).unwrap(), bytes);
    assert_eq!(pool.summary().unwrap(), state);
}

#[test]
fn preflight_respects_input_limit_not_just_total_balance() {
    let dir = Dir::new();
    let mut wallet = Wallet::create().unwrap();
    let owner = wallet.receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(owner, 10_000); 10]).unwrap();
    let mut pool = genesis.create_pool(&dir.0.join("pool")).unwrap();
    wallet
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let recipient = wallet.receive_recipient(0).unwrap();
    assert_eq!(wallet.balance().unwrap(), TEST_SUPPLY);
    assert_eq!(
        wallet.check_payment_to(&recipient, 80_000, 1, 10),
        Err(WalletError::InsufficientFunds)
    );
    assert_eq!(wallet.check_payment_to(&recipient, 79_999, 1, 10), Ok(()));
    assert!(wallet.pending_id().is_none());
}

#[test]
fn restored_wallet_must_rescan_before_preflight_can_succeed() {
    let dir = Dir::new();
    let password = rand::random::<[u8; 32]>();
    let path = dir.0.join("wallet");
    let mut wallet = WalletStore::create(&path, &password).unwrap();
    let owner = wallet.view().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    let mut pool = genesis.create_pool(&dir.0.join("pool")).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    wallet.sync(&history).unwrap();
    let recipient = wallet.view().unwrap().receive_recipient(0).unwrap();
    let receipt = wallet.receipt().unwrap();
    drop(wallet);
    let mut wallet = WalletStore::open(&path, &password, Some(receipt)).unwrap();
    assert_eq!(
        wallet.check_payment_to(&recipient, 1, 1, 10),
        Err(StoreError::Wallet(WalletError::NotSynced))
    );
    assert_eq!(wallet.receipt().unwrap(), receipt);
    wallet.sync(&history).unwrap();
    assert_eq!(wallet.check_payment_to(&recipient, 1, 1, 10), Ok(()));
}
