//! Real authorization tests. Starting notes/keys exist only in this test process.
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::process::{Command, Stdio};

use orchard::builder::{Builder, BundleType};
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, Scope, SpendAuthorizingKey};
use orchard::tree::MerkleHashOrchard;
use orchard::value::NoteValue;
use rand::rngs::OsRng;
use zevune_orchard_lab::domain::{
    self, Domain, Error, NetworkKind, Verifier, DOMAIN_SIZE, PREFIX_SIZE,
};
use zevune_orchard_lab::{wire, CIRCUIT, VERSION};

#[path = "support/fixtures.rs"]
mod fixtures;

fn test_domain() -> Domain {
    Domain::new(NetworkKind::Test, [0x11; 32], [0x22; 32], 17).unwrap()
}
fn hex(raw: &[u8]) -> String {
    raw.iter().map(|v| format!("{v:02x}")).collect()
}
#[test]
fn independent_transcript_vector() {
    let fields: Vec<_> = include_str!("../../../testdata/domain-v1.txt")
        .lines()
        .collect();
    assert_eq!(fields.len(), 6);
    let d = test_domain();
    assert_eq!(hex(d.as_bytes()), fields[0]);
    assert_eq!(hex(&d.id()), fields[1]);
    assert_eq!(fields[2], "100");
    assert_eq!(fields[3], "1000");
    assert_eq!(hex(&[0x33; 32]), fields[4]);
    assert_eq!(
        hex(&d.digest_for_commitment(100, 1000, [0x33; 32]).unwrap()),
        fields[5]
    );
}
#[test]
fn descriptor_canonicality_and_unknown_suites_fail_closed() {
    let d = test_domain();
    let raw = d.as_bytes();
    for end in 0..DOMAIN_SIZE {
        assert!(Domain::decode(&raw[..end]).is_err());
    }
    let mut extended = raw.to_vec();
    extended.push(0);
    assert!(Domain::decode(&extended).is_err());
    for index in [0, 8, 77, 78] {
        let mut changed = *raw;
        changed[index] = 255;
        assert!(Domain::decode(&changed).is_err());
    }
    for range in [9..41, 41..73, 73..77] {
        let mut changed = *raw;
        changed[range].fill(0);
        assert!(Domain::decode(&changed).is_err());
    }
    assert_eq!(Domain::decode(raw).unwrap(), d);
}
#[test]
fn every_domain_component_is_in_the_transcript() {
    let d = test_domain();
    let original = d.digest_for_commitment(100, 1000, [0x33; 32]).unwrap();
    for index in [8, 9, 40, 41, 72, 76] {
        let mut changed = *d.as_bytes();
        changed[index] ^= 1;
        if index == 8 {
            changed[index] = NetworkKind::Development as u8;
        }
        let next = Domain::decode(&changed).unwrap();
        assert_ne!(next.id(), d.id());
        assert_ne!(
            next.digest_for_commitment(100, 1000, [0x33; 32]).unwrap(),
            original
        );
    }
}
#[test]
fn signing_metadata_limits_are_explicit() {
    let d = test_domain();
    assert_eq!(d.digest_for_commitment(0, 0, [0; 32]), Err(Error::Metadata));
    assert_eq!(
        d.digest_for_commitment(1, u64::MAX, [0; 32]),
        Err(Error::Metadata)
    );
    assert!(d
        .digest_for_commitment(u64::MAX, i64::MAX as u64, [0; 32])
        .is_ok());
    let original = d.digest_for_commitment(100, 1000, [0x33; 32]).unwrap();
    for value in [
        d.digest_for_commitment(101, 1000, [0x33; 32]),
        d.digest_for_commitment(100, 1001, [0x33; 32]),
        d.digest_for_commitment(100, 1000, [0x34; 32]),
    ] {
        assert_ne!(value.unwrap(), original);
    }
}

fn check_process(domain: &Domain, raw: &[u8], opt_in: bool) -> std::process::Output {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_zevune-domain-check"));
    if opt_in {
        cmd.arg("--no-real-funds");
    }
    cmd.arg("--domain-hex").arg(hex(domain.as_bytes()));
    let mut child = cmd
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    // Invalid command lines may close stdin immediately.
    let _ = child.stdin.take().unwrap().write_all(raw);
    child.wait_with_output().unwrap()
}

