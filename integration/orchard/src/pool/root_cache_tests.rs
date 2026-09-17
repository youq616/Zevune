//! An uncached oracle for the derived commitment root. The reference hash below
//! is State::summary from 951971f46e964d259275653063c2dc9c2dcfd104; its root is
//! always recomputed by the upstream frontier, never read from the new cache.
use super::*;

fn uncached_summary(state: &State) -> Summary {
    let mut h = Sha256::new();
    h.update(b"ZEVUNE-ORCHARD-POOL-STATE\0\x01");
    h.update(state.genesis);
    h.update(state.height.to_be_bytes());
    h.update(state.head);
    h.update(state.fees.to_be_bytes());
    h.update(state.frontier.tree_size().to_be_bytes());
    let root = state.frontier.root().to_bytes();
    h.update(root);
    h.update((state.spent.len() as u64).to_be_bytes());
    for nf in &state.spent {
        h.update(nf);
    }
    h.update((state.outputs.len() as u64).to_be_bytes());
    for cm in &state.outputs {
        h.update(cm);
    }
    h.update((state.anchors.len() as u64).to_be_bytes());
    for anchor in &state.anchors {
        h.update(anchor);
    }
    Summary {
        height: state.height,
        app_hash: h.finalize().into(),
        root,
        commitments: state.frontier.tree_size(),
        nullifiers: state.spent.len() as u64,
        fees: state.fees,
    }
}

pub(super) fn assert_state(state: &State) -> Summary {
    let expected = uncached_summary(state);
    assert_eq!(state.commitment_root, expected.root);
    assert_eq!(state.summary(), expected);
    expected
}

// Called with the existing legacy selection test's genuine, independently
// spendable payments. This adds no proof generation and no verifier substitute.
pub(super) fn assert_candidate_sequence(pool: &PoolStore, first: &[u8], second: &[u8]) {
    let before = assert_state(&pool.state);
    let mut candidate = pool.state.clone();
    assert_eq!(assert_state(&candidate), before);
    let height = before.height + 1;
    candidate
        .apply_transaction(height, &pool.state.anchors, first, &pool.verifier)
        .unwrap();
    let after_first = assert_state(&candidate);
    assert_ne!(after_first.root, before.root);

    let mut invalid = second.to_vec();
    *invalid.last_mut().unwrap() ^= 1;
    assert_eq!(
        candidate.apply_transaction(height, &pool.state.anchors, &invalid, &pool.verifier),
        Err(PoolError::Authorization)
    );
    assert_eq!(assert_state(&candidate), after_first);
    candidate
        .apply_transaction(height, &pool.state.anchors, second, &pool.verifier)
        .unwrap();
    let after_second = assert_state(&candidate);
    assert_ne!(after_second.root, after_first.root);
    assert_eq!(
        candidate.apply_transaction(height, &pool.state.anchors, first, &pool.verifier),
        Err(PoolError::DoubleSpend)
    );
    assert_eq!(assert_state(&candidate), after_second);

    // The fee error occurs after genuine authorization but before frontier or
    // root publication. Alter only a disposable test state to reach overflow.
    let mut overflow = pool.state.clone();
    overflow.fees = u64::MAX;
    let before_overflow = assert_state(&overflow);
    assert_eq!(
        overflow.apply_transaction(height, &pool.state.anchors, first, &pool.verifier),
        Err(PoolError::FeeOverflow)
    );
    assert_eq!(assert_state(&overflow), before_overflow);
    assert_eq!(assert_state(&pool.state), before);
}

#[test]
fn cached_root_matches_uncached_summary_for_initialization_clones_and_empty_blocks() {
    let receiver = crate::wallet::Wallet::create().unwrap();
    let note = tests::fixtures::genesis_note(receiver.receive_address(0).unwrap());
    let commitments = [ExtractedNoteCommitment::from(note.commitment()).to_bytes()];
    let verifier = AuthorizationVerifier::new();
    // Exercise the state constructors for the 01, 02 and 03 header policies,
    // with both empty and nonempty frontiers. Public 03 manifest creation and
    // real funded histories are independently checked by active_flow_tests.
    for initial in [&[][..], commitments.as_slice()] {
        for (domain, profile) in [
            (None, StorageProfile::LegacyJournal),
            (Some([2; 32]), StorageProfile::LegacyJournal),
            (Some([3; 32]), StorageProfile::ActiveSegmentsV1),
        ] {
            let state = State::from_storage_policy(initial, domain, profile).unwrap();
            let before = assert_state(&state);
            assert_eq!(assert_state(&state.clone()), before);
            let next = state.execute(1, [1; 32], &[], &verifier).unwrap();
            let after = assert_state(&next);
            assert_eq!(after.root, before.root);
            assert_eq!(after.commitments, before.commitments);
            assert_eq!(after.height, 1);
            assert_ne!(after.app_hash, before.app_hash);
            assert_eq!(assert_state(&next.clone()), after);
            assert_eq!(assert_state(&state), before);
        }
    }
}
