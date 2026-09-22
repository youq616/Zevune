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

fn cli(script_name: &str, args: &[String], approval: &str, late_error: bool) -> Output {
    let python = std::env::var_os("ZEVUNE_CHAIN_PYTHON").expect("explicit native test Python");
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../scripts")
        .join(script_name).canonicalize().unwrap();
    let backend = Path::new(env!("CARGO_BIN_EXE_zevune-pool-recovery")).canonicalize().unwrap();
    let digest = hex(&Sha256::digest(fs::read(&backend).unwrap()));
    let mut command = Command::new(python);
    if late_error {
        // Test-only lost result AFTER the real second package write/validation.
        // Never replace successful native authentication with a test double.
        command.arg("-c").arg(r#"import sys
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv.pop(1))
import ledger_backup
from ledger_recovery_backend import RecoveryBackend
original=RecoveryBackend.package
def lose(self,base_path,base,source,pin,deadline,output=None):
    result=original(self,base_path,base,source,pin,deadline,output)
    if output is not None and pin.height==2:
        raise RuntimeError("test_only_lost_reply")
    return result
RecoveryBackend.package=lose
sys.exit(ledger_backup.main())
"#).arg(script.parent().unwrap());
    } else { command.arg(&script); }
    command.arg("--no-real-funds").args(args);
    if args[0] != "inspect" {
        command.args(["--backend", &text(&backend), "--backend-sha256", &digest]);
    }
    command.env_remove("PYTHONDONTWRITEBYTECODE").env_remove("PYTHONPYCACHEPREFIX")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn().unwrap();
    child.stdin.take().unwrap().write_all(approval.as_bytes()).unwrap();
    child.wait_with_output().unwrap()
}
fn create_args(output: &Path, paths: &[PathBuf], pins: &[ActiveRecoveryCheckpoint]) -> Vec<String> {
    assert_eq!(paths.len(), pins.len());
    let mut args=vec!["create".into(),text(output),"--reserve-bytes".into(),"0".into()];
    for (path,pin) in paths.iter().zip(pins) { args.extend(["--source".into(),text(path),hex(&pin.to_bytes())]); }
    args
}
fn inspect_args(output: &Path, pins: &[ActiveRecoveryCheckpoint]) -> Vec<String> {
    let mut args=vec!["inspect".into(),text(output)];
    for pin in pins { args.extend(["--checkpoint".into(),hex(&pin.to_bytes())]); }
    args
}
fn passed(output: &Output, height: u64, replay: bool) {
    assert!(output.status.success(), "native ledger backup command failed");
    let report=std::str::from_utf8(&output.stdout).unwrap();
    for field in ["\"completed\":true", "\"snapshot_imported\":false", "\"finality_verified\":false",
                  "\"validator_ready\":false", "\"real_funds_allowed\":false"] { assert!(report.contains(field)); }
    assert!(report.contains(&format!("\"replay_verified\":{replay}")));
    assert!(report.contains(&format!("\"height\":{height},")));
}
fn failed(output: &Output, root: &Path) {
    assert!(!output.status.success());assert!(output.stdout.is_empty());
    assert!(!String::from_utf8_lossy(&output.stderr).contains(root.to_str().unwrap()));
}

