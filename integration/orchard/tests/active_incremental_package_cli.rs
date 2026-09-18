#![cfg(feature = "local-funding-lab")]
//! Real incremental package processes with independent wire/JSON expectations.
//! These fixtures commit ordinary empty blocks; genuine payment recovery is
//! covered by the existing funded flow without adding proof generation here.
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use zevune_orchard_lab::pool::recovery::active::package::ActiveIncrementalPackage;
use zevune_orchard_lab::pool::recovery::active::{ActiveArchive, ActiveRecoveryCheckpoint};
use zevune_orchard_lab::pool::recovery::RecoveryArchive;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::pool::{PoolError, Summary};
use zevune_orchard_lab::wallet::Wallet;

const PACK: &str = "pack-active-incremental";
const VERIFY: &str = "verify-active-incremental";
const RESTORE: &str = "restore-active-incremental";
type DirectoryBytes = BTreeMap<String, Vec<u8>>;
type Range = (u32, u32, u32);

#[derive(PartialEq, Eq)]
enum TreeEntry {
    Directory,
    File(Vec<u8>),
    Link(PathBuf),
}

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let path = std::env::temp_dir().join(format!(
            "zevune-active-incremental-package-cli-{}",
            hex(&nonce)
        ));
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

fn tree_bytes(path: &Path) -> BTreeMap<PathBuf, TreeEntry> {
    fn walk(root: &Path, path: &Path, out: &mut BTreeMap<PathBuf, TreeEntry>) {
        for entry in fs::read_dir(path).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            let name = path.strip_prefix(root).unwrap().to_path_buf();
            let kind = entry.file_type().unwrap();
            if kind.is_symlink() {
                out.insert(name, TreeEntry::Link(fs::read_link(path).unwrap()));
            } else if kind.is_dir() {
                out.insert(name, TreeEntry::Directory);
                walk(root, &path, out);
            } else {
                assert!(kind.is_file());
                out.insert(name, TreeEntry::File(fs::read(path).unwrap()));
            }
        }
    }
    let mut out = BTreeMap::new();
    walk(path, path, &mut out);
    out
}

fn unchanged(path: &Path, expected: &DirectoryBytes) {
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
        "command changed an existing file or directory membership"
    );
    output
}

fn package_args(
    mode: &str,
    base: &Path,
    base_pin: ActiveRecoveryCheckpoint,
    source: &Path,
    later_pin: ActiveRecoveryCheckpoint,
    target: Option<&Path>,
) -> Vec<String> {
    let mut args = vec![
        mode.into(),
        "--no-real-funds".into(),
        "--base".into(),
        text(base),
        "--base-checkpoint".into(),
        hex(&base_pin.to_bytes()),
        "--source".into(),
        text(source),
        "--checkpoint".into(),
        hex(&later_pin.to_bytes()),
    ];
    if let Some(target) = target {
        args.extend(["--output".into(), text(target)]);
    }
    args
}

fn set_option(args: &mut [String], key: &str, value: String) {
    let index = args.iter().position(|arg| arg == key).unwrap();
    args[index + 1] = value;
}

fn expected_json(
    mode: &str,
    base: ActiveRecoveryCheckpoint,
    later: ActiveRecoveryCheckpoint,
    ranges: &[Range],
) -> String {
    let appended = ranges.iter().map(|range| u64::from(range.2)).sum::<u64>();
    assert_eq!(base.length() + appended, later.length());
    let package_bytes = 268 + 12 * ranges.len() as u64 + appended;
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
    let written = mode == PACK;
    let restored = mode == RESTORE;
    format!("{{\"format\":\"zevune-active-incremental-package-1\",\"operation\":\"{mode}\",\"package_format\":\"ZVAIPK01\",\"package_bytes\":{package_bytes},\"base_checkpoint\":\"{}\",\"checkpoint\":\"{}\",\"base_height\":{},\"height\":{},\"base_bytes\":{},\"bytes\":{},\"reused_bytes\":{},\"appended_bytes\":{appended},\"unchanged_segment_count\":{unchanged},\"new_segment_count\":{},\"ranges\":[{encoded_ranges}],\"replay_verified\":true,\"byte_prefix_verified\":true,\"incremental_backup_written\":{written},\"archive_restored\":{restored},\"snapshot_imported\":false,\"finality_verified\":false,\"validator_ready\":false,\"real_funds_allowed\":false}}\n", hex(&base.to_bytes()), hex(&later.to_bytes()), base.height(), later.height(), base.length(), later.length(), base.length(), later.segment_count() - base.segment_count())
}

