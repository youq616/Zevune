//! Public, zero-value fixture for the cross-process consensus test. No issuance.
use orchard::builder::{Builder, BundleType};
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, Scope, SpendingKey};
use orchard::value::NoteValue;
use orchard::Anchor;
use rand::{rngs::OsRng, RngCore};
use std::fs::OpenOptions;
use std::io::Write;
use zevune_orchard_lab::wire::{encode, AuthorizationVerifier};
use zevune_orchard_lab::{signing_digest, Context, CIRCUIT, NETWORK, VERSION};
#[test]
fn zero_value_real_proof_for_consensus() {
    let key = loop {
        let mut b = [0; 32]; OsRng.fill_bytes(&mut b);
        if let Some(k) = Option::<SpendingKey>::from(SpendingKey::from_bytes(b)) { break k; }
    };
    let address = FullViewingKey::from(&key).address_at(0u32, Scope::External);
    let mut builder = Builder::new(BundleType::DEFAULT, VERSION, VERSION.default_flags(), Anchor::empty_tree()).unwrap();
    builder.add_output(None, address, NoteValue::from_raw(0), [0; 512]).unwrap();
    let bundle = builder.build::<i64>(OsRng).unwrap().unwrap().0;
    let context = Context { network: NETWORK.into(), expiry_height: 9999, fee: 0 };
    let digest = signing_digest(&bundle, &context).unwrap();
    let signed = bundle.create_proof(&ProvingKey::build(CIRCUIT), OsRng).unwrap().apply_signatures(OsRng, digest, &[]).unwrap();
    let wire = encode(&signed, &context).unwrap();
    AuthorizationVerifier::new().verify(&wire).unwrap();
    assert_eq!(*signed.value_balance(), 0); assert_eq!(signed.actions().len(), 2);
    // Only already-public signed transaction data can be exported by this test.
    if let Some(path) = std::env::var_os("ZEVUNE_POOL_FIXTURE") {
        let mut f = OpenOptions::new().create_new(true).write(true).open(path).unwrap();
        f.write_all(&wire).unwrap(); f.sync_all().unwrap();
    }
}
