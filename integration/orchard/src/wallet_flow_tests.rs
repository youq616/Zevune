//! Private funded bootstrap remains confined to unit-test code. Nothing here
//! creates an issuance API, secret-bearing CI artifact or production faucet.
use super::*;
use crate::wallet::{vault, Wallet, WalletError, WalletProver};
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, Scope};
use rand::{rngs::OsRng, RngCore};
use std::path::PathBuf;

use super::tests::fixtures;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let name: String = random.iter().map(|b| format!("{b:02x}")).collect();
        let p = std::env::temp_dir().join(format!("zevune-wallet-test-{name}"));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn commit(pool: &mut PoolStore, height: u64, txs: &[Vec<u8>]) -> Summary {
    let mut id = [0; 32];
    id[..8].copy_from_slice(&height.to_be_bytes());
    let plan = pool.prepare(height, id, txs).unwrap();
    pool.commit(plan).unwrap()
}

#[test]
fn wallet_nonzero_multinote_payment_change_expiry_backup_and_rescan() {
    let dir = Dir::new();
    let path = dir.path("pool.journal");
    let mut password = zeroize::Zeroizing::new([0; 32]);
    OsRng.fill_bytes(password.as_mut());
    let issuer = fixtures::key();
    let ifvk = FullViewingKey::from(&issuer);
    let initial = fixtures::genesis_note(ifvk.address_at(0u32, Scope::External));
    let cm = ExtractedNoteCommitment::from(initial.commitment());
    let initial_cms = [cm.to_bytes()];
    let mut pool = PoolStore::create_with_genesis(&path, &initial_cms).unwrap();
    let origin = pool.wallet_history().unwrap();
    let mut bob = Wallet::create().unwrap();
    let mut carol = Wallet::create().unwrap();
    let mut dave = Wallet::create().unwrap();
    for w in [&mut bob, &mut carol, &mut dave] {
        w.sync(&origin).unwrap();
        assert_eq!(w.balance().unwrap(), 0);
    }
    let pk = ProvingKey::build(crate::CIRCUIT);
    let (witness, _) = fixtures::witness(&[MerkleHashOrchard::from_cmx(&cm)], 0);
    // Two independently encrypted incoming notes, at two derived receive addresses.
    let funding = fixtures::prove(
        &pk,
        &issuer,
        initial,
        witness,
        &[
            (bob.receive_address(0).unwrap(), 30_000),
            (bob.receive_address(1).unwrap(), 30_000),
            (ifvk.address_at(0u32, Scope::External), 39_000),
        ],
        &fixtures::context(),
    );
    let funding_raw = crate::wire::encode(&funding, &fixtures::context()).unwrap();
    let first = commit(&mut pool, 1, &[funding_raw]);
    let h1 = pool.wallet_history().unwrap();
    assert_eq!(h1.tip(), &first);
    assert_eq!(pool.summary().unwrap(), first);
    bob.sync(&h1).unwrap();
    carol.sync(&h1).unwrap();
    assert_eq!(bob.balance().unwrap(), 60_000);
    assert_eq!(carol.balance().unwrap(), 0);
    let prover = WalletProver::new();
    assert!(matches!(
        bob.build_payment(
            carol.receive_address(0).unwrap(),
            60_000,
            1_000,
            20,
            &prover
        ),
        Err(WalletError::InsufficientFunds)
    ));
    assert!(bob.pending_id().is_none());
    assert!(matches!(
        bob.build_payment(carol.receive_address(0).unwrap(), 1, 0, 20, &prover),
        Err(WalletError::Bounds)
    ));
    let pay = bob
        .build_payment(
            carol.receive_address(0).unwrap(),
            50_000,
            1_000,
            20,
            &prover,
        )
        .unwrap();
    assert_eq!(bob.available_balance().unwrap(), 0);
    assert_eq!(bob.balance().unwrap(), 60_000);
    assert_eq!(bob.pending_id(), Some(pay.id()));
    let pending_file = dir.path("bob-pending.vault");
    vault::write_new(&pending_file, &bob, password.as_ref()).unwrap();
    let encrypted = fs::read(&pending_file).unwrap();
    assert_eq!(encrypted.len(), vault::SEALED_BYTES);
    assert!(vault::write_new(&pending_file, &bob, password.as_ref()).is_err());
    assert_eq!(fs::read(&pending_file).unwrap(), encrypted);
    drop(bob);
    let mut bob = vault::read(&pending_file, password.as_ref()).unwrap();
    assert_eq!(bob.balance(), Err(WalletError::NotSynced));
    bob.sync(&h1).unwrap();
    assert_eq!(bob.pending_id(), Some(pay.id()));
    assert_eq!(bob.available_balance().unwrap(), 0);
    assert!(matches!(
        bob.build_payment(carol.receive_address(0).unwrap(), 1, 1_000, 20, &prover),
        Err(WalletError::Pending)
    ));
    let mut broken = pay.bytes().to_vec();
    *broken.last_mut().unwrap() ^= 1;
    assert!(pool
        .prepare(2, [7; 32], &[pay.bytes().to_vec(), broken])
        .is_err());
    assert_eq!(pool.summary().unwrap(), first);
    commit(&mut pool, 2, &[pay.bytes().to_vec()]);
    let h2 = pool.wallet_history().unwrap();
    bob.sync(&h2).unwrap();
    carol.sync(&h2).unwrap();
    assert!(bob.pending_id().is_none());
    assert_eq!(bob.balance().unwrap(), 9_000); // Internal-scope change is found.
    assert_eq!(carol.balance().unwrap(), 50_000);
    // A backed-up checkpoint cannot silently accept an older local ledger.
    let sealed = vault::seal(&carol, password.as_ref()).unwrap();
    let mut recovered_carol = vault::open(&sealed, password.as_ref()).unwrap();
    assert_eq!(recovered_carol.sync(&h1), Err(WalletError::Rollback));
    assert_eq!(recovered_carol.balance(), Err(WalletError::NotSynced));
    recovered_carol.sync(&h2).unwrap();
    assert_eq!(recovered_carol.balance().unwrap(), 50_000);
    let expires = recovered_carol
        .build_payment(dave.receive_address(0).unwrap(), 40_000, 1_000, 3, &prover)
        .unwrap();
    commit(&mut pool, 3, &[]);
    recovered_carol
        .sync(&pool.wallet_history().unwrap())
        .unwrap();
    assert_eq!(recovered_carol.pending_id(), Some(expires.id()));
    // Expiry is inclusive: a pending snapshot at exactly its expiry is valid.
    let sealed = vault::seal(&recovered_carol, password.as_ref()).unwrap();
    recovered_carol = vault::open(&sealed, password.as_ref()).unwrap();
    recovered_carol
        .sync(&pool.wallet_history().unwrap())
        .unwrap();
    assert_eq!(recovered_carol.available_balance().unwrap(), 0);
    commit(&mut pool, 4, &[]);
    recovered_carol
        .sync(&pool.wallet_history().unwrap())
        .unwrap();
    assert!(recovered_carol.pending_id().is_none());
    assert_eq!(recovered_carol.available_balance().unwrap(), 50_000);
    assert!(matches!(
        pool.prepare(5, [5; 32], &[expires.bytes().to_vec()]),
        Err(PoolError::Expired)
    ));
    let onward = recovered_carol
        .build_payment(dave.receive_address(0).unwrap(), 40_000, 1_000, 20, &prover)
        .unwrap();
    let end = commit(&mut pool, 5, &[onward.bytes().to_vec()]);
    let full = pool.wallet_history().unwrap();
    bob.sync(&full).unwrap();
    recovered_carol.sync(&full).unwrap();
    dave.sync(&full).unwrap();
    assert_eq!(
        (
            bob.balance().unwrap(),
            recovered_carol.balance().unwrap(),
            dave.balance().unwrap(),
            end.fees
        ),
        (9_000, 9_000, 40_000, 3_000)
    );
    assert_eq!(
        39_000
            + bob.balance().unwrap()
            + recovered_carol.balance().unwrap()
            + dave.balance().unwrap()
            + end.fees,
        100_000
    );
    let file = dir.path("dave.vault");
    vault::write_new(&file, &dave, password.as_ref()).unwrap();
    drop(dave);
    drop(pool);
    let mut pool = PoolStore::open_with_genesis(&path, &initial_cms).unwrap();
    assert_eq!(pool.summary().unwrap(), end);
    let mut dave = vault::read(&file, password.as_ref()).unwrap();
    dave.sync(&pool.wallet_history().unwrap()).unwrap();
    assert_eq!(dave.balance().unwrap(), 40_000);
    assert_eq!(dave.sync(&h2), Err(WalletError::Rollback));
    assert_eq!(dave.balance().unwrap(), 40_000);
    assert!(matches!(
        pool.prepare(6, [6; 32], &[onward.bytes().to_vec()]),
        Err(PoolError::DoubleSpend)
    ));
    drop(pool);
    assert!(matches!(PoolStore::open(&path), Err(PoolError::Genesis)));
}

