//! Real wallet-local process + original Orchard/PoolStore. NO-FUNDS only.
#![cfg(feature = "local-funding-lab")]
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};
use zeroize::Zeroizing;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::wallet::address::Recipient;
use zevune_orchard_lab::wallet::vault::store::{StoreReceipt, WalletStore};
use zevune_orchard_lab::wallet::WalletError;

struct Home(PathBuf);
impl Home {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "zevune-checked-prepare-cli-{:032x}",
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
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|v| format!("{v:02x}")).collect()
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
fn command(op: u8, password: &[u8], pin: StoreReceipt, fields: &[String], success: bool) -> String {
    let mut raw = Zeroizing::new(b"ZVWCLI01".to_vec());
    raw.push(op);
    raw.extend_from_slice(&(password.len() as u16).to_be_bytes());
    raw.extend_from_slice(password);
    raw.push(1);
    raw.extend_from_slice(&pin.journal_id);
    raw.extend_from_slice(&pin.generation.to_be_bytes());
    raw.extend_from_slice(&pin.digest);
    raw.push(fields.len() as u8);
    for field in fields {
        raw.extend_from_slice(&(field.len() as u16).to_be_bytes());
        raw.extend_from_slice(field.as_bytes());
    }
    assert!(raw.len() < 4096);
    let mut child = Command::new(env!("CARGO_BIN_EXE_zevune-wallet-local"))
        .arg("--no-real-funds")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    if child.stdin.take().unwrap().write_all(&raw).is_err() {
        let _ = child.kill();
        let _ = child.wait();
        panic!("failed delivering bounded private test frame");
    }
    let end = Instant::now() + Duration::from_secs(300);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < end => thread::sleep(Duration::from_millis(5)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                panic!("actual preparation command exceeded original request budget");
            }
        }
    };
    assert_eq!(status.success(), success);
    let mut output = String::new();
    child
        .stdout
        .take()
        .unwrap()
        .take(4097)
        .read_to_string(&mut output)
        .unwrap();
    assert!(output.len() <= 4096);
    if !success {
        assert!(output.is_empty());
    }
    output
}
fn setup(home: &Home, password: &[u8], active: bool) -> (TestGenesis, StoreReceipt, Vec<String>) {
    let source = home.0.join("wallet");
    let journal = home.0.join("pool");
    let manifest = home.0.join("genesis");
    let wallet = WalletStore::create(&source, password).unwrap();
    let pin = wallet.receipt().unwrap();
    let owner = wallet.view().unwrap().receive_address(0).unwrap();
    let genesis = if active {
        TestGenesis::generate_active(&[(owner, TEST_SUPPLY)]).unwrap()
    } else {
        TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap()
    };
    genesis.write_new(&manifest).unwrap();
    let pool = genesis.create_pool(&journal).unwrap();
    let summary = pool.summary().unwrap();
    let fields = vec![
        source.to_str().unwrap().to_owned(),
        journal.to_str().unwrap().to_owned(),
        manifest.to_str().unwrap().to_owned(),
        hex(&genesis.digest()),
        Recipient::new(owner, genesis.signing_domain())
            .unwrap()
            .encode(),
        "1000".to_owned(),
        "1".to_owned(),
        "10".to_owned(),
        home.0.join("payment").to_str().unwrap().to_owned(),
        "0".to_owned(),
        hex(&summary.app_hash),
    ];
    drop(pool);
    drop(wallet);
    (genesis, pin, fields)
}

