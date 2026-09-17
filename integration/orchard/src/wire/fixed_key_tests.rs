//! Real authorization across independent caches sharing only a fixed public key.
use super::{decode, encode, payload_digest, AuthorizationVerifier, WireError};
use crate::{CIRCUIT, NETWORK};
use orchard::circuit::{OrchardCircuitVersion, ProvingKey};
use orchard::keys::{FullViewingKey, Scope};
use orchard::tree::MerkleHashOrchard;
use std::sync::Barrier;

#[path = "../../tests/support/fixtures.rs"]
mod fixtures;

#[test]
fn concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold() {
    let alice = fixtures::key();
    let bob = fixtures::key();
    let sender = FullViewingKey::from(&alice).address_at(0u32, Scope::External);
    let receiver = FullViewingKey::from(&bob).address_at(0u32, Scope::External);
    let note = fixtures::genesis_note(sender);
    let leaf = MerkleHashOrchard::from_cmx(&note.commitment().into());
    let (path, _) = fixtures::witness(&[leaf], 0);
    let context = fixtures::context();
    assert_eq!(context.network, NETWORK);
    let bundle = fixtures::prove(
        &ProvingKey::build(CIRCUIT),
        &alice,
        note,
        path,
        &[(receiver, 60_000), (sender, 39_000)],
        &context,
    );
    let raw = encode(&bundle, &context).unwrap();
    let digest = payload_digest(&raw);
    let first = AuthorizationVerifier::new();
    let existing = AuthorizationVerifier::new();
    assert_eq!(
        first.key.circuit_version(),
        OrchardCircuitVersion::FixedPostNu6_2
    );
    assert!(std::ptr::eq(first.key, existing.key));
    assert!(!first.verified.contains(&raw, digest).unwrap());
    assert!(!existing.verified.contains(&raw, digest).unwrap());
    assert_eq!(first.verify(&raw), Ok(digest));
    assert!(first.verified.contains(&raw, digest).unwrap());
    assert!(!existing.verified.contains(&raw, digest).unwrap());

    let proof_start = super::HEADER_SIZE + bundle.actions().len() * super::ACTION_SIZE + 4;
    let changed: Vec<_> = [proof_start, raw.len() - 1]
        .into_iter()
        .map(|index| {
            let mut invalid = raw.clone();
            invalid[index] ^= 1;
            // These mutations must reach authorization, not a decoder rejection.
            assert!(decode(&invalid).is_ok());
            invalid
        })
        .collect();
    let ready = Barrier::new(4);
    // The first instance has already initialized the key. This checks concurrent
    // use and separate real checks, not a race to initialize an empty OnceLock.
    std::thread::scope(|scope| {
        for _ in 0..4 {
            let raw = &raw;
            let changed = &changed;
            let ready = &ready;
            let key = first.key;
            scope.spawn(move || {
                let verifier = AuthorizationVerifier::new();
                ready.wait();
                assert!(std::ptr::eq(verifier.key, key));
                assert_eq!(verifier.key.circuit_version(), CIRCUIT);
                assert!(!verifier.verified.contains(raw, digest).unwrap());
                assert_eq!(verifier.verify(raw), Ok(digest));
                assert!(verifier.verified.contains(raw, digest).unwrap());
                for invalid in changed {
                    let invalid_digest = payload_digest(invalid);
                    assert!(!verifier.verified.contains(invalid, invalid_digest).unwrap());
                    assert_eq!(verifier.verify(invalid), Err(WireError::Authorization));
                    assert!(!verifier.verified.contains(invalid, invalid_digest).unwrap());
                    assert_eq!(verifier.verify(raw), Ok(digest));
                }
            });
        }
    });
    assert!(!existing.verified.contains(&raw, digest).unwrap());
    assert_eq!(existing.verify(&raw), Ok(digest));
    assert!(existing.verified.contains(&raw, digest).unwrap());
    assert!(!AuthorizationVerifier::new()
        .verified
        .contains(&raw, digest)
        .unwrap());
    assert_eq!(first.verify(&raw), Ok(digest));
}