#[test]
fn real_backup_set_restore_and_continued_spend() {
    let dir=Temporary::new();
    let mut alice=Wallet::create().unwrap();let mut bob=Wallet::create().unwrap();let mut carol=Wallet::create().unwrap();
    let genesis=TestGenesis::generate_active(&[(alice.receive_address(0).unwrap(),TEST_SUPPLY)]).unwrap();
    let source=dir.path("live");let paths=[dir.path("original-base"),dir.path("original-one"),dir.path("original-two")];
    let pool=genesis.create_pool(&source).unwrap();
    let (mut pool,p0)=archive(pool,&paths[0],&source,&genesis);
    let prover=WalletProver::new();
    let history=genesis.wallet_history(&mut pool).unwrap();alice.sync(&history).unwrap();bob.sync(&history).unwrap();
    let first=alice.build_payment(bob.receive_address(0).unwrap(),60_000,1_000,10,&prover).unwrap();
    commit(&mut pool,1,&[first.bytes().to_vec()]);
    let (mut pool,p1)=archive(pool,&paths[1],&source,&genesis);
    bob.sync(&genesis.wallet_history(&mut pool).unwrap()).unwrap();
    let second=bob.build_payment(carol.receive_address(0).unwrap(),40_000,1_000,10,&prover).unwrap();
    let expected=commit(&mut pool,2,&[second.bytes().to_vec()]);
    let (pool,p2)=archive(pool,&paths[2],&source,&genesis);drop(pool);
    let pins=[p0,p1,p2];let originals:Vec<_>=paths.iter().map(|p|bytes(p)).collect();
    let output=dir.path("backup-set");let args=create_args(&output,&paths,&pins);
    failed(&cli("ledger_backup.py",&args,"NO\n",false),&dir.0);assert!(!output.exists());
    passed(&cli("ledger_backup.py",&args,"BACKUP-CHAIN\n",false),2,true);
    assert!(bytes(&output.join("base"))==originals[0]);
    let marker=fs::read(output.join("BACKUP.json")).unwrap();
    let increments:Vec<_>=(1..=2).map(|i|fs::read(output.join(format!("increment-{i:02}.zvaipk"))).unwrap()).collect();
    passed(&cli("ledger_backup.py",&inspect_args(&output,&pins),"",false),2,false);
    failed(&cli("ledger_backup.py",&args,"BACKUP-CHAIN\n",false),&dir.0);
    failed(&cli("ledger_backup.py",&inspect_args(&output,&pins[..2]),"",false),&dir.0);
    let bad=dir.path("wrong-order");
    failed(&cli("ledger_backup.py",&create_args(&bad,&[paths[0].clone(),paths[2].clone(),paths[1].clone()],&pins),"BACKUP-CHAIN\n",false),&dir.0);
    assert!(!bad.exists());
    // Fixed trusted receipts individually validate both fork endpoints, but
    // independently valid states may NOT be treated as an append chain.
    let fork=dir.path("fork");
    ActiveArchive::open(&paths[0],p0).unwrap().copy_new(&fork).unwrap();
    let mut fork_pool=genesis.open_pool(&fork).unwrap();
    let alternate=fork_pool.prepare(1,[7;32],&[first.bytes().to_vec()]).unwrap();
    fork_pool.commit(alternate).unwrap();
    commit(&mut fork_pool,2,&[]);let q2=fork_pool.active_recovery_checkpoint().unwrap();drop(fork_pool);
    assert!(q2.length()>p1.length()); // pass cheap increasing-length checks first
    assert_eq!(q2.height(),p2.height());
    let fork_bytes=bytes(&fork);let rejected=dir.path("fork-rejected");
    failed(&cli("ledger_backup.py",&create_args(&rejected,&[paths[0].clone(),paths[1].clone(),fork.clone()],&[p0,p1,q2]),"BACKUP-CHAIN\n",false),&dir.0);
    assert!(!rejected.exists());assert!(bytes(&fork)==fork_bytes);
    // Controlled failure after genuine final package write: retain every
    // completed artifact, do not fabricate the final marker or auto-resume.
    let partial=dir.path("lost-ack");
    failed(&cli("ledger_backup.py",&create_args(&partial,&paths,&pins),"BACKUP-CHAIN\n",true),&dir.0);
    assert!(!partial.join("BACKUP.json").exists());assert!(bytes(&partial.join("base"))==originals[0]);
    for (i,raw) in increments.iter().enumerate() { assert!(fs::read(partial.join(format!("increment-{:02}.zvaipk",i+1))).unwrap()==*raw); }
    failed(&cli("ledger_backup.py",&create_args(&partial,&paths,&pins),"BACKUP-CHAIN\n",false),&dir.0);
    for (i,raw) in increments.iter().enumerate() { assert!(fs::read(partial.join(format!("increment-{:02}.zvaipk",i+1))).unwrap()==*raw); }
    let base_only=dir.path("base-only");
    passed(&cli("ledger_backup.py",&create_args(&base_only,&paths[..1],&pins[..1]),"BACKUP-CHAIN\n",false),0,true);
    passed(&cli("ledger_backup.py",&inspect_args(&base_only,&pins[..1]),"",false),0,false);
    // Direct interoperability with the independently accepted recovery module.
    let restored=dir.path("restored");
    let mut restore_args=vec!["restore".into(),text(&restored),"--base".into(),text(&output.join("base")),
        "--base-checkpoint".into(),hex(&p0.to_bytes()),"--reserve-bytes".into(),"0".into()];
    for i in 1..=2 { restore_args.extend(["--step".into(),text(&output.join(format!("increment-{i:02}.zvaipk"))),hex(&pins[i].to_bytes())]); }
    let result=cli("ledger_restore.py",&restore_args,"RESTORE-CHAIN\n",false);
    assert!(result.status.success(),"existing restore rejected new backup set");
    for (i,raw) in originals.iter().enumerate() { assert!(bytes(&restored.join(format!("stage-{i:02}")))==*raw); }
    let active=dir.path("continued");
    ActiveArchive::open(&restored.join("stage-02"),p2).unwrap().copy_new(&active).unwrap();
    let mut pool=genesis.open_pool(&active).unwrap();assert_eq!(pool.summary().unwrap(),expected);
    assert_eq!(pool.prepare(3,[3;32],&[second.bytes().to_vec()]).err(),Some(PoolError::DoubleSpend));
    carol.sync(&genesis.wallet_history(&mut pool).unwrap()).unwrap();assert_eq!(carol.balance().unwrap(),40_000);
    let payment=carol.build_payment(alice.receive_address(0).unwrap(),20_000,1_000,10,&prover).unwrap();
    let continued=commit(&mut pool,3,&[payment.bytes().to_vec()]);drop(pool);
    let pool=genesis.open_pool(&active).unwrap();assert_eq!(pool.summary().unwrap(),continued);assert_eq!(continued.fees,3_000);drop(pool);
    for (i,path) in paths.iter().enumerate() { assert!(bytes(path)==originals[i]); }
    assert!(fs::read(output.join("BACKUP.json")).unwrap()==marker);
    for (i,raw) in increments.iter().enumerate() { assert!(fs::read(output.join(format!("increment-{:02}.zvaipk",i+1))).unwrap()==*raw); }
    passed(&cli("ledger_backup.py",&inspect_args(&output,&pins),"",false),2,false);
    println!("Real baseline/incremental backup set, native prefix/fork checks, retained failures and restore interoperability with genuine continued spend passed.");
}