#[test]
fn wallet_rejects_changed_checkpoint_ancestry_without_mutation() {
    let dir = Dir::new();
    let mut a = PoolStore::create(&dir.path("a")).unwrap();
    let mut b = PoolStore::create(&dir.path("b")).unwrap();
    commit(&mut a, 1, &[]);
    let other = b.prepare(1, [9; 32], &[]).unwrap();
    b.commit(other).unwrap();
    commit(&mut b, 2, &[]);
    let mut wallet = Wallet::create().unwrap();
    wallet.sync(&a.wallet_history().unwrap()).unwrap();
    let sealed = vault::seal(&wallet, b"synthetic-local-test-password").unwrap();
    let mut restored = vault::open(&sealed, b"synthetic-local-test-password").unwrap();
    assert_eq!(
        restored.sync(&b.wallet_history().unwrap()),
        Err(WalletError::Rollback)
    );
    assert_eq!(
        wallet.sync(&b.wallet_history().unwrap()),
        Err(WalletError::Rollback)
    );
    assert_eq!(wallet.height(), Some(1));
    assert_eq!(wallet.balance().unwrap(), 0);
}

#[test]
fn wallet_history_replay_keeps_append_cursor_and_rejects_disk_drift() {
    let dir = Dir::new();
    let mut pool = PoolStore::create(&dir.path("p")).unwrap();
    for height in 1..4 {
        let before = pool.wallet_history().unwrap();
        assert_eq!(before.tip().height, height - 1);
        commit(&mut pool, height, &[]);
    }
    assert_eq!(pool.wallet_history().unwrap().tip().height, 3);
    // A same-handle fault injection works under Windows exclusive file locks.
    pool.file.write_all(&[0]).unwrap();
    assert!(matches!(pool.wallet_history(), Err(PoolError::Corrupt)));
    assert!(matches!(pool.summary(), Err(PoolError::Unavailable)));
}

