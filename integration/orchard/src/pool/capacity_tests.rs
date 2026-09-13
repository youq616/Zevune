//! Test-only smaller limits exercise the same writer on real temporary files.
//! They do not increase production limits or replace proof verification.
use super::*;
use rand::{rngs::OsRng, RngCore};
use std::io::Seek;
use std::path::PathBuf;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let name: String = nonce.iter().map(|b| format!("{b:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-capacity-{name}"));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn journal(pool: &mut PoolStore) -> Vec<u8> {
    // Use the owning handle: Windows locks may exclude a second reader.
    pool.file.rewind().unwrap();
    let mut bytes = Vec::new();
    pool.file.read_to_end(&mut bytes).unwrap();
    bytes
}

#[test]
fn capacity_prepare_rejects_before_unpersistable_empty_block() {
    let dir = Dir::new();
    let mut pool = PoolStore::create(&dir.0.join("journal")).unwrap();
    let before = pool.summary().unwrap();
    let bytes = journal(&mut pool);
    // A record needs 4 prefix + 114 body + 32 checksum bytes even with no tx.
    pool.test_byte_limit = Some(pool.length + 149);
    assert!(matches!(
        pool.prepare(1, [1; 32], &[]),
        Err(PoolError::Bounds)
    ));
    assert_eq!(pool.summary().unwrap(), before);
    assert_eq!(journal(&mut pool), bytes);
}

#[test]
fn capacity_selection_requires_space_for_even_an_empty_record() {
    let dir = Dir::new();
    let mut pool = PoolStore::create(&dir.0.join("journal")).unwrap();
    pool.test_byte_limit = Some(pool.length + 149);
    let before = pool.summary().unwrap();
    let bytes = journal(&mut pool);
    selection::ATTEMPTS.with(|n| n.set(0));
    assert!(matches!(
        pool.select_proposal(1, [1; 32], 10, &[vec![0; 10]]),
        Err(PoolError::Bounds)
    ));
    assert_eq!(selection::ATTEMPTS.with(|n| n.get()), 0);
    assert_eq!(pool.summary().unwrap(), before);
    assert_eq!(journal(&mut pool), bytes);
}

#[test]
fn capacity_exact_empty_frame_commits_reopens_and_stops_cleanly() {
    let dir = Dir::new();
    let path = dir.0.join("journal");
    let mut pool = PoolStore::create(&path).unwrap();
    let limit = pool.length + 150;
    pool.test_byte_limit = Some(limit);
    let chosen = pool.select_proposal(1, [1; 32], 0, &[]).unwrap();
    let prepared = pool.prepare(1, [1; 32], &[]).unwrap();
    assert_eq!(chosen.mask, 0);
    assert_eq!(prepared.result(), &chosen.result);
    let committed = pool.commit(prepared).unwrap();
    assert_eq!(pool.file.metadata().unwrap().len(), limit);
    let bytes = journal(&mut pool);
    assert!(matches!(
        pool.prepare(2, [2; 32], &[]),
        Err(PoolError::Bounds)
    ));
    assert_eq!(pool.summary().unwrap(), committed);
    assert_eq!(journal(&mut pool), bytes);
    drop(pool);
    let mut reopened = PoolStore::open(&path).unwrap();
    reopened.test_byte_limit = Some(limit);
    assert_eq!(reopened.summary().unwrap(), committed);
    assert!(matches!(
        reopened.prepare(2, [2; 32], &[]),
        Err(PoolError::Bounds)
    ));
    assert_eq!(journal(&mut reopened), bytes);
}

#[test]
fn capacity_commit_rechecks_the_budget_and_preserves_the_source() {
    let dir = Dir::new();
    let mut pool = PoolStore::create(&dir.0.join("journal")).unwrap();
    let prepared = pool.prepare(1, [1; 32], &[]).unwrap();
    let before = pool.summary().unwrap();
    let bytes = journal(&mut pool);
    // There is no runtime setting for this. A test-only tighter bound verifies
    // that PreparedBlock cannot bypass the repeated commit-side check.
    pool.test_byte_limit = Some(pool.length + 149);
    assert!(matches!(pool.commit(prepared), Err(PoolError::Bounds)));
    assert_eq!(pool.summary().unwrap(), before);
    assert_eq!(journal(&mut pool), bytes);
}

