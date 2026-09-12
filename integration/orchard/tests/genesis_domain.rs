#![cfg(feature = "local-funding-lab")]

//! Genuine signatures/proofs and real bounded stores. All accounts and test
//! allocations are ephemeral; no secret or wallet plaintext is logged/exported.
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::PathBuf;
use zevune_orchard_lab::pool::testnet::{TestGenesis, MAX_GENESIS_BYTES, TEST_SUPPLY};
use zevune_orchard_lab::pool::{PoolError, PoolStore};
use zevune_orchard_lab::wallet::vault::store::{StoreError, WalletStore};
use zevune_orchard_lab::wallet::{Wallet, WalletError, WalletProver};
use zevune_orchard_lab::wire::{
    decode, encode, AuthorizationVerifier, WireError, BOUND_MAGIC, MAGIC,
};

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let name: String = nonce.iter().map(|n| format!("{n:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-domain-{name}"));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn alternate_deployment(genesis: &TestGenesis) -> TestGenesis {
    let mut bytes = genesis.bytes().to_vec();
    // Change only the PUBLIC deployment nonce, not accounts, openings or values.
    bytes[50..82].fill(0x52);
    if bytes == genesis.bytes() {
        bytes[50] ^= 1;
    }
    TestGenesis::decode(&bytes).unwrap()
}
fn legacy_genesis(genesis: &TestGenesis) -> TestGenesis {
    let mut bytes = genesis.bytes().to_vec();
    bytes[..8].copy_from_slice(b"ZVTGEN01");
    bytes.drain(50..82);
    TestGenesis::decode(&bytes).unwrap()
}

#[test]
fn identical_notes_different_deployment_have_different_signed_state() {
    let owner = Wallet::create().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    let other = alternate_deployment(&genesis);
    let legacy = legacy_genesis(&genesis);
    assert_eq!(genesis.bytes().len(), 197);
    assert_eq!(legacy.bytes().len(), 165);
    assert_eq!(genesis.signing_domain(), Some(genesis.digest()));
    assert_eq!(legacy.signing_domain(), None);
    let a = genesis.initial_summary().unwrap();
    let b = other.initial_summary().unwrap();
    assert_eq!(a.root, b.root);
    assert_eq!(a.commitments, b.commitments);
    assert_ne!(a.app_hash, b.app_hash);
    assert_ne!(genesis.signing_domain(), other.signing_domain());
    assert_eq!(a.root, legacy.initial_summary().unwrap().root);
    assert_ne!(a.app_hash, legacy.initial_summary().unwrap().app_hash);
}

#[test]
fn zero_nonce_wrong_versions_truncation_and_extra_bytes_are_rejected() {
    let owner = Wallet::create().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    let mut bytes = genesis.bytes().to_vec();
    bytes[50..82].fill(0);
    assert!(TestGenesis::decode(&bytes).is_err());
    for magic in [b"ZVTGEN00", b"ZVTGEN03", b"ZVTGEN99"] {
        let mut raw = genesis.bytes().to_vec();
        raw[..8].copy_from_slice(magic);
        assert!(TestGenesis::decode(&raw).is_err());
    }
    for profile in [
        genesis,
        legacy_genesis(&TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap()),
    ] {
        for end in 0..profile.bytes().len() {
            assert!(TestGenesis::decode(&profile.bytes()[..end]).is_err());
        }
        let mut raw = profile.bytes().to_vec();
        raw.push(0);
        assert!(TestGenesis::decode(&raw).is_err());
    }
    assert!(TestGenesis::decode(&vec![0; MAX_GENESIS_BYTES + 1]).is_err());
}

