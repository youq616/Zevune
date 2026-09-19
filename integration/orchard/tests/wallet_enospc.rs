#![cfg(all(target_os = "linux", feature = "local-funding-lab"))]
//! Public encrypted-wallet operations on a dedicated, bounded Linux tmpfs.
//! The harness must observe ENOSPC on the named wallet write using a buffer-safe
//! syscall trace. This is a running-kernel test, not physical disk or power loss.
use orchard::Address;
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File, Metadata, OpenOptions};
use std::io::{ErrorKind, Write};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use zeroize::Zeroizing;
use zevune_orchard_lab::pool::history::WalletHistory;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::pool::{PoolError, PoolStore, Summary};
use zevune_orchard_lab::wallet::address::Recipient;
use zevune_orchard_lab::wallet::vault::store::{StoreError, StoreReceipt, WalletStore};
use zevune_orchard_lab::wallet::{Wallet, WalletError, WalletProver};

const PAGE_BYTES: u64 = 4096;
const FILE_HEADER: usize = 72;
const RECORD_BYTES: usize = 32_948;
const RECORD_PREFIX: usize = 40;
const FILLER_LIMIT: usize = 16 * 1024 * 1024;
type DirectoryBytes = BTreeMap<String, Vec<u8>>;

#[derive(Clone, Copy)]
enum Case {
    Sync,
    Compact,
}
impl Case {
    fn name(self) -> &'static str {
        match self {
            Self::Sync => "wallet_sync_enospc_preserves_outbox_and_recovers",
            Self::Compact => "wallet_compact_enospc_preserves_source_and_recovers",
        }
    }

    fn target(self) -> &'static str {
        match self {
            Self::Sync => "source/wallet.journal",
            Self::Compact => "compacted/wallet.journal",
        }
    }
}

struct Environment {
    mount: PathBuf,
    control: PathBuf,
}
impl Environment {
    fn required() -> Self {
        fn directory(variable: &str) -> PathBuf {
            let path = std::env::var_os(variable).expect("missing ENOSPC environment");
            let path = PathBuf::from(path);
            assert!(path.is_absolute(), "ENOSPC directory must be absolute");
            assert!(fs::symlink_metadata(&path).unwrap().is_dir());
            assert!(fs::canonicalize(&path).unwrap() == path);
            path
        }
        let mount = directory("ZEVUNE_ENOSPC_DIR");
        let control = directory("ZEVUNE_ENOSPC_CONTROL_DIR");
        let mounted = fs::metadata(&mount).unwrap();
        assert_eq!(mounted.blksize(), PAGE_BYTES);
        assert_ne!(mounted.dev(), fs::metadata(&control).unwrap().dev());
        assert!(fs::read_dir(&mount).unwrap().next().is_none());
        for name in [
            "genesis.bin",
            "pool",
            "source",
            "checkpoint.bin",
            "recovered-checkpoint.bin",
            "backup",
            "restored",
            "receipt.json",
        ] {
            assert!(!control.join(name).exists(), "ENOSPC output already exists");
        }
        Self { mount, control }
    }
}