#[test]
fn real_proof_rejects_domain_transplant_legacy_wrapping_and_tampering() {
    let d = test_domain();
    let owner = fixtures::key();
    let receiver = fixtures::key();
    let sender = FullViewingKey::from(&owner).address_at(0u32, Scope::External);
    let recipient = FullViewingKey::from(&receiver).address_at(0u32, Scope::External);
    let note = fixtures::genesis_note(sender);
    let leaf = MerkleHashOrchard::from_cmx(&note.commitment().into());
    let (path, anchor) = fixtures::witness(&[leaf], 0);
    let ctx = fixtures::context();
    let pk = ProvingKey::build(CIRCUIT);
    let mut builder = Builder::new(
        BundleType::DEFAULT,
        VERSION,
        VERSION.default_flags(),
        anchor,
    )
    .unwrap();
    builder
        .add_spend(FullViewingKey::from(&owner), note, path.clone())
        .unwrap();
    builder
        .add_output(None, recipient, NoteValue::from_raw(60_000), [0; 512])
        .unwrap();
    builder
        .add_output(None, sender, NoteValue::from_raw(39_000), [0; 512])
        .unwrap();
    let unsigned = builder.build::<i64>(OsRng).unwrap().unwrap().0;
    let digest = d.signing_digest(&unsigned, &ctx).unwrap();
    let signed = unsigned
        .create_proof(&pk, OsRng)
        .unwrap()
        .apply_signatures(OsRng, digest, &[SpendAuthorizingKey::from(&owner)])
        .unwrap();
    let raw = domain::encode(&signed, &ctx, &d).unwrap();
    let verifier = Verifier::new(d.clone());
    let payload = verifier.verify(&raw).unwrap();
    assert_eq!(payload, wire::payload_digest(&raw));
    assert_eq!(
        domain::encode(&domain::decode(&raw, &d).unwrap().bundle, &ctx, &d).unwrap(),
        raw
    );
    // Both real signatures and real proof were checked, not only a hash prefix.
    for index in [
        PREFIX_SIZE + 15,
        PREFIX_SIZE + 23,
        PREFIX_SIZE + 31,
        PREFIX_SIZE + wire::HEADER_SIZE + 160,
        PREFIX_SIZE + wire::HEADER_SIZE + 820,
        PREFIX_SIZE + wire::HEADER_SIZE + 2 * wire::ACTION_SIZE + 4,
        raw.len() - 1,
    ] {
        let mut changed = raw.clone();
        changed[index] ^= 1;
        assert!(
            verifier.verify(&changed).is_err(),
            "accepted changed byte {index}"
        );
    }
    let mut fee = raw.clone();
    fee[PREFIX_SIZE + 23] ^= 1;
    fee[PREFIX_SIZE + 31] ^= 1;
    assert_eq!(verifier.verify(&fee), Err(Error::Authorization));
    for end in 0..raw.len() {
        assert!(domain::decode(&raw[..end], &d).is_err());
    }
    let mut extra = raw.clone();
    extra.push(0);
    assert!(verifier.verify(&extra).is_err());
    // Retain identical Orchard commitment/anchor and overwrite only the domain
    // header. A valid proof alone cannot transplant the spend authority.
    let foreign = Domain::new(NetworkKind::Test, [0x44; 32], [0x22; 32], 17).unwrap();
    let foreign_verifier = Verifier::new(foreign.clone());
    assert_eq!(foreign_verifier.verify(&raw), Err(Error::Domain));
    let mut transplanted = raw.clone();
    transplanted[8..PREFIX_SIZE].copy_from_slice(&foreign.id());
    assert!(domain::decode(&transplanted, &foreign).is_ok());
    assert_eq!(
        foreign_verifier.verify(&transplanted),
        Err(Error::Authorization)
    );
    // Changing rules/kind/epoch still invalidates all authorization signatures.
    for changed in [
        Domain::new(NetworkKind::Development, [0x11; 32], [0x22; 32], 17).unwrap(),
        Domain::new(NetworkKind::Test, [0x11; 32], [0x55; 32], 17).unwrap(),
        Domain::new(NetworkKind::Test, [0x11; 32], [0x22; 32], 18).unwrap(),
    ] {
        let other = changed.signing_digest(&signed, &ctx).unwrap();
        for action in signed.actions().iter() {
            assert!(action.rk().verify(&other, action.authorization()).is_err());
        }
        assert!(signed
            .binding_validating_key()
            .verify(&other, signed.authorization().binding_signature())
            .is_err());
    }
    let legacy_verifier = wire::AuthorizationVerifier::new();
    assert!(legacy_verifier.verify(&raw).is_err());
    assert!(legacy_verifier.verify(&raw[PREFIX_SIZE..]).is_err());
    let legacy = fixtures::prove(
        &pk,
        &owner,
        note,
        path,
        &[(recipient, 60_000), (sender, 39_000)],
        &ctx,
    );
    let legacy_raw = wire::encode(&legacy, &ctx).unwrap();
    legacy_verifier.verify(&legacy_raw).unwrap();
    assert!(verifier.verify(&legacy_raw).is_err());
    let wrapped = domain::encode(&legacy, &ctx, &d).unwrap();
    assert_eq!(verifier.verify(&wrapped), Err(Error::Authorization));
    // CLI executes real checks; it never grants state admission or confirmation.
    let result = check_process(&d, &raw, true);
    assert!(result.status.success());
    let stdout = String::from_utf8(result.stdout).unwrap();
    assert!(stdout.contains("\"authorization_verified\":true"));
    assert!(stdout.contains("\"ledger_checked\":false"));
    assert!(stdout.contains("\"confirmed\":false"));
    assert!(stdout.contains(&hex(&payload)));
    assert!(result.stderr.is_empty());
    for (domain, bytes, opt_in) in [
        (&foreign, raw.as_slice(), true),
        (&d, wrapped.as_slice(), true),
        (&d, raw.as_slice(), false),
    ] {
        let failure = check_process(domain, bytes, opt_in);
        assert!(!failure.status.success());
        assert!(failure.stdout.is_empty());
    }
    // Optional public-only corpus for Go/Rust interop; never export the private
    // genesis opening, seed, keys, witness, decrypted amounts or recovery files.
    if let Some(folder) = std::env::var_os("ZEVUNE_DOMAIN_FIXTURES") {
        let folder = std::path::PathBuf::from(folder);
        fs::create_dir(&folder).unwrap();
        for (name, bytes) in [
            ("domain.bin", d.as_bytes().as_slice()),
            ("foreign-domain.bin", foreign.as_bytes().as_slice()),
            ("transaction.bin", raw.as_slice()),
            ("transplanted.bin", transplanted.as_slice()),
            ("wrapped-legacy.bin", wrapped.as_slice()),
        ] {
            OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(folder.join(name))
                .unwrap()
                .write_all(bytes)
                .unwrap();
        }
    }
}