#[test]
fn real_cli_both_profiles_keep_rejections_unchanged_and_save_one_pending_record() {
    for active in [false, true] {
        let home = Home::new();
        let password = Zeroizing::new(rand::random::<[u8; 32]>());
        let (genesis, pin, fields) = setup(&home, password.as_ref(), active);
        let source = Path::new(&fields[0]);
        let journal = Path::new(&fields[1]);
        let before = files(source);
        let reference = files(journal);
        let receiver = Recipient::decode(&fields[4])
            .unwrap()
            .for_domain(genesis.signing_domain())
            .unwrap();
        let other_domain = Recipient::new(receiver, Some([0x7f; 32])).unwrap();
        let legacy = Recipient::new(receiver, None).unwrap();
        for (index, value) in [
            (9, "1".to_owned()),
            (10, "ff".repeat(32)),
            (10, "0".repeat(64)),
            (5, "0".to_owned()),
            (5, "100000".to_owned()),
            (6, "11".to_owned()),
            (7, "101".to_owned()),
            (4, other_domain.encode()),
            (4, legacy.encode()),
        ] {
            let mut bad = fields.clone();
            bad[index] = value;
            command(12, password.as_ref(), pin, &bad, false);
            assert!(files(source) == before);
            assert!(files(journal) == reference);
            assert!(!Path::new(&fields[8]).exists());
        }
        fs::write(&fields[8], b"existing-output").unwrap();
        command(12, password.as_ref(), pin, &fields, false);
        assert!(files(source) == before);
        assert!(fs::read(&fields[8]).unwrap() == b"existing-output");
        fs::remove_file(&fields[8]).unwrap(); // explicit TEST fixture, never runtime cleanup
        let response = command(12, password.as_ref(), pin, &fields, true);
        assert!(response.contains("\"result\":\"checkpoint_payment_saved_not_broadcast\""));
        assert!(response.contains("\"checkpoint_matched\":true"));
        assert!(response.contains("\"broadcast\":false"));
        assert!(response.contains(&format!("\"app_hash\":\"{}\"", fields[10])));
        assert!(!response.contains("\"confirmed\""));
        let raw = fs::read(&fields[8]).unwrap();
        let txid: [u8; 32] = Sha256::digest(&raw).into();
        let saved = files(source);
        assert!(files(journal) == reference);
        let mut pool = genesis.open_pool(journal).unwrap();
        let history = genesis.wallet_history(&mut pool).unwrap();
        let mut wallet = WalletStore::open(source, password.as_ref(), Some(pin)).unwrap();
        let saved_pin = wallet.receipt().unwrap();
        assert_eq!(saved_pin.generation, pin.generation + 1);
        assert_eq!(wallet.view().unwrap().pending_id(), Some(txid));
        assert_eq!(wallet.view().unwrap().height(), Some(0));
        assert_eq!(
            wallet.view().unwrap().balance(),
            Err(WalletError::NotSynced)
        );
        wallet.sync(&history).unwrap();
        assert_eq!(wallet.receipt().unwrap(), saved_pin);
        assert!(wallet.pending_payment().unwrap().unwrap().bytes() == raw.as_slice());
        assert_eq!(wallet.view().unwrap().available_balance(), Ok(0));
        drop(wallet);
        drop(pool);
        assert!(files(source) == saved);
        let mut retry = fields.clone();
        retry[8] = home.0.join("another-payment").to_str().unwrap().to_owned();
        command(12, password.as_ref(), saved_pin, &retry, false);
        assert!(files(source) == saved);
        assert!(!Path::new(&retry[8]).exists());
        pool = genesis.open_pool(journal).unwrap();
        let prepared = pool.prepare(1, [0x51; 32], &[raw]).unwrap();
        let tip = pool.commit(prepared).unwrap();
        drop(pool);
        let advanced_reference = files(journal);
        let mut stale = fields.clone();
        stale[8] = home.0.join("stale-payment").to_str().unwrap().to_owned();
        command(12, password.as_ref(), saved_pin, &stale, false);
        assert!(files(source) == saved);
        assert!(files(journal) == advanced_reference);
        assert!(!Path::new(&stale[8]).exists());
        let scan = vec![
            fields[0].clone(),
            fields[1].clone(),
            fields[2].clone(),
            fields[3].clone(),
            tip.height.to_string(),
            hex(&tip.app_hash),
        ];
        let response = command(11, password.as_ref(), saved_pin, &scan, true);
        assert!(response.contains("\"pending\":false"));
        assert!(response.contains("\"balance\":99999"));
    }
}

