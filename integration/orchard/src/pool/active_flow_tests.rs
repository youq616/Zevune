//! State and wallet integration through the ordinary active-store entry points.
//! No height edits, accepting verifier, synthetic record execution or reduced
//! segment capacity stands in for the 10000-record and 1 MiB growth checks.
use super::*;
use crate::pool::root_cache_tests::assert_state;
use crate::pool::testnet::{TestGenesis, TEST_SUPPLY};
use crate::wallet::{Wallet, WalletError, WalletProver};
use rand::{rngs::OsRng, RngCore};
use std::collections::BTreeMap;
use std::path::PathBuf;

const SEGMENT_LIMIT: usize = 1024 * 1024;
const EMPTY_FRAME_BYTES: usize = 150;
type DirectoryBytes = BTreeMap<String, Vec<u8>>;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let name: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-active-flow-{name}"));
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

fn block_id(height: u64) -> Hash {
    let mut id = [0; 32];
    id[..8].copy_from_slice(&height.to_be_bytes());
    id
}

fn commit(pool: &mut PoolStore, height: u64, txs: &[Vec<u8>]) -> Summary {
    let plan = pool.prepare(height, block_id(height), txs).unwrap();
    let predicted = plan.result().clone();
    let result = pool.commit(plan).unwrap();
    assert_eq!(result, predicted);
    assert_eq!(pool.summary().unwrap(), result);
    result
}

fn selected_commit(pool: &mut PoolStore, height: u64, txs: &[Vec<u8>]) -> Summary {
    let before = pool.active_capacity().unwrap();
    assert_eq!(assert_state(&pool.state), before.0);
    let selection = pool
        .select_proposal(height, block_id(height), selection::MAX_PROPOSAL_BYTES, txs)
        .unwrap();
    assert_eq!(selection.mask, (1u64 << txs.len()) - 1);
    let plan = pool.prepare(height, block_id(height), txs).unwrap();
    assert_eq!(plan.result(), &selection.result);
    assert_eq!(pool.active_capacity().unwrap(), before);
    let committed = pool.commit(plan).unwrap();
    assert_eq!(committed, selection.result);
    assert_eq!(pool.summary().unwrap(), committed);
    assert_eq!(assert_state(&pool.state), committed);
    committed
}

// Read external handles only after dropping the store. In particular, Windows
// exclusive locks must not turn an intended data check into a lock-error test.
fn directory_bytes(path: &Path) -> DirectoryBytes {
    fs::read_dir(path)
        .unwrap()
        .map(|entry| {
            let entry = entry.unwrap();
            assert!(entry.file_type().unwrap().is_file());
            (
                entry.file_name().into_string().unwrap(),
                fs::read(entry.path()).unwrap(),
            )
        })
        .collect()
}

fn write_directory(path: &Path, entries: &DirectoryBytes) {
    fs::create_dir(path).unwrap();
    for (name, bytes) in entries {
        fs::write(path.join(name), bytes).unwrap();
    }
}