#[test]
fn durable_wallet_outbox_resumes_exact_real_payment_after_lost_acknowledgement() {
    use crate::wallet::vault::store::{StoreError, WalletStore};
    let dir = Dir::new();
    let path = dir.path("durable.zwallet");
    let backup = dir.path("pending-copy.zwallet");
    let mut password = zeroize::Zeroizing::new([0; 32]);
    OsRng.fill_bytes(password.as_mut());
    let mut bob = WalletStore::create(&path, password.as_ref()).unwrap();
    let mut carol = Wallet::create().unwrap();
    let destination = carol.receive_address(0).unwrap();
    let issuer = fixtures::key();
    let ifvk = FullViewingKey::from(&issuer);
    let initial = fixtures::genesis_note(ifvk.address_at(0u32, Scope::External));
    let cm = ExtractedNoteCommitment::from(initial.commitment());
    let mut pool = PoolStore::create_with_genesis(&dir.path("funded.journal"), &[cm.to_bytes()])
        .unwrap();
    let pk = ProvingKey::build(crate::CIRCUIT);
    let (witness, _) = fixtures::witness(&[MerkleHashOrchard::from_cmx(&cm)], 0);
    let funding = fixtures::prove(
        &pk,
        &issuer,
        initial,
        witness,
        &[
            (bob.view().unwrap().receive_address(0).unwrap(), 60_000),
            (ifvk.address_at(0u32, Scope::External), 39_000),
        ],
        &fixtures::context(),
    );
    let raw = crate::wire::encode(&funding, &fixtures::context()).unwrap();
    commit(&mut pool, 1, &[raw]);
    let h1 = pool.wallet_history().unwrap();
    bob.sync(&h1).unwrap();
    let prover = WalletProver::new();
    let payment = bob.prepare_payment(destination, 50_000, 1_000, 20, &prover).unwrap();
    let receipt = bob.receipt().unwrap();
    assert_eq!(bob.view().unwrap().available_balance().unwrap(), 0);
    bob.backup_new(&backup).unwrap();
    drop(bob);
    // Recover the backup, not an in-memory copy. Its outbox is still encrypted.
    let mut bob = WalletStore::open(&backup, password.as_ref(), Some(receipt)).unwrap();
    assert!(matches!(
        bob.pending_payment(),
        Err(StoreError::Wallet(WalletError::NotSynced))
    ));
    bob.sync(&h1).unwrap();
    let resumed = bob.pending_payment().unwrap().unwrap();
    assert_eq!(resumed.id(), payment.id());
    assert_eq!(resumed.bytes(), payment.bytes());
    assert!(matches!(
        bob.prepare_payment(destination, 1, 1_000, 20, &prover),
        Err(StoreError::Wallet(WalletError::Pending))
    ));
    commit(&mut pool, 2, &[resumed.bytes().to_vec()]);
    let h2 = pool.wallet_history().unwrap();
    bob.sync(&h2).unwrap();
    carol.sync(&h2).unwrap();
    assert!(bob.pending_payment().unwrap().is_none());
    assert_eq!(bob.view().unwrap().balance().unwrap(), 9_000);
    assert_eq!(carol.balance().unwrap(), 50_000);
    let before = bob.receipt().unwrap();
    bob.lose_next_sync_acknowledgement_for_test();
    // A genuine proof is made, but NO Payment value is returned to the caller.
    assert!(matches!(
        bob.prepare_payment(destination, 4_000, 1_000, 20, &prover),
        Err(StoreError::Io)
    ));
    assert!(matches!(bob.pending_payment(), Err(StoreError::Unavailable)));
    drop(bob);
    let mut bob = WalletStore::open(&backup, password.as_ref(), Some(before)).unwrap();
    bob.sync(&h2).unwrap();
    let recovered = bob.pending_payment().unwrap().unwrap();
    let end = commit(&mut pool, 3, &[recovered.bytes().to_vec()]);
    let h3 = pool.wallet_history().unwrap();
    bob.sync(&h3).unwrap();
    carol.sync(&h3).unwrap();
    assert_eq!(bob.view().unwrap().balance().unwrap(), 4_000);
    assert_eq!(carol.balance().unwrap(), 54_000);
    assert_eq!(end.fees, 3_000);
    assert!(bob.pending_payment().unwrap().is_none());
    assert_eq!(39_000 + 4_000 + 54_000 + end.fees, 100_000);
    assert!(matches!(
        pool.prepare(4, [4; 32], &[recovered.bytes().to_vec()]),
        Err(PoolError::DoubleSpend)
    ));
}
