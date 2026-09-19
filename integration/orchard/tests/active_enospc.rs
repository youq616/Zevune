#![cfg(all(target_os = "linux", feature = "local-funding-lab"))]
//! Genuine payment writes on a dedicated, bounded Linux tmpfs. The external
//! harness must observe ENOSPC on the named journal with a buffer-safe syscall
//! trace; a filler error alone does not establish the journal's errno. These
//! tests exercise a running kernel, not physical disk failure or power loss.
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File, Metadata, OpenOptions};
use std::io::{ErrorKind, Write};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use zevune_orchard_lab::pool::recovery::active::{ActiveArchive, ActiveRecoveryCheckpoint};
use zevune_orchard_lab::pool::selection::MAX_PROPOSAL_BYTES;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::pool::{PoolError, PoolStore, PreparedBlock, StorageProfile, Summary};
use zevune_orchard_lab::wallet::{Wallet, WalletProver};
use zevune_orchard_lab::wire::MAX_ENVELOPE_SIZE;

const PAGE_BYTES: u64 = 4096;
const SEGMENT_BYTES: u64 = 1024 * 1024;
const EMPTY_FRAME_BYTES: u64 = 150;
const FILLER_LIMIT: usize = 16 * 1024 * 1024;
type DirectoryBytes = BTreeMap<String, Vec<u8>>;

#[derive(Clone, Copy)]
enum Case {
    Tail,
    NewSegment,
}
impl Case {
    fn name(self) -> &'static str {
        match self {
            Self::Tail => "active_tail_enospc_preserves_state_and_recovers",
            Self::NewSegment => "active_new_segment_enospc_preserves_state_and_recovers",
        }
    }

    fn target(self) -> &'static str {
        match self {
            Self::Tail => "source/00000000.journal",
            Self::NewSegment => "source/00000001.journal",
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
        // The harness may already own its trace output in control. All test
        // outputs must still be new; no existing source or backup is reused.
        for name in [
            "genesis.bin",
            "checkpoint.bin",
            "backup",
            "restored",
            "receipt.json",
        ] {
            assert!(!control.join(name).exists(), "ENOSPC output already exists");
        }
        Self { mount, control }
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn digest(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
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

fn directory_bytes(path: &Path) -> DirectoryBytes {
    let mut entries = BTreeMap::new();
    for entry in fs::read_dir(path).unwrap() {
        let entry = entry.unwrap();
        let metadata = fs::symlink_metadata(entry.path()).unwrap();
        assert!(metadata.is_file());
        assert_eq!(metadata.nlink(), 1);
        assert!(metadata.len() <= SEGMENT_BYTES);
        assert!(entries.len() < 3);
        let name = entry.file_name().into_string().unwrap();
        assert!(matches!(
            name.as_str(),
            "genesis" | "00000000.journal" | "00000001.journal"
        ));
        assert!(entries
            .insert(name, fs::read(entry.path()).unwrap())
            .is_none());
    }
    entries
}

fn unchanged(path: &Path, expected: &DirectoryBytes) {
    assert!(
        directory_bytes(path) == *expected,
        "public journal bytes changed"
    );
}

fn block_id(height: u64) -> [u8; 32] {
    let mut id = [1; 32];
    id[..8].copy_from_slice(&height.to_be_bytes());
    id
}

fn empty_block(pool: &mut PoolStore) {
    let height = pool.summary().unwrap().height + 1;
    let prepared = pool.prepare(height, block_id(height), &[]).unwrap();
    assert_eq!(pool.commit(prepared).unwrap().height, height);
}

fn balances(wallets: [&Wallet; 3]) -> [u64; 3] {
    wallets.map(|wallet| wallet.balance().unwrap())
}

// Independently encode the documented one-payment record. The partial suffix
// must be the beginning of this actual prepared payment frame, and the restored
// successful commit must later produce the whole identical frame.
fn payment_frame(base: &Summary, next: &Summary, payment: &[u8]) -> Vec<u8> {
    let mut body = b"ZVOBLK01".to_vec();
    body.extend_from_slice(&next.height.to_be_bytes());
    body.extend_from_slice(&block_id(next.height));
    body.extend_from_slice(&base.app_hash);
    body.extend_from_slice(&next.app_hash);
    body.extend_from_slice(&1u16.to_be_bytes());
    body.extend_from_slice(&u32::try_from(payment.len()).unwrap().to_be_bytes());
    body.extend_from_slice(payment);
    let mut frame = u32::try_from(body.len()).unwrap().to_be_bytes().to_vec();
    frame.extend_from_slice(&body);
    frame.extend_from_slice(&digest(&body));
    assert_eq!(frame.len(), 154 + payment.len());
    frame
}

fn fill_to_enospc(path: &Path) -> usize {
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
                assert!(written > 0);
                assert_eq!(written as u64 % PAGE_BYTES, 0);
                // Keep every allocated filler page in place through failure,
                // reopen checks and recovery; the harness owns final cleanup.
                filler.sync_all().unwrap();
                return written;
            }
        }
    }
    panic!("ENOSPC was not reached within the bounded filler budget");
}