#[test]
fn real_payment_cannot_cross_identical_note_roots_or_be_relabelled() {
    let dir = Dir::new();
    let wallet_file = dir.0.join("sender.wallet");
    let mut password = [0; 32];
    OsRng.fill_bytes(&mut password);
    let mut sender = WalletStore::create(&wallet_file, &password).unwrap();
    let recipient = Wallet::create().unwrap().receive_address(0).unwrap();
    let owner = sender.view().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    let other = alternate_deployment(&genesis);
    let legacy = legacy_genesis(&genesis);
    let path_a = dir.0.join("a.journal");
    let path_b = dir.0.join("b.journal");
    let path_old = dir.0.join("legacy.journal");
    let mut a = genesis.create_pool(&path_a).unwrap();
    let mut b = other.create_pool(&path_b).unwrap();
    let old = legacy.create_pool(&path_old).unwrap();
    let original_a = a.summary().unwrap();
    let original_b = b.summary().unwrap();
    sender
        .sync(&genesis.wallet_history(&mut a).unwrap())
        .unwrap();
    let payment = sender
        .prepare_payment(recipient, 25_000, 1_000, 10, &WalletProver::new())
        .unwrap();
    let raw = payment.bytes().to_vec();
    assert_eq!(&raw[..8], BOUND_MAGIC);
    assert_eq!(raw.len(), 9_198);
    for end in 0..raw.len() {
        assert!(decode(&raw[..end]).is_err());
    }
    let mut oversized = raw.clone();
    oversized.push(0);
    assert!(decode(&oversized).is_err());
    let mut zero_domain = raw.clone();
    zero_domain[8..40].fill(0);
    assert!(matches!(decode(&zero_domain), Err(WireError::Policy)));
    let mut future = raw.clone();
    future[..8].copy_from_slice(b"ZVORLAB3");
    assert!(decode(&future).is_err());
    let mut tx = decode(&raw).unwrap();
    assert_eq!(tx.context.signing_domain, genesis.signing_domain());
    assert_eq!(encode(&tx.bundle, &tx.context).unwrap(), raw);
    let verifier = AuthorizationVerifier::new();
    verifier.verify(&raw).unwrap();
    verifier.verify(&raw).unwrap(); // true cached authorization, not state permission
    let prepared = a.prepare(1, [1; 32], std::slice::from_ref(&raw)).unwrap();
    assert_eq!(original_a.root, original_b.root);
    assert!(matches!(
        b.prepare(1, [1; 32], std::slice::from_ref(&raw)),
        Err(PoolError::Domain)
    ));
    assert!(matches!(
        old.prepare(1, [1; 32], std::slice::from_ref(&raw)),
        Err(PoolError::Domain)
    ));

    // Editing the public domain does not produce valid signatures for B.
    tx.context.signing_domain = other.signing_domain();
    let relabelled = encode(&tx.bundle, &tx.context).unwrap();
    assert!(matches!(
        verifier.verify(&relabelled),
        Err(WireError::Authorization)
    ));
    assert!(matches!(
        b.prepare(1, [1; 32], &[relabelled]),
        Err(PoolError::Authorization)
    ));
    tx.context.signing_domain = None;
    let downgraded = encode(&tx.bundle, &tx.context).unwrap();
    assert_eq!(&downgraded[..8], MAGIC);
    assert!(matches!(
        verifier.verify(&downgraded),
        Err(WireError::Authorization)
    ));
    assert!(matches!(
        a.prepare(1, [1; 32], &[downgraded]),
        Err(PoolError::Domain)
    ));
    assert_eq!(a.summary().unwrap(), original_a);
    assert_eq!(b.summary().unwrap(), original_b);

    // A restored encrypted outbox must not acquire a different chain's policy.
    let receipt = sender.receipt().unwrap();
    drop(sender);
    let before_wallet = fs::read(&wallet_file).unwrap();
    let mut restored = WalletStore::open(&wallet_file, &password, Some(receipt)).unwrap();
    assert!(matches!(
        restored.sync(&other.wallet_history(&mut b).unwrap()),
        Err(StoreError::Wallet(WalletError::History))
    ));
    assert_eq!(restored.receipt().unwrap(), receipt);
    restored
        .sync(&genesis.wallet_history(&mut a).unwrap())
        .unwrap();
    assert_eq!(restored.pending_payment().unwrap().unwrap().bytes(), raw);
    drop(restored);
    assert_eq!(fs::read(&wallet_file).unwrap(), before_wallet);
    a.commit(prepared).unwrap();
    let accepted = a.summary().unwrap();
    drop(a);
    drop(b);
    drop(old);
    let saved_a = fs::read(&path_a).unwrap();
    let saved_b = fs::read(&path_b).unwrap();
    assert!(matches!(other.open_pool(&path_a), Err(PoolError::Genesis)));
    assert!(matches!(legacy.open_pool(&path_a), Err(PoolError::Genesis)));
    assert!(PoolStore::open(&path_a).is_err());
    assert_eq!(
        genesis.open_pool(&path_a).unwrap().summary().unwrap(),
        accepted
    );
    assert_eq!(
        other.open_pool(&path_b).unwrap().summary().unwrap(),
        original_b
    );
    assert_eq!(fs::read(&path_a).unwrap(), saved_a);
    assert_eq!(fs::read(&path_b).unwrap(), saved_b);

    // Even rewriting the journal header/base hash and recomputing its public
    // checksum cannot transplant a correctly signed A transaction into B.
    let header_size = 76 + 32; // new header and exactly one initial commitment
    assert_eq!(saved_b.len(), header_size);
    let mut transplanted = saved_b;
    transplanted.extend_from_slice(&saved_a[header_size..]);
    let body_start = header_size + 4;
    let n = u32::from_be_bytes(transplanted[header_size..body_start].try_into().unwrap()) as usize;
    transplanted[body_start + 48..body_start + 80].copy_from_slice(&original_b.app_hash);
    let checksum = Sha256::digest(&transplanted[body_start..body_start + n]);
    transplanted[body_start + n..body_start + n + 32].copy_from_slice(&checksum);
    let attack_path = dir.0.join("cross-domain-replay.journal");
    fs::write(&attack_path, &transplanted).unwrap();
    assert!(matches!(
        other.open_pool(&attack_path),
        Err(PoolError::Domain)
    ));
    assert_eq!(fs::read(&attack_path).unwrap(), transplanted);
}

