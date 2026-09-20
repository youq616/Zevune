//! Native, in-process storage experiments. The ordinary worker/growth test is
//! unchanged and remains a separate acceptance gate. These tests use real
//! PoolStore execution, real files and genuine Orchard payments, not doubles.
use super::commit_timing::{Phase, Session, Snapshot, N};
use super::testnet::{TestGenesis, TEST_SUPPLY};
use super::{Hash, PoolError, PoolStore, Summary};
use crate::wallet::{Wallet, WalletProver};
use rand::{rngs::OsRng, RngCore};
use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

const BLOCKS: u64 = 8_192;
struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let suffix: String = nonce.iter().map(|n| format!("{n:02x}")).collect();
        let root = std::env::temp_dir().canonicalize().unwrap();
        let path = root.join(format!("zevune-commit-timing-{suffix}"));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn child(&self, name: &str) -> PathBuf { self.0.join(name) }
    fn clean(&self) { fs::remove_dir_all(&self.0).unwrap(); }
}
impl Drop for Directory {
    fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
}
fn id(height: u64) -> Hash {
    let mut value = [9; 32];
    value[..8].copy_from_slice(&height.to_be_bytes());
    value
}
fn commit(pool: &mut PoolStore, height: u64, txs: &[Vec<u8>]) -> Summary {
    let prepared = pool.prepare(height, id(height), txs).unwrap();
    let expected = prepared.result().clone();
    let actual = pool.commit(prepared).unwrap();
    assert_eq!(actual, expected);
    assert_eq!(pool.summary().unwrap(), actual);
    actual
}
fn bytes(path: &Path) -> BTreeMap<String, Vec<u8>> {
    let mut result = BTreeMap::new();
    for entry in fs::read_dir(path).unwrap() {
        let entry = entry.unwrap();
        let meta = fs::symlink_metadata(entry.path()).unwrap();
        assert!(meta.is_file() && meta.len() <= 1_048_576);
        assert!(result.len() < 4);
        result.insert(entry.file_name().into_string().unwrap(), fs::read(entry.path()).unwrap());
    }
    result
}
fn genesis() -> TestGenesis {
    let wallet = Wallet::create().unwrap();
    TestGenesis::generate_active(&[(wallet.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap()
}

#[test]
fn rejected_stale_candidate_keeps_state_and_bytes_and_is_not_a_timing_success() {
    let dir = Directory::new();
    let genesis = genesis();
    let path = dir.child("ledger");
    let mut pool = genesis.create_pool(&path).unwrap();
    let stale = pool.prepare(1, id(1), &[]).unwrap();
    let expected = commit(&mut pool, 1, &[]);
    drop(pool);
    let before = bytes(&path);
    let mut pool = genesis.open_pool(&path).unwrap();
    let session = Session::start(1);
    assert_eq!(pool.commit(stale).err(), Some(PoolError::Stale));
    let report = session.finish();
    assert!(report.valid);
    assert_eq!((report.attempts, report.accepted, report.failed, report.last_accepted), (1, 0, 1, 1));
    assert_eq!(report.failure.unwrap().pending, Some(Phase::Preflight));
    assert!(report.ordinary.iter().all(|m| m.count == 0));
    assert_eq!(pool.summary().unwrap(), expected);
    drop(pool);
    assert!(bytes(&path) == before);
    dir.clean();
}

#[test]
fn injected_append_failures_preserve_error_semantics_and_do_not_pollute_success_metrics() {
    // Existing cfg(test) interruptions, NOT ENOSPC, a physical power-loss test,
    // or a production failure switch. Even full sync is not API acceptance.
    for point in 1..=4 {
        let dir = Directory::new();
        let genesis = genesis();
        let path = dir.child("ledger");
        let mut pool = genesis.create_pool(&path).unwrap();
        let plan = pool.prepare(1, id(1), &[]).unwrap();
        let result = plan.result().clone();
        pool.active.as_mut().unwrap().fault = point;
        let session = Session::start(0);
        assert_eq!(pool.commit(plan).err(), Some(PoolError::Storage));
        assert_eq!(pool.summary().err(), Some(PoolError::Unavailable));
        let report = session.finish();
        assert!(report.valid);
        assert_eq!((report.attempts, report.accepted, report.failed, report.last_accepted), (1, 0, 1, 0));
        assert_eq!(report.total.count, 0);
        assert!(report.ordinary.iter().chain(&report.rotating).all(|m| m.count == 0));
        let failure = report.failure.unwrap();
        assert_eq!(failure.height, 1);
        if point == 1 { assert_eq!(failure.pending, Some(Phase::RotationPrepare)); }
        if point == 2 { assert_eq!(failure.pending, Some(Phase::WriteFrame)); }
        if point == 3 {
            assert!(failure.pending.is_none());
            assert_ne!(failure.completed_mask & (1 << Phase::WriteFrame as usize), 0);
            assert_eq!(failure.completed_mask & (1 << Phase::FileSync as usize), 0);
        }
        if point == 4 {
            assert!(failure.pending.is_none());
            assert_ne!(failure.completed_mask & (1 << Phase::FileSync as usize), 0);
            assert_eq!(failure.completed_mask & (1 << Phase::StatePublish as usize), 0);
        }
        drop(pool);
        // Reopen follows the real implementation; no repair or automatic retry.
        if point < 3 {
            assert!(genesis.open_pool(&path).is_err());
        } else {
            let reopened = genesis.open_pool(&path).unwrap();
            assert_eq!(reopened.summary().unwrap(), result);
        }
        dir.clean();
    }
}

fn assert_profile(r: &Snapshot, segments: u32) {
    assert!(r.valid && r.failure.is_none());
    assert_eq!((r.attempts, r.accepted, r.failed, r.last_accepted, r.paid), (BLOCKS, BLOCKS, 0, BLOCKS, 2));
    assert_eq!(r.rotated, u64::from(segments));
    assert_eq!(r.total.count, BLOCKS);
    let mut summed = 0;
    for i in 0..N {
        let a = r.ordinary[i];
        let b = r.rotating[i];
        let optional = i == Phase::RotationPrepare as usize || i == Phase::DirectorySync as usize;
        assert_eq!(a.count, if optional { 0 } else { BLOCKS - r.rotated });
        assert_eq!(b.count, r.rotated);
        assert!(a.max_ns <= a.total_ns && b.max_ns <= b.total_ns);
        summed += a.total_ns + b.total_ns;
    }
    assert!(summed <= r.total.total_ns);
}

fn publish(report: &str) {
    assert!(report.len() <= 16 * 1024);
    if let Some(path) = std::env::var_os("ZEVUNE_COMMIT_TIMING_DIR") {
        let dir = PathBuf::from(path);
        let meta = fs::symlink_metadata(&dir).unwrap();
        assert!(dir.is_absolute() && meta.is_dir() && !meta.file_type().is_symlink());
        let mut file = fs::OpenOptions::new().create_new(true).write(true).open(dir.join("profile.json")).unwrap();
        file.write_all(report.as_bytes()).unwrap();
        file.sync_all().unwrap();
    }
    println!("ACTIVE_COMMIT_TIMING {report}");
}

#[test]
#[ignore = "bounded native storage experiment; dedicated CI runs this exact test"]
fn native_paired_commits() {
    let deadline = Instant::now() + Duration::from_secs(600);
    let dir = Directory::new();
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let mut carol = Wallet::create().unwrap();
    let genesis = TestGenesis::generate_active(&[(alice.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let timed_path = dir.child("timed");
    let plain_path = dir.child("plain");
    let mut pool = genesis.create_pool(&timed_path).unwrap();
    let prover = WalletProver::new();
    let mut payments: BTreeMap<u64, Vec<Vec<u8>>> = BTreeMap::new();
    let session = Session::start(0);
    for height in 1..=BLOCKS {
        assert!(Instant::now() < deadline, "native profiling experiment exceeded budget");
        if height == 2 || height == 6_991 {
            let history = genesis.wallet_history(&mut pool).unwrap();
            alice.sync(&history).unwrap(); bob.sync(&history).unwrap(); carol.sync(&history).unwrap();
            let payment = if height == 2 {
                alice.build_payment(bob.receive_address(0).unwrap(), 60_000, 1_000, height + 99, &prover).unwrap()
            } else {
                bob.build_payment(carol.receive_address(0).unwrap(), 40_000, 1_000, height + 99, &prover).unwrap()
            };
            payments.insert(height, vec![payment.bytes().to_vec()]);
        }
        let txs = payments.get(&height).map_or(&[][..], Vec::as_slice);
        let state = commit(&mut pool, height, txs);
        if !txs.is_empty() {
            // Rejection is checked before expiry, not 8192 blocks later.
            assert_eq!(pool.prepare(height + 1, id(height + 1), txs).err(), Some(PoolError::DoubleSpend));
            assert_eq!(pool.summary().unwrap(), state);
        }
    }
    let report = session.finish();
    let state = pool.summary().unwrap();
    let capacity = pool.active_capacity().unwrap();
    assert_eq!(capacity.2, 2, "default-size rotation did not occur twice");
    assert_profile(&report, capacity.2);
    let history = genesis.wallet_history(&mut pool).unwrap();
    alice.sync(&history).unwrap(); bob.sync(&history).unwrap(); carol.sync(&history).unwrap();
    assert_eq!((alice.balance().unwrap(), bob.balance().unwrap(), carol.balance().unwrap(), state.fees), (39_000, 19_000, 40_000, 2_000));
    drop(history);
    drop(pool);
    let physical = bytes(&timed_path);

    // Replay the exact same signed inputs through an unrecorded real store.
    // This is a byte/state equivalence control, NOT a randomized performance A/B.
    let mut plain = genesis.create_pool(&plain_path).unwrap();
    for height in 1..=BLOCKS {
        assert!(Instant::now() < deadline, "native profiling control exceeded budget");
        commit(&mut plain, height, payments.get(&height).map_or(&[][..], Vec::as_slice));
    }
    assert_eq!(plain.summary().unwrap(), state);
    assert_eq!(plain.active_capacity().unwrap(), capacity);
    drop(plain);
    assert!(bytes(&plain_path) == physical, "instrumented and unrecorded storage bytes differ");
    let mut reopened = genesis.open_pool(&timed_path).unwrap();
    assert_eq!(reopened.summary().unwrap(), state);
    assert_eq!(reopened.active_capacity().unwrap(), capacity);
    let continued = commit(&mut reopened, BLOCKS + 1, &[]);
    drop(reopened);
    let reopened = genesis.open_pool(&timed_path).unwrap();
    assert_eq!(reopened.summary().unwrap(), continued);
    drop(reopened);
    assert!(Instant::now() < deadline, "native profiling replay exceeded budget");
    // All store handles are closed before directory deletion on both platforms.
    dir.clean();
    // No completion output until genuine checks and explicit cleanup succeeded.
    let profile = report.json();
    let json = format!("{{\"blocks\":{BLOCKS},\"control_bytes_equal\":true,\"replay_and_continuation\":true,\"real_funds_allowed\":false,\"profile\":{profile}}}");
    publish(&json);
}
