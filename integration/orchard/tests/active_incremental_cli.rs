#![cfg(feature = "local-funding-lab")]
//! Actual read-only planning processes, with independent physical expectations
//! and genuine payments. No production incremental writer is implied by these
//! tests, and no secret, payment plaintext or transaction is printed.
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use zevune_orchard_lab::pool::recovery::active::{ActiveArchive, ActiveRecoveryCheckpoint};
use zevune_orchard_lab::pool::recovery::RecoveryArchive;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::pool::{PoolError, Summary};
use zevune_orchard_lab::wallet::{Wallet, WalletProver};

type DirectoryBytes = BTreeMap<String, Vec<u8>>;
type TreeBytes = BTreeMap<PathBuf, Option<Vec<u8>>>;
type Range = (u32, u32, u32);

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let path =
            std::env::temp_dir().join(format!("zevune-active-incremental-cli-{}", hex(&nonce)));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}
impl Drop for Dir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn text(path: &Path) -> String {
    path.to_str().unwrap().to_owned()
}

fn directory_bytes(path: &Path) -> DirectoryBytes {
    fs::read_dir(path)
        .unwrap()
        .map(|entry| {
            let entry = entry.unwrap();
            assert!(entry.file_type().unwrap().is_file());
            (
                entry.file_name().into_string().unwrap(),
                fs::read(entry.path()).unwrap(),
            )
        })
        .collect()
}

fn tree_bytes(path: &Path) -> TreeBytes {
    fn walk(root: &Path, path: &Path, out: &mut TreeBytes) {
        for entry in fs::read_dir(path).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            let name = path.strip_prefix(root).unwrap().to_path_buf();
            if entry.file_type().unwrap().is_dir() {
                out.insert(name, None);
                walk(root, &path, out);
            } else {
                assert!(entry.file_type().unwrap().is_file());
                out.insert(name, Some(fs::read(path).unwrap()));
            }
        }
    }
    let mut out = BTreeMap::new();
    walk(path, path, &mut out);
    out
}

fn write_fixture(path: &Path, entries: &DirectoryBytes) {
    fs::create_dir(path).unwrap();
    for (name, bytes) in entries {
        fs::write(path.join(name), bytes).unwrap();
    }
}

fn call(args: &[String]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"))
        .args(args)
        .output()
        .unwrap()
}

fn call_readonly(args: &[String], dir: &Dir) -> Output {
    let original = tree_bytes(&dir.0);
    let output = call(args);
    assert!(
        tree_bytes(&dir.0) == original,
        "planning changed directory membership or file bytes"
    );
    output
}

fn plan_args(
    base: &Path,
    base_pin: ActiveRecoveryCheckpoint,
    later: &Path,
    pin: ActiveRecoveryCheckpoint,
) -> Vec<String> {
    vec![
        "plan-active-incremental".into(),
        "--no-real-funds".into(),
        "--base".into(),
        text(base),
        "--base-checkpoint".into(),
        hex(&base_pin.to_bytes()),
        "--source".into(),
        text(later),
        "--checkpoint".into(),
        hex(&pin.to_bytes()),
    ]
}

fn set_option(args: &mut [String], key: &str, value: String) {
    let index = args.iter().position(|arg| arg == key).unwrap();
    args[index + 1] = value;
}

fn expected_json(
    base: ActiveRecoveryCheckpoint,
    later: ActiveRecoveryCheckpoint,
    ranges: &[Range],
) -> String {
    let appended = ranges.iter().map(|range| u64::from(range.2)).sum::<u64>();
    assert_eq!(base.length() + appended, later.length());
    let changed_old = ranges
        .iter()
        .filter(|range| range.0 < base.segment_count())
        .count();
    let unchanged = base.segment_count() - u32::try_from(changed_old).unwrap();
    let encoded_ranges = ranges
        .iter()
        .map(|&(index, offset, length)| {
            assert!(length > 0);
            format!("{{\"segment_index\":{index},\"offset\":{offset},\"length\":{length}}}")
        })
        .collect::<Vec<_>>()
        .join(",");
    format!("{{\"format\":\"zevune-active-incremental-plan-1\",\"operation\":\"plan-active-incremental\",\"base_checkpoint\":\"{}\",\"checkpoint\":\"{}\",\"base_height\":{},\"height\":{},\"base_bytes\":{},\"bytes\":{},\"reused_bytes\":{},\"appended_bytes\":{appended},\"unchanged_segment_count\":{unchanged},\"new_segment_count\":{},\"ranges\":[{encoded_ranges}],\"replay_verified\":true,\"byte_prefix_verified\":true,\"incremental_backup_written\":false,\"snapshot_imported\":false,\"finality_verified\":false,\"validator_ready\":false,\"real_funds_allowed\":false}}\n", hex(&base.to_bytes()), hex(&later.to_bytes()), base.height(), later.height(), base.length(), later.length(), base.length(), later.segment_count() - base.segment_count())
}