fn assert_noncanonical_layouts_reject(
    dir: &Dir,
    genesis: &TestGenesis,
    original: &DirectoryBytes,
    expected: &Summary,
) {
    assert_eq!(original.len(), 2);
    let records = &original["00000000.journal"];
    let first_body = u32::from_be_bytes(records[..4].try_into().unwrap()) as usize;
    let first_frame = first_body + 36;
    assert_eq!(records.len(), first_frame + EMPTY_FRAME_BYTES);
    assert!(records.len() < SEGMENT_LIMIT);

    // These are the complete bytes of two actually committed blocks. Changing
    // only their physical split cannot be accepted as a different segment use.
    for (name, split) in [
        ("split-record-length", 2),
        ("split-payment-record", first_frame - 33),
        ("split-record-checksum", first_frame - 1),
        ("early-rotation", first_frame),
    ] {
        let mut altered = original.clone();
        altered.insert("00000000.journal".into(), records[..split].to_vec());
        altered.insert("00000001.journal".into(), records[split..].to_vec());
        let path = dir.path(name);
        write_directory(&path, &altered);
        assert!(genesis.open_pool(&path).is_err(), "accepted {name}");
        assert_eq!(directory_bytes(&path), altered);
    }

    // Relabeling only the immutable header cannot reinterpret a 03 ledger as
    // legacy even when its public commitments and signing domain are retained.
    let mut wrong_header = original.clone();
    wrong_header.get_mut("genesis").unwrap()[..8].copy_from_slice(b"ZVOPOL02");
    let path = dir.path("wrong-header-profile");
    write_directory(&path, &wrong_header);
    assert!(genesis.open_pool(&path).is_err());
    assert_eq!(directory_bytes(&path), wrong_header);

    // Keep every byte length, record field and state digest unchanged. Corrupt
    // the genuine first payment's binding signature and recompute its ordinary
    // record checksum. Rejection must come from authorization, not that checksum
    // or a noncanonical layout, and must not repair the supplied directory.
    let mut forged = original.clone();
    let bytes = forged.get_mut("00000000.journal").unwrap();
    let end = 4 + first_body;
    bytes[end - 1] ^= 1;
    let checksum = Sha256::digest(&bytes[4..end]);
    bytes[end..end + 32].copy_from_slice(&checksum);
    let path = dir.path("rehashed-invalid-authorization");
    write_directory(&path, &forged);
    assert!(matches!(
        genesis.open_pool(&path),
        Err(PoolError::Authorization)
    ));
    assert_eq!(directory_bytes(&path), forged);

    // Control: the identical unmodified bytes fully replay and authenticate the
    // wallet history, so preceding failures cannot be attributed to bad input
    // fixtures or a general inability to open copied active directories.
    let path = dir.path("unchanged-copy");
    write_directory(&path, original);
    let mut reopened = genesis.open_pool(&path).unwrap();
    assert_eq!(&reopened.summary().unwrap(), expected);
    assert_eq!(&assert_state(&reopened.state), expected);
    assert_eq!(
        genesis.wallet_history(&mut reopened).unwrap().tip(),
        expected
    );
    drop(reopened);
    assert_eq!(directory_bytes(&path), *original);
}

