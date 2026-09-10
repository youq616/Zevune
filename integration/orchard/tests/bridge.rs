//! Actual cryptography and actual bytes; fixture secrets stay inside this test.
#[path = "support/fixtures.rs"]
mod fixtures;
use fixtures::{context, genesis_note, key, prove, witness};
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, Scope};
use orchard::tree::MerkleHashOrchard;
use std::collections::BTreeSet;
use std::fs::OpenOptions;
use std::io::{Cursor, Write};
use std::path::Path;
use zevune_orchard_lab::wire::{
    decode, encode, AuthorizationVerifier, ACTION_SIZE, HEADER_SIZE, MAX_ENVELOPE_SIZE,
};
use zevune_orchard_lab::worker;
use zevune_orchard_lab::{StateView, Verifier, CIRCUIT};

#[test]
fn real_wire_roundtrip_individual_authorization_and_rejections() {
    let owner = key();
    let recipient = key();
    let fvk = FullViewingKey::from(&owner);
    let initial = genesis_note(fvk.address_at(0u32, Scope::External));
    let leaves = [MerkleHashOrchard::from_cmx(&initial.commitment().into())];
    let (path, _) = witness(&leaves, 0);
    let pk = ProvingKey::build(CIRCUIT);
    let ctx = context();
    let bundle = prove(
        &pk,
        &owner,
        initial,
        path,
        &[
            (
                FullViewingKey::from(&recipient).address_at(0u32, Scope::External),
                60_000,
            ),
            (fvk.address_at(0u32, Scope::External), 39_000),
        ],
        &ctx,
    );
    let raw = encode(&bundle, &ctx).unwrap();
    assert_eq!(raw.len(), 9_166);
    let decoded = decode(&raw).unwrap();
    assert_eq!(encode(&decoded.bundle, &decoded.context).unwrap(), raw);
    let verifier = AuthorizationVerifier::new();
    let digest = verifier.verify(&raw).unwrap();
    assert_eq!(digest, zevune_orchard_lab::wire::payload_digest(&raw));
    assert!(Verifier::new()
        .verify(
            &bundle,
            &ctx,
            &StateView {
                height: 0,
                anchors: &[bundle.anchor().to_bytes()],
                spent: &BTreeSet::new(),
                outputs: &BTreeSet::new(),
            }
        )
        .is_ok());
    for n in 0..raw.len() {
        assert!(decode(&raw[..n]).is_err());
    }
    let mut appended = raw.clone();
    appended.push(0);
    assert!(decode(&appended).is_err());
    assert!(decode(&vec![0; MAX_ENVELOPE_SIZE + 1]).is_err());
    for offset in [
        HEADER_SIZE + 2 * ACTION_SIZE + 4,
        HEADER_SIZE + 820,
        raw.len() - 1,
        15,
        23,
        HEADER_SIZE + 160,
    ] {
        let mut altered = raw.clone();
        altered[offset] ^= 1;
        assert!(verifier.verify(&altered).is_err());
    }
    for offset in [
        32,
        HEADER_SIZE,
        HEADER_SIZE + 32,
        HEADER_SIZE + 64,
        HEADER_SIZE + 96,
        HEADER_SIZE + 128,
    ] {
        let mut altered = raw.clone();
        altered[offset..offset + 32].fill(255);
        assert!(decode(&altered).is_err());
    }
    for offset in [HEADER_SIZE + 64, HEADER_SIZE + 128] {
        let mut altered = raw.clone();
        altered[offset..offset + 32].fill(0);
        assert!(decode(&altered).is_err());
    }
    let mut request = Vec::from(*worker::REQUEST_MAGIC);
    request.extend_from_slice(&1u64.to_be_bytes());
    request.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    request.extend_from_slice(&raw);
    let mut input = Vec::new();
    worker::write_frame(&mut input, &request).unwrap();
    let mut output = Vec::new();
    worker::serve(&mut Cursor::new(input), &mut output).unwrap();
    let mut output = Cursor::new(output);
    let hello = worker::read_frame(&mut output, 40).unwrap().unwrap();
    assert_eq!(hello.len(), 40);
    let response = worker::read_frame(&mut output, 49).unwrap().unwrap();
    assert_eq!(&response[..8], worker::RESPONSE_MAGIC);
    assert_eq!(response[16], 0);
    assert_eq!(&response[17..], &digest);
    // Only signed public bytes are handed to the Go test. No recipient mapping,
    // key, decrypted note, witness, or seed leaves this test process.
    if let Some(dir) = std::env::var_os("ZEVUNE_PUBLIC_FIXTURE_DIR") {
        let path = Path::new(&dir).join("authorized.bin");
        let mut f = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(path)
            .unwrap();
        f.write_all(&raw).unwrap();
        f.sync_all().unwrap();
    }
}
