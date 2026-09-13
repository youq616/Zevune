use super::*;
use crate::pool::testnet::{TestGenesis, TEST_SUPPLY};
use crate::wallet::{Wallet, WalletProver};
use rand::{rngs::OsRng, RngCore};
use std::io::Seek;
use std::path::PathBuf;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut b = [0; 16];
        OsRng.fill_bytes(&mut b);
        let name: String = b.iter().map(|x| format!("{x:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-selection-{name}"));
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
    pool.file.rewind().unwrap();
    let mut raw = Vec::new();
    pool.file.read_to_end(&mut raw).unwrap();
    raw
}
fn reference(pool: &PoolStore, height: u64, id: Hash, limit: usize, txs: &[Vec<u8>]) -> Selection {
    let mut last_result = pool.prepare(height, id, &[]).unwrap().result().clone();
    let mut chosen = Vec::new();
    let mut mask = 0;
    let mut remaining = limit;
    for (i, tx) in txs.iter().take(MAX_CANDIDATES).enumerate() {
        if chosen.len() == MAX_BLOCK_TRANSACTIONS {
            break;
        }
        if tx.is_empty() || tx.len() > remaining {
            continue;
        }
        let mut trial = chosen.clone();
        trial.push(tx.clone());
        if let Ok(prepared) = pool.prepare(height, id, &trial) {
            last_result = prepared.result().clone();
            chosen = trial;
            mask |= 1u64 << i;
            remaining -= tx.len();
        }
    }
    Selection {
        result: last_result,
        mask,
    }
}

#[test]
fn genuine_selection_matches_prefix_reference_and_never_persists() {
    let dir = Dir::new();
    let path = dir.0.join("pool.journal");
    let mut wallets: Vec<_> = (0..3).map(|_| Wallet::create().unwrap()).collect();
    let recipient = Wallet::create().unwrap().receive_address(0).unwrap();
    let allocations = [
        (wallets[0].receive_address(0).unwrap(), 30_000),
        (wallets[1].receive_address(0).unwrap(), 30_000),
        (wallets[2].receive_address(0).unwrap(), 40_000),
    ];
    let genesis = TestGenesis::generate(&allocations).unwrap();
    let mut pool = genesis.create_pool(&path).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    let prover = WalletProver::new();
    let mut txs = Vec::new();
    for (i, wallet) in wallets.iter_mut().enumerate() {
        wallet.sync(&history).unwrap();
        txs.push(
            wallet
                .build_payment(recipient, 5_000, 100 + i as u64, 10, &prover)
                .unwrap()
                .bytes()
                .to_vec(),
        );
    }
    let before = pool.summary().unwrap();
    let original = journal(&mut pool);
    let mut bad_signature = txs[0].clone();
    *bad_signature.last_mut().unwrap() ^= 1;
    let mut wrong_domain = txs[1].clone();
    wrong_domain[8] ^= 1;
    let cases = [
        vec![
            bad_signature.clone(),
            txs[0].clone(),
            txs[0].clone(),
            txs[1].clone(),
            txs[2].clone(),
        ],
        vec![
            txs[2].clone(),
            wrong_domain,
            vec![0; 17],
            txs[1].clone(),
            txs[0].clone(),
        ],
        vec![Vec::new(), txs[1].clone(), bad_signature, txs[2].clone()],
    ];
    for candidates in &cases {
        for limit in [
            0,
            txs[0].len() - 1,
            txs[0].len(),
            txs[0].len() * 2,
            MAX_PROPOSAL_BYTES,
        ] {
            let expected = reference(&pool, 1, [1; 32], limit, candidates);
            let actual = pool.select_proposal(1, [1; 32], limit, candidates).unwrap();
            assert_eq!(actual.mask, expected.mask);
            assert_eq!(actual.result, expected.result);
            assert_eq!(pool.summary().unwrap(), before);
            assert_eq!(journal(&mut pool), original);
        }
    }
    let mut last = vec![Vec::new(); MAX_CANDIDATES];
    last[63] = txs[0].clone();
    assert_eq!(
        pool.select_proposal(1, [1; 32], MAX_PROPOSAL_BYTES, &last)
            .unwrap()
            .mask,
        1u64 << 63
    );
    ATTEMPTS.with(|n| n.set(0));
    let actual = pool
        .select_proposal(1, [1; 32], MAX_PROPOSAL_BYTES, &txs)
        .unwrap();
    assert_eq!(ATTEMPTS.with(|n| n.get()), 3);
    ATTEMPTS.with(|n| n.set(0));
    let expected = reference(&pool, 1, [1; 32], MAX_PROPOSAL_BYTES, &txs);
    // The old greedy method applies prefixes of lengths 1, 2 and 3.
    assert_eq!(ATTEMPTS.with(|n| n.get()), 6);
    assert_eq!(actual.mask, 7);
    assert_eq!(actual.result, expected.result);

    // A late fee-overflow rejection must leave the disposable state untouched.
    let mut candidate = pool.state.clone();
    candidate.fees = u64::MAX;
    let unchanged = candidate.summary();
    assert_eq!(
        candidate
            .apply_transaction(1, &pool.state.anchors, &txs[0], &pool.verifier)
            .unwrap_err(),
        PoolError::FeeOverflow
    );
    assert_eq!(candidate.summary(), unchanged);

    // Selection is not a reservation or reusable commit permission.
    let prepared = pool.prepare(1, [1; 32], &txs).unwrap();
    let committed = pool.commit(prepared).unwrap();
    assert_eq!(committed, actual.result);
    assert_eq!(
        pool.select_proposal(2, [2; 32], MAX_PROPOSAL_BYTES, &txs)
            .unwrap()
            .mask,
        0
    );
    drop(pool);
    let reopened = genesis.open_pool(&path).unwrap();
    assert_eq!(reopened.summary().unwrap(), committed);
    assert_eq!(
        reopened
            .select_proposal(2, [2; 32], MAX_PROPOSAL_BYTES, &txs)
            .unwrap()
            .mask,
        0
    );
}