#[test]
fn real_cli_export_failure_preserves_signed_outbox_for_explicit_original_export() {
    let home = Home::new();
    let password = Zeroizing::new(rand::random::<[u8; 32]>());
    let (genesis, pin, mut fields) = setup(&home, password.as_ref(), false);
    fields[8] = home
        .0
        .join("absent-parent")
        .join("payment")
        .to_str()
        .unwrap()
        .to_owned();
    // Initial create-only check passes; original export fails AFTER persistence.
    command(12, password.as_ref(), pin, &fields, false);
    assert!(!Path::new(&fields[8]).exists());
    let source = Path::new(&fields[0]);
    let saved = files(source);
    let mut pool = genesis.open_pool(Path::new(&fields[1])).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    let mut wallet = WalletStore::open(source, password.as_ref(), Some(pin)).unwrap();
    let saved_pin = wallet.receipt().unwrap();
    assert_eq!(saved_pin.generation, pin.generation + 1);
    assert!(wallet.view().unwrap().pending_id().is_some());
    wallet.sync(&history).unwrap();
    let signed = wallet.pending_payment().unwrap().unwrap().bytes().to_vec();
    drop(wallet);
    drop(pool);
    assert!(files(source) == saved);
    let output = home.0.join("explicit-pending-export");
    let export_fields = vec![
        fields[0].clone(),
        fields[1].clone(),
        fields[2].clone(),
        fields[3].clone(),
        output.to_str().unwrap().to_owned(),
    ];
    command(5, password.as_ref(), saved_pin, &export_fields, true);
    assert!(fs::read(output).unwrap() == signed);
    assert!(files(source) == saved);
}

