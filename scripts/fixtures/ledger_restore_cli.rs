#![cfg(feature = "local-funding-lab")]
//! Real Python coordinator + original native recovery, never an accepting double.
//! Copied from exact tracked source into an isolated test-only build directory.
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use zevune_orchard_lab::pool::recovery::active::{ActiveArchive, ActiveRecoveryCheckpoint};
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::pool::{PoolError, PoolStore, Summary};
use zevune_orchard_lab::wallet::{Wallet, WalletProver};

struct Temporary(PathBuf);
impl Temporary {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let root = std::env::temp_dir().canonicalize().unwrap().join(format!("zevune-chain-{}", hex(&nonce)));
        fs::create_dir(&root).unwrap();
        Self(root)
    }
    fn path(&self, name: &str) -> PathBuf { self.0.join(name) }
}
impl Drop for Temporary {
    fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
}
fn hex(raw: &[u8]) -> String { raw.iter().map(|b| format!("{b:02x}")).collect() }
fn text(path: &Path) -> String { path.to_str().unwrap().to_owned() }
fn bytes(path: &Path) -> BTreeMap<String, Vec<u8>> {
    fs::read_dir(path).unwrap().map(|e| {
        let e = e.unwrap();
        assert!(e.file_type().unwrap().is_file());
        (e.file_name().into_string().unwrap(), fs::read(e.path()).unwrap())
    }).collect()
}
fn commit(pool: &mut PoolStore, height: u64, txs: &[Vec<u8>]) -> Summary {
    let mut id = [1; 32]; id[..8].copy_from_slice(&height.to_be_bytes());
    let candidate = pool.prepare(height, id, txs).unwrap();
    pool.commit(candidate).unwrap()
}
fn archive(mut pool: PoolStore, path: &Path, source: &Path, genesis: &TestGenesis) -> (PoolStore, ActiveRecoveryCheckpoint) {
    let pin = pool.active_recovery_checkpoint().unwrap();
    drop(pool);
    let mut original = ActiveArchive::open(source, pin).unwrap();
    assert_eq!(original.copy_new(path).unwrap(), pin);
    drop(original);
    (genesis.open_pool(source).unwrap(), pin)
}

fn cli(args: &[String], confirm: bool) -> Output {
    let python = std::env::var_os("ZEVUNE_CHAIN_PYTHON").expect("explicit native test Python");
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../scripts/ledger_restore.py");
    let backend = Path::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"));
    let digest = hex(&Sha256::digest(fs::read(backend).unwrap()));
    let mut command = Command::new(python);
    command.arg(script).arg("--no-real-funds").args(args)
        .args(["--backend", &text(backend), "--backend-sha256", &digest])
        .env_remove("PYTHONDONTWRITEBYTECODE").env_remove("PYTHONPYCACHEPREFIX")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn().unwrap();
    child.stdin.take().unwrap().write_all(if confirm { b"RESTORE-CHAIN\n" } else { b"NO\n" }).unwrap();
    child.wait_with_output().unwrap()
}
fn restore_args(output: &Path, base: &Path, pins: &[ActiveRecoveryCheckpoint], packages: &[PathBuf]) -> Vec<String> {
    let mut args = vec!["restore".into(), text(output), "--base".into(), text(base),
                        "--base-checkpoint".into(), hex(&pins[0].to_bytes()), "--reserve-bytes".into(), "0".into()];
    for (package, pin) in packages.iter().zip(&pins[1..]) {
        args.extend(["--step".into(), text(package), hex(&pin.to_bytes())]);
    }
    args
}
fn verify_args(output: &Path, pins: &[ActiveRecoveryCheckpoint]) -> Vec<String> {
    let mut args = vec!["verify".into(), text(output)];
    for pin in pins { args.extend(["--checkpoint".into(), hex(&pin.to_bytes())]); }
    args
}
fn passed(output: &Output, height: u64) {
    assert!(output.status.success(), "native ledger chain command failed");
    let result = std::str::from_utf8(&output.stdout).unwrap();
    for field in ["\"completed\":true", "\"snapshot_imported\":false", "\"validator_ready\":false",
                  "\"finality_verified\":false", "\"real_funds_allowed\":false"] { assert!(result.contains(field)); }
    assert!(result.contains(&format!("\"height\":{height},")));
}
fn failed(output: &Output, root: &Path) {
    assert!(!output.status.success()); assert!(output.stdout.is_empty());
    assert!(!String::from_utf8_lossy(&output.stderr).contains(root.to_str().unwrap()));
}