fn success(output: &Output, expected: &str) {
    assert!(
        output.status.success(),
        "package CLI failed: {}",
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
    assert!(error.contains("partial or complete NEW target may remain"));
    assert!(!error.contains(dir.0.to_str().unwrap()));
}

fn verify_active(path: &Path, pin: ActiveRecoveryCheckpoint) {
    let expected = format!("{{\"operation\":\"verify-active\",\"checkpoint\":\"{}\",\"height\":{},\"bytes\":{},\"checkpoint_format\":\"ZVARCP01\",\"storage_profile\":\"ActiveSegmentsV1\",\"app_hash\":\"{}\",\"segment_count\":{},\"replay_verified\":true,\"finality_verified\":false,\"validator_ready\":false,\"real_funds_allowed\":false}}\n", hex(&pin.to_bytes()), pin.height(), pin.length(), hex(&pin.app_hash()), pin.segment_count());
    success(
        &call(&[
            "verify-active".into(),
            "--no-real-funds".into(),
            "--source".into(),
            text(path),
            "--checkpoint".into(),
            hex(&pin.to_bytes()),
        ]),
        &expected,
    );
}

// The wire expectation is independently assembled from physical snapshots and
// literal format fields, never from the production plan/package encoder.
fn expected_package(
    base: ActiveRecoveryCheckpoint,
    later: ActiveRecoveryCheckpoint,
    ranges: &[Range],
    later_bytes: &DirectoryBytes,
) -> Vec<u8> {
    let mut out = b"ZVAIPK01".to_vec();
    out.extend_from_slice(&base.to_bytes());
    out.extend_from_slice(&later.to_bytes());
    out.extend_from_slice(&u32::try_from(ranges.len()).unwrap().to_be_bytes());
    for &(index, offset, length) in ranges {
        out.extend_from_slice(&index.to_be_bytes());
        out.extend_from_slice(&offset.to_be_bytes());
        out.extend_from_slice(&length.to_be_bytes());
    }
    assert_eq!(out.len(), 268 + 12 * ranges.len());
    for &(index, offset, length) in ranges {
        let bytes = &later_bytes[&format!("{index:08}.journal")];
        let start = offset as usize;
        let end = start + length as usize;
        out.extend_from_slice(&bytes[start..end]);
    }
    assert_eq!(
        out.len() as u64,
        268 + 12 * ranges.len() as u64 + later.length() - base.length()
    );
    out
}

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
    state: Summary,
    bytes: DirectoryBytes,
}

fn snapshot(genesis: &TestGenesis, path: PathBuf, blocks: u64) -> Snapshot {
    let mut pool = genesis.create_pool(&path).unwrap();
    for height in 1..=blocks {
        let mut id = [1; 32];
        id[..8].copy_from_slice(&height.to_be_bytes());
        let prepared = pool.prepare(height, id, &[]).unwrap();
        pool.commit(prepared).unwrap();
    }
    let state = pool.summary().unwrap();
    let pin = pool.active_recovery_checkpoint().unwrap();
    drop(pool);
    let bytes = directory_bytes(&path);
    assert_eq!(pin, physical_pin(&bytes, &state));
    Snapshot {
        path,
        pin,
        state,
        bytes,
    }
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
    let base = snapshot(&genesis, dir.path("base"), base_height);
    let later = snapshot(&genesis, dir.path("later"), later_height);
    Fixture {
        dir,
        genesis,
        base,
        later,
    }
}