fn unavailable<T>(result: Result<T, PoolError>) {
    assert_eq!(result.err(), Some(PoolError::Unavailable));
}

fn assert_unavailable(
    pool: &mut PoolStore,
    genesis: &TestGenesis,
    before: &Summary,
    competing: PreparedBlock,
) {
    let height = before.height + 1;
    unavailable(pool.summary());
    unavailable(pool.prepare(height, block_id(height), &[]));
    unavailable(pool.select_proposal(height, block_id(height), MAX_PROPOSAL_BYTES, &[]));
    unavailable(pool.check_checkpoint(before.height, before.app_hash));
    unavailable(pool.wallet_history());
    unavailable(genesis.wallet_history(pool));
    unavailable(pool.active_capacity());
    unavailable(pool.active_recovery_checkpoint());
    unavailable(pool.commit(competing));
    unavailable(pool.summary());
    // The profile label and unsupported legacy export keep their established
    // semantics. Neither publishes committed state or authenticates history.
    assert_eq!(pool.storage_profile(), StorageProfile::ActiveSegmentsV1);
    assert_eq!(pool.recovery_checkpoint().err(), Some(PoolError::Bounds));
}

struct Receipt {
    case: Case,
    target: Metadata,
    before_len: u64,
    before_hash: Option<[u8; 32]>,
    after_hash: [u8; 32],
    frame_len: usize,
    suffix_len: usize,
    checkpoint: ActiveRecoveryCheckpoint,
    filler_bytes: usize,
}
impl Receipt {
    fn write(&self, control: &Path) {
        let before_hash = self
            .before_hash
            .map_or_else(|| "null".to_owned(), |hash| format!("\"{}\"", hex(&hash)));
        // All values are fixed labels, integers, public hashes or assertions
        // already established below. No transaction, wallet or path is logged.
        let encoded = format!(
            concat!(
                "{{\"schema_version\":1,\"case\":\"{case}\",",
                "\"profile\":\"active_segments_v1\",\"filesystem\":\"tmpfs\",",
                "\"target_rel\":\"{target}\",\"target_dev\":{dev},",
                "\"target_ino\":{ino},\"target_nlink\":{nlink},",
                "\"before_len\":{before},\"after_len\":{after},",
                "\"frame_len\":{frame},\"changed_suffix_len\":{suffix},",
                "\"before_sha256\":{before_hash},\"after_sha256\":\"{after_hash}\",",
                "\"checkpoint_height\":{height},\"checkpoint_apphash\":\"{apphash}\",",
                "\"checkpoint_pin_sha256\":\"{pin_hash}\",",
                "\"filler_errno\":28,\"filler_bytes\":{filler},",
                "\"commit_storage\":true,\"store_unavailable\":true,",
                "\"reopen_rejected\":true,\"committed_prefix_preserved\":true,",
                "\"no_new_summary_published\":true,\"backup_unchanged\":true,",
                "\"rejected_source_unchanged\":true,\"restored_replay\":true,",
                "\"continuation_done\":true}}\n"
            ),
            case = self.case.name(),
            target = self.case.target(),
            dev = self.target.dev(),
            ino = self.target.ino(),
            nlink = self.target.nlink(),
            before = self.before_len,
            after = self.target.len(),
            frame = self.frame_len,
            suffix = self.suffix_len,
            before_hash = before_hash,
            after_hash = hex(&self.after_hash),
            height = self.checkpoint.height(),
            apphash = hex(&self.checkpoint.app_hash()),
            pin_hash = hex(&digest(&self.checkpoint.to_bytes())),
            filler = self.filler_bytes,
        );
        write_new(&control.join("receipt.json"), encoded.as_bytes());
    }
}