fn digest(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

// Public receipt fields only. The encrypted backup is independently bound to
// this exact tip before a fault; an authenticated older prefix is insufficient.
fn pin_bytes(receipt: StoreReceipt) -> [u8; 72] {
    let mut bytes = [0; 72];
    bytes[..32].copy_from_slice(&receipt.journal_id);
    bytes[32..40].copy_from_slice(&receipt.generation.to_be_bytes());
    bytes[40..].copy_from_slice(&receipt.digest);
    bytes
}

fn read_pin(path: &Path) -> StoreReceipt {
    let bytes = fs::read(path).unwrap();
    assert_eq!(bytes.len(), 72);
    StoreReceipt {
        journal_id: bytes[..32].try_into().unwrap(),
        generation: u64::from_be_bytes(bytes[32..40].try_into().unwrap()),
        digest: bytes[40..].try_into().unwrap(),
    }
}

fn write_new(path: &Path, bytes: &[u8]) {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap();
    file.write_all(bytes).unwrap();
    file.sync_all().unwrap();
}

fn unchanged(path: &Path, expected: &[u8]) {
    assert!(
        fs::read(path).unwrap() == expected,
        "encrypted file changed"
    );
}

fn pool_bytes(path: &Path) -> DirectoryBytes {
    let mut files = BTreeMap::new();
    for entry in fs::read_dir(path).unwrap() {
        let entry = entry.unwrap();
        let metadata = fs::symlink_metadata(entry.path()).unwrap();
        assert!(metadata.is_file());
        assert_eq!(metadata.nlink(), 1);
        assert!(metadata.len() <= 1024 * 1024);
        assert!(files.len() < 2);
        let name = entry.file_name().into_string().unwrap();
        assert!(matches!(name.as_str(), "genesis" | "00000000.journal"));
        assert!(files
            .insert(name, fs::read(entry.path()).unwrap())
            .is_none());
    }
    files
}

fn block_id(height: u64) -> [u8; 32] {
    let mut id = [1; 32];
    id[..8].copy_from_slice(&height.to_be_bytes());
    id
}

fn commit_payment(pool: &mut PoolStore, payment: &[u8]) -> Summary {
    let height = pool.summary().unwrap().height + 1;
    let prepared = pool
        .prepare(height, block_id(height), &[payment.to_vec()])
        .unwrap();
    pool.commit(prepared).unwrap()
}

fn reject_duplicates(pool: &mut PoolStore, path: &Path, payments: &[&[u8]]) {
    let before = pool.summary().unwrap();
    let bytes = pool_bytes(path);
    for payment in payments {
        assert_eq!(
            pool.prepare(
                before.height + 1,
                block_id(before.height + 1),
                &[payment.to_vec()],
            )
            .err(),
            Some(PoolError::DoubleSpend)
        );
        assert_eq!(pool.summary().unwrap(), before);
        assert!(pool_bytes(path) == bytes, "rejected block changed journal");
    }
}

fn fill_to_enospc(path: &Path, free_one_page: bool) -> usize {
    let mut filler = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap();
    let bytes = [0xa5; 64 * 1024];
    let mut written = 0;
    while written < FILLER_LIMIT {
        let take = bytes.len().min(FILLER_LIMIT - written);
        match filler.write(&bytes[..take]) {
            Ok(0) => panic!("filler write made no progress"),
            Ok(count) => written += count,
            Err(error) if error.kind() == ErrorKind::Interrupted => continue,
            Err(error) => {
                assert_eq!(
                    error.raw_os_error(),
                    Some(28),
                    "filler must reach real ENOSPC"
                );
                assert!(written > PAGE_BYTES as usize);
                assert_eq!(written as u64 % PAGE_BYTES, 0);
                if free_one_page {
                    // The new compacted file needs one page for its header and
                    // a partial record. No space is released after the fault.
                    written -= PAGE_BYTES as usize;
                    filler.set_len(written as u64).unwrap();
                }
                filler.sync_all().unwrap();
                return written;
            }
        }
    }
    panic!("ENOSPC was not reached within the bounded filler budget");
}

fn unavailable<T>(result: Result<T, StoreError>) {
    assert_eq!(result.err(), Some(StoreError::Unavailable));
}

fn assert_unavailable(
    store: &mut WalletStore,
    history: &WalletHistory,
    recipient: &Recipient,
    address: Address,
    prover: &WalletProver,
    receipt: StoreReceipt,
    control: &Path,
) {
    unavailable(store.view());
    unavailable(store.receipt());
    unavailable(store.storage_status());
    unavailable(store.sync(history));
    unavailable(store.pending_payment());
    unavailable(store.check_payment_to(recipient, 1, 1, 10));
    unavailable(store.prepare_payment(address, 1, 1, 10, prover));
    unavailable(store.prepare_payment_to(recipient, 1, 1, 10, prover));
    let backup = control.join("unavailable-backup.journal");
    let compacted = control.join("unavailable-compacted.journal");
    assert!(!backup.exists() && !compacted.exists());
    unavailable(store.backup_new(&backup));
    unavailable(store.compact_copy_new(&compacted, receipt));
    assert!(!backup.exists() && !compacted.exists());
}

fn assert_not_synced(store: &WalletStore) {
    assert_eq!(store.view().unwrap().balance(), Err(WalletError::NotSynced));
    assert_eq!(
        store.view().unwrap().available_balance(),
        Err(WalletError::NotSynced)
    );
    assert_eq!(
        store.pending_payment().err(),
        Some(StoreError::Wallet(WalletError::NotSynced))
    );
}

fn assert_pending(store: &WalletStore, receipt: StoreReceipt, payment: &[u8], id: [u8; 32]) {
    assert_eq!(store.receipt().unwrap(), receipt);
    assert_eq!(store.view().unwrap().height(), Some(0));
    assert_eq!(store.view().unwrap().balance().unwrap(), TEST_SUPPLY);
    assert_eq!(store.view().unwrap().available_balance().unwrap(), 0);
    assert!(store.view().unwrap().pending_id() == Some(id));
    let pending = store.pending_payment().unwrap().unwrap();
    assert!(pending.id() == id);
    assert!(pending.bytes() == payment, "saved outbox changed");
}

struct Receipt {
    case: Case,
    target: Metadata,
    before_len: u64,
    before_hash: Option<[u8; 32]>,
    after_hash: [u8; 32],
    suffix_len: usize,
    source_receipt: StoreReceipt,
    recovered_receipt: StoreReceipt,
    backup_len: usize,
    backup_hash: [u8; 32],
    filler_bytes: usize,
}
impl Receipt {
    fn write(&self, control: &Path) {
        let before_hash = self
            .before_hash
            .map_or_else(|| "null".to_owned(), |hash| format!("\"{}\"", hex(&hash)));
        // These fixed labels, lengths, encrypted-file hashes and public receipt
        // hashes disclose no keys, passwords, plaintext or signed payment bytes.
        let encoded = format!(
            concat!(
                "{{\"schema_version\":1,\"case\":\"{case}\",",
                "\"profile\":\"wallet_journal_v1\",\"filesystem\":\"tmpfs\",",
                "\"target_rel\":\"{target}\",\"target_dev\":{dev},",
                "\"target_ino\":{ino},\"target_nlink\":{nlink},",
                "\"before_len\":{before},\"after_len\":{after},",
                "\"frame_len\":{frame},\"changed_suffix_len\":{suffix},",
                "\"before_sha256\":{before_hash},\"after_sha256\":\"{after_hash}\",",
                "\"receipt_generation\":{generation},",
                "\"receipt_pin_sha256\":\"{pin_hash}\",",
                "\"recovered_receipt_generation\":{recovered_generation},",
                "\"recovered_receipt_pin_sha256\":\"{recovered_pin_hash}\",",
                "\"backup_len\":{backup_len},\"backup_sha256\":\"{backup_hash}\",",
                "\"filler_errno\":28,\"filler_bytes\":{filler},",
                "\"wallet_io\":true,\"store_unavailable\":{unavailable},",
                "\"source_retired_after_success\":{retired},",
                "\"reopen_rejected\":true,\"source_prefix_preserved\":true,",
                "\"backup_unchanged\":true,\"rejected_target_unchanged\":true,",
                "\"exact_pending_recovered\":true,\"continuation_done\":true,",
                "\"retained_receipt_unchanged\":true,\"new_target_receipt_verified\":true}}\n"
            ),
            case = self.case.name(),
            target = self.case.target(),
            dev = self.target.dev(),
            ino = self.target.ino(),
            nlink = self.target.nlink(),
            before = self.before_len,
            after = self.target.len(),
            frame = RECORD_BYTES,
            suffix = self.suffix_len,
            before_hash = before_hash,
            after_hash = hex(&self.after_hash),
            generation = self.source_receipt.generation,
            pin_hash = hex(&digest(&pin_bytes(self.source_receipt))),
            recovered_generation = self.recovered_receipt.generation,
            recovered_pin_hash = hex(&digest(&pin_bytes(self.recovered_receipt))),
            backup_len = self.backup_len,
            backup_hash = hex(&self.backup_hash),
            filler = self.filler_bytes,
            unavailable = matches!(self.case, Case::Sync),
            retired = matches!(self.case, Case::Compact),
        );
        write_new(&control.join("receipt.json"), encoded.as_bytes());
    }
}

fn run_case(case: Case) {
    let environment = Environment::required();
    let source_root = match case {
        Case::Sync => &environment.mount,
        Case::Compact => &environment.control,
    };
    fs::create_dir(source_root.join("source")).unwrap();
    fs::create_dir(environment.control.join("backup")).unwrap();
    fs::create_dir(environment.control.join("restored")).unwrap();
    if matches!(case, Case::Compact) {
        fs::create_dir(environment.mount.join("compacted")).unwrap();
    }
    let source_path = source_root.join("source/wallet.journal");
    let target = environment.mount.join(case.target());
    let backup = environment.control.join("backup/wallet.journal");
    let restored = environment.control.join("restored/wallet.journal");
    let checkpoint_path = environment.control.join("checkpoint.bin");
    let recovered_checkpoint_path = environment.control.join("recovered-checkpoint.bin");
    let pool_path = environment.control.join("pool");
    let mut password = Zeroizing::new([0; 32]);
    OsRng.fill_bytes(password.as_mut());
    let mut source = WalletStore::create(&source_path, password.as_ref()).unwrap();
    let owner = source.view().unwrap().receive_address(0).unwrap();
    let mut bob = Wallet::create().unwrap();
    let mut carol = Wallet::create().unwrap();
    let genesis = TestGenesis::generate_active(&[(owner, TEST_SUPPLY)]).unwrap();
    genesis
        .write_new(&environment.control.join("genesis.bin"))
        .unwrap();
    let mut pool = genesis.create_pool(&pool_path).unwrap();
    let old_history = genesis.wallet_history(&mut pool).unwrap();
    source.sync(&old_history).unwrap();
    bob.sync(&old_history).unwrap();
    carol.sync(&old_history).unwrap();
    let recipient = bob.receive_recipient(0).unwrap();
    let recipient_address = bob.receive_address(0).unwrap();
    let prover = WalletProver::new();
    let first_payment = source
        .prepare_payment_to(&recipient, 60_000, 1_000, 10, &prover)
        .unwrap();
    let first_id = first_payment.id();
    let first = first_payment.bytes().to_vec();
    let source_receipt = source.receipt().unwrap();
    assert_eq!(source_receipt.generation, 3);
    assert_pending(&source, source_receipt, &first, first_id);
    let original = fs::read(&source_path).unwrap();
    let status = source.storage_status().unwrap();
    assert_eq!(original.len(), FILE_HEADER + 3 * RECORD_BYTES);
    assert_eq!(status.file_bytes, original.len() as u64);
    assert_eq!((status.records_used, status.records_remaining), (3, 253));
    assert_eq!(source.backup_new(&backup).unwrap(), source_receipt);
    unchanged(&backup, &original);
    write_new(&checkpoint_path, &pin_bytes(source_receipt));
    File::open(&environment.control)
        .unwrap()
        .sync_all()
        .unwrap();

    // In the sync case confirmation is committed independently before the
    // wallet fails while trying to save the cleared reservation and checkpoint.
    let confirmed = if matches!(case, Case::Sync) {
        Some(commit_payment(&mut pool, &first))
    } else {
        None
    };
    drop(pool);
    let mut pool = genesis.open_pool(&pool_path).unwrap();
    if let Some(expected) = &confirmed {
        assert_eq!(&pool.summary().unwrap(), expected);
    }
    let current_history = genesis.wallet_history(&mut pool).unwrap();
    let prior_metadata = fs::symlink_metadata(&source_path).unwrap();
    if matches!(case, Case::Sync) {
        assert_eq!(
            prior_metadata.blocks() * 512,
            prior_metadata.len().div_ceil(PAGE_BYTES) * PAGE_BYTES
        );
    }
    let filler_bytes = fill_to_enospc(
        &environment.mount.join("filler"),
        matches!(case, Case::Compact),
    );
    match case {
        Case::Sync => {
            assert_eq!(source.sync(&current_history), Err(StoreError::Io));
            assert_unavailable(
                &mut source,
                &current_history,
                &recipient,
                recipient_address,
                &prover,
                source_receipt,
                &environment.control,
            );
        }
        Case::Compact => {
            assert_eq!(
                source.compact_copy_new(&target, source_receipt).err(),
                Some(StoreError::Io)
            );
            source.sync(&old_history).unwrap();
            assert_pending(&source, source_receipt, &first, first_id);
            assert_eq!(source.storage_status().unwrap(), status);
            assert_eq!(
                source.check_payment_to(&recipient, 1, 1, 10),
                Err(StoreError::Wallet(WalletError::Pending))
            );
            assert_eq!(
                source
                    .prepare_payment_to(&recipient, 1, 1, 10, &prover)
                    .err(),
                Some(StoreError::Wallet(WalletError::Pending))
            );
            unchanged(&source_path, &original);
        }
    }
    let damaged = fs::read(&target).unwrap();
    let target_metadata = fs::symlink_metadata(&target).unwrap();
    assert!(target_metadata.is_file());
    assert_eq!(target_metadata.nlink(), 1);
    assert_eq!(
        target_metadata.dev(),
        fs::metadata(&environment.mount).unwrap().dev()
    );
    assert_eq!(target_metadata.len(), damaged.len() as u64);
    let (before_len, before_hash, suffix_len) = match case {
        Case::Sync => {
            assert_eq!(prior_metadata.dev(), target_metadata.dev());
            assert_eq!(prior_metadata.ino(), target_metadata.ino());
            assert!(
                damaged.starts_with(&original),
                "saved encrypted prefix changed"
            );
            assert_eq!(
                damaged.len() as u64,
                (original.len() as u64).div_ceil(PAGE_BYTES) * PAGE_BYTES
            );
            let suffix = &damaged[original.len()..];
            assert!(suffix.len() > RECORD_PREFIX && suffix.len() < RECORD_BYTES);
            assert!(suffix[..8] == (source_receipt.generation + 1).to_be_bytes());
            assert!(suffix[8..RECORD_PREFIX] == source_receipt.digest);
            // AEAD salts/nonces are random. Only the retained prefix and the
            // documented public record prefix can be compared across attempts.
            (original.len() as u64, Some(digest(&original)), suffix.len())
        }
        Case::Compact => {
            assert_eq!(damaged.len() as u64, PAGE_BYTES);
            assert!(damaged[..8] == *b"ZVWJNL01");
            assert!(damaged[FILE_HEADER..FILE_HEADER + 8] == 1u64.to_be_bytes());
            assert!(
                damaged[FILE_HEADER + 8..FILE_HEADER + RECORD_PREFIX]
                    == digest(&damaged[..FILE_HEADER])
            );
            assert_eq!(
                source.compact_copy_new(&target, source_receipt).err(),
                Some(StoreError::Io)
            );
            unchanged(&target, &damaged);
            assert_pending(&source, source_receipt, &first, first_id);
            (0, None, damaged.len() - FILE_HEADER)
        }
    };
    unchanged(&backup, &original);

    // Release only the failed live handle. The damaged file, filler and backup
    // remain present; recovery never truncates a partial authenticated record.
    let mut source = match case {
        Case::Sync => {
            drop(source);
            None
        }
        Case::Compact => Some(source),
    };
    for expected in [None, Some(source_receipt)] {
        assert_eq!(
            WalletStore::open(&target, password.as_ref(), expected).err(),
            Some(StoreError::Corrupt)
        );
        unchanged(&target, &damaged);
    }
    let retained_receipt = read_pin(&checkpoint_path);
    assert_eq!(retained_receipt, source_receipt);
    let (mut recovered, recovered_receipt) = match case {
        Case::Sync => {
            let mut trusted =
                WalletStore::open(&backup, password.as_ref(), Some(retained_receipt)).unwrap();
            assert_eq!(trusted.receipt().unwrap(), retained_receipt);
            assert_not_synced(&trusted);
            assert_eq!(trusted.backup_new(&restored).unwrap(), retained_receipt);
            drop(trusted);
            unchanged(&restored, &original);
            let recovered =
                WalletStore::open(&restored, password.as_ref(), Some(retained_receipt)).unwrap();
            (recovered, retained_receipt)
        }
        Case::Compact => {
            let source = source.as_mut().unwrap();
            let (recovered, bridge) = source
                .compact_copy_new(&restored, retained_receipt)
                .unwrap();
            assert_eq!(bridge.source, retained_receipt);
            assert_ne!(bridge.target.journal_id, retained_receipt.journal_id);
            assert_eq!(bridge.target.generation, 1);
            assert_eq!(recovered.receipt().unwrap(), bridge.target);
            assert_unavailable(
                source,
                &old_history,
                &recipient,
                recipient_address,
                &prover,
                source_receipt,
                &environment.control,
            );
            unchanged(&source_path, &original);
            (recovered, bridge.target)
        }
    };
    assert_not_synced(&recovered);
    if matches!(case, Case::Compact) {
        // A new journal's authenticated ancestry cannot be pinned with the
        // source receipt, even when it contains the same keys and exact outbox.
        let compacted_bytes = fs::read(&restored).unwrap();
        drop(recovered);
        assert_eq!(
            WalletStore::open(&restored, password.as_ref(), Some(source_receipt)).err(),
            Some(StoreError::Rollback)
        );
        unchanged(&restored, &compacted_bytes);
        recovered =
            WalletStore::open(&restored, password.as_ref(), Some(recovered_receipt)).unwrap();
        assert_not_synced(&recovered);
        unchanged(&restored, &compacted_bytes);
    }
    write_new(&recovered_checkpoint_path, &pin_bytes(recovered_receipt));
    File::open(&environment.control)
        .unwrap()
        .sync_all()
        .unwrap();
    assert_eq!(read_pin(&recovered_checkpoint_path), recovered_receipt);
    let before_rescan = fs::read(&restored).unwrap();
    recovered.sync(&old_history).unwrap();
    assert_pending(&recovered, recovered_receipt, &first, first_id);
    unchanged(&restored, &before_rescan);

    let paid = match confirmed {
        Some(summary) => summary,
        None => commit_payment(&mut pool, &first),
    };
    assert_eq!(
        (paid.height, paid.commitments, paid.nullifiers, paid.fees),
        (1, 3, 2, 1_000)
    );
    drop(current_history);
    drop(pool);
    let mut pool = genesis.open_pool(&pool_path).unwrap();
    assert_eq!(pool.summary().unwrap(), paid);
    reject_duplicates(&mut pool, &pool_path, &[&first]);
    let confirmed_history = genesis.wallet_history(&mut pool).unwrap();
    recovered.sync(&confirmed_history).unwrap();
    bob.sync(&confirmed_history).unwrap();
    carol.sync(&confirmed_history).unwrap();
    assert!(recovered.pending_payment().unwrap().is_none());
    assert!(recovered.view().unwrap().pending_id().is_none());
    assert_eq!(recovered.view().unwrap().height(), Some(1));
    assert_eq!(
        recovered.view().unwrap().available_balance().unwrap(),
        39_000
    );
    assert_eq!(bob.balance().unwrap(), 60_000);
    assert_eq!(carol.balance().unwrap(), 0);
    let confirmed_receipt = recovered.receipt().unwrap();
    let confirmed_bytes = fs::read(&restored).unwrap();
    assert_eq!(
        recovered.sync(&old_history),
        Err(StoreError::Wallet(WalletError::Rollback))
    );
    assert_eq!(recovered.receipt().unwrap(), confirmed_receipt);
    assert_eq!(recovered.view().unwrap().height(), Some(1));
    assert_eq!(recovered.view().unwrap().balance().unwrap(), 39_000);
    assert_eq!(
        recovered.view().unwrap().available_balance().unwrap(),
        39_000
    );
    assert!(recovered.pending_payment().unwrap().is_none());
    assert!(recovered.view().unwrap().pending_id().is_none());
    unchanged(&restored, &confirmed_bytes);
    let second = recovered
        .prepare_payment_to(
            &carol.receive_recipient(0).unwrap(),
            10_000,
            1_000,
            10,
            &prover,
        )
        .unwrap();
    assert!(recovered.pending_payment().unwrap().unwrap().bytes() == second.bytes());
    assert_eq!(recovered.view().unwrap().available_balance().unwrap(), 0);
    let continued = commit_payment(&mut pool, second.bytes());
    assert_eq!(
        (
            continued.height,
            continued.commitments,
            continued.nullifiers,
            continued.fees,
        ),
        (2, 5, 4, 2_000)
    );
    reject_duplicates(&mut pool, &pool_path, &[&first, second.bytes()]);
    let history = genesis.wallet_history(&mut pool).unwrap();
    recovered.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    let balances = [
        recovered.view().unwrap().balance().unwrap(),
        bob.balance().unwrap(),
        carol.balance().unwrap(),
    ];
    assert_eq!(balances, [28_000, 60_000, 10_000]);
    assert_eq!(balances.iter().sum::<u64>() + continued.fees, TEST_SUPPLY);
    assert_eq!(
        recovered.view().unwrap().available_balance().unwrap(),
        balances[0]
    );
    assert!(recovered.pending_payment().unwrap().is_none());
    let final_receipt = recovered.receipt().unwrap();
    let final_wallet = fs::read(&restored).unwrap();
    drop(recovered);
    drop(source);
    let pool_checkpoint = pool.active_recovery_checkpoint().unwrap();
    let final_pool = pool_bytes(&pool_path);
    drop(pool);
    let mut pool = genesis.open_pool(&pool_path).unwrap();
    assert_eq!(pool.summary().unwrap(), continued);
    assert_eq!(pool.active_recovery_checkpoint().unwrap(), pool_checkpoint);
    let mut reopened =
        WalletStore::open(&restored, password.as_ref(), Some(final_receipt)).unwrap();
    assert_not_synced(&reopened);
    reopened
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert_eq!(reopened.receipt().unwrap(), final_receipt);
    assert_eq!(
        reopened.view().unwrap().available_balance().unwrap(),
        balances[0]
    );
    assert!(reopened.pending_payment().unwrap().is_none());
    drop(reopened);
    drop(pool);
    unchanged(&restored, &final_wallet);
    assert!(pool_bytes(&pool_path) == final_pool);
    unchanged(&backup, &original);
    unchanged(&target, &damaged);
    if matches!(case, Case::Compact) {
        unchanged(&source_path, &original);
    }
    assert_eq!(read_pin(&checkpoint_path), source_receipt);
    assert_eq!(read_pin(&recovered_checkpoint_path), recovered_receipt);
    Receipt {
        case,
        target: target_metadata,
        before_len,
        before_hash,
        after_hash: digest(&damaged),
        suffix_len,
        source_receipt,
        recovered_receipt,
        backup_len: original.len(),
        backup_hash: digest(&original),
        filler_bytes,
    }
    .write(&environment.control);
}

#[test]
#[ignore = "requires the dedicated 8 MiB tmpfs and wallet ENOSPC trace harness"]
fn wallet_sync_enospc_preserves_outbox_and_recovers() {
    run_case(Case::Sync);
}

#[test]
#[ignore = "requires the dedicated 8 MiB tmpfs and wallet ENOSPC trace harness"]
fn wallet_compact_enospc_preserves_source_and_recovers() {
    run_case(Case::Compact);
}