#[test]
fn capacity_rejects_before_attempting_any_candidate_authorization() {
    let dir = Dir::new();
    let mut pool = PoolStore::create(&dir.0.join("journal")).unwrap();
    pool.test_byte_limit = Some(pool.length + 150 + 4 + 9);
    selection::ATTEMPTS.with(|n| n.set(0));
    assert!(matches!(
        pool.prepare(1, [1; 32], &[vec![0; 10]]),
        Err(PoolError::Bounds)
    ));
    let chosen = pool
        .select_proposal(1, [1; 32], 10, &[vec![0; 10]])
        .unwrap();
    assert_eq!(chosen.mask, 0);
    assert_eq!(selection::ATTEMPTS.with(|n| n.get()), 0);
}

#[test]
fn capacity_accounting_matches_the_actual_record_encoder() {
    // These are framing fixtures, deliberately not valid payment envelopes.
    for count in 0..=MAX_BLOCK_TRANSACTIONS {
        for size in [0, 1, 9, 9198, MAX_ENVELOPE_SIZE] {
            let txs = vec![vec![0; size]; count];
            let body = Record {
                height: 1,
                block_id: [1; 32],
                base_hash: [2; 32],
                result_hash: [3; 32],
                transactions: txs.clone(),
            }
            .encode()
            .unwrap();
            for initial in [44, 76, 108, 4096] {
                let end = initial + body.len() as u64 + 36;
                assert_eq!(budget::record_end(initial, end, &txs).unwrap(), end);
                assert!(matches!(
                    budget::record_end(initial, end - 1, &txs),
                    Err(PoolError::Bounds)
                ));
            }
        }
    }
}

#[test]
fn capacity_invalid_lengths_counts_and_overflow_are_rejected() {
    assert!(budget::JournalBudget::new(u64::MAX, u64::MAX).is_err());
    assert!(budget::JournalBudget::new(151, 150).is_err());
    assert!(budget::JournalBudget::new(0, 149).is_err());
    let b = budget::JournalBudget::new(0, u64::MAX).unwrap();
    assert!(b.after_transaction(usize::MAX).is_none());
    assert!(b.after_transaction(MAX_ENVELOPE_SIZE + 1).is_none());
    assert!(
        budget::record_end(0, u64::MAX, &vec![Vec::new(); MAX_BLOCK_TRANSACTIONS + 1]).is_err()
    );
    assert!(budget::record_end(0, u64::MAX, &[vec![0; MAX_ENVELOPE_SIZE + 1]]).is_err());
    assert_eq!(
        budget::record_end(u64::MAX - 150, u64::MAX, &[]).unwrap(),
        u64::MAX
    );
}

#[test]
fn capacity_invalid_instance_still_fails_closed() {
    let dir = Dir::new();
    let mut pool = PoolStore::create(&dir.0.join("journal")).unwrap();
    pool.available = false;
    assert!(matches!(
        pool.prepare(1, [1; 32], &[]),
        Err(PoolError::Unavailable)
    ));
    assert!(matches!(
        pool.select_proposal(1, [1; 32], 0, &[]),
        Err(PoolError::Unavailable)
    ));
}

