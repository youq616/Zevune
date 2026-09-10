//! All initial value exists ONLY in this test fixture. There is no issuance API.
//! Private keys and note plaintexts are generated in process, never printed.
use std::collections::BTreeSet;
use std::time::Instant;

use incrementalmerkletree::{Hashable, Level};
use orchard::builder::{Builder, BundleType};
use orchard::bundle::{Authorized, BundleVersion};
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, Scope, SpendAuthorizingKey, SpendingKey};
use orchard::note::{RandomSeed, Rho};
use orchard::primitives::redpallas::{Binding, Signature, SpendAuth};
use orchard::tree::{MerkleHashOrchard, MerklePath};
use orchard::value::NoteValue;
use orchard::{Action, Address, Anchor, Bundle, Note, NoteVersion, Proof};
use rand::{rngs::OsRng, RngCore};
use zevune_orchard_lab::{signing_digest, Context, Error, StateView, Verifier, CIRCUIT, NETWORK, VERSION};

type Signed = Bundle<Authorized, i64>;

fn key() -> ([u8; 32], SpendingKey) {
    loop {
        let mut bytes = [0; 32];
        OsRng.fill_bytes(&mut bytes);
        if let Some(sk) = Option::<SpendingKey>::from(SpendingKey::from_bytes(bytes)) {
            return (bytes, sk);
        }
    }
}

// Low-level note assembly is confined to the synthetic starting fixture.
// Actual received outputs below MUST use upstream authenticated trial decryption.
fn genesis_note(address: Address) -> Note {
    let rho = Rho::from_bytes(&[0; 32]).unwrap();
    loop {
        let mut raw = [0; 32];
        OsRng.fill_bytes(&mut raw);
        if let Some(seed) = Option::<RandomSeed>::from(RandomSeed::from_bytes(raw, &rho)) {
            if let Some(note) = Option::<Note>::from(Note::from_parts(
                address, NoteValue::from_raw(100_000), rho, seed, NoteVersion::V2,
            )) {
                return note;
            }
        }
    }
}

// Small test witness tree; ALL hashing and empty roots use upstream primitives.
// Not a production tree, snapshot format, wallet database or membership service.
fn witness(leaves: &[MerkleHashOrchard], position: usize) -> (MerklePath, Anchor) {
    assert!(position < leaves.len());
    let mut nodes = leaves.to_vec();
    let mut index = position;
    let mut path = [MerkleHashOrchard::empty_leaf(); 32];
    for (level, sibling) in path.iter_mut().enumerate() {
        let l = Level::from(level as u8);
        *sibling = nodes.get(index ^ 1).copied().unwrap_or_else(|| MerkleHashOrchard::empty_root(l));
        nodes = nodes.chunks(2).map(|pair| {
            let right = pair.get(1).copied().unwrap_or_else(|| MerkleHashOrchard::empty_root(l));
            MerkleHashOrchard::combine(l, &pair[0], &right)
        }).collect();
        index >>= 1;
    }
    (MerklePath::from_parts(position as u32, path), nodes[0].into())
}

fn context(fee: u64) -> Context {
    Context { network: NETWORK.into(), expiry_height: 100, fee }
}

fn prove(
    pk: &ProvingKey,
    sk: &SpendingKey,
    note: Note,
    path: MerklePath,
    outputs: &[(Address, u64)],
    ctx: &Context,
) -> (Signed, f64) {
    let anchor = path.root(note.commitment().into());
    let mut b = Builder::new(BundleType::DEFAULT, VERSION, VERSION.default_flags(), anchor).unwrap();
    b.add_spend(FullViewingKey::from(sk), note, path).unwrap();
    for &(address, value) in outputs {
        // No outgoing recovery key is used for this test scenario. This is NOT
        // a decision about future wallet recovery/disclosure policy.
        b.add_output(None, address, NoteValue::from_raw(value), [0; 512]).unwrap();
    }
    let unauthorized = b.build::<i64>(OsRng).unwrap().unwrap().0;
    let digest = signing_digest(&unauthorized, ctx).unwrap();
    let start = Instant::now();
    let proven = unauthorized.create_proof(pk, OsRng).unwrap();
    let proof_ms = start.elapsed().as_secs_f64() * 1000.0;
    let signed = proven.apply_signatures(OsRng, digest, &[SpendAuthorizingKey::from(sk)]).unwrap();
    (signed, proof_ms)
}

fn rebuild(bundle: &Signed, auth: Authorized, anchor: Anchor, version: BundleVersion) -> Result<Signed, orchard::bundle::BundleError> {
    Bundle::try_from_parts(bundle.actions().clone(), *bundle.flags(), *bundle.value_balance(), anchor, auth, version)
}