#[test]
fn package_cli_exact_tail_bytes_restore_without_later_and_continue() {
    let f = fixture(1, 3);
    let package = f.dir.path("incremental.zvaipk");
    let restored = f.dir.path("restored");
    let ranges = [(0, 150, 300)];
    assert_eq!(f.base.bytes["00000000.journal"].len(), 150);
    assert_eq!(f.later.bytes["00000000.journal"].len(), 450);
    let wire = expected_package(f.base.pin, f.later.pin, &ranges, &f.later.bytes);
    assert_eq!(wire.len(), 580);
    success(
        &call(&package_args(
            PACK,
            &f.base.path,
            f.base.pin,
            &f.later.path,
            f.later.pin,
            Some(&package),
        )),
        &expected_json(PACK, f.base.pin, f.later.pin, &ranges),
    );
    assert!(fs::read(&package).unwrap() == wire);
    unchanged(&f.base.path, &f.base.bytes);
    unchanged(&f.later.path, &f.later.bytes);

    // Verification and recovery now have no original later directory to read.
    fs::remove_dir_all(&f.later.path).unwrap();
    success(
        &call_readonly(
            &package_args(
                VERIFY,
                &f.base.path,
                f.base.pin,
                &package,
                f.later.pin,
                None,
            ),
            &f.dir,
        ),
        &expected_json(VERIFY, f.base.pin, f.later.pin, &ranges),
    );
    success(
        &call(&package_args(
            RESTORE,
            &f.base.path,
            f.base.pin,
            &package,
            f.later.pin,
            Some(&restored),
        )),
        &expected_json(RESTORE, f.base.pin, f.later.pin, &ranges),
    );
    unchanged(&restored, &f.later.bytes);
    verify_active(&restored, f.later.pin);
    let mut pool = f.genesis.open_pool(&restored).unwrap();
    assert_eq!(pool.summary().unwrap(), f.later.state);
    let prepared = pool.prepare(4, [4; 32], &[]).unwrap();
    let continued = pool.commit(prepared).unwrap();
    assert_eq!(continued.height, 4);
    assert_eq!(continued.commitments, f.later.state.commitments);
    assert_eq!(continued.nullifiers, f.later.state.nullifiers);
    assert_eq!(continued.fees, f.later.state.fees);
    let continued_pin = pool.active_recovery_checkpoint().unwrap();
    drop(pool);
    assert_eq!(
        physical_pin(&directory_bytes(&restored), &continued),
        continued_pin
    );
    verify_active(&restored, continued_pin);
    unchanged(&f.base.path, &f.base.bytes);
    assert!(fs::read(&package).unwrap() == wire);
    assert!(!f.later.path.exists());
}

#[test]
fn package_cli_genesis_same_content_and_new_segment_have_exact_schema() {
    let f = fixture(0, 3);
    let copy = f.dir.path("same-content-copy");
    write_fixture(&copy, &f.later.bytes);
    assert_eq!(f.base.bytes.len(), 1);
    assert_eq!(f.base.pin.height(), 0);
    let cases = [
        (&f.base, &f.base, f.base.path.as_path(), vec![]),
        (&f.later, &f.later, f.later.path.as_path(), vec![]),
        (&f.later, &f.later, copy.as_path(), vec![]),
        (&f.base, &f.later, f.later.path.as_path(), vec![(0, 0, 450)]),
    ];
    for (number, (base, later, source, ranges)) in cases.into_iter().enumerate() {
        let package = f.dir.path(&format!("package-{number}"));
        let restored = f.dir.path(&format!("restored-{number}"));
        let wire = expected_package(base.pin, later.pin, &ranges, &later.bytes);
        if ranges.is_empty() {
            assert_eq!(wire.len(), 268);
        }
        for (mode, input, output) in [
            (PACK, source, Some(package.as_path())),
            (VERIFY, package.as_path(), None),
            (RESTORE, package.as_path(), Some(restored.as_path())),
        ] {
            success(
                &call(&package_args(
                    mode, &base.path, base.pin, input, later.pin, output,
                )),
                &expected_json(mode, base.pin, later.pin, &ranges),
            );
            assert!(fs::read(&package).unwrap() == wire);
            unchanged(&base.path, &base.bytes);
            unchanged(source, &later.bytes);
        }
        unchanged(&restored, &later.bytes);
    }
    unchanged(&f.base.path, &f.base.bytes);
    unchanged(&f.later.path, &f.later.bytes);
    unchanged(&copy, &f.later.bytes);
}

