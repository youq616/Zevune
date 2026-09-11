#![cfg(feature = "local-funding-lab")]

//! Real local operator processes. Test passwords are public constants; generated
//! wallet seeds and witnesses are never printed or stored without encryption.
use rand::{rngs::OsRng, RngCore};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use zevune_orchard_lab::pool::testnet::TestGenesis;
use zevune_orchard_lab::pool::PoolError;
use zevune_orchard_lab::wire::AuthorizationVerifier;

const PASSWORD: &[u8] = b"synthetic-operator-test-password";
struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let name: String = random.iter().map(|b| format!("{b:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-cli-test-{name}"));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self, name: &str) -> String {
        self.0.join(name).to_str().unwrap().into()
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn request(op: u8, password: &[u8], fields: &[&str], pin: Option<&str>) -> Vec<u8> {
    let mut raw = b"ZVWCLI01".to_vec();
    raw.push(op);
    raw.extend_from_slice(&(password.len() as u16).to_be_bytes());
    raw.extend_from_slice(password);
    raw.push(u8::from(pin.is_some()));
    if let Some(pin) = pin {
        raw.extend_from_slice(&unhex(pin));
    }
    raw.push(fields.len() as u8);
    for field in fields {
        raw.extend_from_slice(&(field.len() as u16).to_be_bytes());
        raw.extend_from_slice(field.as_bytes());
    }
    raw
}
fn invoke(raw: &[u8], opt_in: bool) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_zevune-wallet-local"));
    if opt_in {
        command.arg("--no-real-funds");
    }
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    // The opt-in rejection may exit before reading; no secret is put in argv.
    let _ = child.stdin.take().unwrap().write_all(raw);
    child.wait_with_output().unwrap()
}
fn call(op: u8, fields: &[&str], pin: Option<&str>) -> String {
    let result = invoke(&request(op, PASSWORD, fields, pin), true);
    assert!(result.status.success(), "local operator did not succeed");
    assert!(result.stderr.is_empty());
    assert!(!result.stdout.windows(PASSWORD.len()).any(|b| b == PASSWORD));
    let text = String::from_utf8(result.stdout).unwrap();
    assert!(text.starts_with("{\"ok\":true,\"scope\":\"local_journal_only_no_funds\","));
    text
}
fn rejects(raw: &[u8]) {
    let result = invoke(raw, true);
    assert!(!result.status.success());
    assert!(result.stdout.is_empty());
    assert!(!result.stderr.windows(PASSWORD.len()).any(|b| b == PASSWORD));
}
fn text_field(text: &str, key: &str) -> String {
    let prefix = format!("\"{key}\":\"");
    text.split_once(&prefix)
        .unwrap()
        .1
        .split_once('"')
        .unwrap()
        .0
        .into()
}
fn unhex(text: &str) -> Vec<u8> {
    text.as_bytes()
        .chunks(2)
        .map(|b| u8::from_str_radix(std::str::from_utf8(b).unwrap(), 16).unwrap())
        .collect()
}
fn has_number(text: &str, key: &str, value: u64) -> bool {
    text.contains(&format!("\"{key}\":{value},"))
}

#[test]
fn malformed_requests_and_missing_opt_in_never_create_wallets() {
    let dir = Dir::new();
    let wallet = dir.path("never-created.zwallet");
    let raw = request(0, PASSWORD, &[&wallet], None);
    assert!(!invoke(&raw, false).status.success());
    for n in [0, 1, 8, 9, 10, 11, raw.len() - 1] {
        rejects(&raw[..n]);
    }
    let mut changed = raw.clone();
    changed.push(0);
    rejects(&changed);
    changed = raw.clone();
    changed[8] = 255;
    rejects(&changed);
    rejects(&vec![0; 16_385]);
    rejects(&request(0, b"short", &[&wallet], None));
    rejects(&request(0, PASSWORD, &["relative.zwallet"], None));
    assert!(!Path::new(&wallet).exists());
}

#[test]
fn encrypted_backup_restore_addresses_and_wrong_password() {
    let dir = Dir::new();
    let wallet = dir.path("original.zwallet");
    let backup = dir.path("backup.zwallet");
    let restored = dir.path("restored.zwallet");
    let created = call(0, &[&wallet], None);
    let receipt = text_field(&created, "receipt");
    assert_eq!(receipt.len(), 144);
    let address = text_field(&call(1, &[&wallet, "17"], Some(&receipt)), "address");
    assert!(address.starts_with("zvlab:"));
    assert_eq!(address.len(), 101);
    let original = fs::read(&wallet).unwrap();
    rejects(&request(0, PASSWORD, &[&wallet], None));
    rejects(&request(1, b"synthetic-wrong-password", &[&wallet, "17"], None));
    rejects(&request(1, PASSWORD, &[&wallet, "01"], None));
    rejects(&request(1, PASSWORD, &[&wallet, "17"], Some(&"00".repeat(72))));
    assert_eq!(fs::read(&wallet).unwrap(), original);
    call(2, &[&wallet, &backup], Some(&receipt));
    call(6, &[&backup, &restored], Some(&receipt));
    assert_eq!(fs::read(&backup).unwrap(), original);
    assert_eq!(fs::read(&restored).unwrap(), original);
    assert_eq!(text_field(&call(1, &[&restored, "17"], None), "address"), address);
    rejects(&request(2, PASSWORD, &[&wallet, &backup], None));
    rejects(&request(6, PASSWORD, &[&backup, &wallet], None));
    assert_eq!(fs::read(&wallet).unwrap(), original);
}

