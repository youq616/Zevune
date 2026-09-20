#![cfg(all(target_os = "linux", feature = "local-funding-lab"))]
//! First-payment persistence on the existing dedicated 8 MiB tmpfs harness.
//! No fault flag, mock verifier, broadcast, host-disk filling or automatic retry.
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{ErrorKind, Write};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use zeroize::Zeroizing;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::pool::PoolError;
use zevune_orchard_lab::wallet::vault::store::{StoreError, StoreReceipt, WalletStore};
use zevune_orchard_lab::wallet::{Wallet, WalletError, WalletProver};

const HEADER: usize = 72;
const RECORD: usize = 32_948;
const PAGE: u64 = 4096;
const CASE: &str = "wallet_prepare_enospc_rejects_partial_outbox_and_recovers";

fn directory(variable: &str) -> PathBuf {
    let path = PathBuf::from(std::env::var_os(variable).expect("missing harness directory"));
    assert!(path.is_absolute());
    assert!(fs::symlink_metadata(&path).unwrap().is_dir());
    assert!(path.canonicalize().unwrap() == path);
    assert!(fs::read_dir(&path).unwrap().next().is_none());
    path
}

fn hash(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn pin(receipt: StoreReceipt) -> [u8; 72] {
    let mut bytes = [0; 72];
    bytes[..32].copy_from_slice(&receipt.journal_id);
    bytes[32..40].copy_from_slice(&receipt.generation.to_be_bytes());
    bytes[40..].copy_from_slice(&receipt.digest);
    bytes
}

fn write_new(path: &Path, bytes: &[u8]) {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .unwrap();
    file.write_all(bytes).unwrap();
    file.sync_all().unwrap();
}

fn same(path: &Path, bytes: &[u8]) {
    assert!(fs::read(path).unwrap() == bytes, "retained bytes changed");
}

fn pool_bytes(path: &Path) -> BTreeMap<String, Vec<u8>> {
    let mut result = BTreeMap::new();
    for entry in fs::read_dir(path).unwrap() {
        let entry = entry.unwrap();
        let meta = fs::symlink_metadata(entry.path()).unwrap();
        assert!(meta.is_file() && meta.nlink() == 1 && meta.len() <= 1_048_576);
        assert!(result.len() < 2);
        let name = entry.file_name().into_string().unwrap();
        assert!(matches!(name.as_str(), "genesis" | "00000000.journal"));
        assert!(result
            .insert(name, fs::read(entry.path()).unwrap())
            .is_none());
    }
    result
}

fn fill(path: &Path) -> usize {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .unwrap();
    let bytes = [0xa5; 65_536];
    let mut size = 0;
    while size < 16 * 1024 * 1024 {
        match file.write(&bytes) {
            Ok(0) => panic!("filler made no progress"),
            Ok(count) => size += count,
            Err(error) if error.kind() == ErrorKind::Interrupted => continue,
            Err(error) => {
                assert_eq!(error.raw_os_error(), Some(28));
                assert!(size > PAGE as usize);
                assert_eq!(size as u64 % PAGE, 0);
                file.sync_all().unwrap();
                return size;
            }
        }
    }
    panic!("bounded filler did not reach ENOSPC");
}

#[test]
#[ignore = "requires the dedicated 8 MiB tmpfs and wallet_prepare ENOSPC trace harness"]
fn wallet_prepare_enospc_rejects_partial_outbox_and_recovers() {
    let mount = directory("ZEVUNE_ENOSPC_DIR");
    let control = directory("ZEVUNE_ENOSPC_CONTROL_DIR");
    let mounted = fs::metadata(&mount).unwrap();
    assert_eq!(mounted.blksize(), PAGE);
    assert_ne!(mounted.dev(), fs::metadata(&control).unwrap().dev());
    fs::create_dir(mount.join("source")).unwrap();
    fs::create_dir(control.join("backup")).unwrap();
    fs::create_dir(control.join("restored")).unwrap();
    let source_path = mount.join("source/wallet.journal");
    let backup_path = control.join("backup/wallet.journal");
    let restored_path = control.join("restored/wallet.journal");
    let pool_path = control.join("pool");
    let mut password = Zeroizing::new([0; 32]);
    OsRng.fill_bytes(password.as_mut());
    let mut source = WalletStore::create(&source_path, password.as_ref()).unwrap();
    let owner = source.view().unwrap().receive_address(0).unwrap();
    let mut bob = Wallet::create().unwrap();
    let genesis = TestGenesis::generate_active(&[(owner, TEST_SUPPLY)]).unwrap();
    let mut pool = genesis.create_pool(&pool_path).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    source.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    let recipient = bob.receive_recipient(0).unwrap();
    let address = bob.receive_address(0).unwrap();
    let prover = WalletProver::new();
    let saved = source.receipt().unwrap();
    assert_eq!(saved.generation, 2);
    assert!(source.pending_payment().unwrap().is_none());
    assert!(source.view().unwrap().pending_id().is_none());
    assert_eq!(
        source.view().unwrap().available_balance().unwrap(),
        TEST_SUPPLY
    );
    source
        .check_payment_to(&recipient, 60_000, 1_000, 10)
        .unwrap();
    let original = fs::read(&source_path).unwrap();
    assert_eq!(original.len(), HEADER + 2 * RECORD);
    assert_eq!(source.backup_new(&backup_path).unwrap(), saved);
    same(&backup_path, &original);
    write_new(&control.join("checkpoint.bin"), &pin(saved));
    File::open(&control).unwrap().sync_all().unwrap();
    let state = pool.summary().unwrap();
    let ledger = pool_bytes(&pool_path);
    let before = fs::metadata(&source_path).unwrap();
    assert_eq!(before.blocks() * 512, before.len().div_ceil(PAGE) * PAGE);
    let filler_bytes = fill(&mount.join("filler"));

    // The genuine proof and reservation are prepared in memory, but persistence
    // fails before the public API can return ANY signed Payment. Do not retrieve
    // internal candidate bytes, free disk space, truncate, or retry this store.
    assert_eq!(
        source
            .prepare_payment_to(&recipient, 60_000, 1_000, 10, &prover)
            .err(),
        Some(StoreError::Io)
    );
    assert_eq!(source.view().err(), Some(StoreError::Unavailable));
    assert_eq!(source.receipt().err(), Some(StoreError::Unavailable));
    assert_eq!(source.storage_status().err(), Some(StoreError::Unavailable));
    assert_eq!(
        source.pending_payment().err(),
        Some(StoreError::Unavailable)
    );
    assert_eq!(source.sync(&history), Err(StoreError::Unavailable));
    assert_eq!(
        source.check_payment_to(&recipient, 1, 1, 10),
        Err(StoreError::Unavailable)
    );
    assert_eq!(
        source.prepare_payment(address, 1, 1, 10, &prover).err(),
        Some(StoreError::Unavailable)
    );
    assert_eq!(
        source
            .prepare_payment_to(&recipient, 1, 1, 10, &prover)
            .err(),
        Some(StoreError::Unavailable)
    );
    let refused = control.join("unavailable.journal");
    assert_eq!(
        source.backup_new(&refused).err(),
        Some(StoreError::Unavailable)
    );
    assert_eq!(
        source.compact_copy_new(&refused, saved).err(),
        Some(StoreError::Unavailable)
    );
    assert!(!refused.exists());
    assert_eq!(pool.summary().unwrap(), state);
    assert!(pool_bytes(&pool_path) == ledger);
    let damaged = fs::read(&source_path).unwrap();
    let target = fs::symlink_metadata(&source_path).unwrap();
    assert!(target.is_file());
    assert_eq!(target.nlink(), 1);
    assert_eq!((target.dev(), target.ino()), (before.dev(), before.ino()));
    assert_eq!(target.dev(), mounted.dev());
    assert_eq!(target.len(), before.len().div_ceil(PAGE) * PAGE);
    assert_eq!(target.len(), damaged.len() as u64);
    assert!(damaged.starts_with(&original));
    let suffix = &damaged[original.len()..];
    assert_eq!(suffix.len(), 3664);
    assert!(suffix[..8] == 3u64.to_be_bytes());
    assert!(suffix[8..40] == saved.digest);
    drop(source);
    for expected in [None, Some(saved)] {
        assert_eq!(
            WalletStore::open(&source_path, password.as_ref(), expected).err(),
            Some(StoreError::Corrupt)
        );
        same(&source_path, &damaged);
    }
    same(&backup_path, &original);
    same(&control.join("checkpoint.bin"), &pin(saved));

    // An independently pinned PRE-ATTEMPT backup contains no signed outbox.
    // This explicit recovery is justified only for this observed partial-write,
    // no-return/no-broadcast fixture, not for a general uncertain payment result.
    let mut trusted = WalletStore::open(&backup_path, password.as_ref(), Some(saved)).unwrap();
    assert_eq!(trusted.backup_new(&restored_path).unwrap(), saved);
    drop(trusted);
    same(&restored_path, &original);
    let mut recovered = WalletStore::open(&restored_path, password.as_ref(), Some(saved)).unwrap();
    assert_eq!(
        recovered.view().unwrap().balance(),
        Err(WalletError::NotSynced)
    );
    assert_eq!(
        recovered.pending_payment().err(),
        Some(StoreError::Wallet(WalletError::NotSynced))
    );
    recovered.sync(&history).unwrap();
    assert_eq!(recovered.receipt().unwrap(), saved);
    assert!(recovered.pending_payment().unwrap().is_none());
    assert!(recovered.view().unwrap().pending_id().is_none());
    assert_eq!(
        recovered.view().unwrap().available_balance().unwrap(),
        TEST_SUPPLY
    );
    same(&restored_path, &original);
    let payment = recovered
        .prepare_payment_to(&recipient, 60_000, 1_000, 10, &prover)
        .unwrap();
    let pending = recovered.receipt().unwrap();
    assert_eq!(pending.generation, 3);
    write_new(&control.join("pending-checkpoint.bin"), &pin(pending));
    File::open(&control).unwrap().sync_all().unwrap();
    let pending_bytes = fs::read(&restored_path).unwrap();
    drop(recovered);
    let mut recovered =
        WalletStore::open(&restored_path, password.as_ref(), Some(pending)).unwrap();
    assert_eq!(
        recovered.view().unwrap().balance(),
        Err(WalletError::NotSynced)
    );
    recovered.sync(&history).unwrap();
    assert_eq!(recovered.receipt().unwrap(), pending);
    assert!(recovered.pending_payment().unwrap().unwrap().bytes() == payment.bytes());
    assert!(recovered.view().unwrap().pending_id() == Some(payment.id()));
    assert_eq!(recovered.view().unwrap().available_balance().unwrap(), 0);
    assert_eq!(
        recovered.check_payment_to(&recipient, 1, 1, 10),
        Err(StoreError::Wallet(WalletError::Pending))
    );
    same(&restored_path, &pending_bytes);

    let plan = pool
        .prepare(1, [1; 32], &[payment.bytes().to_vec()])
        .unwrap();
    let paid = pool.commit(plan).unwrap();
    assert_eq!(
        (paid.height, paid.commitments, paid.nullifiers, paid.fees),
        (1, 3, 2, 1_000)
    );
    drop(pool);
    let mut pool = genesis.open_pool(&pool_path).unwrap();
    assert_eq!(pool.summary().unwrap(), paid);
    let confirmed_ledger = pool_bytes(&pool_path);
    assert_eq!(
        pool.prepare(2, [2; 32], &[payment.bytes().to_vec()]).err(),
        Some(PoolError::DoubleSpend)
    );
    assert_eq!(pool.summary().unwrap(), paid);
    assert!(pool_bytes(&pool_path) == confirmed_ledger);
    let confirmed_history = genesis.wallet_history(&mut pool).unwrap();
    recovered.sync(&confirmed_history).unwrap();
    bob.sync(&confirmed_history).unwrap();
    assert_eq!(
        recovered.view().unwrap().available_balance().unwrap(),
        39_000
    );
    assert_eq!(bob.balance().unwrap(), 60_000);
    assert!(recovered.pending_payment().unwrap().is_none());
    assert!(recovered.view().unwrap().pending_id().is_none());
    let final_receipt = recovered.receipt().unwrap();
    assert_eq!(final_receipt.generation, 4);
    let final_bytes = fs::read(&restored_path).unwrap();
    assert_eq!(
        recovered.sync(&history),
        Err(StoreError::Wallet(WalletError::Rollback))
    );
    assert_eq!(recovered.receipt().unwrap(), final_receipt);
    same(&restored_path, &final_bytes);
    drop(recovered);
    drop(pool);
    let mut pool = genesis.open_pool(&pool_path).unwrap();
    assert_eq!(pool.summary().unwrap(), paid);
    let mut reopened =
        WalletStore::open(&restored_path, password.as_ref(), Some(final_receipt)).unwrap();
    reopened
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert_eq!(reopened.receipt().unwrap(), final_receipt);
    assert_eq!(
        reopened.view().unwrap().available_balance().unwrap(),
        39_000
    );
    assert!(reopened.pending_payment().unwrap().is_none());
    drop(reopened);
    drop(pool);
    same(&restored_path, &final_bytes);
    same(&source_path, &damaged);
    same(&backup_path, &original);
    same(&control.join("checkpoint.bin"), &pin(saved));
    same(&control.join("pending-checkpoint.bin"), &pin(pending));
    write_new(&control.join("final-checkpoint.bin"), &pin(final_receipt));
    File::open(&control).unwrap().sync_all().unwrap();

    // Only fixed booleans, lengths, encrypted-file hashes and public pin hashes.
    let receipt = format!(
        concat!(
            "{{\"schema_version\":1,\"case\":\"{CASE}\",",
            "\"profile\":\"wallet_prepare_v1\",\"filesystem\":\"tmpfs\",",
            "\"target_rel\":\"source/wallet.journal\",\"target_dev\":{dev},",
            "\"target_ino\":{ino},\"target_nlink\":1,\"before_len\":{before},",
            "\"after_len\":{after},\"frame_len\":{RECORD},\"changed_suffix_len\":3664,",
            "\"before_sha256\":\"{old_hash}\",\"after_sha256\":\"{bad_hash}\",",
            "\"receipt_generation\":2,\"pending_generation\":3,\"final_generation\":4,",
            "\"receipt_pin_sha256\":\"{old_pin}\",\"pending_pin_sha256\":\"{pending_pin}\",",
            "\"final_pin_sha256\":\"{final_pin}\",\"backup_len\":{before},",
            "\"backup_sha256\":\"{old_hash}\",\"restored_len\":{final_len},",
            "\"restored_sha256\":\"{final_hash}\",\"filler_errno\":28,\"filler_bytes\":{filler},",
            "\"wallet_io\":true,\"store_unavailable\":true,\"no_payment_returned\":true,",
            "\"pool_unchanged_on_failure\":true,\"reopen_rejected\":true,",
            "\"source_prefix_preserved\":true,\"backup_unchanged\":true,",
            "\"empty_outbox_restored\":true,\"new_pending_exact\":true,",
            "\"duplicate_rejected\":true,\"continuation_done\":true,",
            "\"retained_receipts_unchanged\":true,\"real_funds_allowed\":false}}\n"
        ),
        CASE = CASE,
        RECORD = RECORD,
        dev = target.dev(),
        ino = target.ino(),
        before = original.len(),
        after = damaged.len(),
        old_hash = hex(&hash(&original)),
        bad_hash = hex(&hash(&damaged)),
        old_pin = hex(&hash(&pin(saved))),
        pending_pin = hex(&hash(&pin(pending))),
        final_pin = hex(&hash(&pin(final_receipt))),
        final_len = final_bytes.len(),
        final_hash = hex(&hash(&final_bytes)),
        filler = filler_bytes,
    );
    assert!(receipt.len() <= 16 * 1024);
    write_new(&control.join("receipt.json"), receipt.as_bytes());
}
