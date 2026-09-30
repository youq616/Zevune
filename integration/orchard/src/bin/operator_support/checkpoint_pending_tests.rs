use super::*;
use crate::parse;
use std::fs;
use zevune_orchard_lab::pool::testnet::TEST_SUPPLY;
use zevune_orchard_lab::pool::PoolError;
use zevune_orchard_lab::wallet::address::Recipient;
use zevune_orchard_lab::wallet::vault::store::StoreError;
use zevune_orchard_lab::wallet::WalletError;

#[test]
fn recovery_frame_requires_receipt_exact_seven_fields_and_no_suffix() {
    let password = b"synthetic-recovery-parser-password";
    let mut raw = b"ZVWCLI01".to_vec();
    raw.push(13);
    raw.extend_from_slice(&(password.len() as u16).to_be_bytes());
    raw.extend_from_slice(password);
    let offset = raw.len();
    raw.push(1);
    raw.extend_from_slice(&[1; 32]);
    raw.extend_from_slice(&1u64.to_be_bytes());
    raw.extend_from_slice(&[2; 32]);
    raw.push(7);
    for field in [
        "wallet", "journal", "genesis", "digest", "output", "0", "hash",
    ] {
        raw.extend_from_slice(&(field.len() as u16).to_be_bytes());
        raw.extend_from_slice(field.as_bytes());
    }
    assert_eq!(parse(&raw).unwrap().op, 13);
    for end in 0..raw.len() {
        assert!(parse(&raw[..end]).is_err());
    }
    let mut no_pin = raw.clone();
    no_pin[offset] = 0;
    no_pin.drain(offset + 1..offset + 73);
    assert!(parse(&no_pin).is_err());
    let mut count = raw.clone();
    count[offset + 73] = 6;
    assert!(parse(&count).is_err());
    raw.push(0);
    assert!(parse(&raw).is_err());
}

#[test]
fn original_export_race_holds_both_stores_and_never_changes_wallet() {
    let home = std::env::temp_dir().join(format!(
        "zevune-pending-export-race-{:032x}",
        rand::random::<u128>()
    ));
    fs::create_dir(&home).unwrap();
    struct Cleanup(std::path::PathBuf);
    impl Drop for Cleanup {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    let _cleanup = Cleanup(home.clone());
    let password = zeroize::Zeroizing::new(rand::random::<[u8; 32]>());
    let source = home.join("wallet");
    let journal = home.join("pool");
    let manifest = home.join("genesis");
    let target = home.join("recovered");
    let mut wallet = WalletStore::create(&source, password.as_ref()).unwrap();
    let owner = wallet.view().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    genesis.write_new(&manifest).unwrap();
    let mut pool = genesis.create_pool(&journal).unwrap();
    let summary = pool.summary().unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    let payment = wallet
        .prepare_payment_from_history(
            &history,
            &Recipient::new(owner, genesis.signing_domain()).unwrap(),
            1_000,
            1,
            10,
        )
        .unwrap();
    let pin = wallet.receipt().unwrap();
    drop(wallet);
    drop(pool);
    let original_wallet = fs::read(&source).unwrap();
    let original_pool = fs::read(&journal).unwrap();
    let fields = [
        source.to_str().unwrap().to_owned(),
        journal.to_str().unwrap().to_owned(),
        manifest.to_str().unwrap().to_owned(),
        hex(&genesis.digest()),
        target.to_str().unwrap().to_owned(),
        "0".to_owned(),
        hex(&summary.app_hash),
    ];
    let request = Request {
        op: 13,
        password: password.as_ref(),
        pin: Some(pin),
        fields: fields.iter().map(String::as_str).collect(),
    };
    let failed = execute_with_export(request, |path, recovered| {
        assert!(recovered.bytes() == payment.bytes());
        assert_eq!(recovered.id(), payment.id());
        assert!(matches!(
            genesis.open_pool(&journal),
            Err(PoolError::Locked)
        ));
        assert!(matches!(
            WalletStore::open(&source, password.as_ref(), Some(pin)),
            Err(StoreError::Locked)
        ));
        // Real create-only race AFTER initial validation. No accepting fake
        // exporter: the original exporter must fail against this new file.
        fs::write(path, b"preserve-existing-output")?;
        export(path, recovered)
    });
    assert!(failed.is_err());
    assert!(fs::read(&target).unwrap() == b"preserve-existing-output");
    assert!(fs::read(&source).unwrap() == original_wallet);
    assert!(fs::read(&journal).unwrap() == original_pool);
    wallet = WalletStore::open(&source, password.as_ref(), Some(pin)).unwrap();
    assert_eq!(wallet.receipt().unwrap(), pin);
    assert_eq!(wallet.view().unwrap().pending_id(), Some(payment.id()));
    assert_eq!(
        wallet.view().unwrap().balance(),
        Err(WalletError::NotSynced)
    );
    drop(wallet);
    assert!(fs::read(&source).unwrap() == original_wallet);
}