#[test]
fn operator_processes_prepare_resume_and_confirm_two_real_payments() {
    let dir = Dir::new();
    let alice = dir.path("alice.zwallet");
    let bob = dir.path("bob.zwallet");
    let carol = dir.path("carol.zwallet");
    let journal = dir.path("state.journal");
    let manifest = dir.path("public-genesis.bin");
    for wallet in [&alice, &bob, &carol] {
        call(0, &[wallet], None);
    }
    let bob_address = text_field(&call(1, &[&bob, "0"], None), "address");
    let carol_address = text_field(&call(1, &[&carol, "0"], None), "address");
    let init = call(7, &[&alice, &journal, &manifest], None);
    let digest = text_field(&init, "genesis_sha256");
    let genesis = TestGenesis::read_pinned(
        Path::new(&manifest),
        unhex(&digest).try_into().unwrap(),
    )
    .unwrap();
    let initial = call(3, &[&alice, &journal, &manifest, &digest], None);
    assert!(has_number(&initial, "balance", 100_000));
    let before = fs::read(&alice).unwrap();
    // Bad recipient checksum must fail before synchronization or signing.
    let mut bad_address = bob_address.clone();
    bad_address.pop();
    bad_address.push(if bob_address.ends_with('0') { '1' } else { '0' });
    let first = dir.path("first.tx");
    rejects(&request(
        4,
        PASSWORD,
        &[&alice, &journal, &manifest, &digest, &bad_address, "60000", "1000", "20", &first],
        None,
    ));
    assert_eq!(fs::read(&alice).unwrap(), before);
    assert!(!Path::new(&first).exists());
    let prepared = call(
        4,
        &[&alice, &journal, &manifest, &digest, &bob_address, "60000", "1000", "20", &first],
        None,
    );
    let tx1 = fs::read(&first).unwrap();
    AuthorizationVerifier::new().verify(&tx1).unwrap();
    let pending = call(3, &[&alice, &journal, &manifest, &digest], None);
    assert!(has_number(&pending, "available", 0));
    assert!(pending.contains("\"pending\":true"));
    let backup = dir.path("alice-backup.zwallet");
    let restored = dir.path("alice-restored.zwallet");
    let receipt = text_field(&prepared, "receipt");
    call(2, &[&alice, &backup], Some(&receipt));
    call(6, &[&backup, &restored], Some(&receipt));
    let resumed = dir.path("resumed.tx");
    let resumed_status = call(5, &[&restored, &journal, &manifest, &digest, &resumed], None);
    assert_eq!(fs::read(&resumed).unwrap(), tx1);
    assert_eq!(text_field(&prepared, "txid"), text_field(&resumed_status, "txid"));
    rejects(&request(5, PASSWORD, &[&restored, &journal, &manifest, &digest, &resumed], None));
    assert_eq!(fs::read(&resumed).unwrap(), tx1);
    {
        let mut pool = genesis.open_pool(Path::new(&journal)).unwrap();
        let plan = pool.prepare(1, [1; 32], std::slice::from_ref(&tx1)).unwrap();
        pool.commit(plan).unwrap();
    }
    assert!(has_number(&call(3, &[&restored, &journal, &manifest, &digest], None), "balance", 39_000));
    assert!(has_number(&call(3, &[&bob, &journal, &manifest, &digest], None), "balance", 60_000));
    let second = dir.path("second.tx");
    call(
        4,
        &[&bob, &journal, &manifest, &digest, &carol_address, "40000", "1000", "20", &second],
        None,
    );
    let tx2 = fs::read(&second).unwrap();
    {
        let mut pool = genesis.open_pool(Path::new(&journal)).unwrap();
        let plan = pool.prepare(2, [2; 32], std::slice::from_ref(&tx2)).unwrap();
        let final_state = pool.commit(plan).unwrap();
        assert_eq!(final_state.fees, 2_000);
        assert!(matches!(
            pool.prepare(3, [3; 32], std::slice::from_ref(&tx1)),
            Err(PoolError::DoubleSpend)
        ));
    }
    for (wallet, balance) in [(&restored, 39_000), (&bob, 19_000), (&carol, 40_000)] {
        let status = call(3, &[wallet, &journal, &manifest, &digest], None);
        assert!(has_number(&status, "balance", balance));
        assert!(has_number(&status, "available", balance));
        assert!(status.contains("\"pending\":false"));
    }
}