#[test]
fn legacy_wallet_and_log_remain_legacy_without_implicit_migration() {
    let dir = Dir::new();
    let mut sender = Wallet::create().unwrap();
    let receiver = Wallet::create().unwrap().receive_address(0).unwrap();
    let modern =
        TestGenesis::generate(&[(sender.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let old = legacy_genesis(&modern);
    let path = dir.0.join("old.journal");
    let mut pool = old.create_pool(&path).unwrap();
    sender
        .sync(&old.wallet_history(&mut pool).unwrap())
        .unwrap();
    let tx = sender
        .build_payment(receiver, 10_000, 1_000, 5, &WalletProver::new())
        .unwrap();
    assert_eq!(&tx.bytes()[..8], MAGIC);
    assert_eq!(decode(tx.bytes()).unwrap().context.signing_domain, None);
    let prepared = pool.prepare(1, [1; 32], &[tx.bytes().to_vec()]).unwrap();
    pool.commit(prepared).unwrap();
    let summary = pool.summary().unwrap();
    drop(pool);
    let bytes = fs::read(&path).unwrap();
    assert_eq!(&bytes[..8], b"ZVOPOL01");
    assert!(modern.open_pool(&path).is_err());
    assert_eq!(old.open_pool(&path).unwrap().summary().unwrap(), summary);
    assert_eq!(fs::read(&path).unwrap(), bytes);
    let new_pool = modern.create_pool(&dir.0.join("modern.journal")).unwrap();
    assert!(matches!(
        new_pool.prepare(1, [1; 32], &[tx.bytes().to_vec()]),
        Err(PoolError::Domain)
    ));
}

#[test]
fn maximum_action_bound_payment_fits_exact_envelope_and_survives_replay() {
    let dir = Dir::new();
    let mut sender = Wallet::create().unwrap();
    let owner = sender.receive_address(0).unwrap();
    let destination = Wallet::create().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[(owner, 12_500); 8]).unwrap();
    let path = dir.0.join("maximum.journal");
    let mut pool = genesis.create_pool(&path).unwrap();
    sender
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let payment = sender
        .build_payment(destination, 99_000, 1_000, 10, &WalletProver::new())
        .unwrap();
    let tx = decode(payment.bytes()).unwrap();
    assert_eq!(tx.bundle.actions().len(), 8);
    assert_eq!(
        payment.bytes().len(),
        zevune_orchard_lab::wire::MAX_ENVELOPE_SIZE
    );
    assert_eq!(payment.bytes().len(), 28_134);
    assert!(decode(&payment.bytes()[..28_102]).is_err());
    let mut extra = payment.bytes().to_vec();
    extra.push(0);
    assert!(matches!(decode(&extra), Err(WireError::Bounds)));
    let prepared = pool
        .prepare(1, [9; 32], &[payment.bytes().to_vec()])
        .unwrap();
    let committed = pool.commit(prepared).unwrap();
    assert_eq!(committed.fees, 1_000);
    drop(pool);
    assert_eq!(
        genesis.open_pool(&path).unwrap().summary().unwrap(),
        committed
    );
}