fn corrupted_ciphertext(bundle: &Signed) -> Signed {
    let mut actions = bundle.actions().clone();
    let a = &actions.head;
    let mut ciphertext = a.encrypted_note().clone();
    ciphertext.enc_ciphertext[17] ^= 1;
    actions.head = Action::from_parts(*a.nullifier(), a.rk().clone(), *a.cmx(), ciphertext, a.cv_net().clone(), a.authorization().clone()).unwrap();
    Bundle::try_from_parts(actions, *bundle.flags(), *bundle.value_balance(), *bundle.anchor(), bundle.authorization().clone(), VERSION).unwrap()
}

#[test]
fn upstream_public_empty_root_vectors() {
    // Public vectors from zcash/orchard tag 0.15.5, src/test_vectors/commitment_tree.rs.
    // First two non-leaf roots; upstream code is MIT OR Apache-2.0, see NOTICE.md.
    let expected = [
        [0xd1,0xab,0x25,0x07,0xc8,0x09,0xc2,0x71,0x3c,0x00,0x0f,0x52,0x5e,0x9f,0xbd,0xcb,0x06,0xc9,0x58,0x38,0x4e,0x51,0xb9,0xcc,0x7f,0x79,0x2d,0xde,0x6c,0x97,0xf4,0x11],
        [0xc7,0x41,0x3f,0x46,0x14,0xcd,0x64,0x04,0x3a,0xbb,0xab,0x7c,0xc1,0x09,0x5c,0x9b,0xb1,0x04,0x23,0x1c,0xea,0x89,0xe2,0xc3,0xe0,0xdf,0x83,0x76,0x95,0x56,0xd0,0x30],
    ];
    for (i, bytes) in expected.iter().enumerate() {
        assert_eq!(&MerkleHashOrchard::empty_root(Level::from((i + 1) as u8)).to_bytes(), bytes);
    }
    assert!(Option::<Anchor>::from(Anchor::from_bytes([255;32])).is_none());
}

#[test]
fn raw_key_reconstruction_preserves_local_receiver() {
    let (mut bytes, sk) = key();
    let original = FullViewingKey::from(&sk).address_at(7u32, Scope::External);
    let restored = SpendingKey::from_bytes(bytes).unwrap();
    assert!(original == FullViewingKey::from(&restored).address_at(7u32, Scope::External));
    bytes.fill(0); // Not a secure-erasure claim: stack/compiler copies may remain.
}

#[test]
fn builder_rejects_wrong_owner_and_nonmember_path() {
    let (_, owner) = key();
    let (_, outsider) = key();
    let fvk = FullViewingKey::from(&owner);
    let note = genesis_note(fvk.address_at(0u32, Scope::External));
    let leaves = [MerkleHashOrchard::from_cmx(&note.commitment().into())];
    let (path, anchor) = witness(&leaves, 0);
    let mut b = Builder::new(BundleType::DEFAULT, VERSION, VERSION.default_flags(), anchor).unwrap();
    assert!(b.add_spend(FullViewingKey::from(&outsider), note, path.clone()).is_err());
    let mut b = Builder::new(BundleType::DEFAULT, VERSION, VERSION.default_flags(), Anchor::empty_tree()).unwrap();
    assert!(b.add_spend(fvk, note, path).is_err());
}

