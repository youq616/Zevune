#![cfg(feature = "local-funding-lab")]
//! Actual active recovery processes and two genuine nonzero payments. Every
//! allocation is ephemeral and valueless; no secret or transaction is logged.
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use zevune_orchard_lab::pool::recovery::active::ActiveRecoveryCheckpoint;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::pool::{PoolError, Summary};
use zevune_orchard_lab::wallet::{Wallet, WalletProver};

type DirectoryBytes = BTreeMap<String, Vec<u8>>;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let path = std::env::temp_dir().join(format!("zevune-active-recovery-cli-{}", hex(&nonce)));
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
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn text(path: &Path) -> String {
    path.to_str().unwrap().to_owned()
}

fn call(args: &[String]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"))
        .args(args)
        .output()
        .unwrap()
}

fn checkpoint_args(
    source: &Path,
    manifest: &Path,
    genesis: &TestGenesis,
    s: &Summary,
) -> Vec<String> {
    vec![
        "checkpoint-active".into(),
        "--no-real-funds".into(),
        "--source".into(),
        text(source),
        "--genesis".into(),
        text(manifest),
        "--genesis-sha256".into(),
        hex(&genesis.digest()),
        "--height".into(),
        s.height.to_string(),
        "--app-hash".into(),
        hex(&s.app_hash),
    ]
}

fn archive_args(mode: &str, source: &Path, encoded: &str, target: Option<&Path>) -> Vec<String> {
    let mut args = vec![
        mode.into(),
        "--no-real-funds".into(),
        "--source".into(),
        text(source),
        "--checkpoint".into(),
        encoded.into(),
    ];
    if let Some(path) = target {
        args.extend(["--output".into(), text(path)]);
    }
    args
}

fn set_option(args: &mut [String], key: &str, value: String) {
    let index = args.iter().position(|argument| argument == key).unwrap();
    args[index + 1] = value;
}