#[test]
fn active_profile_domain_rejections_preserve_bytes_reservations_and_legacy_contract() {
    let dir = Dir::new();
    let active_path = dir.path("active");
    let legacy_path = dir.path("legacy.journal");
    let old_path = dir.path("lab1.journal");
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let genesis =
        TestGenesis::generate_active(&[(alice.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    assert_eq!(&genesis.bytes()[..8], b"ZVTGEN03");
    assert_eq!(genesis.storage_profile(), StorageProfile::ActiveSegmentsV1);
    assert_eq!(genesis.storage_profile().max_records(), 1_000_000);
    assert_eq!(
        genesis.storage_profile().max_journal_bytes(),
        1024 * 1024 * 1024
    );
    assert_eq!(genesis.signing_domain(), Some(genesis.digest()));

    // Keep every public allocation, opening and deployment nonce identical:
    // the selected profile itself must still bind a different signature domain.
    let mut legacy_bytes = genesis.bytes().to_vec();
    legacy_bytes[..8].copy_from_slice(b"ZVTGEN02");
    let legacy = TestGenesis::decode(&legacy_bytes).unwrap();
    let mut old_bytes = legacy_bytes.clone();
    old_bytes[..8].copy_from_slice(b"ZVTGEN01");
    old_bytes.drain(50..82);
    let old = TestGenesis::decode(&old_bytes).unwrap();
    assert_eq!(legacy.storage_profile(), StorageProfile::LegacyJournal);
    assert_eq!(old.storage_profile(), StorageProfile::LegacyJournal);
    assert_eq!(legacy.storage_profile().max_records(), 10_000);
    assert_eq!(
        legacy.storage_profile().max_journal_bytes(),
        64 * 1024 * 1024
    );
    assert_eq!(legacy.signing_domain(), Some(legacy.digest()));
    assert_eq!(old.signing_domain(), None);
    let initial = genesis.initial_summary().unwrap();
    let legacy_initial = legacy.initial_summary().unwrap();
    let old_initial = old.initial_summary().unwrap();
    assert_eq!(initial.root, legacy_initial.root);
    assert_eq!(initial.root, old_initial.root);
    assert_ne!(initial.app_hash, legacy_initial.app_hash);
    assert_ne!(initial.app_hash, old_initial.app_hash);
    assert_ne!(legacy_initial.app_hash, old_initial.app_hash);

    for end in 0..genesis.bytes().len() {
        assert!(TestGenesis::decode(&genesis.bytes()[..end]).is_err());
    }
    let mut zero_nonce = genesis.bytes().to_vec();
    zero_nonce[50..82].fill(0);
    assert!(TestGenesis::decode(&zero_nonce).is_err());
    let mut trailing = genesis.bytes().to_vec();
    trailing.push(0);
    assert!(TestGenesis::decode(&trailing).is_err());

    let mut active = genesis.create_pool(&active_path).unwrap();
    let mut legacy_pool = legacy.create_pool(&legacy_path).unwrap();
    let old_pool = old.create_pool(&old_path).unwrap();
    assert_eq!(active.storage_profile(), StorageProfile::ActiveSegmentsV1);
    assert_eq!(legacy_pool.storage_profile(), StorageProfile::LegacyJournal);
    assert_eq!(active.summary().unwrap(), initial);
    assert_eq!(legacy_pool.summary().unwrap(), legacy_initial);
    assert_eq!(old_pool.summary().unwrap(), old_initial);
    for pool in [&active, &legacy_pool, &old_pool] {
        assert_state(&pool.state);
    }
    let initial_capacity = active.active_capacity().unwrap();
    assert_eq!(initial_capacity, (initial.clone(), 108, 0, 0));
    let old_plan = legacy_pool.prepare(1, block_id(1), &[]).unwrap();
    let old_receipt = legacy_pool.recovery_checkpoint().unwrap();
    assert!(legacy_pool.active_capacity().is_err());
    assert_eq!(legacy_pool.summary().unwrap(), legacy_initial);
    alice
        .sync(&genesis.wallet_history(&mut active).unwrap())
        .unwrap();
    assert_eq!(alice.balance().unwrap(), TEST_SUPPLY);
    let payment = alice
        .build_payment(
            bob.receive_address(0).unwrap(),
            25_000,
            1_000,
            10,
            &WalletProver::new(),
        )
        .unwrap();
    let raw = payment.bytes().to_vec();
    let reservation = alice.pending_id();
    assert_eq!(reservation, Some(payment.id()));
    drop(active);
    drop(legacy_pool);
    drop(old_pool);
    let original = directory_bytes(&active_path);
    let original_legacy = fs::read(&legacy_path).unwrap();
    let original_old = fs::read(&old_path).unwrap();
    assert_eq!(original.len(), 1);
    assert_eq!(&original["genesis"][..8], b"ZVOPOL03");
    assert_eq!(&original_legacy[..8], b"ZVOPOL02");
    assert_eq!(&original_old[..8], b"ZVOPOL01");
    for incompatible in [&legacy, &old] {
        assert!(incompatible.open_pool(&active_path).is_err());
        assert!(incompatible.create_pool(&active_path).is_err());
    }
    for incompatible in [&legacy_path, &old_path] {
        assert!(genesis.open_pool(incompatible).is_err());
        assert!(genesis.create_pool(incompatible).is_err());
    }
    assert!(recovery::RecoveryArchive::open(&active_path, old_receipt).is_err());
    let flat = dir.path("flattened-active-header.journal");
    fs::write(&flat, &original["genesis"]).unwrap();
    assert!(genesis.open_pool(&flat).is_err());
    assert!(legacy.open_pool(&flat).is_err());
    assert!(PoolStore::open(&flat).is_err());
    assert_eq!(directory_bytes(&active_path), original);
    assert_eq!(fs::read(&legacy_path).unwrap(), original_legacy);
    assert_eq!(fs::read(&old_path).unwrap(), original_old);

    let mut active = genesis.open_pool(&active_path).unwrap();
    let mut legacy_pool = legacy.open_pool(&legacy_path).unwrap();
    assert!(matches!(active.commit(old_plan), Err(PoolError::Stale)));
    assert!(active.recovery_checkpoint().is_err());
    assert!(active
        .check_checkpoint(old_receipt.height(), old_receipt.app_hash())
        .is_err());
    assert!(matches!(
        legacy.wallet_history(&mut active),
        Err(PoolError::Genesis)
    ));
    assert_eq!(
        alice.sync(&legacy.wallet_history(&mut legacy_pool).unwrap()),
        Err(WalletError::Rollback)
    );
    assert!(matches!(
        legacy_pool.prepare(1, block_id(1), std::slice::from_ref(&raw)),
        Err(PoolError::Domain)
    ));
    let mut relabelled = crate::wire::decode(&raw).unwrap();
    relabelled.context.signing_domain = legacy.signing_domain();
    let relabelled = crate::wire::encode(&relabelled.bundle, &relabelled.context).unwrap();
    assert!(matches!(
        legacy_pool.prepare(1, block_id(1), &[relabelled]),
        Err(PoolError::Authorization)
    ));

    let mut bad_signature = raw.clone();
    *bad_signature.last_mut().unwrap() ^= 1;
    assert!(matches!(
        active.prepare(1, block_id(1), std::slice::from_ref(&bad_signature)),
        Err(PoolError::Authorization)
    ));
    assert!(matches!(
        active.prepare(1, block_id(1), &[raw.clone(), raw.clone()]),
        Err(PoolError::DoubleSpend)
    ));
    assert!(matches!(
        active.prepare(2, block_id(2), &[]),
        Err(PoolError::Height)
    ));
    assert!(active
        .select_proposal(2, block_id(2), selection::MAX_PROPOSAL_BYTES, &[])
        .is_err());
    assert!(active
        .select_proposal(1, block_id(1), selection::MAX_PROPOSAL_BYTES + 1, &[])
        .is_err());
    let candidates = [bad_signature, raw.clone(), raw.clone()];
    let selected = active
        .select_proposal(1, block_id(1), selection::MAX_PROPOSAL_BYTES, &candidates)
        .unwrap();
    assert_eq!(selected.mask, 2);
    assert_eq!(
        active
            .prepare(1, block_id(1), std::slice::from_ref(&raw))
            .unwrap()
            .result(),
        &selected.result
    );
    assert_eq!(active.summary().unwrap(), initial);
    assert_eq!(active.active_capacity().unwrap(), initial_capacity);
    assert_eq!(legacy_pool.summary().unwrap(), legacy_initial);
    assert_eq!(alice.pending_id(), reservation);
    assert_eq!(assert_state(&active.state), initial);
    assert_eq!(assert_state(&legacy_pool.state), legacy_initial);
    assert_eq!(alice.balance().unwrap(), TEST_SUPPLY);
    assert_eq!(alice.available_balance().unwrap(), 0);
    drop(active);
    drop(legacy_pool);
    assert_eq!(directory_bytes(&active_path), original);
    assert_eq!(fs::read(&legacy_path).unwrap(), original_legacy);
    assert_eq!(fs::read(&old_path).unwrap(), original_old);

    let mut active = genesis.open_pool(&active_path).unwrap();
    assert_eq!(commit(&mut active, 1, &[raw]), selected.result);
    assert_eq!(assert_state(&active.state), selected.result);
    let expected = commit(&mut active, 2, &[]);
    assert_eq!(assert_state(&active.state), expected);
    let history = genesis.wallet_history(&mut active).unwrap();
    alice.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    assert!(alice.pending_id().is_none());
    assert_eq!(alice.balance().unwrap(), 74_000);
    assert_eq!(bob.balance().unwrap(), 25_000);
    assert_eq!(expected.fees, 1_000);
    drop(active);
    let committed_bytes = directory_bytes(&active_path);
    assert_noncanonical_layouts_reject(&dir, &genesis, &committed_bytes, &expected);
    assert_eq!(directory_bytes(&active_path), committed_bytes);
}

#[test]
fn real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002() {
    let dir = Dir::new();
    let path = dir.path("active-growth");
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let mut carol = Wallet::create().unwrap();
    let genesis =
        TestGenesis::generate_active(&[(alice.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let mut pool = genesis.create_pool(&path).unwrap();
    let start = std::time::Instant::now();

    // Every padding block goes through actual prepare, independent commit
    // execution, write and sync. Leave room for an empty frame, but not the
    // genuine nonzero payment, so that payment forces production-size rotation.
    let padding = (SEGMENT_LIMIT - 4096) / EMPTY_FRAME_BYTES;
    for height in 1..=padding as u64 {
        commit(&mut pool, height, &[]);
    }
    let before_payment = pool.active_capacity().unwrap();
    assert_eq!(before_payment.0.height, padding as u64);
    assert_eq!(before_payment.1, 108 + (padding * EMPTY_FRAME_BYTES) as u64);
    assert_eq!(before_payment.2, 1);
    assert_eq!(before_payment.3 as usize, padding * EMPTY_FRAME_BYTES);
    alice
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let prover = WalletProver::new();
    let first = alice
        .build_payment(
            bob.receive_address(0).unwrap(),
            60_000,
            1_000,
            padding as u64 + 100,
            &prover,
        )
        .unwrap()
        .bytes()
        .to_vec();
    let first_frame_bytes = EMPTY_FRAME_BYTES + 4 + first.len();
    assert!(before_payment.3 as usize + EMPTY_FRAME_BYTES <= SEGMENT_LIMIT);
    assert!(before_payment.3 as usize + first_frame_bytes > SEGMENT_LIMIT);
    assert!(first_frame_bytes <= SEGMENT_LIMIT);
    let first_height = padding as u64 + 1;
    let paid = selected_commit(&mut pool, first_height, std::slice::from_ref(&first));
    let after_payment = pool.active_capacity().unwrap();
    assert_eq!(after_payment.0, paid);
    assert_eq!(after_payment.1, before_payment.1 + first_frame_bytes as u64);
    assert_eq!(after_payment.2, 2);
    assert_eq!(after_payment.3 as usize, first_frame_bytes);
    assert!(matches!(
        pool.prepare(first_height + 1, block_id(first_height + 1), &[first]),
        Err(PoolError::DoubleSpend)
    ));
    assert_eq!(pool.active_capacity().unwrap(), after_payment);
    let paid_history = genesis.wallet_history(&mut pool).unwrap();
    alice.sync(&paid_history).unwrap();
    bob.sync(&paid_history).unwrap();
    assert_eq!(alice.balance().unwrap(), 39_000);
    assert_eq!(bob.balance().unwrap(), 60_000);
    assert!(alice.pending_id().is_none());
    drop(paid_history);

    for height in first_height + 1..=9998 {
        commit(&mut pool, height, &[]);
    }
    let at_9999 = selected_commit(&mut pool, 9999, &[]);
    assert_eq!(at_9999.height, 9999);
    let at_10000 = selected_commit(&mut pool, 10000, &[]);
    assert_eq!(at_10000.height, 10000);
    bob.sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let second = bob
        .build_payment(
            carol.receive_address(0).unwrap(),
            40_000,
            1_000,
            10020,
            &prover,
        )
        .unwrap()
        .bytes()
        .to_vec();
    let second_frame_bytes = EMPTY_FRAME_BYTES + 4 + second.len();
    // The first block beyond the legacy ceiling carries a real second-hop
    // spend, with change and a fee, and selection/prepare/commit all agree.
    let at_10001 = selected_commit(&mut pool, 10001, std::slice::from_ref(&second));
    assert_eq!(at_10001.height, 10001);
    assert_eq!(at_10001.commitments, 5);
    assert_eq!(at_10001.nullifiers, 4);
    assert_eq!(at_10001.fees, 2_000);
    let before_reopen = pool.active_capacity().unwrap();
    assert_eq!(before_reopen.2, 2);
    drop(pool);
    let persisted = directory_bytes(&path);
    assert_eq!(persisted.len(), 3);
    assert_eq!(
        persisted["00000000.journal"].len(),
        padding * EMPTY_FRAME_BYTES
    );
    assert_eq!(
        persisted["00000001.journal"].len(),
        before_reopen.3 as usize
    );
    assert_eq!(
        persisted
            .values()
            .map(|bytes| bytes.len() as u64)
            .sum::<u64>(),
        before_reopen.1
    );
    assert!(persisted["00000000.journal"].len() + first_frame_bytes > SEGMENT_LIMIT);
    assert!(persisted["00000001.journal"].len() <= SEGMENT_LIMIT);

    let mut pool = genesis.open_pool(&path).unwrap();
    assert_eq!(pool.summary().unwrap(), at_10001);
    assert_eq!(assert_state(&pool.state), at_10001);
    assert_eq!(pool.active_capacity().unwrap(), before_reopen);
    pool.check_checkpoint(at_10001.height, at_10001.app_hash)
        .unwrap();
    assert!(matches!(
        pool.prepare(10002, block_id(10002), std::slice::from_ref(&second)),
        Err(PoolError::DoubleSpend)
    ));
    let rejected = pool
        .select_proposal(
            10002,
            block_id(10002),
            selection::MAX_PROPOSAL_BYTES,
            &[second],
        )
        .unwrap();
    assert_eq!(rejected.mask, 0);
    assert_eq!(pool.active_capacity().unwrap(), before_reopen);
    let final_summary = selected_commit(&mut pool, 10002, &[]);
    assert_eq!(final_summary, rejected.result);
    assert_eq!(final_summary.height, 10002);
    let history = genesis.wallet_history(&mut pool).unwrap();
    assert_eq!(history.tip(), &final_summary);
    alice.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    assert!(bob.pending_id().is_none());
    assert_eq!(alice.balance().unwrap(), 39_000);
    assert_eq!(bob.balance().unwrap(), 19_000);
    assert_eq!(carol.balance().unwrap(), 40_000);
    assert_eq!(
        alice.balance().unwrap()
            + bob.balance().unwrap()
            + carol.balance().unwrap()
            + final_summary.fees,
        TEST_SUPPLY
    );
    let final_capacity = pool.active_capacity().unwrap();
    assert_eq!(
        final_capacity.1,
        (108 + 10_000 * EMPTY_FRAME_BYTES + first_frame_bytes + second_frame_bytes) as u64
    );
    assert_eq!(final_capacity.1, before_reopen.1 + EMPTY_FRAME_BYTES as u64);
    assert_eq!(final_capacity.2, 2);
    assert_eq!(final_capacity.3, before_reopen.3 + EMPTY_FRAME_BYTES as u32);
    println!(
        "active Rust growth: height={} logical_bytes={} segments={} elapsed_ms={}",
        final_summary.height,
        final_capacity.1,
        final_capacity.2,
        start.elapsed().as_millis()
    );
}

#[test]
fn legacy_normal_commits_stop_at_10000_without_mutating_state_or_journal() {
    let dir = Dir::new();
    let path = dir.path("legacy-record-ceiling.journal");
    let mut pool = PoolStore::create(&path).unwrap();
    assert_eq!(pool.storage_profile(), StorageProfile::LegacyJournal);
    let start = std::time::Instant::now();
    // Use the public empty-genesis legacy constructor and every ordinary
    // prepare/commit/write/sync operation. No private height assignment or
    // constructed record stream substitutes for reaching the actual ceiling.
    for height in 1..=10_000 {
        commit(&mut pool, height, &[]);
    }
    let before = pool.summary().unwrap();
    assert_eq!(before.height, 10_000);
    assert_eq!(assert_state(&pool.state), before);
    assert_eq!(before.commitments, 0);
    assert_eq!(before.nullifiers, 0);
    assert_eq!(before.fees, 0);
    // Read through the owning locked handle; opening a second read handle can
    // itself fail under Windows locking and would not test unchanged bytes.
    pool.file.rewind().unwrap();
    let mut original = Vec::new();
    pool.file.read_to_end(&mut original).unwrap();
    assert_eq!(original.len(), 44 + 10_000 * EMPTY_FRAME_BYTES);
    assert_eq!(&original[..8], b"ZVOPOL01");
    assert!(matches!(
        pool.prepare(10_001, block_id(10_001), &[]),
        Err(PoolError::Height)
    ));
    assert!(matches!(
        pool.select_proposal(10_001, block_id(10_001), selection::MAX_PROPOSAL_BYTES, &[]),
        Err(PoolError::Height)
    ));
    assert_eq!(pool.summary().unwrap(), before);
    pool.file.rewind().unwrap();
    let mut after_rejections = Vec::new();
    pool.file.read_to_end(&mut after_rejections).unwrap();
    assert_eq!(after_rejections, original);
    drop(pool);
    assert_eq!(fs::read(&path).unwrap(), original);

    let reopened = PoolStore::open(&path).unwrap();
    assert_eq!(reopened.storage_profile(), StorageProfile::LegacyJournal);
    assert_eq!(reopened.summary().unwrap(), before);
    assert_eq!(assert_state(&reopened.state), before);
    assert!(matches!(
        reopened.prepare(10_001, block_id(10_001), &[]),
        Err(PoolError::Height)
    ));
    assert!(matches!(
        reopened.select_proposal(10_001, block_id(10_001), selection::MAX_PROPOSAL_BYTES, &[]),
        Err(PoolError::Height)
    ));
    assert_eq!(reopened.summary().unwrap(), before);
    drop(reopened);
    assert_eq!(fs::read(&path).unwrap(), original);
    println!(
        "legacy Rust growth: height={} journal_bytes={} elapsed_ms={}",
        before.height,
        original.len(),
        start.elapsed().as_millis()
    );
}

#[test]
fn active_write_failures_poison_store_without_publishing_partial_state() {
    let dir = Dir::new();
    let owner = Wallet::create().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate_active(&[(owner, TEST_SUPPLY)]).unwrap();
    // These are test-only interruptions in the real append wrapper. Reopening
    // written bytes in the same running OS is not evidence about power loss.
    for point in 1..=4 {
        let path = dir.path(&format!("active-fault-{point}"));
        let mut pool = genesis.create_pool(&path).unwrap();
        let before = pool.summary().unwrap();
        let old_length = pool.length;
        let old_capacity = pool.active.as_ref().unwrap().capacity();
        let plan = pool.prepare(1, block_id(1), &[]).unwrap();
        let expected = plan.result().clone();
        let competing = pool.prepare(1, block_id(1), &[]).unwrap();
        pool.active.as_mut().unwrap().fault = point;
        assert_eq!(pool.commit(plan), Err(PoolError::Storage));
        assert_eq!(pool.summary(), Err(PoolError::Unavailable));
        assert_eq!(pool.state.summary(), before);
        assert_eq!(assert_state(&pool.state), before);
        assert_eq!(pool.length, old_length);
        assert_eq!(pool.active.as_ref().unwrap().capacity(), old_capacity);
        assert!(matches!(
            pool.prepare(1, block_id(1), &[]),
            Err(PoolError::Unavailable)
        ));
        assert!(matches!(
            pool.select_proposal(1, block_id(1), selection::MAX_PROPOSAL_BYTES, &[]),
            Err(PoolError::Unavailable)
        ));
        assert_eq!(pool.active_capacity(), Err(PoolError::Unavailable));
        assert_eq!(pool.commit(competing), Err(PoolError::Unavailable));
        drop(pool);
        let persisted = directory_bytes(&path);
        assert_eq!(persisted.len(), 2);
        let expected_frame_bytes = match point {
            1 => 0, // New segment exists but nothing has been written.
            2 => EMPTY_FRAME_BYTES / 2,
            3 | 4 => EMPTY_FRAME_BYTES,
            _ => unreachable!(),
        };
        assert_eq!(persisted["00000000.journal"].len(), expected_frame_bytes);
        if point <= 2 {
            // The empty/partial segment is retained and explicitly rejected;
            // opening must not silently remove or truncate failed writes.
            assert!(genesis.open_pool(&path).is_err());
        } else {
            // Point 3 interrupts before sync; point 4 loses acknowledgement
            // after synchronization. Both complete frames are visible to this
            // same OS and must execute full replay before returning height 1.
            let mut reopened = genesis.open_pool(&path).unwrap();
            assert_eq!(reopened.summary().unwrap(), expected);
            assert_eq!(assert_state(&reopened.state), expected);
            assert_eq!(
                reopened.active_capacity().unwrap(),
                (expected, old_length + EMPTY_FRAME_BYTES as u64, 1, 150)
            );
            drop(reopened);
        }
        assert_eq!(directory_bytes(&path), persisted);
    }
}