fn success(output: &Output, expected: &str) {
    assert!(
        output.status.success(),
        "incremental CLI failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    assert!(output.stdout.is_ascii());
    assert_eq!(
        output.stdout.iter().filter(|&&byte| byte == b'\n').count(),
        1
    );
    assert_eq!(output.stdout, expected.as_bytes());
}

fn failure(output: &Output, dir: &Dir) {
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    let error = String::from_utf8_lossy(&output.stderr);
    assert!(error.contains("Recovery not completed."));
    assert!(!error.contains(dir.0.to_str().unwrap()));
}

// Independent encoding from the physical files and ordinary committed summary;
// neither the production layout hash nor plan renderer supplies expectations.
fn physical_pin(entries: &DirectoryBytes, state: &Summary) -> ActiveRecoveryCheckpoint {
    let header = &entries["genesis"];
    let count = u32::try_from(entries.len() - 1).unwrap();
    let header_length = u32::try_from(header.len()).unwrap();
    let mut layout = Sha256::new();
    layout.update(b"ZVARLY01");
    layout.update(header_length.to_be_bytes());
    layout.update(header);
    layout.update(count.to_be_bytes());
    let mut length = header.len() as u64;
    for index in 0..count {
        let bytes = &entries[&format!("{index:08}.journal")];
        layout.update(index.to_be_bytes());
        layout.update(u32::try_from(bytes.len()).unwrap().to_be_bytes());
        layout.update(bytes);
        length += bytes.len() as u64;
    }
    let mut raw = b"ZVARCP01".to_vec();
    raw.extend_from_slice(&Sha256::digest(header));
    raw.extend_from_slice(&state.height.to_be_bytes());
    raw.extend_from_slice(&state.app_hash);
    raw.extend_from_slice(&length.to_be_bytes());
    raw.extend_from_slice(&header_length.to_be_bytes());
    raw.extend_from_slice(&count.to_be_bytes());
    raw.extend_from_slice(&layout.finalize());
    assert_eq!(raw.len(), 128);
    ActiveRecoveryCheckpoint::from_bytes(&raw).unwrap()
}

struct Snapshot {
    path: PathBuf,
    pin: ActiveRecoveryCheckpoint,
    bytes: DirectoryBytes,
}

fn snapshot(genesis: &TestGenesis, path: PathBuf, blocks: u64, branch: u8) -> Snapshot {
    let mut pool = genesis.create_pool(&path).unwrap();
    for height in 1..=blocks {
        let mut id = [branch; 32];
        id[..8].copy_from_slice(&height.to_be_bytes());
        let prepared = pool.prepare(height, id, &[]).unwrap();
        pool.commit(prepared).unwrap();
    }
    let state = pool.summary().unwrap();
    let pin = pool.active_recovery_checkpoint().unwrap();
    drop(pool);
    let bytes = directory_bytes(&path);
    assert_eq!(pin, physical_pin(&bytes, &state));
    Snapshot { path, pin, bytes }
}

struct Fixture {
    dir: Dir,
    genesis: TestGenesis,
    base: Snapshot,
    later: Snapshot,
}

fn fixture(base_height: u64, later_height: u64) -> Fixture {
    let dir = Dir::new();
    let wallet = Wallet::create().unwrap();
    let genesis =
        TestGenesis::generate_active(&[(wallet.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let base = snapshot(&genesis, dir.path("base"), base_height, 1);
    let later = snapshot(&genesis, dir.path("later"), later_height, 1);
    Fixture {
        dir,
        genesis,
        base,
        later,
    }
}

#[test]
fn active_incremental_cli_real_payments_restore_spend_and_rehashed_bad_signature() {
    let dir = Dir::new();
    let source = dir.path("first-payment");
    let backup = dir.path("backup");
    let restored = dir.path("restored-second-payment");
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let mut carol = Wallet::create().unwrap();
    let genesis =
        TestGenesis::generate_active(&[(alice.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let mut pool = genesis.create_pool(&source).unwrap();
    alice
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    let prover = WalletProver::new();
    let first = alice
        .build_payment(bob.receive_address(0).unwrap(), 60_000, 1_000, 100, &prover)
        .unwrap()
        .bytes()
        .to_vec();
    let prepared = pool
        .prepare(1, [1; 32], std::slice::from_ref(&first))
        .unwrap();
    let paid = pool.commit(prepared).unwrap();
    assert_eq!(paid.height, 1);
    assert_eq!(paid.commitments, 3);
    assert_eq!(paid.nullifiers, 2);
    assert_eq!(paid.fees, 1_000);
    let base_pin = pool.active_recovery_checkpoint().unwrap();
    drop(pool);
    let base_bytes = directory_bytes(&source);
    assert_eq!(base_pin, physical_pin(&base_bytes, &paid));
    let mut archive = ActiveArchive::open(&source, base_pin).unwrap();
    assert_eq!(archive.copy_new(&backup).unwrap(), base_pin);
    drop(archive);
    let mut archive = ActiveArchive::open(&backup, base_pin).unwrap();
    assert_eq!(archive.copy_new(&restored).unwrap(), base_pin);
    drop(archive);
    assert!(directory_bytes(&backup) == base_bytes);
    assert!(directory_bytes(&restored) == base_bytes);

    // Bob's first scan is of the actual restored history, before he signs the
    // genuine onward payment. The plan later spans exactly this second record.
    let mut recovered = genesis.open_pool(&restored).unwrap();
    assert_eq!(recovered.summary().unwrap(), paid);
    let history = genesis.wallet_history(&mut recovered).unwrap();
    alice.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    assert_eq!(alice.balance().unwrap(), 39_000);
    assert_eq!(bob.balance().unwrap(), 60_000);
    assert_eq!(carol.balance().unwrap(), 0);
    assert!(alice.pending_id().is_none());
    drop(history);
    let second = bob
        .build_payment(
            carol.receive_address(0).unwrap(),
            40_000,
            1_000,
            100,
            &prover,
        )
        .unwrap()
        .bytes()
        .to_vec();
    let prepared = recovered
        .prepare(2, [2; 32], std::slice::from_ref(&second))
        .unwrap();
    let continued = recovered.commit(prepared).unwrap();
    assert_eq!(continued.height, 2);
    assert_eq!(continued.commitments, 5);
    assert_eq!(continued.nullifiers, 4);
    assert_eq!(continued.fees, 2_000);
    for payment in [&first, &second] {
        assert!(matches!(
            recovered.prepare(3, [3; 32], std::slice::from_ref(payment)),
            Err(PoolError::DoubleSpend)
        ));
    }
    let history = genesis.wallet_history(&mut recovered).unwrap();
    alice.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    assert_eq!(alice.balance().unwrap(), 39_000);
    assert_eq!(bob.balance().unwrap(), 19_000);
    assert_eq!(carol.balance().unwrap(), 40_000);
    assert!(bob.pending_id().is_none());
    assert_eq!(
        alice.balance().unwrap()
            + bob.balance().unwrap()
            + carol.balance().unwrap()
            + continued.fees,
        TEST_SUPPLY
    );
    drop(history);
    let later_pin = recovered.active_recovery_checkpoint().unwrap();
    drop(recovered);
    let later_bytes = directory_bytes(&restored);
    assert_eq!(later_pin, physical_pin(&later_bytes, &continued));
    let old_length = u32::try_from(base_bytes["00000000.journal"].len()).unwrap();
    let added_length = u32::try_from(later_bytes["00000000.journal"].len()).unwrap() - old_length;
    assert_eq!(added_length as usize, 150 + 4 + second.len());
    let expected = expected_json(base_pin, later_pin, &[(0, old_length, added_length)]);
    let args = plan_args(&source, base_pin, &restored, later_pin);
    success(&call_readonly(&args, &dir), &expected);
    success(&call_readonly(&args, &dir), &expected);

    // Alter the signature in the NEW record, keeping the valid base prefix and
    // recomputing its record checksum and the entire physical checkpoint. The
    // public planning chain must fail at archive open with Authorization, not
    // merely at a stale layout hash or an unrelated first-record corruption.
    let mut forged = later_bytes.clone();
    let bytes = forged.get_mut("00000000.journal").unwrap();
    let start = old_length as usize;
    assert!(bytes[..start] == base_bytes["00000000.journal"][..]);
    let body = u32::from_be_bytes(bytes[start..start + 4].try_into().unwrap()) as usize;
    let end = start + 4 + body;
    assert_eq!(end + 32, bytes.len());
    bytes[end - 1] ^= 1;
    let checksum = Sha256::digest(&bytes[start + 4..end]);
    bytes[end..].copy_from_slice(&checksum);
    let forged_pin = physical_pin(&forged, &continued);
    assert_ne!(forged_pin, later_pin);
    let forged_path = dir.path("new-record-bad-signature");
    write_fixture(&forged_path, &forged);
    assert!(matches!(
        ActiveArchive::open(&forged_path, forged_pin),
        Err(PoolError::Authorization)
    ));
    failure(
        &call_readonly(
            &plan_args(&source, base_pin, &forged_path, forged_pin),
            &dir,
        ),
        &dir,
    );
    success(&call_readonly(&args, &dir), &expected);
    assert!(directory_bytes(&source) == base_bytes);
    assert!(directory_bytes(&backup) == base_bytes);
    assert!(directory_bytes(&restored) == later_bytes);
    assert!(directory_bytes(&forged_path) == forged);
}

#[test]
fn active_incremental_cli_genesis_and_same_content_have_exact_empty_plan_schema() {
    let f = fixture(0, 3);
    let copy = f.dir.path("same-content-copy");
    write_fixture(&copy, &f.later.bytes);
    for (base, pin, later) in [
        (&f.base.path, f.base.pin, &f.base.path),
        (&f.later.path, f.later.pin, &f.later.path),
        (&f.later.path, f.later.pin, &copy),
    ] {
        success(
            &call_readonly(&plan_args(base, pin, later, pin), &f.dir),
            &expected_json(pin, pin, &[]),
        );
    }
    assert_eq!(f.base.bytes.len(), 1);
    assert_eq!(f.base.pin.height(), 0);
    assert_eq!(f.later.bytes["00000000.journal"].len(), 450);
    success(
        &call_readonly(
            &plan_args(&f.base.path, f.base.pin, &f.later.path, f.later.pin),
            &f.dir,
        ),
        &expected_json(f.base.pin, f.later.pin, &[(0, 0, 450)]),
    );
}

#[test]
fn active_incremental_cli_options_profiles_and_legacy_pins_are_rejected_readonly() {
    let f = fixture(1, 3);
    let base = plan_args(&f.base.path, f.base.pin, &f.later.path, f.later.pin);
    let mut cases = vec![vec![base[0].clone()]];
    let mut no_ack = base.clone();
    no_ack.retain(|arg| arg != "--no-real-funds");
    cases.push(no_ack);
    let mut duplicate_ack = base.clone();
    duplicate_ack.push("--no-real-funds".into());
    cases.push(duplicate_ack);
    for key in ["--base", "--base-checkpoint", "--source", "--checkpoint"] {
        let index = base.iter().position(|arg| arg == key).unwrap();
        let mut missing = base.clone();
        missing.drain(index..index + 2);
        cases.push(missing);
        let mut duplicate = base.clone();
        duplicate.extend([key.into(), base[index + 1].clone()]);
        cases.push(duplicate);
        let mut missing_value = base.clone();
        missing_value.remove(index + 1);
        cases.push(missing_value);
    }
    for key in ["--output", "--unknown"] {
        let mut extra = base.clone();
        extra.extend([key.into(), text(&f.dir.path("must-not-create"))]);
        cases.push(extra);
    }
    for key in ["--base", "--source"] {
        let mut relative = base.clone();
        set_option(&mut relative, key, "relative-directory".into());
        cases.push(relative);
    }
    for key in ["--base-checkpoint", "--checkpoint"] {
        let encoded = hex(&f.later.pin.to_bytes());
        for invalid in [
            encoded.to_uppercase(),
            encoded[..encoded.len() - 2].into(),
            format!("{encoded}00"),
            "00".repeat(128),
            "g".repeat(256),
            "0".repeat(4097),
        ] {
            let mut args = base.clone();
            set_option(&mut args, key, invalid);
            cases.push(args);
        }
    }
    let mut legacy_bytes = f.genesis.bytes().to_vec();
    legacy_bytes[..8].copy_from_slice(b"ZVTGEN02");
    let legacy = TestGenesis::decode(&legacy_bytes).unwrap();
    let legacy_path = f.dir.path("legacy.journal");
    let mut legacy_pool = legacy.create_pool(&legacy_path).unwrap();
    let prepared = legacy_pool.prepare(1, [1; 32], &[]).unwrap();
    legacy_pool.commit(prepared).unwrap();
    let legacy_pin = legacy_pool.recovery_checkpoint().unwrap();
    drop(legacy_pool);
    RecoveryArchive::open(&legacy_path, legacy_pin).unwrap();
    for key in ["--base-checkpoint", "--checkpoint"] {
        let mut args = base.clone();
        set_option(&mut args, key, hex(&legacy_pin.to_bytes()));
        cases.push(args);
    }
    for key in ["--base", "--source"] {
        let mut args = base.clone();
        set_option(&mut args, key, text(&legacy_path));
        cases.push(args);
    }
    for args in cases {
        failure(&call_readonly(&args, &f.dir), &f.dir);
        assert!(!f.dir.path("must-not-create").exists());
    }
    success(
        &call_readonly(&base, &f.dir),
        &expected_json(f.base.pin, f.later.pin, &[(0, 150, 300)]),
    );
    let help = call_readonly(&["--help".into()], &f.dir);
    assert!(help.status.success());
    assert!(String::from_utf8(help.stdout)
        .unwrap()
        .contains("plan-active-incremental"));
}

#[test]
fn active_incremental_cli_individually_valid_forks_rollback_and_networks_fail() {
    let f = fixture(1, 3);
    let same_height_fork = snapshot(&f.genesis, f.dir.path("same-height-fork"), 1, 9);
    let higher_fork = snapshot(&f.genesis, f.dir.path("higher-fork"), 3, 9);
    assert_eq!(same_height_fork.pin.height(), f.base.pin.height());
    assert_eq!(same_height_fork.pin.length(), f.base.pin.length());
    assert_ne!(same_height_fork.pin.app_hash(), f.base.pin.app_hash());
    let wallet = Wallet::create().unwrap();
    let other_genesis =
        TestGenesis::generate_active(&[(wallet.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let other_network = snapshot(&other_genesis, f.dir.path("other-network"), 3, 1);
    for (base, later, wrong_network) in [
        (&f.base, &same_height_fork, false),
        (&f.base, &higher_fork, false),
        (&f.later, &f.base, false),
        (&f.base, &other_network, true),
    ] {
        // Both pins independently open and fully verify. In particular these
        // failures are neither malformed hashes nor writer-lock substitutes.
        let mut left = ActiveArchive::open(&base.path, base.pin).unwrap();
        let mut right = ActiveArchive::open(&later.path, later.pin).unwrap();
        left.verify().unwrap();
        right.verify().unwrap();
        let result = left.incremental_plan(&mut right);
        if wrong_network {
            assert!(matches!(result, Err(PoolError::Genesis)));
        } else {
            assert!(matches!(result, Err(PoolError::Stale)));
        }
        drop(right);
        drop(left);
        failure(
            &call_readonly(
                &plan_args(&base.path, base.pin, &later.path, later.pin),
                &f.dir,
            ),
            &f.dir,
        );
    }
    success(
        &call_readonly(
            &plan_args(&f.base.path, f.base.pin, &f.later.path, f.later.pin),
            &f.dir,
        ),
        &expected_json(f.base.pin, f.later.pin, &[(0, 150, 300)]),
    );
}

#[test]
fn active_incremental_cli_wrong_pins_missing_and_damaged_bytes_fail_on_either_side() {
    let f = fixture(1, 3);
    let args = plan_args(&f.base.path, f.base.pin, &f.later.path, f.later.pin);
    for (key, pin) in [
        ("--base-checkpoint", f.later.pin),
        ("--checkpoint", f.base.pin),
    ] {
        let mut wrong_pin = args.clone();
        set_option(&mut wrong_pin, key, hex(&pin.to_bytes()));
        failure(&call_readonly(&wrong_pin, &f.dir), &f.dir);
    }
    for (side, original) in [("--base", &f.base), ("--source", &f.later)] {
        let mut damaged = original.bytes.clone();
        *damaged
            .get_mut("00000000.journal")
            .unwrap()
            .last_mut()
            .unwrap() ^= 1;
        let mut truncated = original.bytes.clone();
        truncated.get_mut("00000000.journal").unwrap().pop();
        let mut appended = original.bytes.clone();
        appended.get_mut("00000000.journal").unwrap().push(0);
        let mut missing = original.bytes.clone();
        missing.remove("00000000.journal");
        let mut extra = original.bytes.clone();
        extra.insert("unexpected".into(), b"keep extra entry".to_vec());
        let mut bad_header = original.bytes.clone();
        bad_header.get_mut("genesis").unwrap()[0] ^= 1;
        for (number, bytes) in [damaged, truncated, appended, missing, extra, bad_header]
            .into_iter()
            .enumerate()
        {
            let path = f.dir.path(&format!("{side}-physical-error-{number}"));
            write_fixture(&path, &bytes);
            let mut candidate = args.clone();
            set_option(&mut candidate, side, text(&path));
            failure(&call_readonly(&candidate, &f.dir), &f.dir);
            assert!(directory_bytes(&path) == bytes);
        }
        let mut absent = args.clone();
        set_option(&mut absent, side, text(&f.dir.path("absent-directory")));
        failure(&call_readonly(&absent, &f.dir), &f.dir);
    }
    success(
        &call_readonly(&args, &f.dir),
        &expected_json(f.base.pin, f.later.pin, &[(0, 150, 300)]),
    );
}

#[test]
fn active_incremental_cli_writer_locks_reject_and_shared_readers_coexist() {
    let f = fixture(1, 3);
    let args = plan_args(&f.base.path, f.base.pin, &f.later.path, f.later.pin);
    let original = tree_bytes(&f.dir.0);
    for path in [&f.base.path, &f.later.path] {
        let owner = f.genesis.open_pool(path).unwrap();
        failure(&call(&args), &f.dir);
        drop(owner);
        assert!(tree_bytes(&f.dir.0) == original);
    }
    let left = ActiveArchive::open(&f.base.path, f.base.pin).unwrap();
    let right = ActiveArchive::open(&f.later.path, f.later.pin).unwrap();
    for path in [&f.base.path, &f.later.path] {
        assert!(matches!(f.genesis.open_pool(path), Err(PoolError::Locked)));
    }
    success(
        &call_readonly(&args, &f.dir),
        &expected_json(f.base.pin, f.later.pin, &[(0, 150, 300)]),
    );
    drop(right);
    drop(left);
    for path in [&f.base.path, &f.later.path] {
        f.genesis.open_pool(path).unwrap();
    }
    assert!(tree_bytes(&f.dir.0) == original);
}

#[test]
fn active_incremental_cli_readonly_stdout_fails_with_writable_and_empty_controls() {
    let f = fixture(1, 3);
    let sink = f.dir.path("read-only-stdout");
    fs::write(&sink, b"keep stdout sink").unwrap();
    for (number, later, pin, ranges) in [
        (0, &f.later.path, f.later.pin, vec![(0, 150, 300)]),
        (1, &f.base.path, f.base.pin, vec![]),
    ] {
        let args = plan_args(&f.base.path, f.base.pin, later, pin);
        let expected = expected_json(f.base.pin, pin, &ranges);
        let receipt = f.dir.path(&format!("writable-stdout-{number}.json"));
        let stdout = File::create_new(&receipt).unwrap();
        let mut expected_tree = tree_bytes(&f.dir.0);
        expected_tree.insert(
            receipt.strip_prefix(&f.dir.0).unwrap().to_path_buf(),
            Some(expected.as_bytes().to_vec()),
        );
        let mut positive = Command::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"))
            .args(&args)
            .stdout(Stdio::from(stdout))
            .output()
            .unwrap();
        assert!(positive.stdout.is_empty());
        positive.stdout = fs::read(&receipt).unwrap();
        success(&positive, &expected);
        assert!(tree_bytes(&f.dir.0) == expected_tree);
        let original = tree_bytes(&f.dir.0);
        let mut read_only = File::open(&sink).unwrap();
        assert!(
            read_only.write_all(b"must not be written").is_err(),
            "stdout fixture unexpectedly permits writing"
        );
        let output = Command::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"))
            .args(&args)
            .stdout(Stdio::from(read_only))
            .output()
            .unwrap();
        failure(&output, &f.dir);
        assert!(tree_bytes(&f.dir.0) == original);
        assert_eq!(fs::read(&sink).unwrap(), b"keep stdout sink");
        assert!(directory_bytes(&f.base.path) == f.base.bytes);
        assert!(directory_bytes(&f.later.path) == f.later.bytes);
        success(&call_readonly(&args, &f.dir), &expected);
    }
}
