//! Public-only worker framing and state rejection checks. No real wallet data.
use rand::{rngs::OsRng, RngCore};
use serde_json::{json, Value};
use std::io::Cursor;
use std::path::PathBuf;
use zevune_payment_lab::{
    store::Store,
    wallet::{create_genesis, Wallet},
    wire::Transaction,
    worker, Error,
};
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        let mut id = [0; 16];
        OsRng.fill_bytes(&mut id);
        let p = std::env::temp_dir().join(format!("zevune-ipc-test-{}", hex::encode(id)));
        std::fs::create_dir(&p).unwrap();
        Self(p)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn frame(value: Value) -> Vec<u8> {
    let body = serde_json::to_vec(&value).unwrap();
    let mut bytes = (body.len() as u32).to_be_bytes().to_vec();
    bytes.extend_from_slice(&body);
    bytes
}
fn replies(bytes: &[u8]) -> Vec<Value> {
    let mut out = vec![];
    let mut pos = 0;
    while pos < bytes.len() {
        let n = u32::from_be_bytes(bytes[pos..pos + 4].try_into().unwrap()) as usize;
        pos += 4;
        out.push(serde_json::from_slice(&bytes[pos..pos + n]).unwrap());
        pos += n;
    }
    out
}
#[test]
fn worker_has_no_private_key_or_issuance_operations() {
    let dir = Temp::new();
    let genesis = create_genesis(Wallet::generate().address()).unwrap();
    let home = dir.0.join("worker");
    let store = Store::open(&home, &genesis).unwrap();
    let baseline = store.ledger.summary();
    let mut input = frame(json!({"op":"info","id":1}));
    input.extend(frame(json!({"op":"check","id":2,"tx":"00"})));
    input.extend(frame(json!({"op":"info","id":3})));
    let mut output = Vec::new();
    worker::serve(store, Cursor::new(input), &mut output).unwrap();
    let responses = replies(&output);
    assert_eq!(responses.len(), 3);
    assert_eq!(responses[0]["id"], 1);
    assert_eq!(responses[1]["ok"], false);
    assert_eq!(responses[1]["error"], "rejected");
    assert_eq!(responses[0]["data"], responses[2]["data"]);
    for op in ["prove", "wallet-new", "mint", "export-viewing-key"] {
        let store = Store::open(&home, &genesis).unwrap();
        let result = worker::serve(
            store,
            Cursor::new(frame(json!({"op":op,"id":4}))),
            Vec::new(),
        );
        assert!(matches!(result, Err(Error::Encoding)));
    }
    let store = Store::open(&home, &genesis).unwrap();
    assert_eq!(store.ledger.summary(), baseline);
    assert!(matches!(
        worker::serve(store, Cursor::new(600001u32.to_be_bytes()), Vec::new()),
        Err(Error::Limit)
    ));
    let store = Store::open(&home, &genesis).unwrap();
    assert!(matches!(
        worker::serve(store, Cursor::new(vec![0, 1]), Vec::new()),
        Err(Error::Encoding)
    ));
    let store = Store::open(&home, &genesis).unwrap();
    assert_eq!(store.ledger.summary(), baseline);
}
#[test]
fn random_untrusted_bytes_do_not_panic_or_decode_to_another_encoding() {
    for n in 0..2048usize {
        let mut data = vec![0u8; n % 1024];
        OsRng.fill_bytes(&mut data);
        if n % 2 == 0 && data.len() >= 4 {
            data[..4].copy_from_slice(b"ZVP1");
        }
        if let Ok(tx) = Transaction::decode(&data) {
            assert_eq!(tx.encode().unwrap(), data);
        }
    }
}