#[test]
fn real_cli_recovery_after_export_failure_is_exact_and_never_updates_wallet() {
    for active in [false, true] {
        let home = Home::new();
        let password = Zeroizing::new(rand::random::<[u8; 32]>());
        let (genesis, pin, mut prepare) = setup(&home, password.as_ref(), active);
        prepare[8] = home
            .0
            .join("missing-parent")
            .join("not-exported.tx")
            .to_str()
            .unwrap()
            .to_owned();
        command(12, password.as_ref(), pin, &prepare, false);
        let source = Path::new(&prepare[0]);
        let journal = Path::new(&prepare[1]);
        let saved = files(source);
        let reference = files(journal);
        // Establish expected exact bytes independently using the ORIGINAL
        // pending accessor after a same-checkpoint scan, then close both stores.
        let mut pool = genesis.open_pool(journal).unwrap();
        let history = genesis.wallet_history(&mut pool).unwrap();
        let mut wallet = WalletStore::open(source, password.as_ref(), Some(pin)).unwrap();
        let saved_pin = wallet.receipt().unwrap();
        let id = wallet.view().unwrap().pending_id().unwrap();
        assert_eq!(saved_pin.generation, pin.generation + 1);
        assert_eq!(
            wallet.view().unwrap().balance(),
            Err(WalletError::NotSynced)
        );
        wallet.sync(&history).unwrap();
        let expected = wallet.pending_payment().unwrap().unwrap();
        assert_eq!(wallet.receipt().unwrap(), saved_pin);
        drop(wallet);
        drop(pool);
        assert!(files(source) == saved);
        assert!(files(journal) == reference);
        let mut f = vec![
            prepare[0].clone(),
            prepare[1].clone(),
            prepare[2].clone(),
            prepare[3].clone(),
            home.0.join("recovered.tx").to_str().unwrap().to_owned(),
            prepare[9].clone(),
            prepare[10].clone(),
        ];
        if active {
            let mut inside = f.clone();
            inside[4] = journal
                .join("must-not-alter-pool.tx")
                .to_str()
                .unwrap()
                .to_owned();
            command(13, password.as_ref(), pin, &inside, false);
            assert!(!Path::new(&inside[4]).exists());
            assert!(files(source) == saved);
            assert!(files(journal) == reference);
        }
        for (index, value) in [
            (5, "1".to_owned()),
            (6, "ff".repeat(32)),
            (6, "0".repeat(64)),
        ] {
            let mut bad = f.clone();
            bad[index] = value;
            command(13, password.as_ref(), pin, &bad, false);
            assert!(!Path::new(&f[4]).exists());
            assert!(files(source) == saved);
            assert!(files(journal) == reference);
        }
        // Two separate actual processes explicitly recover, without asking for
        // another proof, updating the wallet or consuming a journal generation.
        for name in ["recovered.tx", "same-again.tx"] {
            f[4] = home.0.join(name).to_str().unwrap().to_owned();
            let response = command(13, password.as_ref(), pin, &f, true);
            assert!(response.contains("\"result\":\"checkpoint_pending_exported_not_broadcast\""));
            assert!(response.contains("\"wallet_unchanged\":true"));
            assert!(response.contains("\"checkpoint_matched\":true"));
            assert!(response.contains("\"broadcast\":false"));
            assert!(response.contains(&format!("\"txid\":\"{}\"", hex(&id))));
            assert!(!response.contains("\"balance\"") && !response.contains("\"confirmed\""));
            assert!(fs::read(&f[4]).unwrap() == expected.bytes());
            assert!(files(source) == saved);
            assert!(files(journal) == reference);
            wallet = WalletStore::open(source, password.as_ref(), Some(saved_pin)).unwrap();
            assert_eq!(wallet.receipt().unwrap(), saved_pin);
            assert_eq!(wallet.view().unwrap().pending_id(), Some(id));
            assert_eq!(wallet.view().unwrap().height(), Some(0));
            assert_eq!(
                wallet.view().unwrap().balance(),
                Err(WalletError::NotSynced)
            );
            drop(wallet);
            assert!(files(source) == saved);
        }
        let existing = fs::read(&f[4]).unwrap();
        command(13, password.as_ref(), saved_pin, &f, false);
        assert!(fs::read(&f[4]).unwrap() == existing);
        f[4] = prepare[8].clone(); // export I/O error, not a preflight shortcut
        command(13, password.as_ref(), saved_pin, &f, false);
        assert!(files(source) == saved);
        assert!(files(journal) == reference);
        assert!(!Path::new(&f[4]).exists());
        // Once genuine committed history consumes the payment, this read-only
        // API refuses recovery but does NOT silently reconcile the saved wallet.
        pool = genesis.open_pool(journal).unwrap();
        let block = pool
            .prepare(1, [0x49; 32], &[expected.bytes().to_vec()])
            .unwrap();
        let tip = pool.commit(block).unwrap();
        drop(pool);
        let advanced_reference = files(journal);
        f[4] = home
            .0
            .join("must-not-export.tx")
            .to_str()
            .unwrap()
            .to_owned();
        command(13, password.as_ref(), saved_pin, &f, false); // stale checkpoint
        f[5] = tip.height.to_string();
        f[6] = hex(&tip.app_hash);
        command(13, password.as_ref(), saved_pin, &f, false); // consumed pending
        assert!(!Path::new(&f[4]).exists());
        assert!(files(source) == saved);
        assert!(files(journal) == advanced_reference);
        wallet = WalletStore::open(source, password.as_ref(), Some(saved_pin)).unwrap();
        assert_eq!(wallet.view().unwrap().pending_id(), Some(id));
        assert_eq!(wallet.receipt().unwrap(), saved_pin);
        assert_eq!(
            wallet.view().unwrap().balance(),
            Err(WalletError::NotSynced)
        );
        drop(wallet);
        assert!(files(source) == saved);
    }
}
