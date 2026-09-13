//! Real encrypted temporary files only; no production fault-injection switches.
use super::*;
use std::path::PathBuf;

const PASSWORD: &[u8] = b"synthetic-compaction-tests-only";
struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let path =
            std::env::temp_dir().join(format!("zevune-compact-{:032x}", rand::random::<u128>()));
        fs::create_dir(&path).unwrap();
        Self(path)
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
fn read_owned(store: &mut WalletStore) -> Vec<u8> {
    let pos = store.file.stream_position().unwrap();
    store.file.seek(SeekFrom::Start(0)).unwrap();
    let mut raw = Vec::new();
    store.file.read_to_end(&mut raw).unwrap();
    store.file.seek(SeekFrom::Start(pos)).unwrap();
    raw
}

#[test]
fn compacted_checkpoint_is_authenticated_but_requires_rescan_and_new_receipt() {
    let dir = Dir::new();
    let original = dir.path("source");
    let target = dir.path("target");
    let mut source = WalletStore::create(&original, PASSWORD).unwrap();
    let address = source.view().unwrap().receive_address(11).unwrap();
    let mut pool = crate::pool::PoolStore::create(&dir.path("pool")).unwrap();
    source.sync(&pool.wallet_history().unwrap()).unwrap();
    let expected = source.receipt().unwrap();
    let before = read_owned(&mut source);
    let (mut copy, bridge) = source.compact_copy_new(&target, expected).unwrap();
    assert_eq!(bridge.source, expected);
    assert_ne!(bridge.source.journal_id, bridge.target.journal_id);
    assert_eq!(bridge.target.generation, 1);
    assert_eq!(copy.receipt().unwrap(), bridge.target);
    assert_eq!(copy.storage_status().unwrap().records_remaining, 255);
    assert_eq!(source.receipt(), Err(StoreError::Unavailable));
    assert!(matches!(source.view(), Err(StoreError::Unavailable)));
    assert_eq!(read_owned(&mut source), before);
    assert_eq!(copy.view().unwrap().balance(), Err(WalletError::NotSynced));
    assert_eq!(copy.view().unwrap().receive_address(11).unwrap(), address);
    assert!(matches!(
        WalletStore::open(&target, PASSWORD, None),
        Err(StoreError::Locked)
    ));
    copy.sync(&pool.wallet_history().unwrap()).unwrap();
    assert_eq!(copy.receipt().unwrap(), bridge.target); // unchanged rescan needs no record
    drop(copy);
    assert!(matches!(
        WalletStore::open(&target, PASSWORD, Some(expected)),
        Err(StoreError::Rollback)
    ));
    let mut copy = WalletStore::open(&target, PASSWORD, Some(bridge.target)).unwrap();
    let plan = pool.prepare(1, [7; 32], &[]).unwrap();
    pool.commit(plan).unwrap();
    copy.sync(&pool.wallet_history().unwrap()).unwrap();
    assert_eq!(copy.receipt().unwrap().generation, 2);
    assert_eq!(copy.view().unwrap().height(), Some(1));
    drop(source);
    assert_eq!(fs::read(&original).unwrap(), before);
    // Old backup keys cannot be remotely revoked. Do not claim cross-copy locks.
    assert!(WalletStore::open(&original, PASSWORD, Some(expected)).is_ok());
}

#[test]
fn compaction_requires_exact_current_pin_and_never_overwrites_targets() {
    let dir = Dir::new();
    let path = dir.path("source");
    let mut source = WalletStore::create(&path, PASSWORD).unwrap();
    let ancestor = source.receipt().unwrap();
    let mut pool = crate::pool::PoolStore::create(&dir.path("pool")).unwrap();
    source.sync(&pool.wallet_history().unwrap()).unwrap();
    let current = source.receipt().unwrap();
    let before = read_owned(&mut source);
    let target = dir.path("target");
    let mut wrong = current;
    wrong.digest[0] ^= 1;
    for pin in [ancestor, wrong] {
        assert!(matches!(
            source.compact_copy_new(&target, pin),
            Err(StoreError::Rollback)
        ));
        assert!(!target.exists());
    }
    fs::write(&target, b"keep-existing-file").unwrap();
    for destination in [&path, &target, &dir.0, &dir.path("absent/child")] {
        assert!(source.compact_copy_new(destination, current).is_err());
        assert_eq!(source.receipt().unwrap(), current);
        assert_eq!(read_owned(&mut source), before);
    }
    assert_eq!(fs::read(&target).unwrap(), b"keep-existing-file");
}

#[test]
fn partial_and_lost_ack_compaction_preserve_source_and_do_not_repair_targets() {
    let dir = Dir::new();
    for fault in [3, 4] {
        let path = dir.path(&format!("source-{fault}"));
        let target = dir.path(&format!("copy-{fault}"));
        let mut source = WalletStore::create(&path, PASSWORD).unwrap();
        let expected = source.receipt().unwrap();
        let before = read_owned(&mut source);
        source.fault = fault;
        assert!(matches!(
            source.compact_copy_new(&target, expected),
            Err(StoreError::Io)
        ));
        assert_eq!(source.receipt().unwrap(), expected);
        assert_eq!(read_owned(&mut source), before);
        let written = fs::read(&target).unwrap();
        assert!(source.compact_copy_new(&target, expected).is_err());
        assert_eq!(fs::read(&target).unwrap(), written);
        if fault == 3 {
            assert!(WalletStore::open(&target, PASSWORD, None).is_err());
        } else {
            // A failed acknowledgement can leave a valid copy. Do not assume
            // no file exists, silently retry, or enable simultaneous spending.
            let copy = WalletStore::open(&target, PASSWORD, None).unwrap();
            assert_eq!(
                payload(&copy.wallet, copy.outbox.as_deref()).unwrap()[..],
                payload(&source.wallet, source.outbox.as_deref()).unwrap()[..]
            );
            assert_eq!(copy.view().unwrap().balance(), Err(WalletError::NotSynced));
        }
    }
}

