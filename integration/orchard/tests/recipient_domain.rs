//! Public address checks and real NO-FUNDS payments; no secrets logged.
use zevune_orchard_lab::wallet::address::{AddressError, Recipient};
use zevune_orchard_lab::wallet::{Wallet, WalletError};

#[test]
fn network_recipient_requires_a_verified_history_not_only_keys() {
    let wallet = Wallet::create().unwrap();
    assert!(matches!(
        wallet.signing_domain(),
        Err(WalletError::NotSynced)
    ));
    assert!(matches!(
        wallet.receive_recipient(0),
        Err(WalletError::NotSynced)
    ));
    assert!(wallet.receive_address(0).is_ok()); // explicitly raw/legacy primitive
}

#[test]
fn canonical_receiver_formats_preserve_legacy_without_domain_fallback() {
    let receiver = Wallet::create().unwrap().receive_address(12).unwrap();
    let bound = Recipient::new(receiver, Some([1; 32])).unwrap();
    let legacy = Recipient::new(receiver, None).unwrap();
    assert_eq!(bound.encode().len(), 175);
    assert_eq!(legacy.encode().len(), 101);
    for (recipient, expected) in [(bound, Some([1; 32])), (legacy, None)] {
        let decoded = Recipient::decode(&recipient.encode()).unwrap();
        assert!(decoded.for_domain(expected).unwrap() == receiver);
        assert!(matches!(
            decoded.for_domain(Some([2; 32])),
            Err(AddressError::Network)
        ));
    }
    assert!(bound.for_domain(None).is_err());
    assert!(legacy.for_domain(Some([1; 32])).is_err());
    assert!(Recipient::new(receiver, Some([0; 32])).is_err());
}

#[test]
fn recipient_parser_rejects_truncation_mutation_and_noncanonical_input() {
    let receiver = Wallet::create().unwrap().receive_address(0).unwrap();
    for domain in [None, Some([3; 32])] {
        let original = Recipient::new(receiver, domain).unwrap().encode();
        for end in 0..original.len() {
            assert!(Recipient::decode(&original[..end]).is_err());
        }
        for offset in 0..original.len() {
            let mut altered = original.as_bytes().to_vec();
            altered[offset] = if altered[offset] == b'0' { b'1' } else { b'0' };
            assert!(Recipient::decode(std::str::from_utf8(&altered).unwrap()).is_err());
        }
        for text in [
            original.to_uppercase(),
            format!("{original}:extra"),
            format!(" {original}"),
            format!("{original}\n"),
            "é".repeat(101),
        ] {
            assert!(Recipient::decode(&text).is_err());
        }
    }
    assert!(Recipient::decode(&"a".repeat(4097)).is_err());
}

#[cfg(feature = "local-funding-lab")]
#[test]
fn checked_recipient_real_payment_survives_backup_and_does_not_cross_networks() {
    use rand::{rngs::OsRng, RngCore};
    use std::{fs, path::PathBuf};
    use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
    use zevune_orchard_lab::wallet::vault::store::WalletStore;
    use zevune_orchard_lab::wallet::WalletProver;
    use zevune_orchard_lab::wire::{decode, AuthorizationVerifier};

    struct Dir(PathBuf);
    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    let dir =
        Dir(std::env::temp_dir().join(format!("zevune-recipient-{:032x}", rand::random::<u128>())));
    fs::create_dir(&dir.0).unwrap();
    let mut password = [0; 32];
    OsRng.fill_bytes(&mut password);
    let started = std::time::Instant::now();
    let wallet_path = dir.0.join("sender.wallet");
    let backup_path = dir.0.join("backup.wallet");
    let mut sender = WalletStore::create(&wallet_path, &password).unwrap();
    let owner = sender.view().unwrap().receive_address(0).unwrap();
    let mut receiver = Wallet::create().unwrap();
    let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    let mut pool = genesis.create_pool(&dir.0.join("pool.journal")).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    sender.sync(&history).unwrap();
    receiver.sync(&history).unwrap();
    let recipient = receiver.receive_recipient(0).unwrap();
    let mut other = genesis.digest();
    other[0] ^= 1;
    if other == [0; 32] {
        other[1] = 1;
    }
    let wrong = Recipient::new(receiver.receive_address(0).unwrap(), Some(other)).unwrap();
    let legacy = Recipient::new(receiver.receive_address(0).unwrap(), None).unwrap();
    eprintln!("recipient-phase: initialized {:?}", started.elapsed());
    let prover = WalletProver::new();
    eprintln!(
        "recipient-phase: public prover ready {:?}",
        started.elapsed()
    );
    // Windows enforces the live file lock even for another handle in this
    // process. Read exact encrypted bytes through the owning store's create-only
    // backup, rather than weakening the lock or skipping the unchanged-file check.
    let before_path = dir.0.join("before-rejection.wallet");
    sender.backup_new(&before_path).unwrap();
    let original = fs::read(&before_path).unwrap();
    let receipt = sender.receipt().unwrap();
    for (index, address) in [wrong, legacy].into_iter().enumerate() {
        assert!(sender
            .prepare_payment_to(&address, 25_000, 1_000, 10, &prover)
            .is_err());
        assert_eq!(sender.receipt().unwrap(), receipt);
        assert!(sender.pending_payment().unwrap().is_none());
        let after_path = dir.0.join(format!("after-rejection-{index}.wallet"));
        sender.backup_new(&after_path).unwrap();
        assert_eq!(fs::read(&after_path).unwrap(), original);
    }
    eprintln!("recipient-phase: rejection guards {:?}", started.elapsed());
    let payment = sender
        .prepare_payment_to(&recipient, 25_000, 1_000, 10, &prover)
        .unwrap();
    assert_eq!(
        decode(payment.bytes()).unwrap().context.signing_domain,
        genesis.signing_domain()
    );
    AuthorizationVerifier::new()
        .verify(payment.bytes())
        .unwrap();
    eprintln!(
        "recipient-phase: payment saved and verified {:?}",
        started.elapsed()
    );
    sender.backup_new(&backup_path).unwrap();
    let receipt = sender.receipt().unwrap();
    drop(sender);
    let mut restored = WalletStore::open(&backup_path, &password, Some(receipt)).unwrap();
    assert!(matches!(
        restored.view().unwrap().signing_domain(),
        Err(WalletError::NotSynced)
    ));
    restored.sync(&history).unwrap();
    assert_eq!(
        restored.pending_payment().unwrap().unwrap().bytes(),
        payment.bytes()
    );
    assert_eq!(
        restored.view().unwrap().signing_domain().unwrap(),
        genesis.signing_domain()
    );
    let pending = pool
        .prepare(1, [4; 32], &[payment.bytes().to_vec()])
        .unwrap();
    pool.commit(pending).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    receiver.sync(&history).unwrap();
    restored.sync(&history).unwrap();
    eprintln!(
        "recipient-phase: committed and rescanned {:?}",
        started.elapsed()
    );
    assert_eq!(receiver.balance().unwrap(), 25_000);
    assert_eq!(restored.view().unwrap().balance().unwrap(), 74_000);
    assert_eq!(pool.summary().unwrap().fees, 1_000);
    assert!(restored.pending_payment().unwrap().is_none());
    assert!(pool
        .prepare(2, [5; 32], &[payment.bytes().to_vec()])
        .is_err());
}