#[test]
fn package_cli_options_profiles_and_two_independent_pins_are_required() {
    let f = fixture(1, 3);
    let package = f.dir.path("independently-encoded-package");
    let target = f.dir.path("must-not-create");
    let ranges = [(0, 150, 300)];
    let wire = expected_package(f.base.pin, f.later.pin, &ranges, &f.later.bytes);
    fs::write(&package, &wire).unwrap();
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

    for mode in [PACK, VERIFY, RESTORE] {
        let source = if mode == PACK {
            &f.later.path
        } else {
            &package
        };
        let output = (mode != VERIFY).then_some(target.as_path());
        let valid = package_args(mode, &f.base.path, f.base.pin, source, f.later.pin, output);
        let mut cases = vec![vec![mode.into()]];
        let mut no_ack = valid.clone();
        no_ack.retain(|arg| arg != "--no-real-funds");
        cases.push(no_ack);
        let mut duplicate_ack = valid.clone();
        duplicate_ack.push("--no-real-funds".into());
        cases.push(duplicate_ack);
        let mut unknown = valid.clone();
        unknown.extend(["--unknown".into(), "value".into()]);
        cases.push(unknown);
        let mut keys = vec!["--base", "--base-checkpoint", "--source", "--checkpoint"];
        if mode == VERIFY {
            let mut unexpected_output = valid.clone();
            unexpected_output.extend(["--output".into(), text(&target)]);
            cases.push(unexpected_output);
        } else {
            keys.push("--output");
        }
        for key in keys {
            let index = valid.iter().position(|arg| arg == key).unwrap();
            let mut missing = valid.clone();
            missing.drain(index..index + 2);
            cases.push(missing);
            let mut duplicate = valid.clone();
            duplicate.extend([key.into(), valid[index + 1].clone()]);
            cases.push(duplicate);
        }
        let mut missing_value = valid.clone();
        missing_value.pop();
        cases.push(missing_value);
        for key in ["--base", "--source", "--output"] {
            if valid.iter().any(|arg| arg == key) {
                let mut relative = valid.clone();
                set_option(&mut relative, key, "relative-path".into());
                cases.push(relative);
            }
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
                hex(&legacy_pin.to_bytes()),
            ] {
                let mut args = valid.clone();
                set_option(&mut args, key, invalid);
                cases.push(args);
            }
        }
        for (key, pin) in [
            ("--base-checkpoint", f.later.pin),
            ("--checkpoint", f.base.pin),
        ] {
            let mut wrong_pin = valid.clone();
            set_option(&mut wrong_pin, key, hex(&pin.to_bytes()));
            cases.push(wrong_pin);
        }
        for key in ["--base", "--source"] {
            let mut old_profile = valid.clone();
            set_option(&mut old_profile, key, text(&legacy_path));
            cases.push(old_profile);
            let mut absent = valid.clone();
            set_option(&mut absent, key, text(&f.dir.path("absent-input")));
            cases.push(absent);
        }
        if mode != PACK {
            // This base independently opens with its own correct pin, but is
            // not the baseline declared by the independently encoded package.
            let mut wrong_base = valid.clone();
            set_option(&mut wrong_base, "--base", text(&f.later.path));
            set_option(
                &mut wrong_base,
                "--base-checkpoint",
                hex(&f.later.pin.to_bytes()),
            );
            cases.push(wrong_base);
        }
        for args in cases {
            failure(&call_readonly(&args, &f.dir), &f.dir);
            assert!(!target.exists());
        }
    }
    success(
        &call_readonly(
            &package_args(
                VERIFY,
                &f.base.path,
                f.base.pin,
                &package,
                f.later.pin,
                None,
            ),
            &f.dir,
        ),
        &expected_json(VERIFY, f.base.pin, f.later.pin, &ranges),
    );
    let help = call_readonly(&["--help".into()], &f.dir);
    assert!(help.status.success());
    let help = String::from_utf8(help.stdout).unwrap();
    for mode in [PACK, VERIFY, RESTORE] {
        assert!(help.contains(mode));
    }
}

#[test]
fn package_cli_corrupt_header_ranges_payload_and_eof_are_retained() {
    let f = fixture(1, 3);
    let ranges = [(0, 150, 300)];
    let wire = expected_package(f.base.pin, f.later.pin, &ranges, &f.later.bytes);
    let mut cases = Vec::new();
    for offset in [0, 8, 136, wire.len() - 1] {
        let mut changed = wire.clone();
        changed[offset] ^= 1;
        cases.push(changed);
    }
    for (offset, value) in [(264, 2049_u32), (268, 1), (272, 151), (276, 0)] {
        let mut changed = wire.clone();
        changed[offset..offset + 4].copy_from_slice(&value.to_be_bytes());
        cases.push(changed);
    }
    cases.push(wire[..267].to_vec());
    cases.push(wire[..wire.len() - 1].to_vec());
    let mut trailing = wire.clone();
    trailing.push(0);
    cases.push(trailing);
    for (number, bytes) in cases.into_iter().enumerate() {
        let package = f.dir.path(&format!("bad-package-{number}"));
        let target = f.dir.path(&format!("no-target-{number}"));
        fs::write(&package, &bytes).unwrap();
        for mode in [VERIFY, RESTORE] {
            failure(
                &call_readonly(
                    &package_args(
                        mode,
                        &f.base.path,
                        f.base.pin,
                        &package,
                        f.later.pin,
                        (mode == RESTORE).then_some(target.as_path()),
                    ),
                    &f.dir,
                ),
                &f.dir,
            );
            assert!(!target.exists());
            assert!(fs::read(&package).unwrap() == bytes);
        }
    }
    // Retain trusted pins for these transport-damage cases. The library funded
    // flow separately recomputes frame/layout hashes and checks Authorization.
    let good = f.dir.path("good-independent-package");
    fs::write(&good, &wire).unwrap();
    success(
        &call_readonly(
            &package_args(VERIFY, &f.base.path, f.base.pin, &good, f.later.pin, None),
            &f.dir,
        ),
        &expected_json(VERIFY, f.base.pin, f.later.pin, &ranges),
    );
}

