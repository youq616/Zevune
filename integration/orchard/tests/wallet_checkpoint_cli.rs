//! Actual existing wallet CLI, not an accepting verifier or a replacement process.
//! Checkpoint provenance here is a fully replayed LOCAL fixture, not consensus.
#![cfg(feature = "local-funding-lab")]
use std::fs;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};
use zeroize::Zeroizing;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::wallet::vault::store::{StoreReceipt, WalletStore};

struct Home(PathBuf);
impl Home {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "zevune-wallet-checkpoint-cli-{:032x}",
            rand::random::<u128>()
        ));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
}
impl Drop for Home {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn hex(b: &[u8]) -> String {
    b.iter().map(|v| format!("{v:02x}")).collect()
}
fn frame(password: &[u8], pin: StoreReceipt, fields: &[String]) -> Zeroizing<Vec<u8>> {
    let mut raw = Zeroizing::new(b"ZVWCLI01".to_vec());
    raw.push(11);
    raw.extend_from_slice(&(password.len() as u16).to_be_bytes());
    raw.extend_from_slice(password);
    raw.push(1);
    raw.extend_from_slice(&pin.journal_id);
    raw.extend_from_slice(&pin.generation.to_be_bytes());
    raw.extend_from_slice(&pin.digest);
    raw.push(fields.len() as u8);
    for f in fields {
        raw.extend_from_slice(&(f.len() as u16).to_be_bytes());
        raw.extend_from_slice(f.as_bytes());
    }
    raw
}

// All test frames/command responses fit the pipe; no worker threads or detached
// readers. Kill+wait on a failed deadline is TEST FAILURE cleanup, never success.
fn command(raw: &[u8], success: bool) -> String {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_zevune-wallet-local"));
    cmd.arg("--no-real-funds");
    run_command(cmd, raw, success)
}

fn run_command(mut cmd: Command, raw: &[u8], success: bool) -> String {
    assert!(raw.len() < 4096);
    let mut child = cmd
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let wrote = child.stdin.take().unwrap().write_all(raw);
    if wrote.is_err() {
        let _ = child.kill();
        let _ = child.wait();
        panic!("test could not deliver bounded private frame");
    }
    let until = Instant::now() + Duration::from_secs(20);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < until => thread::sleep(Duration::from_millis(5)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                panic!("checkpoint wallet command did not finish in its test budget");
            }
        }
    };
    assert_eq!(status.success(), success, "checkpoint command status");
    let mut output = String::new();
    child
        .stdout
        .take()
        .unwrap()
        .take(4097)
        .read_to_string(&mut output)
        .unwrap();
    assert!(output.len() <= 4096);
    if !success {
        assert!(output.is_empty(), "rejected scan emitted a success record");
    }
    output
}

#[test]
fn actual_command_rechecks_exact_tip_before_wallet_mutation_on_both_profiles() {
    for active in [false, true] {
        let home = Home::new();
        let password = Zeroizing::new(rand::random::<[u8; 32]>());
        let wallet_path = home.0.join("wallet");
        let journal = home.0.join("pool");
        let manifest = home.0.join("genesis");
        let wallet = WalletStore::create(&wallet_path, password.as_ref()).unwrap();
        let owner = wallet.view().unwrap().receive_address(0).unwrap();
        let pin = wallet.receipt().unwrap();
        let genesis = if active {
            TestGenesis::generate_active(&[(owner, TEST_SUPPLY)]).unwrap()
        } else {
            TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap()
        };
        genesis.write_new(&manifest).unwrap();
        let pool = genesis.create_pool(&journal).unwrap();
        let initial = pool.summary().unwrap();
        drop(pool);
        drop(wallet);
        let mut fields = vec![
            wallet_path.to_str().unwrap().to_owned(),
            journal.to_str().unwrap().to_owned(),
            manifest.to_str().unwrap().to_owned(),
            hex(&genesis.digest()),
            "0".to_owned(),
            hex(&initial.app_hash),
        ];
        let before = fs::read(&wallet_path).unwrap();
        let mut mismatch = fields.clone();
        let mut other = initial.app_hash;
        other[0] ^= 1;
        mismatch[5] = hex(&other);
        command(&frame(password.as_ref(), pin, &mismatch), false);
        assert!(fs::read(&wallet_path).unwrap() == before);
        mismatch = fields.clone();
        mismatch[4] = "1".to_owned();
        command(&frame(password.as_ref(), pin, &mismatch), false);
        assert!(fs::read(&wallet_path).unwrap() == before);
        let result = command(&frame(password.as_ref(), pin, &fields), true);
        assert!(result.starts_with("{\"ok\":true,\"scope\":\"local_journal_only_no_funds\","));
        assert!(result.contains("\"checkpoint_matched\":true"));
        assert!(result.contains("\"balance\":100000,\"available\":100000,\"pending\":false"));
        assert!(result.contains(&format!("\"app_hash\":\"{}\"", hex(&initial.app_hash))));
        assert!(!result.contains("\"confirmed\""));
        let wallet = WalletStore::open(&wallet_path, password.as_ref(), Some(pin)).unwrap();
        let current_pin = wallet.receipt().unwrap();
        assert_eq!(wallet.view().unwrap().height(), Some(0));
        drop(wallet);
        // Commit through the actual pool, then reject the OLD checkpoint without
        // applying the newer local history to the encrypted wallet.
        let mut pool = genesis.open_pool(&journal).unwrap();
        let prepared = pool.prepare(1, [17; 32], &[]).unwrap();
        let next = pool.commit(prepared).unwrap();
        drop(pool);
        let before = fs::read(&wallet_path).unwrap();
        command(&frame(password.as_ref(), current_pin, &fields), false);
        assert!(fs::read(&wallet_path).unwrap() == before);
        fields[4] = next.height.to_string();
        fields[5] = hex(&next.app_hash);
        command(&frame(password.as_ref(), current_pin, &fields), true);
        let wallet = WalletStore::open(&wallet_path, password.as_ref(), Some(pin)).unwrap();
        assert_eq!(wallet.view().unwrap().height(), Some(1));
        assert_eq!(wallet.view().unwrap().balance().unwrap(), TEST_SUPPLY);
        drop(wallet);
        // Direct malformed frames bypass frontend validation but cannot mutate.
        let before = fs::read(&wallet_path).unwrap();
        for (index, value) in [(4, "01".to_owned()), (5, "0".repeat(64))] {
            let mut bad = fields.clone();
            bad[index] = value;
            command(&frame(password.as_ref(), current_pin, &bad), false);
            assert!(fs::read(&wallet_path).unwrap() == before);
        }
    }
}