#[test]
fn same_block_output_cannot_become_a_selection_anchor() {
    let dir = Dir::new();
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let carol = Wallet::create().unwrap().receive_address(0).unwrap();
    let genesis =
        TestGenesis::generate(&[(alice.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let mut origin = genesis.create_pool(&dir.0.join("origin")).unwrap();
    let mut shadow = genesis.create_pool(&dir.0.join("shadow")).unwrap();
    let prover = WalletProver::new();
    alice
        .sync(&genesis.wallet_history(&mut origin).unwrap())
        .unwrap();
    let first = alice
        .build_payment(bob.receive_address(0).unwrap(), 20_000, 100, 10, &prover)
        .unwrap()
        .bytes()
        .to_vec();
    let p = shadow
        .prepare(1, [1; 32], std::slice::from_ref(&first))
        .unwrap();
    shadow.commit(p).unwrap();
    bob.sync(&genesis.wallet_history(&mut shadow).unwrap())
        .unwrap();
    let second = bob
        .build_payment(carol, 10_000, 100, 10, &prover)
        .unwrap()
        .bytes()
        .to_vec();
    assert_eq!(
        origin
            .select_proposal(
                1,
                [1; 32],
                MAX_PROPOSAL_BYTES,
                &[first.clone(), second.clone()]
            )
            .unwrap()
            .mask,
        1
    );
    let p = origin.prepare(1, [1; 32], &[first]).unwrap();
    origin.commit(p).unwrap();
    assert_eq!(
        origin
            .select_proposal(
                2,
                [2; 32],
                MAX_PROPOSAL_BYTES,
                std::slice::from_ref(&second)
            )
            .unwrap()
            .mask,
        1
    );
    // The same valid signature can expire without any authorization cache bypass.
    for height in 2..=10 {
        let p = origin.prepare(height, [height as u8; 32], &[]).unwrap();
        origin.commit(p).unwrap();
    }
    assert_eq!(
        origin
            .select_proposal(11, [11; 32], MAX_PROPOSAL_BYTES, &[second])
            .unwrap()
            .mask,
        0
    );
}

#[test]
fn selector_bounds_and_unavailable_store_fail_closed() {
    let dir = Dir::new();
    let mut pool = PoolStore::create(&dir.0.join("empty")).unwrap();
    for (height, id, limit, txs) in [
        (0, [1; 32], 0, vec![]),
        (2, [1; 32], 0, vec![]),
        (1, [0; 32], 0, vec![]),
        (1, [1; 32], MAX_PROPOSAL_BYTES + 1, vec![]),
        (1, [1; 32], 0, vec![Vec::new(); 65]),
        (
            1,
            [1; 32],
            MAX_PROPOSAL_BYTES,
            vec![vec![0; MAX_ENVELOPE_SIZE + 1]],
        ),
    ] {
        assert!(pool.select_proposal(height, id, limit, &txs).is_err());
    }
    pool.available = false;
    assert_eq!(
        pool.select_proposal(1, [1; 32], 0, &[]).unwrap_err(),
        PoolError::Unavailable
    );
}