#[test]
fn package_cli_existing_nested_and_missing_parent_targets_are_not_changed() {
    let f = fixture(1, 3);
    let package = f.dir.path("valid-package");
    let ranges = [(0, 150, 300)];
    let wire = expected_package(f.base.pin, f.later.pin, &ranges, &f.later.bytes);
    fs::write(&package, &wire).unwrap();
    let existing_file = f.dir.path("existing-file");
    let empty_file = f.dir.path("empty-file");
    let existing_directory = f.dir.path("existing-directory");
    let empty_directory = f.dir.path("empty-directory");
    fs::write(&existing_file, b"keep existing file").unwrap();
    fs::write(&empty_file, []).unwrap();
    fs::create_dir(&existing_directory).unwrap();
    fs::write(existing_directory.join("sentinel"), b"keep directory").unwrap();
    fs::create_dir(&empty_directory).unwrap();
    let nested_base = f.base.path.join("must-not-create");
    let nested_later = f.later.path.join("must-not-create");
    let missing_parent = f.dir.path("missing-parent/target");
    for mode in [PACK, RESTORE] {
        let source = if mode == PACK {
            &f.later.path
        } else {
            &package
        };
        let mut targets = vec![
            &existing_file,
            &empty_file,
            &existing_directory,
            &empty_directory,
            &f.base.path,
            &f.later.path,
            &package,
            &nested_base,
            &missing_parent,
        ];
        if mode == PACK {
            targets.push(&nested_later);
        }
        for target in targets {
            failure(
                &call_readonly(
                    &package_args(
                        mode,
                        &f.base.path,
                        f.base.pin,
                        source,
                        f.later.pin,
                        Some(target),
                    ),
                    &f.dir,
                ),
                &f.dir,
            );
        }
    }
    assert!(!nested_base.exists());
    assert!(!nested_later.exists());
    assert!(!missing_parent.exists());
    // Unrelated siblings of the package are legal, including a new restored
    // archive. Parent identity checks must not require an empty parent folder.
    let fresh_package = f.dir.path("fresh-package");
    let fresh_archive = f.dir.path("fresh-archive");
    for (mode, source, target) in [
        (PACK, &f.later.path, &fresh_package),
        (RESTORE, &package, &fresh_archive),
    ] {
        success(
            &call(&package_args(
                mode,
                &f.base.path,
                f.base.pin,
                source,
                f.later.pin,
                Some(target),
            )),
            &expected_json(mode, f.base.pin, f.later.pin, &ranges),
        );
    }
    assert!(fs::read(&package).unwrap() == wire);
    assert!(fs::read(&fresh_package).unwrap() == wire);
    unchanged(&fresh_archive, &f.later.bytes);
    unchanged(&f.base.path, &f.base.bytes);
    unchanged(&f.later.path, &f.later.bytes);
}

