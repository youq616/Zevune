//! Same real replay engine behind writable startup, read-only recovery and
//! checkpoint export. Test counters measure code paths, not memory or latency.
use super::*;
use crate::pool::replay::{COPYING_EXECUTIONS, HISTORY_BLOCKS_COLLECTED};

fn reset_counts() {
    COPYING_EXECUTIONS.with(|n| n.set(0));
    HISTORY_BLOCKS_COLLECTED.with(|n| n.set(0));
}
fn assert_discard_replay() {
    COPYING_EXECUTIONS.with(|n| assert_eq!(n.get(), 0, "per-block state copies"));
    HISTORY_BLOCKS_COLLECTED.with(|n| assert_eq!(n.get(), 0, "full history collected"));
}

#[test]
fn checkpoint_export_and_archive_copy_discard_history_but_keep_the_exact_tip() {
    let dir = Dir::new();
    let source = dir.path("source");
    let mut pool = PoolStore::create(&source).unwrap();
    for id in 1..=48 {
        empty_block(&mut pool, id);
    }
    let summary = pool.summary().unwrap();
    let original = bytes(&mut pool);
    reset_counts();
    let history = pool.wallet_history().unwrap();
    assert_eq!(history.tip(), &summary);
    HISTORY_BLOCKS_COLLECTED.with(|n| assert_eq!(n.get(), 48));
    COPYING_EXECUTIONS.with(|n| assert_eq!(n.get(), 0));
    drop(history);

    // The existing prepared block remains usable after verification, which
    // neither commits it nor replaces the pool's state/candidate slots.
    let prepared = pool.prepare(49, [49; 32], &[]).unwrap();
    reset_counts();
    let pin = pool.recovery_checkpoint().unwrap();
    assert_discard_replay();
    assert_eq!(pin.app_hash(), summary.app_hash);
    assert_eq!(pin.length(), original.len() as u64);
    assert_eq!(pin.journal_hash, Hash::from(Sha256::digest(&original)));
    assert_eq!(bytes(&mut pool), original);
    pool.commit(prepared).unwrap();
    let pin = pool.recovery_checkpoint().unwrap();
    let final_bytes = bytes(&mut pool);
    drop(pool);

    reset_counts();
    let mut archive = RecoveryArchive::open(&source, pin).unwrap();
    // Read-only recovery must retain its shared lock while allowing another
    // independent read-only verifier. It never opens a competing writer.
    let second_reader = RecoveryArchive::open(&source, pin).unwrap();
    assert!(matches!(PoolStore::open(&source), Err(PoolError::Locked)));
    let target = dir.path("target");
    assert_eq!(archive.copy_new(&target).unwrap(), pin);
    assert_discard_replay();
    drop(second_reader);
    drop(archive);
    let mut reopened = PoolStore::open(&target).unwrap();
    assert_eq!(reopened.recovery_checkpoint().unwrap(), pin);
    assert_discard_replay();
    assert_eq!(bytes(&mut reopened), final_bytes);
}

#[test]
fn checkpoint_export_rejects_a_valid_same_length_alternate_history() {
    let dir = Dir::new();
    let mut source = PoolStore::create(&dir.path("source")).unwrap();
    let mut other = PoolStore::create(&dir.path("other")).unwrap();
    for id in 1..=3 {
        empty_block(&mut source, id);
        empty_block(&mut other, id + 100);
    }
    let before = source.summary().unwrap();
    let replacement = bytes(&mut other);
    assert_eq!(replacement.len() as u64, source.length);
    // Mutate via the owning handle: opening a second writer would make this
    // test fail at the Windows lock instead of at the intended tip check.
    source.file.set_len(0).unwrap();
    source.file.write_all(&replacement).unwrap();
    source.file.sync_all().unwrap();
    reset_counts();
    assert!(matches!(
        source.recovery_checkpoint(),
        Err(PoolError::Corrupt)
    ));
    assert_discard_replay();
    assert!(matches!(source.summary(), Err(PoolError::Unavailable)));
    assert_eq!(source.state.summary(), before); // No reconstructed state published.
    assert_eq!(bytes(&mut source), replacement); // No automatic disk repair.
}

