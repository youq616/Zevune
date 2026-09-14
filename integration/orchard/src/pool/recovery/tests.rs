use super::*;
use rand::{rngs::OsRng, RngCore};
use std::path::PathBuf;

struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let name: String = nonce.iter().map(|b| format!("{b:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-recovery-{name}"));
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
fn bytes(pool: &mut PoolStore) -> Vec<u8> {
    pool.file.rewind().unwrap();
    let mut raw = Vec::new();
    pool.file.read_to_end(&mut raw).unwrap();
    raw
}
fn empty_block(pool: &mut PoolStore, id: u8) {
    let p = pool
        .prepare(pool.summary().unwrap().height + 1, [id; 32], &[])
        .unwrap();
    pool.commit(p).unwrap();
}

#[test]
fn recovery_checkpoint_codec_bounds_and_every_truncation() {
    let dir = Dir::new();
    let mut pool = PoolStore::create(&dir.path("pool")).unwrap();
    let cp = pool.recovery_checkpoint().unwrap();
    let raw = cp.to_bytes();
    assert_eq!(RecoveryCheckpoint::from_bytes(&raw).unwrap(), cp);
    for n in 0..raw.len() {
        assert!(RecoveryCheckpoint::from_bytes(&raw[..n]).is_err());
    }
    let mut appended = raw.to_vec();
    appended.push(0);
    assert!(RecoveryCheckpoint::from_bytes(&appended).is_err());
    for range in [8..40, 48..80, 88..120] {
        let mut damaged = raw;
        damaged[range].fill(0);
        assert!(RecoveryCheckpoint::from_bytes(&damaged).is_err());
    }
    for height in [MAX_RECORDS + 1, u64::MAX] {
        let mut damaged = raw;
        damaged[40..48].copy_from_slice(&height.to_be_bytes());
        assert!(RecoveryCheckpoint::from_bytes(&damaged).is_err());
    }
    for size in [0, 43, MAX_JOURNAL_BYTES + 1, u64::MAX] {
        let mut damaged = raw;
        damaged[80..88].copy_from_slice(&size.to_be_bytes());
        assert!(RecoveryCheckpoint::from_bytes(&damaged).is_err());
    }
    let mut damaged = raw;
    damaged[0] ^= 1;
    assert!(RecoveryCheckpoint::from_bytes(&damaged).is_err());
}
#[test]
fn recovery_full_copy_matches_and_original_keeps_prepared_block() {
    let dir = Dir::new();
    let source = dir.path("pool");
    let mut pool = PoolStore::create(&source).unwrap();
    empty_block(&mut pool, 1);
    let prepared = pool.prepare(2, [2; 32], &[]).unwrap();
    let before = bytes(&mut pool);
    let cp = pool.recovery_checkpoint().unwrap();
    assert_eq!(cp.height(), 1);
    assert_eq!(bytes(&mut pool), before);
    // Export has not advanced the committed state or invalidated prepared work.
    pool.commit(prepared).unwrap();
    let fresh = pool.recovery_checkpoint().unwrap();
    assert_ne!(fresh, cp);
    drop(pool);
    assert!(RecoveryArchive::open(&source, cp).is_err());
    let mut archive = RecoveryArchive::open(&source, fresh).unwrap();
    let target = dir.path("restored");
    assert_eq!(archive.copy_new(&target).unwrap(), fresh);
    assert_eq!(fs::read(&source).unwrap(), fs::read(&target).unwrap());
    let restored = PoolStore::open(&target).unwrap();
    restored
        .check_checkpoint(fresh.height(), fresh.app_hash())
        .unwrap();
}
#[test]
fn recovery_refuses_overwrite_live_writers_links_and_unknown_paths() {
    let dir = Dir::new();
    let source = dir.path("pool");
    let mut pool = PoolStore::create(&source).unwrap();
    let cp = pool.recovery_checkpoint().unwrap();
    assert!(matches!(
        RecoveryArchive::open(&source, cp),
        Err(PoolError::Locked)
    ));
    drop(pool);
    let original = fs::read(&source).unwrap();
    let mut archive = RecoveryArchive::open(&source, cp).unwrap();
    assert!(archive.copy_new(&source).is_err());
    let target = dir.path("existing");
    fs::write(&target, b"keep").unwrap();
    assert!(archive.copy_new(&target).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"keep");
    assert!(archive.copy_new(&dir.0).is_err());
    assert!(archive.copy_new(Path::new("relative.journal")).is_err());
    assert!(archive.copy_new(&dir.path("missing/target")).is_err());
    assert!(RecoveryArchive::open(Path::new("relative.journal"), cp).is_err());
    let alias = dir.path("hardlink");
    fs::hard_link(&source, &alias).unwrap();
    assert!(archive.copy_new(&alias).is_err());
    assert_eq!(fs::read(&source).unwrap(), original);
    #[cfg(unix)]
    {
        let link = dir.path("link");
        std::os::unix::fs::symlink(&source, &link).unwrap();
        assert!(RecoveryArchive::open(&link, cp).is_err());
        assert!(archive.copy_new(&link).is_err());
    }
}
#[test]
fn recovery_wrong_state_domain_length_or_bytes_pin_rejected() {
    let dir = Dir::new();
    let source = dir.path("pool");
    let mut pool = PoolStore::create(&source).unwrap();
    empty_block(&mut pool, 1);
    let cp = pool.recovery_checkpoint().unwrap();
    drop(pool);
    for offset in [8, 47, 48, 87, 88] {
        let mut raw = cp.to_bytes();
        raw[offset] ^= 1;
        if let Ok(wrong) = RecoveryCheckpoint::from_bytes(&raw) {
            assert!(RecoveryArchive::open(&source, wrong).is_err());
        }
    }
    let good = fs::read(&source).unwrap();
    let mut corrupt = good.clone();
    *corrupt.last_mut().unwrap() ^= 1;
    fs::write(&source, &corrupt).unwrap();
    assert!(RecoveryArchive::open(&source, cp).is_err());
    let mut self_pinned = cp;
    self_pinned.journal_hash = Sha256::digest(&corrupt).into();
    assert!(RecoveryArchive::open(&source, self_pinned).is_err());
    fs::write(&source, &good[..good.len() - 1]).unwrap();
    assert!(RecoveryArchive::open(&source, cp).is_err());
    fs::write(&source, [&good[..], &[0]].concat()).unwrap();
    assert!(RecoveryArchive::open(&source, cp).is_err());
}
#[test]
fn recovery_partial_write_and_lost_ack_never_replace_or_repair_source() {
    let dir = Dir::new();
    let source = dir.path("pool");
    let mut pool = PoolStore::create(&source).unwrap();
    empty_block(&mut pool, 1);
    let cp = pool.recovery_checkpoint().unwrap();
    drop(pool);
    let before = fs::read(&source).unwrap();
    let mut archive = RecoveryArchive::open(&source, cp).unwrap();
    for fault in [1, 2] {
        let target = dir.path(&format!("fault{fault}"));
        archive.fault = fault;
        assert!(matches!(archive.copy_new(&target), Err(PoolError::Storage)));
        assert!(target.exists());
        assert_eq!(fs::read(&source).unwrap(), before);
        let checked = RecoveryArchive::open(&target, cp);
        assert_eq!(checked.is_ok(), fault == 2);
        drop(checked);
        // Explicitly trying again does not overwrite a partial or complete copy.
        archive.fault = 0;
        let previous = fs::read(&target).unwrap();
        assert!(archive.copy_new(&target).is_err());
        assert_eq!(fs::read(&target).unwrap(), previous);
    }
    archive.copy_new(&dir.path("good")).unwrap();
}
#[test]
fn recovery_invalid_store_does_not_export_a_checkpoint() {
    let dir = Dir::new();
    let source = dir.path("pool");
    let mut pool = PoolStore::create(&source).unwrap();
    pool.available = false;
    assert!(pool.recovery_checkpoint().is_err());
    drop(pool);
    let mut pool = PoolStore::open(&source).unwrap();
    pool.file.write_all(b"incomplete").unwrap();
    assert!(pool.recovery_checkpoint().is_err());
    assert!(!pool.available);
}
#[test]
fn recovery_untrusted_header_sizes_are_bounded_even_with_a_matching_file_hash() {
    let dir = Dir::new();
    let source = dir.path("pool");
    let mut pool = PoolStore::create(&source).unwrap();
    let mut cp = pool.recovery_checkpoint().unwrap();
    drop(pool);
    let mut raw = fs::read(&source).unwrap();
    raw[40..44].copy_from_slice(&u32::MAX.to_be_bytes());
    cp.journal_hash = Sha256::digest(&raw).into();
    fs::write(&source, &raw).unwrap();
    assert!(matches!(
        RecoveryArchive::open(&source, cp),
        Err(PoolError::Bounds)
    ));
}
#[cfg(feature = "local-funding-lab")]
#[test]
fn recovery_real_lab2_payment_replay_and_rechecksums_cannot_bypass_authorization() {
    use crate::pool::testnet::TestGenesis;
    use crate::wallet::{Wallet, WalletProver};
    let dir = Dir::new();
    let source = dir.path("pool");
    let mut alice = Wallet::create().unwrap();
    let mut bob = Wallet::create().unwrap();
    let genesis = TestGenesis::generate(&[(alice.receive_address(0).unwrap(), 100_000)]).unwrap();
    let mut pool = genesis.create_pool(&source).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    alice.sync(&history).unwrap();
    let prover = WalletProver::new();
    let tx = alice
        .build_payment(bob.receive_address(0).unwrap(), 10_000, 100, 20, &prover)
        .unwrap()
        .bytes()
        .to_vec();
    let p = pool.prepare(1, [1; 32], std::slice::from_ref(&tx)).unwrap();
    pool.commit(p).unwrap();
    let cp = pool.recovery_checkpoint().unwrap();
    let good = bytes(&mut pool);
    drop(pool);
    let mut archive = RecoveryArchive::open(&source, cp).unwrap();
    let target = dir.path("restored");
    archive.copy_new(&target).unwrap();
    let mut restored = genesis.open_pool(&target).unwrap();
    assert!(matches!(
        restored.prepare(2, [2; 32], std::slice::from_ref(&tx)),
        Err(PoolError::DoubleSpend)
    ));
    bob.sync(&genesis.wallet_history(&mut restored).unwrap())
        .unwrap();
    let next = bob
        .build_payment(alice.receive_address(1).unwrap(), 1_000, 100, 20, &prover)
        .unwrap()
        .bytes()
        .to_vec();
    let p = restored.prepare(2, [2; 32], &[next]).unwrap();
    assert_eq!(restored.commit(p).unwrap().fees, 200);
    drop(restored);
    drop(archive);
    // Recompute all ordinary hashes around a changed real binding signature.
    // The unchanged real verifier, not the archive checksum, must still reject.
    let mut corrupt = good;
    let header = 76 + 32;
    let body_len = u32::from_be_bytes(corrupt[header..header + 4].try_into().unwrap()) as usize;
    let end = header + 4 + body_len;
    corrupt[end - 1] ^= 1;
    let checksum: Hash = Sha256::digest(&corrupt[header + 4..end]).into();
    corrupt[end..end + 32].copy_from_slice(&checksum);
    let mut forged = cp;
    forged.journal_hash = Sha256::digest(&corrupt).into();
    let bad = dir.path("forged");
    fs::write(&bad, &corrupt).unwrap();
    assert!(matches!(
        RecoveryArchive::open(&bad, forged),
        Err(PoolError::Authorization)
    ));
}