#[test]
fn real_multi_package_recovery_and_continued_spend() {
    let dir = Temporary::new();
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let mut carol = Wallet::create().unwrap();
    let genesis = TestGenesis::generate_active(&[(alice.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let source = dir.path("live"); let base = dir.path("base");
    let one = dir.path("one"); let two = dir.path("two");
    let mut pool = genesis.create_pool(&source).unwrap();
    let (next, p0) = archive(pool, &base, &source, &genesis);
    pool = next;
    let prover = WalletProver::new();
    let history = genesis.wallet_history(&mut pool).unwrap();
    alice.sync(&history).unwrap(); bob.sync(&history).unwrap(); carol.sync(&history).unwrap();
    let payment1 = alice.build_payment(bob.receive_address(0).unwrap(), 60_000, 1_000, 10, &prover).unwrap();
    commit(&mut pool, 1, &[payment1.bytes().to_vec()]);
    let (next, p1) = archive(pool, &one, &source, &genesis);
    pool = next;
    let history = genesis.wallet_history(&mut pool).unwrap();
    bob.sync(&history).unwrap();
    let payment2 = bob.build_payment(carol.receive_address(0).unwrap(), 40_000, 1_000, 10, &prover).unwrap();
    let expected = commit(&mut pool, 2, &[payment2.bytes().to_vec()]);
    let (next, p2) = archive(pool, &two, &source, &genesis);
    pool = next;
    drop(pool);
    let pins = [p0, p1, p2]; let paths = [base.clone(), one.clone(), two.clone()];
    let originals: Vec<_> = paths.iter().map(|p| bytes(p)).collect();
    let first = dir.path("first.increment"); let second = dir.path("second.increment");
    let packages = [first.clone(), second.clone()];
    for i in 0..2 {
        let mut earlier = ActiveArchive::open(&paths[i], pins[i]).unwrap();
        let mut later = ActiveArchive::open(&paths[i+1], pins[i+1]).unwrap();
        earlier.pack_incremental_new(&mut later, &packages[i]).unwrap();
    }
    let increments: Vec<_> = packages.iter().map(|p| fs::read(p).unwrap()).collect();
    let restored = dir.path("restored");
    let args = restore_args(&restored, &base, &pins, &packages);
    failed(&cli(&args, false), &dir.0); assert!(!restored.exists());
    passed(&cli(&args, true), 2);
    for (i, original) in originals.iter().enumerate() {
        assert!(bytes(&restored.join(format!("stage-{i:02}"))) == *original);
    }
    let marker = fs::read(restored.join("RECOVERY.json")).unwrap();
    passed(&cli(&verify_args(&restored, &pins), false), 2);
    assert!(fs::read(restored.join("RECOVERY.json")).unwrap() == marker);
    failed(&cli(&args, true), &dir.0);
    // Omitted/old/out-of-order independent pins cannot bless the directory.
    failed(&cli(&verify_args(&restored, &pins[..2]), false), &dir.0);
    let wrong_order = dir.path("wrong-order");
    failed(&cli(&restore_args(&wrong_order, &base, &pins, &[second.clone(), first.clone()]), true), &dir.0);
    assert!(!wrong_order.exists());
    // Later package corruption leaves only new workspace outputs; never a marker.
    let mut bad = increments[1].clone(); let last = bad.len()-1; bad[last] ^= 1;
    let bad_package = dir.path("bad.increment"); fs::write(&bad_package, &bad).unwrap();
    let partial = dir.path("partial");
    failed(&cli(&restore_args(&partial, &base, &pins, &[first.clone(), bad_package]), true), &dir.0);
    assert!(partial.join("stage-00").is_dir() && partial.join("stage-01").is_dir());
    assert!(!partial.join("RECOVERY.json").exists());
    // A valid same-genesis fork is NOT an extension of the previous archive.
    // Reuse genuine signatures, but commit block one with a different block ID.
    let fork_source = dir.path("fork-source");
    let mut fork = genesis.create_pool(&fork_source).unwrap();
    let fork_first = fork.prepare(1, [9; 32], &[payment1.bytes().to_vec()]).unwrap();
    fork.commit(fork_first).unwrap();
    commit(&mut fork, 2, &[payment2.bytes().to_vec()]);
    let fork_two = dir.path("fork-two");
    let (fork, q2) = archive(fork, &fork_two, &fork_source, &genesis);
    drop(fork);
    assert_ne!(q2, p2);
    let unrelated = dir.path("unrelated");
    fs::create_dir(&unrelated).unwrap();
    for (i, path) in paths[..2].iter().enumerate() {
        ActiveArchive::open(path, pins[i]).unwrap()
            .copy_new(&unrelated.join(format!("stage-{i:02}"))).unwrap();
    }
    ActiveArchive::open(&fork_two, q2).unwrap()
        .copy_new(&unrelated.join("stage-02")).unwrap();
    // Pin the actual fork, not the original endpoint. Every stage individually
    // authenticates; the coordinator must independently refuse their relation.
    let changed_marker = std::str::from_utf8(&marker).unwrap()
        .replace(&hex(&p2.to_bytes()), &hex(&q2.to_bytes()));
    fs::write(unrelated.join("RECOVERY.json"), changed_marker.as_bytes()).unwrap();
    let fork_bytes = bytes(&unrelated.join("stage-02"));
    failed(&cli(&verify_args(&unrelated, &[p0, p1, q2]), false), &dir.0);
    assert!(bytes(&unrelated.join("stage-02")) == fork_bytes);
    assert!(fs::read(unrelated.join("RECOVERY.json")).unwrap() == changed_marker.as_bytes());
    // A base-only recovery is a complete supported module path, not a zero-match test.
    let base_only = dir.path("base-only");
    passed(&cli(&restore_args(&base_only, &base, &pins[..1], &[]), true), 0);
    passed(&cli(&verify_args(&base_only, &pins[..1]), false), 0);
    // Continue from a SEPARATE authenticated copy, keeping the recovery set immutable.
    let active = dir.path("continued");
    ActiveArchive::open(&restored.join("stage-02"), p2).unwrap().copy_new(&active).unwrap();
    let mut reopened = genesis.open_pool(&active).unwrap();
    assert_eq!(reopened.summary().unwrap(), expected);
    assert_eq!(reopened.prepare(3, [3; 32], &[payment2.bytes().to_vec()]).err(), Some(PoolError::DoubleSpend));
    let history = genesis.wallet_history(&mut reopened).unwrap(); carol.sync(&history).unwrap();
    assert_eq!(carol.balance().unwrap(), 40_000);
    let spend = carol.build_payment(alice.receive_address(0).unwrap(), 20_000, 1_000, 10, &prover).unwrap();
    let continued = commit(&mut reopened, 3, &[spend.bytes().to_vec()]);
    drop(reopened);
    let reopened = genesis.open_pool(&active).unwrap(); assert_eq!(reopened.summary().unwrap(), continued);
    assert_eq!(continued.fees, 3_000); drop(reopened);
    for (i, path) in paths.iter().enumerate() { assert!(bytes(path) == originals[i]); }
    for (i, path) in packages.iter().enumerate() { assert!(fs::read(path).unwrap() == increments[i]); }
    passed(&cli(&verify_args(&restored, &pins), false), 2);
    println!("Real multi-increment chain restored, independently verified and continued with genuine spend; no validator activation.");
}