fn run_case(case: Case) {
    let environment = Environment::required();
    let source = environment.mount.join("source");
    let target = environment.mount.join(case.target());
    let backup = environment.control.join("backup");
    let restored = environment.control.join("restored");
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let mut carol = Wallet::create().unwrap();
    let genesis =
        TestGenesis::generate_active(&[(alice.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    genesis
        .write_new(&environment.control.join("genesis.bin"))
        .unwrap();
    let mut pool = genesis.create_pool(&source).unwrap();
    if matches!(case, Case::NewSegment) {
        // Start the real payment pair near the end of segment zero. Wallets
        // permit expiry only within 100 blocks of their scanned height, so a
        // height-one payment must not be reused after thousands of empty blocks.
        let maximum_frame = 154 + MAX_ENVELOPE_SIZE as u64;
        for _ in 0..(SEGMENT_BYTES - maximum_frame) / EMPTY_FRAME_BYTES {
            empty_block(&mut pool);
        }
    }
    alice
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let first_expiry = pool.summary().unwrap().height + 100;
    let prover = WalletProver::new();
    let first = alice
        .build_payment(
            bob.receive_address(0).unwrap(),
            60_000,
            1_000,
            first_expiry,
            &prover,
        )
        .unwrap()
        .bytes()
        .to_vec();
    let first_height = pool.summary().unwrap().height + 1;
    let prepared = pool
        .prepare(
            first_height,
            block_id(first_height),
            std::slice::from_ref(&first),
        )
        .unwrap();
    let paid = pool.commit(prepared).unwrap();
    assert_eq!(
        (paid.commitments, paid.nullifiers, paid.fees),
        (3, 2, 1_000)
    );
    let history = genesis.wallet_history(&mut pool).unwrap();
    alice.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    assert_eq!(balances([&alice, &bob, &carol]), [39_000, 60_000, 0]);
    drop(history);
    let second_expiry = paid.height + 100;
    let second_payment = bob
        .build_payment(
            carol.receive_address(0).unwrap(),
            40_000,
            1_000,
            second_expiry,
            &prover,
        )
        .unwrap();
    let second_id = second_payment.id();
    let second = second_payment.bytes().to_vec();
    let reserved_balance = bob.available_balance().unwrap();
    assert!(bob.pending_id() == Some(second_id));
    let frame_len = 154 + second.len() as u64;
    assert!(frame_len > PAGE_BYTES && frame_len <= SEGMENT_BYTES);
    let (_, _, count, mut tail) = pool.active_capacity().unwrap();
    assert_eq!(count, 1);
    match case {
        Case::Tail => {
            if u64::from(tail).is_multiple_of(PAGE_BYTES) {
                empty_block(&mut pool);
                tail += EMPTY_FRAME_BYTES as u32;
            }
            assert!(u64::from(tail) + frame_len <= SEGMENT_BYTES);
            assert_ne!(u64::from(tail) % PAGE_BYTES, 0);
            assert!(frame_len > PAGE_BYTES - u64::from(tail) % PAGE_BYTES);
        }
        Case::NewSegment => {
            while u64::from(tail) + frame_len <= SEGMENT_BYTES {
                empty_block(&mut pool);
                tail += EMPTY_FRAME_BYTES as u32;
            }
            assert!(u64::from(tail) <= SEGMENT_BYTES);
            assert!(!target.exists());
        }
    }
    let before = pool.summary().unwrap();
    let height = before.height + 1;
    // Preserve room for duplicate-payment checks after the restored commit.
    assert!(height < first_expiry && height < second_expiry);
    assert_eq!(pool.active_capacity().unwrap().3, tail);
    let checkpoint = pool.active_recovery_checkpoint().unwrap();
    assert_eq!(checkpoint.height(), before.height);
    assert_eq!(checkpoint.app_hash(), before.app_hash);
    assert_eq!(checkpoint.segment_count(), 1);
    drop(pool);
    let original = directory_bytes(&source);
    write_new(
        &environment.control.join("checkpoint.bin"),
        &checkpoint.to_bytes(),
    );
    File::open(&environment.control)
        .unwrap()
        .sync_all()
        .unwrap();
    let mut archive = ActiveArchive::open(&source, checkpoint).unwrap();
    assert_eq!(archive.copy_new(&backup).unwrap(), checkpoint);
    drop(archive);
    unchanged(&source, &original);
    unchanged(&backup, &original);

    let mut pool = genesis.open_pool(&source).unwrap();
    assert_eq!(pool.summary().unwrap(), before);
    let prepared = pool
        .prepare(height, block_id(height), std::slice::from_ref(&second))
        .unwrap();
    let expected = prepared.result().clone();
    assert_eq!(
        (expected.commitments, expected.nullifiers, expected.fees),
        (5, 4, 2_000)
    );
    let competing = pool
        .prepare(height, block_id(height), std::slice::from_ref(&second))
        .unwrap();
    let frame = payment_frame(&before, &expected, &second);
    assert_eq!(frame.len() as u64, frame_len);
    let prior_metadata = match case {
        Case::Tail => {
            let metadata = fs::metadata(&target).unwrap();
            assert_eq!(metadata.len(), u64::from(tail));
            assert_eq!(
                metadata.blocks() * 512,
                metadata.len().div_ceil(PAGE_BYTES) * PAGE_BYTES
            );
            Some(metadata)
        }
        Case::NewSegment => None,
    };
    let filler_bytes = fill_to_enospc(&environment.mount.join("filler"));
    assert_eq!(pool.commit(prepared), Err(PoolError::Storage));
    assert_unavailable(&mut pool, &genesis, &before, competing);
    assert!(bob.pending_id() == Some(second_id));
    assert_eq!(bob.available_balance().unwrap(), reserved_balance);
    assert_eq!(balances([&alice, &bob, &carol]), [39_000, 60_000, 0]);
    drop(pool);
    let damaged = directory_bytes(&source);
    let target_metadata = fs::symlink_metadata(&target).unwrap();
    assert!(target_metadata.is_file());
    assert_eq!(target_metadata.nlink(), 1);
    assert_eq!(
        target_metadata.dev(),
        fs::metadata(&environment.mount).unwrap().dev()
    );
    let (before_len, before_hash, after_bytes, suffix_len) = match case {
        Case::Tail => {
            let old = &original["00000000.journal"];
            let after = &damaged["00000000.journal"];
            let prior = prior_metadata.unwrap();
            assert_eq!(prior.dev(), target_metadata.dev());
            assert_eq!(prior.ino(), target_metadata.ino());
            assert_eq!(damaged.len(), original.len());
            assert!(damaged["genesis"] == original["genesis"]);
            assert!(after.starts_with(old));
            let suffix = &after[old.len()..];
            assert!(!suffix.is_empty() && suffix.len() < frame.len());
            assert!(suffix == &frame[..suffix.len()]);
            assert_eq!(
                after.len() as u64,
                (old.len() as u64).div_ceil(PAGE_BYTES) * PAGE_BYTES
            );
            (old.len() as u64, Some(digest(old)), after, suffix.len())
        }
        Case::NewSegment => {
            assert_eq!(damaged.len(), original.len() + 1);
            for (name, bytes) in &original {
                assert!(damaged[name] == *bytes);
            }
            let after = &damaged["00000001.journal"];
            assert!(after.is_empty());
            (0, None, after, 0)
        }
    };
    assert_eq!(target_metadata.len(), after_bytes.len() as u64);
    assert_eq!(genesis.open_pool(&source).err(), Some(PoolError::Corrupt));
    unchanged(&source, &damaged);
    let archive_error = ActiveArchive::open(&source, checkpoint).err();
    assert_eq!(
        archive_error,
        Some(match case {
            Case::Tail => PoolError::Stale,
            Case::NewSegment => PoolError::Corrupt,
        })
    );
    unchanged(&source, &damaged);
    unchanged(&backup, &original);

    // Restore exclusively from the independently pinned, pre-failure backup.
    // The damaged source stays present, full and unchanged throughout recovery.
    let pin_bytes = fs::read(environment.control.join("checkpoint.bin")).unwrap();
    assert!(pin_bytes == checkpoint.to_bytes());
    let retained_pin = ActiveRecoveryCheckpoint::from_bytes(&pin_bytes).unwrap();
    let mut archive = ActiveArchive::open(&backup, retained_pin).unwrap();
    assert_eq!(archive.copy_new(&restored).unwrap(), retained_pin);
    drop(archive);
    unchanged(&restored, &original);
    let mut recovered = genesis.open_pool(&restored).unwrap();
    assert_eq!(recovered.summary().unwrap(), before);
    assert_eq!(
        recovered.active_recovery_checkpoint().unwrap(),
        retained_pin
    );
    assert_eq!(
        recovered
            .prepare(height, block_id(height), std::slice::from_ref(&first))
            .err(),
        Some(PoolError::DoubleSpend)
    );
    let history = genesis.wallet_history(&mut recovered).unwrap();
    assert_eq!(history.tip(), &before);
    alice.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    assert_eq!(balances([&alice, &bob, &carol]), [39_000, 60_000, 0]);
    assert!(alice.pending_id().is_none());
    assert!(bob.pending_id() == Some(second_id));
    assert_eq!(bob.available_balance().unwrap(), reserved_balance);
    drop(history);
    let prepared = recovered
        .prepare(height, block_id(height), std::slice::from_ref(&second))
        .unwrap();
    assert_eq!(prepared.result(), &expected);
    let continued = recovered.commit(prepared).unwrap();
    assert_eq!(continued, expected);
    for payment in [&first, &second] {
        assert_eq!(
            recovered
                .prepare(
                    height + 1,
                    block_id(height + 1),
                    std::slice::from_ref(payment)
                )
                .err(),
            Some(PoolError::DoubleSpend)
        );
    }
    let history = genesis.wallet_history(&mut recovered).unwrap();
    alice.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    assert_eq!(balances([&alice, &bob, &carol]), [39_000, 19_000, 40_000]);
    assert!(alice.pending_id().is_none() && bob.pending_id().is_none());
    assert_eq!(
        balances([&alice, &bob, &carol]).iter().sum::<u64>() + continued.fees,
        TEST_SUPPLY
    );
    drop(history);
    let final_pin = recovered.active_recovery_checkpoint().unwrap();
    drop(recovered);
    let complete = directory_bytes(&restored);
    match case {
        Case::Tail => assert!(complete["00000000.journal"][before_len as usize..] == frame),
        Case::NewSegment => assert!(complete["00000001.journal"] == frame),
    }
    let mut reopened = genesis.open_pool(&restored).unwrap();
    assert_eq!(reopened.summary().unwrap(), continued);
    assert_eq!(reopened.active_recovery_checkpoint().unwrap(), final_pin);
    drop(reopened);
    unchanged(&restored, &complete);
    unchanged(&backup, &original);
    unchanged(&source, &damaged);
    assert!(fs::read(environment.control.join("checkpoint.bin")).unwrap() == checkpoint.to_bytes());
    Receipt {
        case,
        target: target_metadata,
        before_len,
        before_hash,
        after_hash: digest(after_bytes),
        frame_len: frame.len(),
        suffix_len,
        checkpoint,
        filler_bytes,
    }
    .write(&environment.control);
}

#[test]
#[ignore = "requires the dedicated 8 MiB tmpfs and journal ENOSPC trace harness"]
fn active_tail_enospc_preserves_state_and_recovers() {
    run_case(Case::Tail);
}

#[test]
#[ignore = "requires the dedicated 8 MiB tmpfs and journal ENOSPC trace harness"]
fn active_new_segment_enospc_preserves_state_and_recovers() {
    run_case(Case::NewSegment);
}