#[test]
fn corrupt_or_poisoned_source_cannot_be_compacted_into_a_fresh_looking_copy() {
    let dir = Dir::new();
    let mut source = WalletStore::create(&dir.path("source"), PASSWORD).unwrap();
    let pin = source.receipt().unwrap();
    source.file.seek(SeekFrom::Start(0)).unwrap();
    source.file.write_all(b"BADMAGIC").unwrap();
    let target = dir.path("target");
    assert!(matches!(
        source.compact_copy_new(&target, pin),
        Err(StoreError::Corrupt)
    ));
    assert!(!target.exists());
    assert!(matches!(
        source.compact_copy_new(&target, pin),
        Err(StoreError::Unavailable)
    ));
}

#[cfg(feature = "local-funding-lab")]
#[test]
fn full_journal_compacts_exact_real_outbox_and_continues_after_confirmation() {
    use crate::pool::testnet::{TestGenesis, TEST_SUPPLY};
    use crate::wallet::address::Recipient;

    let dir = Dir::new();
    let path = dir.path("full-wallet");
    let target = dir.path("compacted-wallet");
    let mut source = WalletStore::create(&path, PASSWORD).unwrap();
    let owner = source.view().unwrap().receive_address(0).unwrap();
    let recipient_owner = Wallet::create().unwrap();
    let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    let mut pool = genesis.create_pool(&dir.path("pool")).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    source.sync(&history).unwrap();
    let recipient = Recipient::new(
        recipient_owner.receive_address(0).unwrap(),
        genesis.signing_domain(),
    )
    .unwrap();
    let prover = WalletProver::new();
    let payment = source
        .prepare_payment_to(&recipient, 20_000, 1_000, 10, &prover)
        .unwrap();
    // These are real encrypted/synchronized snapshots, not simulated counters
    // and not 256 network transfers. The original capacity test is retained.
    while source.receipt().unwrap().generation < MAX_RECORDS {
        source.persist().unwrap();
    }
    let old_pin = source.receipt().unwrap();
    let source_bytes = read_owned(&mut source);
    assert_eq!(source_bytes.len() as u64, MAX_FILE_BYTES);
    drop(source);
    let mut source = WalletStore::open(&path, PASSWORD, Some(old_pin)).unwrap();
    assert_eq!(
        source.view().unwrap().balance(),
        Err(WalletError::NotSynced)
    );
    let (mut copy, bridge) = source.compact_copy_new(&target, old_pin).unwrap();
    assert_eq!(bridge.source, old_pin);
    assert_eq!(copy.storage_status().unwrap().records_remaining, 255);
    assert_eq!(copy.view().unwrap().balance(), Err(WalletError::NotSynced));
    let foreign = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
    let mut foreign_pool = foreign.create_pool(&dir.path("foreign-pool")).unwrap();
    let before = read_owned(&mut copy);
    assert_eq!(
        copy.sync(&foreign.wallet_history(&mut foreign_pool).unwrap()),
        Err(StoreError::Wallet(WalletError::History))
    );
    assert_eq!(copy.receipt().unwrap(), bridge.target);
    assert_eq!(read_owned(&mut copy), before);
    copy.sync(&history).unwrap();
    assert_eq!(
        copy.pending_payment().unwrap().unwrap().bytes(),
        payment.bytes()
    );
    assert_eq!(copy.receipt().unwrap(), bridge.target);
    let plan = pool
        .prepare(1, [0x73; 32], &[payment.bytes().to_vec()])
        .unwrap();
    pool.commit(plan).unwrap();
    copy.sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert!(copy.pending_payment().unwrap().is_none());
    assert_eq!(copy.view().unwrap().available_balance().unwrap(), 79_000);
    let second = copy
        .prepare_payment_to(&recipient, 5_000, 1_000, 10, &prover)
        .unwrap();
    let plan = pool
        .prepare(2, [0x74; 32], &[second.bytes().to_vec()])
        .unwrap();
    pool.commit(plan).unwrap();
    copy.sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert_eq!(copy.view().unwrap().available_balance().unwrap(), 73_000);
    assert!(pool
        .prepare(3, [0x75; 32], &[payment.bytes().to_vec()])
        .is_err());
    assert!(pool
        .prepare(3, [0x76; 32], &[second.bytes().to_vec()])
        .is_err());
    let latest = copy.receipt().unwrap();
    drop(copy);
    drop(source);
    assert_eq!(fs::read(&path).unwrap(), source_bytes);
    let mut reopened = WalletStore::open(&target, PASSWORD, Some(latest)).unwrap();
    reopened
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert_eq!(
        reopened.view().unwrap().available_balance().unwrap(),
        73_000
    );
}
