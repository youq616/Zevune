#![cfg(feature = "local-funding-lab")]
//! Real signatures/proofs and disks; all assets and passwords are synthetic.
use std::fs;
use std::path::PathBuf;

use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use zevune_orchard_lab::domain::{DomainError, DomainId, NetworkDescriptor, DESCRIPTOR_SIZE};
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::pool::PoolError;
use zevune_orchard_lab::wallet::vault::{self, store::WalletStore};
use zevune_orchard_lab::wallet::{Wallet, WalletError, WalletProver};
use zevune_orchard_lab::wire::{self, AuthorizationVerifier, WireError};

const PASSWORD: &[u8] = b"synthetic-domain-test-password";
struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let text: String = nonce.iter().map(|b| format!("{b:02x}")).collect();
        let dir = std::env::temp_dir().join(format!("zevune-domain-{text}"));
        fs::create_dir(&dir).unwrap();
        Self(dir)
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn descriptor_is_canonical_and_binds_network_genesis_and_rules() {
    let descriptor = NetworkDescriptor::new([1; 32], [2; 32]).unwrap();
    let raw = descriptor.encode();
    assert_eq!(raw.len(), DESCRIPTOR_SIZE);
    assert_eq!(NetworkDescriptor::decode(&raw).unwrap(), descriptor);
    assert_ne!(
        descriptor.id(),
        NetworkDescriptor::new([3; 32], [2; 32]).unwrap().id()
    );
    assert_ne!(
        descriptor.id(),
        NetworkDescriptor::new([1; 32], [3; 32]).unwrap().id()
    );
    for n in 0..raw.len() {
        assert!(NetworkDescriptor::decode(&raw[..n]).is_err());
    }
    let mut bad = raw.to_vec();
    bad.push(0);
    assert_eq!(NetworkDescriptor::decode(&bad), Err(DomainError::Encoding));
    bad = raw.to_vec();
    bad[72] ^= 1;
    assert_eq!(NetworkDescriptor::decode(&bad), Err(DomainError::Rules));
    bad = raw.to_vec();
    bad[7] ^= 1;
    assert_eq!(NetworkDescriptor::decode(&bad), Err(DomainError::Encoding));
    for (network, genesis) in [([0; 32], [1; 32]), ([1; 32], [0; 32])] {
        assert!(NetworkDescriptor::new(network, genesis).is_err());
    }
    assert!(DomainId::from_bytes([0; 32]).is_err());
}

