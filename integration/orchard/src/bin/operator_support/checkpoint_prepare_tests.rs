use super::*;
use crate::parse;
use std::fs;
use zevune_orchard_lab::pool::{testnet::TEST_SUPPLY, PoolError};
use zevune_orchard_lab::wallet::vault::store::StoreError;
use zevune_orchard_lab::wallet::WalletError;

#[test]
fn operation_twelve_requires_exact_fields_receipt_and_no_trailing_frame() {
    let password = b"synthetic-checked-prepare-frame";
    let mut raw = b"ZVWCLI01".to_vec();
    raw.push(12);
    raw.extend_from_slice(&(password.len() as u16).to_be_bytes());
    raw.extend_from_slice(password);
    let offset = raw.len();
    raw.push(1);
    raw.extend_from_slice(&[1; 32]);
    raw.extend_from_slice(&1u64.to_be_bytes());
    raw.extend_from_slice(&[2; 32]);
    raw.push(11);
    for value in [
        "/wallet",
        "/pool",
        "/genesis",
        "pin",
        "recipient",
        "1",
        "1",
        "10",
        "/output",
        "0",
        "hash",
    ] {
        raw.extend_from_slice(&(value.len() as u16).to_be_bytes());
        raw.extend_from_slice(value.as_bytes());
    }
    assert_eq!(parse(&raw).unwrap().op, 12);
    for end in 0..raw.len() {
        assert!(parse(&raw[..end]).is_err());
    }
    let mut bad = raw.clone();
    bad[offset] = 0;
    bad.drain(offset + 1..offset + 73);
    assert!(parse(&bad).is_err());
    bad = raw.clone();
    bad[offset + 73] = 10;
    assert!(parse(&bad).is_err());
    raw.push(0);
    assert!(parse(&raw).is_err());
}

#[test]
fn output_race_keeps_real_pending_and_both_locks_until_export_fails() {
    struct Home(std::path::PathBuf);
    impl Drop for Home {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    let home = Home(std::env::temp_dir().join(format!(
        "zevune-prepare-export-race-{:032x}",
        rand::random::<u128>()
    )));
    fs::create_dir(&home.0).unwrap();
    let password = zeroize::Zeroizing::new(rand::random::<[u8; 32]>());
    let source = home.0.join("wallet");
    let journal = home.0.join("pool");
    let manifest = home.0.join("genesis");
    let target = home.0.join("transaction");
    let wallet = WalletStore::create(&source, password.as_ref()).unwrap();
    let owner = wallet.view().unwrap().receive_address(0).unwrap();
    let pin = wallet.receipt().unwrap();
    let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    genesis.write_new(&manifest).unwrap();
    let pool = genesis.create_pool(&journal).unwrap();
    let summary = pool.summary().unwrap();
    drop(pool);
    drop(wallet);
    let fields = [
        source.to_str().unwrap().to_owned(),
        journal.to_str().unwrap().to_owned(),
        manifest.to_str().unwrap().to_owned(),
        hex(&genesis.digest()),
        super::super::Recipient::new(owner, genesis.signing_domain())
            .unwrap()
            .encode(),
        "1000".to_owned(),
        "1".to_owned(),
        "10".to_owned(),
        target.to_str().unwrap().to_owned(),
        "0".to_owned(),
        hex(&summary.app_hash),
    ];
    let mut signed = Vec::new();
    let result = execute_with_export(
        Request {
            op: 12,
            password: password.as_ref(),
            pin: Some(pin),
            fields: fields.iter().map(String::as_str).collect(),
        },
        |target, payment| {
            assert!(matches!(
                genesis.open_pool(&journal),
                Err(PoolError::Locked)
            ));
            assert!(matches!(
                WalletStore::open(&source, password.as_ref(), Some(pin)),
                Err(StoreError::Locked)
            ));
            signed = payment.bytes().to_vec();
            fs::write(target, b"competing-create-only-output").unwrap();
            export(target, payment)
        },
    );
    assert!(result.is_err());
    assert!(fs::read(&target).unwrap() == b"competing-create-only-output");
    let saved = fs::read(&source).unwrap();
    let mut pool = genesis.open_pool(&journal).unwrap();
    let mut wallet = WalletStore::open(&source, password.as_ref(), Some(pin)).unwrap();
    assert_eq!(wallet.receipt().unwrap().generation, pin.generation + 1);
    assert!(wallet.view().unwrap().pending_id().is_some());
    assert_eq!(
        wallet.view().unwrap().balance(),
        Err(WalletError::NotSynced)
    );
    let history = genesis.wallet_history(&mut pool).unwrap();
    wallet.sync(&history).unwrap();
    assert!(wallet.pending_payment().unwrap().unwrap().bytes() == signed.as_slice());
    drop(wallet);
    let prepared = pool.prepare(1, [0x61; 32], &[signed]).unwrap();
    pool.commit(prepared).unwrap();
    drop(pool);
    assert!(fs::read(&source).unwrap() == saved);
}