fn success(output: &Output, mode: &str, pin: ActiveRecoveryCheckpoint) {
    assert!(
        output.status.success(),
        "active CLI failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let expected = format!("{{\"operation\":\"{mode}\",\"checkpoint\":\"{}\",\"height\":{},\"bytes\":{},\"checkpoint_format\":\"ZVARCP01\",\"storage_profile\":\"ActiveSegmentsV1\",\"app_hash\":\"{}\",\"segment_count\":{},\"replay_verified\":true,\"finality_verified\":false,\"validator_ready\":false,\"real_funds_allowed\":false}}\n", hex(&pin.to_bytes()), pin.height(), pin.length(), hex(&pin.app_hash()), pin.segment_count());
    assert_eq!(String::from_utf8(output.stdout.clone()).unwrap(), expected);
}

fn failure(output: &Output, dir: &Dir) {
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
    let error = String::from_utf8_lossy(&output.stderr);
    assert!(error.contains("Recovery not completed."));
    assert!(error.contains("partial or complete NEW target may remain"));
    assert!(!error.contains(dir.0.to_str().unwrap()));
}

// Read physical bytes only with no live PoolStore, especially on Windows where
// its genesis lock must not turn the intended byte check into a lock failure.
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

fn unchanged(path: &Path, expected: &DirectoryBytes) {
    // Avoid printing complete public journal/transaction bytes on assertion
    // failure; the contract being checked is byte equality, not their content.
    assert!(
        directory_bytes(path) == *expected,
        "directory bytes changed"
    );
}

fn write_fixture(path: &Path, entries: &DirectoryBytes) {
    fs::create_dir(path).unwrap();
    for (name, bytes) in entries {
        fs::write(path.join(name), bytes).unwrap();
    }
}

// Independently assemble the documented external pin from physical files. This
// does not call the production layout hash or checkpoint-export implementation.
fn physical_pin(entries: &DirectoryBytes, s: &Summary) -> ActiveRecoveryCheckpoint {
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
    let mut pin = b"ZVARCP01".to_vec();
    pin.extend_from_slice(&Sha256::digest(header));
    pin.extend_from_slice(&s.height.to_be_bytes());
    pin.extend_from_slice(&s.app_hash);
    pin.extend_from_slice(&length.to_be_bytes());
    pin.extend_from_slice(&header_length.to_be_bytes());
    pin.extend_from_slice(&count.to_be_bytes());
    pin.extend_from_slice(&layout.finalize());
    assert_eq!(pin.len(), 128);
    ActiveRecoveryCheckpoint::from_bytes(&pin).unwrap()
}

struct Fixture {
    dir: Dir,
    source: PathBuf,
    manifest: PathBuf,
    genesis: TestGenesis,
    state: Summary,
    pin: ActiveRecoveryCheckpoint,
    original: DirectoryBytes,
}

fn fixture(blocks: u64) -> Fixture {
    let dir = Dir::new();
    let source = dir.path("source");
    let manifest = dir.path("test-genesis.bin");
    let wallet = Wallet::create().unwrap();
    let genesis =
        TestGenesis::generate_active(&[(wallet.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    genesis.write_new(&manifest).unwrap();
    let mut pool = genesis.create_pool(&source).unwrap();
    for height in 1..=blocks {
        let mut id = [0; 32];
        id[..8].copy_from_slice(&height.to_be_bytes());
        let prepared = pool.prepare(height, id, &[]).unwrap();
        pool.commit(prepared).unwrap();
    }
    let state = pool.summary().unwrap();
    let exported = pool.active_recovery_checkpoint().unwrap();
    drop(pool);
    let original = directory_bytes(&source);
    let pin = physical_pin(&original, &state);
    assert_eq!(exported, pin);
    Fixture {
        dir,
        source,
        manifest,
        genesis,
        state,
        pin,
        original,
    }
}

#[test]
fn active_cli_real_payment_backup_restore_and_receiver_spend() {
    let dir = Dir::new();
    let source = dir.path("source");
    let manifest = dir.path("test-genesis.bin");
    let backup = dir.path("backup");
    let restored = dir.path("restored");
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let mut carol = Wallet::create().unwrap();
    let genesis =
        TestGenesis::generate_active(&[(alice.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    genesis.write_new(&manifest).unwrap();
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
    let exported = pool.active_recovery_checkpoint().unwrap();
    drop(pool);
    let original = directory_bytes(&source);
    let pin = physical_pin(&original, &paid);
    assert_eq!(exported, pin);
    assert_eq!(pin.segment_count(), 1);
    let encoded = hex(&pin.to_bytes());
    assert_eq!(encoded.len(), 256);
    success(
        &call(&checkpoint_args(&source, &manifest, &genesis, &paid)),
        "checkpoint-active",
        pin,
    );
    for (mode, input, output) in [
        ("backup-active", &source, Some(backup.as_path())),
        ("verify-active", &backup, None),
        ("restore-active", &backup, Some(restored.as_path())),
    ] {
        success(
            &call(&archive_args(mode, input, &encoded, output)),
            mode,
            pin,
        );
        unchanged(&source, &original);
        unchanged(&backup, &original);
    }
    unchanged(&restored, &original);

    // Bob has never scanned the source. His first incoming note and its valid
    // witness now come from the ordinary replay of the actual restored bytes.
    let mut recovered = genesis.open_pool(&restored).unwrap();
    assert_eq!(recovered.summary().unwrap(), paid);
    assert!(matches!(
        recovered.prepare(2, [2; 32], std::slice::from_ref(&first)),
        Err(PoolError::DoubleSpend)
    ));
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
    assert_eq!(recovered.summary().unwrap(), continued);
    let history = genesis.wallet_history(&mut recovered).unwrap();
    alice.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    assert_eq!(alice.balance().unwrap(), 39_000);
    assert_eq!(bob.balance().unwrap(), 19_000);
    assert_eq!(carol.balance().unwrap(), 40_000);
    assert!(alice.pending_id().is_none());
    assert!(bob.pending_id().is_none());
    assert_eq!(
        alice.balance().unwrap()
            + bob.balance().unwrap()
            + carol.balance().unwrap()
            + continued.fees,
        TEST_SUPPLY
    );
    drop(history);
    drop(recovered);
    unchanged(&source, &original);
    unchanged(&backup, &original);
    let mut reopened = genesis.open_pool(&restored).unwrap();
    assert_eq!(reopened.summary().unwrap(), continued);
    let final_pin = reopened.active_recovery_checkpoint().unwrap();
    drop(reopened);
    assert_eq!(
        physical_pin(&directory_bytes(&restored), &continued),
        final_pin
    );
    failure(
        &call(&archive_args("verify-active", &restored, &encoded, None)),
        &dir,
    );
    success(
        &call(&checkpoint_args(&restored, &manifest, &genesis, &continued)),
        "checkpoint-active",
        final_pin,
    );
    unchanged(&source, &original);
    unchanged(&backup, &original);
}

#[test]
fn active_cli_genesis_without_segments_is_an_explicit_checkpoint() {
    let f = fixture(0);
    assert_eq!(f.original.len(), 1);
    assert_eq!(f.pin.height(), 0);
    assert_eq!(f.pin.segment_count(), 0);
    assert_eq!(f.pin.length(), f.original["genesis"].len() as u64);
    success(
        &call(&checkpoint_args(
            &f.source,
            &f.manifest,
            &f.genesis,
            &f.state,
        )),
        "checkpoint-active",
        f.pin,
    );
    let backup = f.dir.path("genesis-backup");
    let restored = f.dir.path("genesis-restored");
    let encoded = hex(&f.pin.to_bytes());
    for (mode, source, output) in [
        ("backup-active", &f.source, Some(backup.as_path())),
        ("verify-active", &backup, None),
        ("restore-active", &backup, Some(restored.as_path())),
    ] {
        success(
            &call(&archive_args(mode, source, &encoded, output)),
            mode,
            f.pin,
        );
    }
    unchanged(&f.source, &f.original);
    unchanged(&backup, &f.original);
    unchanged(&restored, &f.original);
    let mut pool = f.genesis.open_pool(&restored).unwrap();
    assert_eq!(pool.summary().unwrap(), f.state);
    let next = pool.prepare(1, [1; 32], &[]).unwrap();
    assert_eq!(pool.commit(next).unwrap().height, 1);
    drop(pool);
    unchanged(&f.source, &f.original);
    unchanged(&backup, &f.original);
}

#[test]
fn active_cli_bad_options_and_exact_tip_fail_without_changes() {
    let f = fixture(1);
    let target = f.dir.path("not-created");
    let encoded = hex(&f.pin.to_bytes());
    let base = archive_args("backup-active", &f.source, &encoded, Some(&target));
    let mut cases = vec![vec![], vec!["unknown".into()], vec!["backup-active".into()]];
    let mut missing_ack = base.clone();
    missing_ack.retain(|arg| arg != "--no-real-funds");
    cases.push(missing_ack);
    let mut duplicate_ack = base.clone();
    duplicate_ack.push("--no-real-funds".into());
    cases.push(duplicate_ack);
    let mut duplicate_source = base.clone();
    duplicate_source.extend(["--source".into(), text(&f.source)]);
    cases.push(duplicate_source);
    let mut unknown = base.clone();
    unknown.extend(["--unknown".into(), "value".into()]);
    cases.push(unknown);
    let mut missing_value = base.clone();
    missing_value.pop();
    cases.push(missing_value);
    for (key, value) in [
        ("--source", "relative-source".into()),
        ("--output", "relative-target".into()),
        ("--checkpoint", encoded.to_uppercase()),
        ("--checkpoint", encoded[..encoded.len() - 2].into()),
        ("--checkpoint", format!("{encoded}00")),
        ("--checkpoint", "00".repeat(128)),
        ("--checkpoint", "g".repeat(256)),
        ("--checkpoint", "0".repeat(4097)),
    ] {
        let mut args = base.clone();
        set_option(&mut args, key, value);
        cases.push(args);
    }
    let checkpoint = checkpoint_args(&f.source, &f.manifest, &f.genesis, &f.state);
    for height in [
        "0",
        "2",
        "01",
        "+1",
        "-1",
        " 1",
        "1 ",
        "1000001",
        "18446744073709551616",
    ] {
        let mut args = checkpoint.clone();
        set_option(&mut args, "--height", height.into());
        cases.push(args);
    }
    for (key, value) in [
        ("--genesis", "relative-manifest".into()),
        ("--genesis-sha256", "00".repeat(32)),
        ("--genesis-sha256", "AA".repeat(32)),
        ("--app-hash", "00".repeat(32)),
        ("--app-hash", "AA".repeat(32)),
    ] {
        let mut args = checkpoint.clone();
        set_option(&mut args, key, value);
        cases.push(args);
    }
    let mut verify_extra_output = archive_args("verify-active", &f.source, &encoded, Some(&target));
    cases.push(verify_extra_output.clone());
    verify_extra_output[0] = "checkpoint-active".into();
    cases.push(verify_extra_output);
    for args in cases {
        failure(&call(&args), &f.dir);
        unchanged(&f.source, &f.original);
        assert!(!target.exists());
        assert!(fs::read(&f.manifest).unwrap().as_slice() == f.genesis.bytes());
    }
    let help = call(&["--help".into()]);
    assert!(help.status.success());
    let help = String::from_utf8(help.stdout).unwrap();
    for command in [
        "checkpoint-active",
        "backup-active",
        "verify-active",
        "restore-active",
    ] {
        assert!(help.contains(command));
    }
}

#[test]
fn active_cli_locked_sources_and_existing_or_nested_targets_are_refused() {
    let f = fixture(1);
    let encoded = hex(&f.pin.to_bytes());
    let target = f.dir.path("after-unlock");
    let owner = f.genesis.open_pool(&f.source).unwrap();
    for (mode, output) in [
        ("backup-active", Some(target.as_path())),
        ("restore-active", Some(target.as_path())),
        ("verify-active", None),
    ] {
        failure(
            &call(&archive_args(mode, &f.source, &encoded, output)),
            &f.dir,
        );
        assert!(!target.exists());
    }
    failure(
        &call(&checkpoint_args(
            &f.source,
            &f.manifest,
            &f.genesis,
            &f.state,
        )),
        &f.dir,
    );
    assert_eq!(owner.summary().unwrap(), f.state);
    drop(owner);
    unchanged(&f.source, &f.original);
    success(
        &call(&archive_args("verify-active", &f.source, &encoded, None)),
        "verify-active",
        f.pin,
    );
    let existing_file = f.dir.path("existing-file");
    let existing_directory = f.dir.path("existing-directory");
    fs::write(&existing_file, b"keep file").unwrap();
    fs::create_dir(&existing_directory).unwrap();
    fs::write(existing_directory.join("sentinel"), b"keep directory").unwrap();
    let existing_bytes = directory_bytes(&existing_directory);
    let nested = f.source.join("must-not-create");
    let missing_parent = f.dir.path("missing-parent/target");
    for destination in [
        &existing_file,
        &existing_directory,
        &f.source,
        &nested,
        &missing_parent,
    ] {
        for mode in ["backup-active", "restore-active"] {
            failure(
                &call(&archive_args(mode, &f.source, &encoded, Some(destination))),
                &f.dir,
            );
            unchanged(&f.source, &f.original);
            assert_eq!(fs::read(&existing_file).unwrap(), b"keep file");
            unchanged(&existing_directory, &existing_bytes);
            assert!(!nested.exists());
            assert!(!missing_parent.exists());
        }
    }
    success(
        &call(&archive_args(
            "backup-active",
            &f.source,
            &encoded,
            Some(&target),
        )),
        "backup-active",
        f.pin,
    );
    unchanged(&target, &f.original);
}

#[test]
fn active_cli_keeps_legacy_profiles_pins_commands_and_json_separate() {
    let f = fixture(1);
    let wallet = Wallet::create().unwrap();
    let legacy =
        TestGenesis::generate(&[(wallet.receive_address(0).unwrap(), TEST_SUPPLY)]).unwrap();
    let manifest = f.dir.path("legacy-genesis.bin");
    let source = f.dir.path("legacy.journal");
    legacy.write_new(&manifest).unwrap();
    let mut pool = legacy.create_pool(&source).unwrap();
    let prepared = pool.prepare(1, [1; 32], &[]).unwrap();
    let state = pool.commit(prepared).unwrap();
    let legacy_pin = pool.recovery_checkpoint().unwrap();
    drop(pool);
    let original = fs::read(&source).unwrap();
    let legacy_encoded = hex(&legacy_pin.to_bytes());
    let active_encoded = hex(&f.pin.to_bytes());
    let target = f.dir.path("profile-mismatch-output");
    failure(
        &call(&checkpoint_args(&source, &manifest, &legacy, &state)),
        &f.dir,
    );
    let mut old_checkpoint = checkpoint_args(&f.source, &f.manifest, &f.genesis, &f.state);
    old_checkpoint[0] = "checkpoint".into();
    failure(&call(&old_checkpoint), &f.dir);
    for (mode, output) in [
        ("backup-active", Some(target.as_path())),
        ("restore-active", Some(target.as_path())),
        ("verify-active", None),
    ] {
        for (candidate, pin) in [
            (&f.source, legacy_encoded.as_str()),
            (&source, active_encoded.as_str()),
            (&source, legacy_encoded.as_str()),
        ] {
            failure(&call(&archive_args(mode, candidate, pin, output)), &f.dir);
            assert!(!target.exists());
        }
    }
    for (mode, output) in [
        ("backup", Some(target.as_path())),
        ("restore", Some(target.as_path())),
        ("pack", Some(target.as_path())),
        ("verify", None),
        ("verify-segments", None),
        ("restore-segments", Some(target.as_path())),
        ("index", None),
        ("locate-height", None),
    ] {
        for pin in [&legacy_encoded, &active_encoded] {
            let mut args = archive_args(mode, &f.source, pin, output);
            if mode == "locate-height" {
                args.extend(["--height".into(), "1".into()]);
            }
            failure(&call(&args), &f.dir);
            assert!(!target.exists());
        }
    }
    let valid_old = call(&archive_args("verify", &source, &legacy_encoded, None));
    assert!(valid_old.status.success());
    assert!(valid_old.stderr.is_empty());
    let expected = format!("{{\"operation\":\"verify\",\"checkpoint\":\"{legacy_encoded}\",\"height\":1,\"bytes\":{},\"replay_verified\":true,\"finality_verified\":false,\"validator_ready\":false,\"real_funds_allowed\":false}}\n", original.len());
    assert_eq!(String::from_utf8(valid_old.stdout).unwrap(), expected);
    assert!(fs::read(&source).unwrap() == original);
    unchanged(&f.source, &f.original);
}

#[test]
fn active_cli_corrupt_missing_extra_and_split_files_fail_before_copy_creation() {
    let f = fixture(2);
    let encoded = hex(&f.pin.to_bytes());
    let mut cases = Vec::new();
    let mut bad_header = f.original.clone();
    bad_header.get_mut("genesis").unwrap()[0] ^= 1;
    cases.push(bad_header);
    let mut damaged = f.original.clone();
    *damaged
        .get_mut("00000000.journal")
        .unwrap()
        .last_mut()
        .unwrap() ^= 1;
    cases.push(damaged);
    let mut missing = f.original.clone();
    missing.remove("00000000.journal");
    cases.push(missing);
    let mut extra = f.original.clone();
    extra.insert("unexpected".into(), b"extra".to_vec());
    cases.push(extra);
    let mut truncated = f.original.clone();
    truncated.get_mut("00000000.journal").unwrap().pop();
    cases.push(truncated);
    let mut appended = f.original.clone();
    appended.get_mut("00000000.journal").unwrap().push(0);
    cases.push(appended);
    let mut early_rotation = f.original.clone();
    let second = early_rotation
        .get_mut("00000000.journal")
        .unwrap()
        .split_off(150);
    early_rotation.insert("00000001.journal".into(), second);
    cases.push(early_rotation);
    for (number, entries) in cases.into_iter().enumerate() {
        let candidate = f.dir.path(&format!("bad-{number}"));
        let target = f.dir.path(&format!("not-created-{number}"));
        write_fixture(&candidate, &entries);
        for (mode, output) in [
            ("verify-active", None),
            ("backup-active", Some(target.as_path())),
            ("restore-active", Some(target.as_path())),
        ] {
            failure(
                &call(&archive_args(mode, &candidate, &encoded, output)),
                &f.dir,
            );
            assert!(!target.exists());
            unchanged(&candidate, &entries);
            unchanged(&f.source, &f.original);
        }
    }
    // These CLI cases intentionally retain the original pin. Core library
    // adversarial tests separately recompute every checksum/layout field and
    // assert genuine Authorization rejection, not merely this pin mismatch.
    success(
        &call(&archive_args("verify-active", &f.source, &encoded, None)),
        "verify-active",
        f.pin,
    );
}

#[test]
fn active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable() {
    let f = fixture(1);
    let target = f.dir.path("complete-without-receipt");
    let restored = f.dir.path("restored-without-receipt");
    let sink = f.dir.path("read-only-stdout");
    fs::write(&sink, b"keep stdout sink").unwrap();
    let encoded = hex(&f.pin.to_bytes());
    // Positive file-redirection control complements the other tests' captured
    // pipes. The exact success JSON must actually reach the writable OS file.
    let receipt = f.dir.path("writable-stdout.json");
    let mut positive = Command::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"))
        .args(archive_args("verify-active", &f.source, &encoded, None))
        .stdout(Stdio::from(File::create_new(&receipt).unwrap()))
        .output()
        .unwrap();
    assert!(positive.stdout.is_empty());
    positive.stdout = fs::read(&receipt).unwrap();
    success(&positive, "verify-active", f.pin);

    let commands = [
        checkpoint_args(&f.source, &f.manifest, &f.genesis, &f.state),
        archive_args("verify-active", &f.source, &encoded, None),
        archive_args("backup-active", &f.source, &encoded, Some(&target)),
        archive_args("restore-active", &target, &encoded, Some(&restored)),
    ];
    for args in commands {
        let mode = &args[0];
        let mut read_only = File::open(&sink).unwrap();
        // First prove the actual OS handle rejects writes. Rust's buffered
        // stdout adapter can swallow Unix EBADF, so a File probe is essential.
        assert!(
            read_only.write_all(b"must not be written").is_err(),
            "{mode}: stdout fixture unexpectedly permits writing"
        );
        let output = Command::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"))
            .args(&args)
            .stdout(Stdio::from(read_only))
            .output()
            .unwrap();
        assert_eq!(
            output.status.code(),
            Some(1),
            "{mode}: rejected stdout did not produce the CLI failure exit"
        );
        failure(&output, &f.dir);
        assert_eq!(fs::read(&sink).unwrap(), b"keep stdout sink");
        unchanged(&f.source, &f.original);
        let copied = match mode.as_str() {
            "backup-active" => Some(&target),
            "restore-active" => Some(&restored),
            _ => None,
        };
        if let Some(copied) = copied {
            // The copy really completed before its receipt failed. It remains
            // byte-exact and passes a later explicit command with good stdout.
            unchanged(copied, &f.original);
            success(
                &call(&archive_args("verify-active", copied, &encoded, None)),
                "verify-active",
                f.pin,
            );
        }
    }
    unchanged(&target, &f.original);
    unchanged(&restored, &f.original);
    // A later explicit command cannot replace the already complete target.
    failure(
        &call(&archive_args(
            "backup-active",
            &f.source,
            &encoded,
            Some(&target),
        )),
        &f.dir,
    );
    unchanged(&target, &f.original);
}