#[cfg(feature = "local-funding-lab")]
#[test]
fn capacity_genuine_payments_share_one_exact_budget_without_state_leaks() {
    use crate::pool::selection::{MAX_CANDIDATES, MAX_PROPOSAL_BYTES};
    use crate::pool::testnet::TestGenesis;
    use crate::wallet::{Wallet, WalletProver};

    let dir = Dir::new();
    let path = dir.0.join("journal");
    let mut wallets: Vec<_> = (0..3).map(|_| Wallet::create().unwrap()).collect();
    let recipient = Wallet::create().unwrap().receive_address(0).unwrap();
    let genesis = TestGenesis::generate(&[
        (wallets[0].receive_address(0).unwrap(), 30_000),
        (wallets[1].receive_address(0).unwrap(), 30_000),
        (wallets[2].receive_address(0).unwrap(), 40_000),
    ])
    .unwrap();
    let mut pool = genesis.create_pool(&path).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    let prover = WalletProver::new();
    let mut txs = Vec::new();
    for wallet in &mut wallets {
        wallet.sync(&history).unwrap();
        txs.push(
            wallet
                .build_payment(recipient, 5_000, 100, 10, &prover)
                .unwrap()
                .bytes()
                .to_vec(),
        );
    }
    assert!(txs.iter().all(|tx| tx.len() == txs[0].len()));
    let before = pool.summary().unwrap();
    let bytes = journal(&mut pool);
    let one_cost = txs[0].len() as u64 + 4;
    let mut invalid = txs[0].clone();
    *invalid.last_mut().unwrap() ^= 1;
    let candidates = vec![
        invalid,
        txs[0].clone(),
        txs[0].clone(),
        txs[1].clone(),
        txs[2].clone(),
    ];
    // Invalid signature and duplicate candidates must consume neither the
    // on-disk budget nor the temporary state reserved for later valid entries.
    for (payload_room, mask) in [
        (0, 0),
        (one_cost - 1, 0),
        (one_cost, 2),
        (2 * one_cost - 1, 2),
        (2 * one_cost, 10),
        (3 * one_cost, 26),
    ] {
        pool.test_byte_limit = Some(pool.length + 150 + payload_room);
        let selected = pool
            .select_proposal(1, [1; 32], MAX_PROPOSAL_BYTES, &candidates)
            .unwrap();
        assert_eq!(selected.mask, mask);
        let kept: Vec<_> = candidates
            .iter()
            .enumerate()
            .filter(|(i, _)| selected.mask & (1u64 << i) != 0)
            .map(|(_, tx)| tx.clone())
            .collect();
        assert_eq!(
            pool.prepare(1, [1; 32], &kept).unwrap().result(),
            &selected.result
        );
        assert_eq!(pool.summary().unwrap(), before);
        assert_eq!(journal(&mut pool), bytes);
    }
    let limit = pool.length + 150 + 2 * one_cost;
    pool.test_byte_limit = Some(limit);
    assert!(matches!(
        pool.prepare(1, [1; 32], &txs),
        Err(PoolError::Bounds)
    ));
    // A smaller ABCI transaction-byte limit remains independently enforced.
    let tight = pool
        .select_proposal(1, [1; 32], txs[0].len(), &candidates)
        .unwrap();
    assert_eq!(tight.mask, 2);
    let mut last = vec![Vec::new(); MAX_CANDIDATES];
    last[63] = txs[0].clone();
    assert_eq!(
        pool.select_proposal(1, [1; 32], MAX_PROPOSAL_BYTES, &last)
            .unwrap()
            .mask,
        1u64 << 63
    );
    let selected = pool
        .select_proposal(1, [1; 32], MAX_PROPOSAL_BYTES, &candidates)
        .unwrap();
    let prepared = pool.prepare(1, [1; 32], &txs[..2]).unwrap();
    let committed = pool.commit(prepared).unwrap();
    assert_eq!(committed, selected.result);
    assert_eq!(committed.fees, 200);
    assert_eq!(pool.length, limit);
    assert_eq!(pool.file.metadata().unwrap().len(), limit);
    assert!(matches!(
        pool.prepare(2, [2; 32], &[]),
        Err(PoolError::Bounds)
    ));
    let full = journal(&mut pool);
    drop(pool);
    let mut restored = genesis.open_pool(&path).unwrap();
    restored.test_byte_limit = Some(limit);
    assert_eq!(restored.summary().unwrap(), committed);
    assert_eq!(journal(&mut restored), full);
    // Restore the normal production bound ONLY in this test; the already
    // committed spends remain invalid after replay and after capacity checks.
    restored.test_byte_limit = None;
    assert!(matches!(
        restored.prepare(2, [2; 32], &txs[..1]),
        Err(PoolError::DoubleSpend)
    ));
    let third = restored.prepare(2, [2; 32], &txs[2..]).unwrap();
    assert_eq!(restored.commit(third).unwrap().fees, 300);
}