#[test]
fn wrong_final_result_with_new_checksums_never_returns_a_verified_archive() {
    let dir = Dir::new();
    let source = dir.path("source");
    let mut pool = PoolStore::create(&source).unwrap();
    for id in 1..=3 {
        empty_block(&mut pool, id);
    }
    let mut pin = pool.recovery_checkpoint().unwrap();
    let mut damaged = bytes(&mut pool);
    drop(pool);
    let body_start = 44 + 2 * 150 + 4;
    damaged[body_start + 80] ^= 1; // Final result hash, after earlier valid records.
    let sum: Hash = Sha256::digest(&damaged[body_start..body_start + 114]).into();
    damaged[body_start + 114..body_start + 146].copy_from_slice(&sum);
    pin.journal_hash = Sha256::digest(&damaged).into();
    fs::write(&source, &damaged).unwrap();
    reset_counts();
    assert!(matches!(
        RecoveryArchive::open(&source, pin),
        Err(PoolError::Corrupt)
    ));
    assert_discard_replay();
    // No leaked read lock from a failed unpublished reconstruction.
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&source)
        .unwrap();
    file.try_lock().unwrap();
    drop(file);
    assert_eq!(fs::read(&source).unwrap(), damaged);
}

#[test]
fn a_shorter_valid_archive_needs_its_own_pin_not_the_later_checkpoint() {
    let dir = Dir::new();
    let source = dir.path("source");
    let mut pool = PoolStore::create(&source).unwrap();
    empty_block(&mut pool, 1);
    let early = pool.recovery_checkpoint().unwrap();
    let prefix = bytes(&mut pool);
    empty_block(&mut pool, 2);
    let later = pool.recovery_checkpoint().unwrap();
    let copy = dir.path("prefix");
    fs::write(&copy, prefix).unwrap();
    assert!(RecoveryArchive::open(&copy, later).is_err());
    reset_counts();
    let verified_old = RecoveryArchive::open(&copy, early).unwrap();
    assert_eq!(verified_old.checkpoint().height(), 1);
    assert_discard_replay();
    // A self-consistent old pin can authenticate old data; it is not a freshness
    // proof. The API must not pretend to solve complete backup rollback.
}

#[test]
fn every_recovery_entry_uses_isolated_replay_without_per_block_state_copies() {
    use crate::pool::replay::COPYING_EXECUTIONS;
    let dir = Dir::new();
    for (name, domain) in [("legacy", None), ("bound", Some([7; 32]))] {
        let source = dir.path(name);
        let mut pool = PoolStore::create_with_policy(&source, &[], domain).unwrap();
        for id in 1..=3 {
            empty_block(&mut pool, id);
        }
        let before = bytes(&mut pool);
        let summary = pool.summary().unwrap();
        COPYING_EXECUTIONS.with(|v| v.set(0));
        let checkpoint = pool.recovery_checkpoint().unwrap();
        assert_eq!(COPYING_EXECUTIONS.with(|v| v.get()), 0);
        assert_eq!(pool.wallet_history().unwrap().tip(), &summary);
        assert_eq!(COPYING_EXECUTIONS.with(|v| v.get()), 0);
        assert_eq!(bytes(&mut pool), before);
        drop(pool);
        let mut archive = RecoveryArchive::open(&source, checkpoint).unwrap();
        assert_eq!(COPYING_EXECUTIONS.with(|v| v.get()), 0);
        let destination = dir.path(&format!("{name}-copy"));
        archive.copy_new(&destination).unwrap();
        assert_eq!(COPYING_EXECUTIONS.with(|v| v.get()), 0);
        assert_eq!(fs::read(&destination).unwrap(), before);
        let recovered = PoolStore::open_with_policy(&destination, &[], domain).unwrap();
        assert_eq!(recovered.summary().unwrap(), summary);
        assert_eq!(COPYING_EXECUTIONS.with(|v| v.get()), 0);
        // Normal live block execution MUST still own an independent copy.
        recovered.prepare(4, [4; 32], &[]).unwrap();
        assert_eq!(COPYING_EXECUTIONS.with(|v| v.get()), 1);
        assert_eq!(recovered.summary().unwrap(), summary);
    }
}