#[test]
fn identical_asset_roots_have_distinct_bound_state_and_no_implicit_migration() {
    let dir = Dir::new();
    let wallet = Wallet::create().unwrap();
    let g = TestGenesis::generate(&[(wallet.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let a = NetworkDescriptor::new([1; 32], g.digest()).unwrap();
    let b = NetworkDescriptor::new([2; 32], g.digest()).unwrap();
    let sa = g.initial_summary_bound(&a).unwrap();
    let sb = g.initial_summary_bound(&b).unwrap();
    assert_eq!(sa.root, sb.root); // Actual same assets, not a root-mismatch test.
    assert_ne!(sa.app_hash, sb.app_hash);
    assert_ne!(sa.app_hash, g.initial_summary().unwrap().app_hash);
    let path = dir.0.join("bound.journal");
    drop(g.create_pool_bound(&path, &a).unwrap());
    let original = fs::read(&path).unwrap();
    assert!(g.open_pool_bound(&path, &b).is_err());
    assert!(g.open_pool(&path).is_err());
    assert_eq!(fs::read(&path).unwrap(), original);
    assert_eq!(g.open_pool_bound(&path, &a).unwrap().summary().unwrap(), sa);
    let old = dir.0.join("legacy.journal");
    drop(g.create_pool(&old).unwrap());
    let old_bytes = fs::read(&old).unwrap();
    assert!(g.open_pool_bound(&old, &a).is_err());
    assert_eq!(fs::read(&old).unwrap(), old_bytes);
    let wrong = NetworkDescriptor::new([1; 32], [99; 32]).unwrap();
    let absent = dir.0.join("never-created.journal");
    assert!(g.create_pool_bound(&absent, &wrong).is_err());
    assert!(!absent.exists());
}

#[test]
fn wallet_domain_is_one_time_authenticated_and_not_taken_from_history() {
    let dir = Dir::new();
    let mut wallet = Wallet::create().unwrap();
    let g = TestGenesis::generate(&[(wallet.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let a = NetworkDescriptor::new([1; 32], g.digest()).unwrap();
    let b = NetworkDescriptor::new([2; 32], g.digest()).unwrap();
    let mut pa = g.create_pool_bound(&dir.0.join("a"), &a).unwrap();
    let mut pb = g.create_pool_bound(&dir.0.join("b"), &b).unwrap();
    let ha = g.wallet_history_bound(&mut pa, &a).unwrap();
    let hb = g.wallet_history_bound(&mut pb, &b).unwrap();
    assert!(wallet.sync(&ha).is_err()); // Legacy wallet cannot silently change mode.
    wallet.bind_domain_once(a.id()).unwrap();
    assert!(wallet.bind_domain_once(b.id()).is_err());
    wallet.sync(&ha).unwrap();
    let before = wallet.balance().unwrap();
    assert!(wallet.sync(&hb).is_err());
    assert_eq!(wallet.balance().unwrap(), before);
    assert!(g.wallet_history(&mut pa).is_err());
    let sealed = vault::seal(&wallet, PASSWORD).unwrap();
    assert_eq!(sealed.len(), vault::SEALED_BYTES);
    let mut restored = vault::open(&sealed, PASSWORD).unwrap();
    assert_eq!(restored.domain(), Some(a.id()));
    assert!(restored.sync(&hb).is_err());
    assert_eq!(restored.balance(), Err(WalletError::NotSynced));
    restored.sync(&ha).unwrap();
    assert_eq!(restored.balance().unwrap(), TEST_SUPPLY);
    let mut old = Wallet::create().unwrap();
    let mut legacy = g.create_pool(&dir.0.join("legacy")).unwrap();
    old.sync(&g.wallet_history(&mut legacy).unwrap()).unwrap();
    assert!(old.bind_domain_once(a.id()).is_err()); // Not a migration operation.
}

#[test]
fn real_bound_two_hop_payment_rejects_replay_relabeling_downgrade_and_preserves_outbox() {
    let dir = Dir::new();
    let alice_path = dir.0.join("alice.wallet");
    let backup_path = dir.0.join("alice-backup.wallet");
    let mut alice = WalletStore::create(&alice_path, PASSWORD).unwrap();
    let address = alice.view().unwrap().receive_address(0).unwrap();
    let g = TestGenesis::generate(&[(address, TEST_SUPPLY)]).unwrap();
    let a = NetworkDescriptor::new([1; 32], g.digest()).unwrap();
    let b = NetworkDescriptor::new([2; 32], g.digest()).unwrap();
    alice.bind_domain_once(a.id()).unwrap();
    let mut bob = Wallet::create_for_domain(a.id()).unwrap();
    let mut carol = Wallet::create_for_domain(a.id()).unwrap();
    let pa_path = dir.0.join("a.pool");
    let pb_path = dir.0.join("b.pool");
    let mut pa = g.create_pool_bound(&pa_path, &a).unwrap();
    let mut pb = g.create_pool_bound(&pb_path, &b).unwrap();
    let ha = g.wallet_history_bound(&mut pa, &a).unwrap();
    alice.sync(&ha).unwrap();
    bob.sync(&ha).unwrap();
    carol.sync(&ha).unwrap();
    let prover = WalletProver::for_domain(a.id());
    let payment = alice
        .prepare_payment(bob.receive_address(0).unwrap(), 60_000, 1_000, 20, &prover)
        .unwrap();
    let raw = payment.bytes().to_vec();
    // Optional public fixtures ONLY. No seed, viewing key, note opening or
    // decrypted payment record is exported. Cross-language CI requires these.
    if let Some(folder) = std::env::var_os("ZEVUNE_BOUND_FIXTURE_DIR") {
        use std::io::Write;
        let folder = PathBuf::from(folder);
        assert!(folder.is_absolute() && folder.is_dir());
        for (name, bytes) in [
            ("domain.bin", a.encode().to_vec()),
            ("payment.bin", raw.clone()),
        ] {
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(folder.join(name))
                .unwrap();
            file.write_all(&bytes).unwrap();
        }
    }
    assert_eq!(&raw[..8], wire::BOUND_MAGIC);
    assert_eq!(payment.id(), <[u8; 32]>::from(Sha256::digest(&raw)));
    let va = AuthorizationVerifier::for_domain(a.id());
    let vb = AuthorizationVerifier::for_domain(b.id());
    va.verify(&raw).unwrap();
    va.verify(&raw).unwrap(); // Warm cache is also scoped.
    assert_eq!(vb.verify(&raw), Err(WireError::Policy));
    let mut relabeled = raw.clone();
    relabeled[8..40].copy_from_slice(&b.id().to_bytes());
    assert!(wire::decode_bound(&relabeled, b.id()).is_ok());
    assert_eq!(vb.verify(&relabeled), Err(WireError::Authorization));
    let mut stripped = wire::MAGIC.to_vec();
    stripped.extend_from_slice(&raw[40..]);
    assert!(wire::decode(&stripped).is_ok());
    assert_eq!(
        AuthorizationVerifier::new().verify(&stripped),
        Err(WireError::Authorization)
    );
    assert!(AuthorizationVerifier::new().verify(&raw).is_err());
    let original_b = pb.summary().unwrap();
    for bad in [&raw, &relabeled, &stripped] {
        assert!(matches!(
            pb.prepare(1, [1; 32], &[bad.to_vec()]),
            Err(PoolError::Authorization)
        ));
        assert_eq!(pb.summary().unwrap(), original_b);
    }
    // Mutations that pass outer shape checks still require real signatures/proofs.
    for offset in [40, 48, 64, 100, raw.len() - 1] {
        let mut changed = raw.clone();
        changed[offset] ^= 1;
        assert!(va.verify(&changed).is_err());
    }
    for n in 0..raw.len() {
        assert!(wire::decode_bound(&raw[..n], a.id()).is_err());
    }
    let mut trailing = raw.clone();
    trailing.push(0);
    assert!(wire::decode_bound(&trailing, a.id()).is_err());
    assert!(wire::decode_bound(&vec![0; wire::MAX_BOUND_ENVELOPE_SIZE + 1], a.id()).is_err());
    let before_a = pa.summary().unwrap();
    assert!(pa.prepare(1, [1; 32], &[raw.clone(), relabeled]).is_err());
    assert_eq!(pa.summary().unwrap(), before_a); // No partial prefix effects.
    let receipt = alice.backup_new(&backup_path).unwrap();
    drop(alice);
    let mut alice = WalletStore::open(&backup_path, PASSWORD, Some(receipt)).unwrap();
    assert!(alice.pending_payment().is_err()); // Must first rescan the correct domain.
    assert!(alice
        .sync(&g.wallet_history_bound(&mut pb, &b).unwrap())
        .is_err());
    alice.sync(&ha).unwrap();
    let resumed = alice.pending_payment().unwrap().unwrap();
    assert_eq!(resumed.bytes(), raw);
    assert_eq!(resumed.id(), payment.id());
    let p = pa.prepare(1, [11; 32], std::slice::from_ref(&raw)).unwrap();
    pa.commit(p).unwrap();
    drop(pa);
    let mut pa = g.open_pool_bound(&pa_path, &a).unwrap();
    let h = g.wallet_history_bound(&mut pa, &a).unwrap();
    alice.sync(&h).unwrap();
    bob.sync(&h).unwrap();
    assert!(alice.pending_payment().unwrap().is_none());
    assert_eq!(alice.view().unwrap().balance().unwrap(), 39_000);
    assert_eq!(bob.balance().unwrap(), 60_000);
    let second = bob
        .build_payment(
            carol.receive_address(0).unwrap(),
            40_000,
            1_000,
            20,
            &prover,
        )
        .unwrap();
    let p = pa.prepare(2, [12; 32], &[second.bytes().to_vec()]).unwrap();
    pa.commit(p).unwrap();
    let h = g.wallet_history_bound(&mut pa, &a).unwrap();
    bob.sync(&h).unwrap();
    carol.sync(&h).unwrap();
    assert_eq!(bob.balance().unwrap(), 19_000);
    assert_eq!(carol.balance().unwrap(), 40_000);
    assert_eq!(
        alice.view().unwrap().balance().unwrap()
            + bob.balance().unwrap()
            + carol.balance().unwrap()
            + pa.summary().unwrap().fees,
        TEST_SUPPLY
    );
    assert!(matches!(
        pa.prepare(3, [13; 32], &[raw]),
        Err(PoolError::DoubleSpend)
    ));
    let final_state = pa.summary().unwrap();
    drop(pa);
    drop(pb);
    assert_eq!(
        g.open_pool_bound(&pa_path, &a).unwrap().summary().unwrap(),
        final_state
    );
    assert_eq!(
        g.open_pool_bound(&pb_path, &b).unwrap().summary().unwrap(),
        original_b
    );
}

#[test]
fn independent_golden_descriptor_matches_go_and_python() {
    let network = core::array::from_fn(|i| (i + 1) as u8);
    let genesis = core::array::from_fn(|i| (i + 33) as u8);
    let d = NetworkDescriptor::new(network, genesis).unwrap();
    let hex = |bytes: &[u8]| bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
    assert_eq!(
        hex(&d.id().to_bytes()),
        "6418d64157c1f482123804763244c63521a55bb8a398b4972962875cabfe2569"
    );
    assert_eq!(hex(&d.encode()), "5a56444f4d4e30320102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f40d506193ea22ad9eca0087c20685e83997d2de70072436341bf887a252ff5ca68" );
}

#[test]
fn legacy_signatures_cannot_be_wrapped_and_wrong_prover_does_not_mutate_wallet() {
    let dir = Dir::new();
    let mut wallet = Wallet::create().unwrap();
    let g = TestGenesis::generate(&[(wallet.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let d = NetworkDescriptor::new([1; 32], g.digest()).unwrap();
    let mut pool = g.create_pool(&dir.0.join("old-pool")).unwrap();
    wallet.sync(&g.wallet_history(&mut pool).unwrap()).unwrap();
    let recipient = Wallet::create().unwrap().receive_address(0).unwrap();
    let legacy_prover = WalletProver::new();
    let tx = wallet
        .build_payment(recipient, 1_000, 1_000, 20, &legacy_prover)
        .unwrap();
    AuthorizationVerifier::new().verify(tx.bytes()).unwrap();
    let decoded = wire::decode(tx.bytes()).unwrap();
    let wrapped = wire::encode_bound(&decoded.bundle, &decoded.context, d.id()).unwrap();
    assert!(wire::decode_bound(&wrapped, d.id()).is_ok());
    assert_eq!(
        AuthorizationVerifier::for_domain(d.id()).verify(&wrapped),
        Err(WireError::Authorization)
    );
    let mut bound = Wallet::create_for_domain(d.id()).unwrap();
    let mut pool = g.create_pool_bound(&dir.0.join("bound-pool"), &d).unwrap();
    bound
        .sync(&g.wallet_history_bound(&mut pool, &d).unwrap())
        .unwrap();
    let before = (bound.height(), bound.balance(), bound.pending_id());
    assert!(matches!(
        bound.build_payment(recipient, 1, 1, 20, &legacy_prover),
        Err(WalletError::Proof)
    ));
    assert_eq!(
        (bound.height(), bound.balance(), bound.pending_id()),
        before
    );
}

#[test]
fn frozen_rule_constants_match_implemented_limits() {
    use zevune_orchard_lab::pool::{MAX_BLOCK_TRANSACTIONS, MAX_COMMITMENTS, MAX_RECORDS};
    use zevune_orchard_lab::{MAX_ACTIONS, MAX_ANCHORS, VERSION};
    assert_eq!(MAX_ACTIONS, 8);
    assert_eq!(MAX_ANCHORS, 64);
    assert_eq!(VERSION.default_flags().to_byte(VERSION), Some(3));
    assert_eq!(MAX_BLOCK_TRANSACTIONS, 16);
    assert_eq!(MAX_COMMITMENTS, 65_536);
    assert_eq!(MAX_RECORDS, 10_000);
    assert_eq!(TEST_SUPPLY, 100_000);
    assert_eq!(wire::MAX_ENVELOPE_SIZE, 28_102);
    assert_eq!(wire::MAX_BOUND_ENVELOPE_SIZE, 28_134);
}
