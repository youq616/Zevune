#![cfg(not(feature = "local-funding-lab"))]

use rand::{rngs::OsRng, RngCore};
use std::fs;
use std::process::Command;

#[test]
fn default_worker_refuses_explicit_funding_arguments() {
    let mut random = [0; 16];
    OsRng.fill_bytes(&mut random);
    let name: String = random.iter().map(|b| format!("{b:02x}")).collect();
    let dir = std::env::temp_dir().join(format!("zevune-default-policy-{name}"));
    fs::create_dir(&dir).unwrap();
    let journal = dir.join("state.journal");
    let result = Command::new(env!("CARGO_BIN_EXE_zevune-pool-worker"))
        .arg("create")
        .arg(&journal)
        .arg(dir.join("public-genesis.bin"))
        .arg("11".repeat(32))
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(!journal.exists());
    assert!(result.stdout.is_empty());
    fs::remove_dir_all(dir).unwrap();
}