#[test]
fn package_cli_writer_locks_reject_and_shared_readers_coexist() {
    let f = fixture(1, 3);
    let package = f.dir.path("locked-package");
    let target = f.dir.path("not-created-while-locked");
    let ranges = [(0, 150, 300)];
    let wire = expected_package(f.base.pin, f.later.pin, &ranges, &f.later.bytes);
    let mut base = ActiveArchive::open(&f.base.path, f.base.pin).unwrap();
    let mut later = ActiveArchive::open(&f.later.path, f.later.pin).unwrap();
    let owner = base.pack_incremental_new(&mut later, &package).unwrap();
    for mode in [VERIFY, RESTORE] {
        failure(
            &call(&package_args(
                mode,
                &f.base.path,
                f.base.pin,
                &package,
                f.later.pin,
                (mode == RESTORE).then_some(target.as_path()),
            )),
            &f.dir,
        );
        assert!(!target.exists());
    }
    // The actual creation handle remains exclusively locked until drop; do
    // not read it through fs::read while its Windows writer lock is held.
    drop(owner);
    drop(later);
    drop(base);
    assert!(fs::read(&package).unwrap() == wire);
    for path in [&f.base.path, &f.later.path] {
        let owner = f.genesis.open_pool(path).unwrap();
        let modes: &[&str] = if path == &f.base.path {
            &[PACK, VERIFY, RESTORE]
        } else {
            &[PACK]
        };
        for &mode in modes {
            let source = if mode == PACK {
                &f.later.path
            } else {
                &package
            };
            failure(
                &call(&package_args(
                    mode,
                    &f.base.path,
                    f.base.pin,
                    source,
                    f.later.pin,
                    (mode != VERIFY).then_some(target.as_path()),
                )),
                &f.dir,
            );
            assert!(!target.exists());
        }
        drop(owner);
        unchanged(&f.base.path, &f.base.bytes);
        unchanged(&f.later.path, &f.later.bytes);
        assert!(fs::read(&package).unwrap() == wire);
    }
    let mut base = ActiveArchive::open(&f.base.path, f.base.pin).unwrap();
    let later = ActiveArchive::open(&f.later.path, f.later.pin).unwrap();
    let reader = ActiveIncrementalPackage::open(&package, &mut base, f.later.pin).unwrap();
    for path in [&f.base.path, &f.later.path] {
        assert!(matches!(f.genesis.open_pool(path), Err(PoolError::Locked)));
    }
    let copied_package = f.dir.path("shared-reader-package");
    let restored = f.dir.path("shared-reader-restored");
    for (mode, source, output) in [
        (PACK, &f.later.path, Some(copied_package.as_path())),
        (VERIFY, &package, None),
        (RESTORE, &package, Some(restored.as_path())),
    ] {
        success(
            &call(&package_args(
                mode,
                &f.base.path,
                f.base.pin,
                source,
                f.later.pin,
                output,
            )),
            &expected_json(mode, f.base.pin, f.later.pin, &ranges),
        );
    }
    drop(reader);
    drop(later);
    drop(base);
    for path in [&f.base.path, &f.later.path] {
        f.genesis.open_pool(path).unwrap();
    }
    assert!(fs::read(&package).unwrap() == wire);
    assert!(fs::read(&copied_package).unwrap() == wire);
    unchanged(&restored, &f.later.bytes);
    unchanged(&f.base.path, &f.base.bytes);
    unchanged(&f.later.path, &f.later.bytes);
}