#[test]
fn real_proofs_two_hops_and_adversarial_cases() {
    let key_start = Instant::now();
    let pk = ProvingKey::build(CIRCUIT);
    let verifier = Verifier::new();
    let keys_ms = key_start.elapsed().as_secs_f64() * 1000.0;
    let (_, alice) = key();
    let (mut bob_bytes, bob) = key();
    let (_, carol) = key();
    let (_, stranger) = key();
    let afvk = FullViewingKey::from(&alice);
    let bfvk = FullViewingKey::from(&bob);
    let cfvk = FullViewingKey::from(&carol);
    let a_addr = afvk.address_at(0u32, Scope::External);
    let b_addr = bfvk.address_at(0u32, Scope::External);
    let c_addr = cfvk.address_at(0u32, Scope::External);
    let initial = genesis_note(a_addr);
    let mut leaves = vec![MerkleHashOrchard::from_cmx(&initial.commitment().into())];
    let (path, root) = witness(&leaves, 0);
    let mut anchors = vec![root.to_bytes()];
    let mut spent = BTreeSet::new();
    let mut outputs: BTreeSet<_> = leaves.iter().map(MerkleHashOrchard::to_bytes).collect();
    let ctx = context(1_000);
    let (first, proof1_ms) = prove(&pk, &alice, initial, path.clone(), &[(b_addr, 60_000), (a_addr, 39_000)], &ctx);
    assert_eq!(first.actions().len(), 2);
    assert_eq!(first.authorization().proof().as_ref().len(), Proof::expected_proof_size(2));
    let view = StateView { height: 0, anchors: &anchors, spent: &spent, outputs: &outputs };
    let verify_start = Instant::now();
    let effects = verifier.verify(&first, &ctx, &view).unwrap();
    let verify1_ms = verify_start.elapsed().as_secs_f64() * 1000.0;
    assert_eq!(effects.fee, 1_000);
    assert!(spent.is_empty()); // Verification itself does not change committed state.
    println!("M4_PHASE valid_proof_and_signatures_and_read_only_check: passed");

    let decrypt_start = Instant::now();
    let incoming = bfvk.to_ivk(Scope::External);
    let received = first.decrypt_outputs_with_keys(std::slice::from_ref(&incoming));
    assert_eq!(received.len(), 1);
    assert!(received[0].2.value().inner() == 60_000 && received[0].3 == b_addr);
    let bob_index = received[0].0;
    let bob_note = received[0].2;
    let decrypt1_ms = decrypt_start.elapsed().as_secs_f64() * 1000.0;
    assert!(first.decrypt_outputs_with_keys(&[FullViewingKey::from(&stranger).to_ivk(Scope::External)]).is_empty());
    let change = first.decrypt_outputs_with_keys(&[afvk.to_ivk(Scope::External)]);
    assert!(change.len() == 1 && change[0].2.value().inner() == 39_000);
    let restored_bob = SpendingKey::from_bytes(bob_bytes).unwrap();
    bob_bytes.fill(0);
    assert!(first.decrypt_outputs_with_keys(&[FullViewingKey::from(&restored_bob).to_ivk(Scope::External)])[0].2 == bob_note);
    println!("M4_PHASE recipient_decryption_change_wrong_key_and_raw_key_recovery: passed");

    let mut foreign = ctx.clone(); foreign.network = "other-network".into();
    assert_eq!(verifier.verify(&first, &foreign, &view), Err(Error::Network));
    let mut changed_expiry = ctx.clone(); changed_expiry.expiry_height += 1;
    assert_eq!(verifier.verify(&first, &changed_expiry, &view), Err(Error::Authorization));
    let expired = StateView { height: 100, ..view };
    assert_eq!(verifier.verify(&first, &ctx, &expired), Err(Error::Expired));
    let overflow = StateView { height: u64::MAX, ..view };
    assert_eq!(verifier.verify(&first, &ctx, &overflow), Err(Error::Expired));
    let unknown = [Anchor::empty_tree().to_bytes()];
    let missing = StateView { anchors: &unknown, ..view };
    assert_eq!(verifier.verify(&first, &ctx, &missing), Err(Error::Anchor));
    let too_many = vec![root.to_bytes(); 65];
    assert_eq!(verifier.verify(&first, &ctx, &StateView { anchors: &too_many, ..view }), Err(Error::Anchor));
    let mut wrong_fee = ctx.clone(); wrong_fee.fee += 1;
    assert_eq!(verifier.verify(&first, &wrong_fee, &view), Err(Error::Fee));
    wrong_fee.fee = u64::MAX;
    assert_eq!(verifier.verify(&first, &wrong_fee, &view), Err(Error::Fee));
    let changed_balance = first.clone().try_map_value_balance(|v| Ok::<_, std::convert::Infallible>(v + 1)).unwrap();
    assert_eq!(verifier.verify(&changed_balance, &ctx, &view), Err(Error::Fee));
    let matching_wrong_fee = context(1_001);
    assert_eq!(verifier.verify(&changed_balance, &matching_wrong_fee, &view), Err(Error::Authorization));
    println!("M4_PHASE network_expiry_anchor_and_value_balance_rejections: passed");

    let mut proof = first.authorization().proof().as_ref().to_vec();
    proof[0] ^= 1;
    let broken = rebuild(&first, Authorized::from_parts(Proof::new(proof), first.authorization().binding_signature().clone()), *first.anchor(), VERSION).unwrap();
    assert_eq!(verifier.verify(&broken, &ctx, &view), Err(Error::Authorization));
    for extra in [false, true] {
        let mut proof = first.authorization().proof().as_ref().to_vec();
        if extra { proof.push(0); } else { proof.pop(); }
        assert!(rebuild(&first, Authorized::from_parts(Proof::new(proof), first.authorization().binding_signature().clone()), *first.anchor(), VERSION).is_err());
    }
    let unsigned = first.clone().map_authorization(&mut (), |_, _, _| Signature::<SpendAuth>::from([0;64]), |_, auth| auth);
    assert_eq!(verifier.verify(&unsigned, &ctx, &view), Err(Error::Authorization));
    let broken_binding = rebuild(&first, Authorized::from_parts(first.authorization().proof().clone(), Signature::<Binding>::from([0;64])), *first.anchor(), VERSION).unwrap();
    assert_eq!(verifier.verify(&broken_binding, &ctx, &view), Err(Error::Authorization));
    let changed_ciphertext = corrupted_ciphertext(&first);
    assert_eq!(verifier.verify(&changed_ciphertext, &ctx, &view), Err(Error::Authorization));
    // V2 historical context is not inferred from the bundle; our boundary is fixed.
    let insecure = rebuild(&first, first.authorization().clone(), *first.anchor(), BundleVersion::orchard_insecure_v1()).unwrap();
    assert_eq!(verifier.verify(&insecure, &ctx, &view), Err(Error::Version));
    let anchor_changed = rebuild(&first, first.authorization().clone(), Anchor::empty_tree(), VERSION).unwrap();
    assert_eq!(verifier.verify(&anchor_changed, &ctx, &missing), Err(Error::Authorization));
    println!("M4_PHASE corrupted_proof_noncanonical_length_signatures_ciphertext_and_version: passed");

    let mut repeated_actions = first.actions().clone();
    repeated_actions.tail[0] = repeated_actions.head.clone();
    let duplicate_action = Bundle::try_from_parts(repeated_actions, *first.flags(), *first.value_balance(), *first.anchor(), first.authorization().clone(), VERSION).unwrap();
    assert_eq!(verifier.verify(&duplicate_action, &ctx, &view), Err(Error::DoubleSpend));
    let mut already_output = outputs.clone(); already_output.insert(effects.commitments[0]);
    let repeated_output = StateView { outputs: &already_output, ..view };
    assert_eq!(verifier.verify(&first, &ctx, &repeated_output), Err(Error::DuplicateOutput));

    // Real proof with negative pool delta: upstream alone may allow external
    // funding. This single-asset lab has NO external funding or minting path.
    let (unbacked, proof_negative_ms) = prove(&pk, &alice, initial, path, &[(b_addr, 101_000)], &context(0));
    assert!(*unbacked.value_balance() < 0);
    assert!(unbacked.verify_proof(&orchard::circuit::VerifyingKey::build(CIRCUIT)).is_ok());
    assert_eq!(verifier.verify(&unbacked, &context(0), &view), Err(Error::Fee));
    println!("M4_PHASE duplicate_checks_and_real_proof_unbacked_pool_delta_rejection: passed");

    // Simulated application of VERIFIED public effects, only in this test.
    spent.extend(effects.nullifiers.iter().copied());
    outputs.extend(effects.commitments.iter().copied());
    leaves.extend(first.actions().iter().map(|a| MerkleHashOrchard::from_cmx(a.cmx())));
    let (bob_path, new_root) = witness(&leaves, 1 + bob_index);
    assert!(bob_path.root(bob_note.commitment().into()) == new_root);
    anchors.push(new_root.to_bytes());
    let after_first = StateView { height: 1, anchors: &anchors, spent: &spent, outputs: &outputs };
    assert_eq!(verifier.verify(&first, &ctx, &after_first), Err(Error::DoubleSpend));
    // Proof remains cryptographically valid: double-spend rejection is a ledger check.
    assert!(first.verify_proof(&orchard::circuit::VerifyingKey::build(CIRCUIT)).is_ok());
    let (second, proof2_ms) = prove(&pk, &restored_bob, bob_note, bob_path, &[(c_addr, 59_000)], &ctx);
    let second_start = Instant::now();
    let second_effects = verifier.verify(&second, &ctx, &after_first).unwrap();
    let verify2_ms = second_start.elapsed().as_secs_f64() * 1000.0;
    assert!(second_effects.nullifiers.iter().all(|n| !spent.contains(n)));
    let received_by_carol = second.decrypt_outputs_with_keys(&[cfvk.to_ivk(Scope::External)]);
    assert!(received_by_carol.len() == 1 && received_by_carol[0].2.value().inner() == 59_000);
    assert!(second.decrypt_outputs_with_keys(&[afvk.to_ivk(Scope::External)]).is_empty());
    println!("M4_PHASE verified_receiver_note_can_be_spent_onward: passed");
    println!("M4_METRICS {{\"scope\":\"single_process_real_crypto_not_network_latency\",\"key_build_ms\":{keys_ms:.3},\"first_proof_ms\":{proof1_ms:.3},\"second_proof_ms\":{proof2_ms:.3},\"negative_delta_proof_ms\":{proof_negative_ms:.3},\"first_verify_ms\":{verify1_ms:.3},\"second_verify_ms\":{verify2_ms:.3},\"first_recipient_scan_ms\":{decrypt1_ms:.3},\"actions_per_valid_bundle\":2,\"proof_bytes\":{}}}", Proof::expected_proof_size(2));
}
