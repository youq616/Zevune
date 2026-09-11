//! Real cryptography regression. Timings measure authorization only, not payments.
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, Scope};
use orchard::tree::MerkleHashOrchard;
use std::time::Instant;
use zevune_orchard_lab::wire::{encode, AuthorizationVerifier, ACTION_SIZE, HEADER_SIZE};
use zevune_orchard_lab::CIRCUIT;

#[path = "support/fixtures.rs"]
mod fixtures;

#[test]
fn real_authorization_reuse_rejects_changed_bytes_and_restarts_cold() {
    let alice = fixtures::key();
    let bob = fixtures::key();
    let sender = FullViewingKey::from(&alice).address_at(0u32, Scope::External);
    let receiver = FullViewingKey::from(&bob).address_at(0u32, Scope::External);
    let note = fixtures::genesis_note(sender);
    let leaf = MerkleHashOrchard::from_cmx(&note.commitment().into());
    let (path, _) = fixtures::witness(&[leaf], 0);
    let bundle = fixtures::prove(
        &ProvingKey::build(CIRCUIT),
        &alice,
        note,
        path,
        &[(receiver, 60_000), (sender, 39_000)],
        &fixtures::context(),
    );
    let raw = encode(&bundle, &fixtures::context()).unwrap();
    let verifier = AuthorizationVerifier::new();
    let start = Instant::now();
    let expected = verifier.verify(&raw).unwrap();
    let cold_us = start.elapsed().as_micros();
    let start = Instant::now();
    for _ in 0..32 {
        assert_eq!(verifier.verify(&raw).unwrap(), expected);
    }
    let warm_total_us = start.elapsed().as_micros();
    // Vary envelope context, commitments, keys, note encryption, signatures and
    // proof. Every mutation must miss the exact-byte cache and be rejected.
    let proof_start = HEADER_SIZE + bundle.actions().len() * ACTION_SIZE + 4;
    for index in [
        15,
        23,
        31,
        63,
        65,
        HEADER_SIZE + 32,
        HEADER_SIZE + 64,
        HEADER_SIZE + 96,
        HEADER_SIZE + 128,
        HEADER_SIZE + 160,
        HEADER_SIZE + 740,
        HEADER_SIZE + 820,
        proof_start,
        raw.len() - 1,
    ] {
        let mut changed = raw.clone();
        changed[index] ^= 1;
        assert!(verifier.verify(&changed).is_err());
        assert_eq!(verifier.verify(&raw).unwrap(), expected);
    }
    let mut changed = raw.clone();
    changed[23] ^= 1;
    changed[31] ^= 1;
    assert!(verifier.verify(&changed).is_err());
    assert!(verifier.verify(&raw[..raw.len() - 1]).is_err());
    let mut extended = raw.clone();
    extended.push(0);
    assert!(verifier.verify(&extended).is_err());
    // A new verifier has a new fixed key and empty cache. Nothing persisted is
    // accepted as a previously verified cache entry.
    drop(verifier);
    assert_eq!(AuthorizationVerifier::new().verify(&raw).unwrap(), expected);
    println!(
        "AUTH_CACHE_SAMPLE scope=authorization_only samples=32 cold_us={cold_us} warm_total_us={warm_total_us} transaction_bytes={}",
        raw.len()
    );
}