#[test]
fn package_cli_stdout_failure_retains_complete_outputs_for_explicit_verify() {
    let f = fixture(1, 3);
    let ranges = [(0, 150, 300)];
    let wire = expected_package(f.base.pin, f.later.pin, &ranges, &f.later.bytes);
    let positive_package = f.dir.path("positive-package");
    let positive_restored = f.dir.path("positive-restored");
    for (mode, source, output) in [
        (PACK, &f.later.path, Some(positive_package.as_path())),
        (VERIFY, &positive_package, None),
        (
            RESTORE,
            &positive_package,
            Some(positive_restored.as_path()),
        ),
    ] {
        let receipt = f.dir.path(&format!("{mode}-writable-stdout.json"));
        let mut result = Command::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"))
            .args(package_args(
                mode,
                &f.base.path,
                f.base.pin,
                source,
                f.later.pin,
                output,
            ))
            .stdout(Stdio::from(File::create_new(&receipt).unwrap()))
            .output()
            .unwrap();
        assert!(result.stdout.is_empty());
        result.stdout = fs::read(&receipt).unwrap();
        success(
            &result,
            &expected_json(mode, f.base.pin, f.later.pin, &ranges),
        );
    }
    assert!(fs::read(&positive_package).unwrap() == wire);
    unchanged(&positive_restored, &f.later.bytes);

    let package = f.dir.path("complete-package-without-receipt");
    let restored = f.dir.path("complete-restore-without-receipt");
    let sink = f.dir.path("read-only-stdout");
    fs::write(&sink, b"keep stdout sink").unwrap();
    for (mode, source, output) in [
        (PACK, &f.later.path, Some(package.as_path())),
        (VERIFY, &package, None),
        (RESTORE, &package, Some(restored.as_path())),
    ] {
        let mut read_only = File::open(&sink).unwrap();
        assert!(
            read_only.write_all(b"must not be written").is_err(),
            "{mode}: stdout fixture unexpectedly permits writes"
        );
        let result = Command::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"))
            .args(package_args(
                mode,
                &f.base.path,
                f.base.pin,
                source,
                f.later.pin,
                output,
            ))
            .stdout(Stdio::from(read_only))
            .output()
            .unwrap();
        failure(&result, &f.dir);
        assert_eq!(fs::read(&sink).unwrap(), b"keep stdout sink");
        assert!(fs::read(&package).unwrap() == wire);
        success(
            &call_readonly(
                &package_args(
                    VERIFY,
                    &f.base.path,
                    f.base.pin,
                    &package,
                    f.later.pin,
                    None,
                ),
                &f.dir,
            ),
            &expected_json(VERIFY, f.base.pin, f.later.pin, &ranges),
        );
        if mode == RESTORE {
            unchanged(&restored, &f.later.bytes);
            verify_active(&restored, f.later.pin);
        }
        unchanged(&f.base.path, &f.base.bytes);
        unchanged(&f.later.path, &f.later.bytes);
    }
    // Receipt loss cannot authorize replacing either complete output.
    for (mode, source, target) in [
        (PACK, &f.later.path, &package),
        (RESTORE, &package, &restored),
    ] {
        failure(
            &call_readonly(
                &package_args(
                    mode,
                    &f.base.path,
                    f.base.pin,
                    source,
                    f.later.pin,
                    Some(target),
                ),
                &f.dir,
            ),
            &f.dir,
        );
    }
}

#[cfg(unix)]
#[test]
fn package_cli_symlink_sources_and_source_parent_alias_targets_are_refused() {
    use std::os::unix::fs::symlink;

    let f = fixture(1, 3);
    let package = f.dir.path("package");
    let ranges = [(0, 150, 300)];
    let wire = expected_package(f.base.pin, f.later.pin, &ranges, &f.later.bytes);
    fs::write(&package, &wire).unwrap();
    let base_alias = f.dir.path("base-link");
    let later_alias = f.dir.path("later-link");
    let package_alias = f.dir.path("package-link");
    symlink(&f.base.path, &base_alias).unwrap();
    symlink(&f.later.path, &later_alias).unwrap();
    symlink(&package, &package_alias).unwrap();
    let target = f.dir.path("no-target");
    for mode in [PACK, VERIFY, RESTORE] {
        let source = if mode == PACK {
            &f.later.path
        } else {
            &package
        };
        let valid = package_args(
            mode,
            &f.base.path,
            f.base.pin,
            source,
            f.later.pin,
            (mode != VERIFY).then_some(target.as_path()),
        );
        let mut base_link = valid.clone();
        set_option(&mut base_link, "--base", text(&base_alias));
        failure(&call_readonly(&base_link, &f.dir), &f.dir);
        let mut source_link = valid.clone();
        set_option(
            &mut source_link,
            "--source",
            text(if mode == PACK {
                &later_alias
            } else {
                &package_alias
            }),
        );
        failure(&call_readonly(&source_link, &f.dir), &f.dir);
        if mode != VERIFY {
            let mut nested = valid.clone();
            set_option(&mut nested, "--output", text(&base_alias.join("nested")));
            failure(&call_readonly(&nested, &f.dir), &f.dir);
            let mut existing_link = valid.clone();
            set_option(&mut existing_link, "--output", text(&package_alias));
            failure(&call_readonly(&existing_link, &f.dir), &f.dir);
        }
        if mode == PACK {
            let mut nested = valid.clone();
            set_option(&mut nested, "--output", text(&later_alias.join("nested")));
            failure(&call_readonly(&nested, &f.dir), &f.dir);
        }
        assert!(!target.exists());
    }
    success(
        &call_readonly(
            &package_args(
                VERIFY,
                &f.base.path,
                f.base.pin,
                &package,
                f.later.pin,
                None,
            ),
            &f.dir,
        ),
        &expected_json(VERIFY, f.base.pin, f.later.pin, &ranges),
    );
}
