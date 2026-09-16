#![cfg(feature = "local-funding-lab")]
//! Real recovery process calls with public, valueless genesis; no mock verifier.
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use zevune_orchard_lab::pool::recovery::RecoveryCheckpoint;
use zevune_orchard_lab::pool::testnet::TestGenesis;
use zevune_orchard_lab::wallet::Wallet;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let path = std::env::temp_dir().join(format!("zevune-recovery-cli-{}", hex(&nonce)));
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
fn hex(raw: &[u8]) -> String {
    raw.iter().map(|b| format!("{b:02x}")).collect()
}
fn call(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_zevune-pool-recovery"))
        .args(args)
        .output()
        .unwrap()
}
fn text(path: &Path) -> &str {
    path.to_str().unwrap()
}
fn pin(output: &Output) -> String {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8(output.stdout.clone()).unwrap();
    assert!(text.contains("\"finality_verified\":false"));
    assert!(text.contains("\"validator_ready\":false"));
    assert!(text.contains("\"real_funds_allowed\":false"));
    text.split("\"checkpoint\":\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string()
}
#[test]
fn recovery_cli_checkpoint_backup_verify_restore_and_continuation() {
    let d = Dir::new();
    let source = d.path("pool");
    let manifest = d.path("genesis");
    let backup = d.path("backup");
    let restored = d.path("restored");
    let wallet = Wallet::create().unwrap();
    let genesis = TestGenesis::generate(&[(wallet.receive_address(0).unwrap(), 100_000)]).unwrap();
    genesis.write_new(&manifest).unwrap();
    let mut pool = genesis.create_pool(&source).unwrap();
    let p = pool.prepare(1, [1; 32], &[]).unwrap();
    let s = pool.commit(p).unwrap();
    let cp = pool.recovery_checkpoint().unwrap();
    drop(pool);
    let original = fs::read(&source).unwrap();
    let result = call(&[
        "checkpoint",
        "--no-real-funds",
        "--source",
        text(&source),
        "--genesis",
        text(&manifest),
        "--genesis-sha256",
        &hex(&genesis.digest()),
        "--height",
        "1",
        "--app-hash",
        &hex(&s.app_hash),
    ]);
    let encoded = pin(&result);
    assert_eq!(encoded, hex(&cp.to_bytes()));
    let result = call(&[
        "backup",
        "--no-real-funds",
        "--source",
        text(&source),
        "--output",
        text(&backup),
        "--checkpoint",
        &encoded,
    ]);
    assert_eq!(pin(&result), encoded);
    let result = call(&[
        "verify",
        "--no-real-funds",
        "--source",
        text(&backup),
        "--checkpoint",
        &encoded,
    ]);
    assert_eq!(pin(&result), encoded);
    let result = call(&[
        "restore",
        "--no-real-funds",
        "--source",
        text(&backup),
        "--output",
        text(&restored),
        "--checkpoint",
        &encoded,
    ]);
    assert_eq!(pin(&result), encoded);
    assert_eq!(fs::read(&source).unwrap(), original);
    assert_eq!(fs::read(&restored).unwrap(), original);
    let mut pool = genesis.open_pool(&restored).unwrap();
    assert_eq!(pool.summary().unwrap(), s);
    let p = pool.prepare(2, [2; 32], &[]).unwrap();
    assert_eq!(pool.commit(p).unwrap().height, 2);
    // Copying cannot modify already saved source/backup bytes.
    assert_eq!(fs::read(&backup).unwrap(), original);
    // Independently assemble the checkpoint layout, not just a round trip.
    let header = &original[..108];
    let mut expected = b"ZVPRCP01".to_vec();
    expected.extend_from_slice(&Sha256::digest(header));
    expected.extend_from_slice(&1u64.to_be_bytes());
    expected.extend_from_slice(&s.app_hash);
    expected.extend_from_slice(&(original.len() as u64).to_be_bytes());
    expected.extend_from_slice(&Sha256::digest(&original));
    assert_eq!(RecoveryCheckpoint::from_bytes(&expected).unwrap(), cp);
}
#[test]
fn recovery_cli_bad_options_do_not_touch_source_or_existing_target() {
    let d = Dir::new();
    let source = d.path("not-a-journal");
    let target = d.path("existing");
    fs::write(&source, b"keep source").unwrap();
    fs::write(&target, b"keep target").unwrap();
    for args in [
        vec![],
        vec!["unknown"],
        vec!["verify"],
        vec![
            "backup",
            "--source",
            text(&source),
            "--output",
            text(&target),
            "--checkpoint",
            "bad",
        ],
        vec![
            "restore",
            "--no-real-funds",
            "--source",
            text(&source),
            "--output",
            text(&target),
            "--checkpoint",
            "bad",
        ],
        vec![
            "verify",
            "--no-real-funds",
            "--source",
            text(&source),
            "--source",
            text(&target),
            "--checkpoint",
            "bad",
        ],
        vec![
            "verify",
            "--no-real-funds",
            "--no-real-funds",
            "--source",
            text(&source),
            "--checkpoint",
            "bad",
        ],
    ] {
        let out = call(&args);
        assert!(!out.status.success());
        assert!(out.stdout.is_empty());
        assert!(!String::from_utf8_lossy(&out.stderr).contains(text(&d.0)));
        assert_eq!(fs::read(&source).unwrap(), b"keep source");
        assert_eq!(fs::read(&target).unwrap(), b"keep target");
    }
    assert!(call(&["--help"]).status.success());
}

#[test]
fn segmented_cli_pack_verify_restore_and_reject_overwrite() {
    let d = Dir::new();
    let source = d.path("pool");
    let folder = d.path("archive");
    let target = d.path("restored");
    let mut pool = zevune_orchard_lab::pool::PoolStore::create(&source).unwrap();
    let prepared = pool.prepare(1, [1; 32], &[]).unwrap();
    pool.commit(prepared).unwrap();
    let cp = pool.recovery_checkpoint().unwrap();
    let encoded = hex(&cp.to_bytes());
    drop(pool);
    let before = fs::read(&source).unwrap();
    for (mode, input, output) in [
        ("pack", &source, Some(&folder)),
        ("verify-segments", &folder, None),
        ("restore-segments", &folder, Some(&target)),
    ] {
        let mut args = vec![
            mode,
            "--no-real-funds",
            "--source",
            text(input),
            "--checkpoint",
            &encoded,
        ];
        if let Some(output) = output {
            args.extend(["--output", text(output)]);
        }
        assert_eq!(pin(&call(&args)), encoded);
        if output.is_some() {
            let refused = call(&args);
            assert!(!refused.status.success());
            assert!(refused.stdout.is_empty());
        }
        // Explicit no-funds acknowledgement cannot be omitted on new commands.
        args.retain(|x| *x != "--no-real-funds");
        assert!(!call(&args).status.success());
    }
    assert_eq!(fs::read(&source).unwrap(), before);
    assert_eq!(fs::read(&target).unwrap(), before);
}

#[test]
fn indexed_cli_locations_match_original_frames_without_writing_sidecars() {
    let d = Dir::new();
    let source = d.path("source");
    let folder = d.path("archive");
    let mut pool = zevune_orchard_lab::pool::PoolStore::create(&source).unwrap();
    for id in 1..=3 {
        let block = pool.prepare(id, [id as u8; 32], &[]).unwrap();
        pool.commit(block).unwrap();
    }
    let cp = pool.recovery_checkpoint().unwrap();
    let encoded = hex(&cp.to_bytes());
    drop(pool);
    assert_eq!(
        pin(&call(&[
            "pack",
            "--no-real-funds",
            "--source",
            text(&source),
            "--output",
            text(&folder),
            "--checkpoint",
            &encoded
        ])),
        encoded
    );
    let before: Vec<_> = fs::read_dir(&folder)
        .unwrap()
        .map(|p| {
            let p = p.unwrap().path();
            (p.file_name().unwrap().to_owned(), fs::read(p).unwrap())
        })
        .collect();
    let out = call(&[
        "index",
        "--no-real-funds",
        "--source",
        text(&folder),
        "--checkpoint",
        &encoded,
    ]);
    assert_eq!(pin(&out), encoded);
    let report = String::from_utf8(out.stdout).unwrap();
    assert!(report.contains("\"header_bytes\":44"));
    assert!(report.contains("\"total_records\":3"));
    assert!(report.contains("\"height\":1,\"offset\":44,\"length\":150"));
    assert!(report.contains("\"height\":3,\"offset\":344,\"length\":150"));
    let out = call(&[
        "locate-height",
        "--no-real-funds",
        "--source",
        text(&folder),
        "--checkpoint",
        &encoded,
        "--height",
        "2",
    ]);
    assert_eq!(pin(&out), encoded);
    let report = String::from_utf8(out.stdout).unwrap();
    assert!(report.contains("\"height\":2,\"offset\":194,\"length\":150"));
    assert!(!report.contains("\"offset\":44,"));
    assert!(!report.contains("\"offset\":344,"));
    for height in [
        "0",
        "4",
        "18446744073709551615",
        "18446744073709551616",
        "01",
        "+1",
        "-1",
        " 1",
    ] {
        let out = call(&[
            "locate-height",
            "--no-real-funds",
            "--source",
            text(&folder),
            "--checkpoint",
            &encoded,
            "--height",
            height,
        ]);
        assert!(!out.status.success(), "height {height}");
        assert!(out.stdout.is_empty());
        assert!(!String::from_utf8_lossy(&out.stderr).contains(text(&d.0)));
    }
    for mode in ["index", "locate-height"] {
        assert!(!call(&[
            mode,
            "--source",
            text(&folder),
            "--checkpoint",
            &encoded,
            "--height",
            "1"
        ])
        .status
        .success());
        assert!(!call(&[
            mode,
            "--no-real-funds",
            "--source",
            text(&folder),
            "--checkpoint",
            &encoded,
            "--output",
            text(&d.path("not-created"))
        ])
        .status
        .success());
    }
    assert!(!d.path("not-created").exists());
    assert_eq!(fs::read_dir(&folder).unwrap().count(), before.len());
    for (name, contents) in before {
        assert_eq!(fs::read(folder.join(name)).unwrap(), contents);
    }
    let mut raw = fs::read(folder.join("segment-000000.bin")).unwrap();
    *raw.last_mut().unwrap() ^= 1;
    fs::write(folder.join("segment-000000.bin"), raw).unwrap();
    let out = call(&[
        "index",
        "--no-real-funds",
        "--source",
        text(&folder),
        "--checkpoint",
        &encoded,
    ]);
    assert!(!out.status.success());
    assert!(out.stdout.is_empty());
}