#[cfg(unix)]
#[test]
fn recovery_readonly_archive_and_changed_source_are_checked_before_target_creation() {
    use std::os::unix::fs::PermissionsExt;
    let dir = Dir::new();
    let path = dir.path("source");
    let mut pool = PoolStore::create(&path).unwrap();
    let cp = pool.recovery_checkpoint().unwrap();
    drop(pool);
    let original = fs::read(&path).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o400)).unwrap();
    let mut archive = RecoveryArchive::open(&path, cp).unwrap();
    archive.copy_new(&dir.path("readonly-copy")).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    // Unix advisory locks do not stop an uncooperative writer. Detect persistent
    // byte changes rather than claiming the lock makes the host tamper-proof.
    let mut changed = original.clone();
    changed[0] ^= 1;
    fs::write(&path, &changed).unwrap();
    let target = dir.path("not-created");
    assert!(matches!(archive.copy_new(&target), Err(PoolError::Corrupt)));
    assert!(!target.exists());
    assert_eq!(fs::read(&path).unwrap(), changed);
}

#[cfg(feature = "local-funding-lab")]
#[test]
fn recovery_legacy_funded_header_is_preserved_not_relabelled_as_lab2() {
    use crate::pool::testnet::TestGenesis;
    use crate::wallet::Wallet;
    let dir = Dir::new();
    let path = dir.path("legacy");
    let wallet = Wallet::create().unwrap();
    let generated =
        TestGenesis::generate(&[(wallet.receive_address(0).unwrap(), 100_000)]).unwrap();
    let mut raw = generated.bytes().to_vec();
    raw[..8].copy_from_slice(b"ZVTGEN01");
    raw.drain(50..82);
    let genesis = TestGenesis::decode(&raw).unwrap();
    let mut pool = genesis.create_pool(&path).unwrap();
    empty_block(&mut pool, 1);
    let cp = pool.recovery_checkpoint().unwrap();
    drop(pool);
    let mut archive = RecoveryArchive::open(&path, cp).unwrap();
    let target = dir.path("copy");
    archive.copy_new(&target).unwrap();
    let raw = fs::read(&target).unwrap();
    assert_eq!(&raw[..8], b"ZVOPOL01");
    let mut restored = genesis.open_pool(&target).unwrap();
    assert_eq!(restored.recovery_checkpoint().unwrap(), cp);
    drop(restored);
    assert!(matches!(
        generated.open_pool(&target),
        Err(PoolError::Genesis)
    ));
}
