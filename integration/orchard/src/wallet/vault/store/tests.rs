use super::*;
use crate::pool::PoolStore;
use std::path::PathBuf;
use std::process::Command;

const PASSWORD: &[u8] = b"synthetic-wallet-storage-tests-only";
struct Dir(PathBuf);
impl Dir {
    fn new() -> Self {
        let mut random = [0; 16];
        OsRng.fill_bytes(&mut random);
        let name: String = random.iter().map(|b| format!("{b:02x}")).collect();
        let path = std::env::temp_dir().join(format!("zevune-wallet-store-{name}"));
        fs::create_dir(&path).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
        }
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
fn advance(pool: &mut PoolStore, height: u64) -> WalletHistory {
    let mut id = [0; 32];
    id[..8].copy_from_slice(&height.to_be_bytes());
    let plan = pool.prepare(height, id, &[]).unwrap();
    pool.commit(plan).unwrap();
    pool.wallet_history().unwrap()
}

#[test]
fn create_sync_backup_reopen_and_exact_source_protection() {
    let dir = Dir::new();
    let path = dir.path("local.zwallet");
    let backup = dir.path("copy.zwallet");
    let mut store = WalletStore::create(&path, PASSWORD).unwrap();
    let address = store.view().unwrap().receive_address(9).unwrap();
    assert_eq!(store.receipt().unwrap().generation, 1);
    assert_eq!(store.view().unwrap().balance(), Err(WalletError::NotSynced));
    assert!(WalletStore::create(&path, PASSWORD).is_err());
    assert!(matches!(
        WalletStore::open(&path, PASSWORD, None),
        Err(StoreError::Locked)
    ));
    let mut pool = PoolStore::create(&dir.path("pool.journal")).unwrap();
    let history = pool.wallet_history().unwrap();
    store.sync(&history).unwrap();
    let receipt = store.receipt().unwrap();
    assert_eq!(receipt.generation, 2);
    store.sync(&history).unwrap();
    assert_eq!(store.receipt().unwrap(), receipt);
    assert!(store.pending_payment().unwrap().is_none());
    assert_eq!(store.backup_new(&backup).unwrap(), receipt);
    assert!(store.backup_new(&backup).is_err());
    assert!(store.backup_new(&path).is_err());
    assert_eq!(store.receipt().unwrap(), receipt);
    drop(store);
    assert_eq!(fs::read(&path).unwrap(), fs::read(&backup).unwrap());
    assert!(matches!(
        WalletStore::open(&path, b"another-synthetic-password", None),
        Err(StoreError::Wallet(WalletError::Authentication))
    ));
    let mut restored = WalletStore::open(&backup, PASSWORD, Some(receipt)).unwrap();
    assert_eq!(
        restored.view().unwrap().receive_address(9).unwrap(),
        address
    );
    assert_eq!(
        restored.view().unwrap().balance(),
        Err(WalletError::NotSynced)
    );
    restored.sync(&history).unwrap();
    assert_eq!(restored.view().unwrap().balance().unwrap(), 0);
    assert_eq!(restored.receipt().unwrap(), receipt);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}

#[test]
fn lock_is_enforced_across_processes() {
    let dir = Dir::new();
    let path = dir.path("locked.zwallet");
    let _store = WalletStore::create(&path, PASSWORD).unwrap();
    let result = Command::new(std::env::current_exe().unwrap())
        .arg("--exact")
        .arg("wallet::vault::store::tests::lock_child")
        .env("ZEVUNE_WALLET_LOCK_TEST_PATH", &path)
        .output()
        .unwrap();
    assert!(result.status.success(), "child lock assertion failed");
}

// Process helper, not an independent functional test. Never accepts a password
// from the process environment; the public constant is confined to test code.
#[test]
fn lock_child() {
    let Some(path) = std::env::var_os("ZEVUNE_WALLET_LOCK_TEST_PATH") else {
        return;
    };
    assert!(matches!(
        WalletStore::open(Path::new(&path), PASSWORD, None),
        Err(StoreError::Locked)
    ));
}

#[test]
fn missing_and_nonregular_files_are_not_created_or_repaired() {
    let dir = Dir::new();
    let path = dir.path("missing.zwallet");
    assert!(WalletStore::open(&path, PASSWORD, None).is_err());
    assert!(!path.exists());
    assert!(matches!(
        WalletStore::open(&dir.0, PASSWORD, None),
        Err(StoreError::Corrupt)
    ));
    fs::write(&path, b"not a wallet").unwrap();
    assert!(WalletStore::open(&path, PASSWORD, None).is_err());
    assert_eq!(fs::read(&path).unwrap(), b"not a wallet");
    #[cfg(unix)]
    {
        let link = dir.path("link.zwallet");
        std::os::unix::fs::symlink(&path, &link).unwrap();
        assert!(WalletStore::open(&link, PASSWORD, None).is_err());
        assert!(WalletStore::create(&link, PASSWORD).is_err());
        assert_eq!(fs::read(&path).unwrap(), b"not a wallet");
    }
}

#[test]
fn partial_write_poison_preserves_failure_and_never_truncates_on_reopen() {
    let dir = Dir::new();
    let path = dir.path("partial.zwallet");
    let mut store = WalletStore::create(&path, PASSWORD).unwrap();
    let before = store.receipt().unwrap();
    let mut pool = PoolStore::create(&dir.path("pool.journal")).unwrap();
    store.fault = 1;
    assert_eq!(
        store.sync(&pool.wallet_history().unwrap()),
        Err(StoreError::Io)
    );
    assert_eq!(store.receipt(), Err(StoreError::Unavailable));
    assert!(matches!(store.view(), Err(StoreError::Unavailable)));
    assert!(matches!(
        store.pending_payment(),
        Err(StoreError::Unavailable)
    ));
    drop(store);
    let damaged = fs::read(&path).unwrap();
    assert!(WalletStore::open(&path, PASSWORD, Some(before)).is_err());
    assert_eq!(fs::read(&path).unwrap(), damaged);
}

#[test]
fn lost_acknowledgement_is_uncertain_and_reopen_reconciles_complete_record() {
    let dir = Dir::new();
    let path = dir.path("uncertain.zwallet");
    let mut store = WalletStore::create(&path, PASSWORD).unwrap();
    let before = store.receipt().unwrap();
    let mut pool = PoolStore::create(&dir.path("pool.journal")).unwrap();
    store.fault = 2;
    assert_eq!(
        store.sync(&pool.wallet_history().unwrap()),
        Err(StoreError::Io)
    );
    assert_eq!(store.receipt(), Err(StoreError::Unavailable));
    drop(store);
    let recovered = WalletStore::open(&path, PASSWORD, Some(before)).unwrap();
    assert_eq!(
        recovered.receipt().unwrap().generation,
        before.generation + 1
    );
    assert_eq!(recovered.view().unwrap().height(), Some(0));
    assert_eq!(
        recovered.view().unwrap().balance(),
        Err(WalletError::NotSynced)
    );
}

#[test]
fn authenticated_predecessor_rejects_rewritten_hash_chain_and_other_journal() {
    let dir = Dir::new();
    let path = dir.path("original.zwallet");
    let mut store = WalletStore::create(&path, PASSWORD).unwrap();
    let mut pool = PoolStore::create(&dir.path("pool.journal")).unwrap();
    store.sync(&pool.wallet_history().unwrap()).unwrap();
    let final_receipt = store.receipt().unwrap();
    drop(store);
    let original = fs::read(&path).unwrap();
    for index in [40, FILE_HEADER + PREFIX + HEADER + 10] {
        let mut changed = original.clone();
        changed[index] ^= 1;
        let mut prev: Hash = Sha256::digest(&changed[..FILE_HEADER]).into();
        // Recompute every unkeyed checksum, not just a one-byte checksum failure.
        for chunk in changed[FILE_HEADER..].chunks_exact_mut(RECORD) {
            chunk[8..PREFIX].copy_from_slice(&prev);
            prev = Sha256::digest(&chunk[..RECORD - 32]).into();
            chunk[RECORD - 32..].copy_from_slice(&prev);
        }
        let forged = dir.path(&format!("forged-{index}.zwallet"));
        fs::write(&forged, changed).unwrap();
        assert!(matches!(
            WalletStore::open(&forged, PASSWORD, None),
            Err(StoreError::Wallet(WalletError::Authentication))
        ));
    }
    assert!(WalletStore::open(&path, PASSWORD, Some(final_receipt)).is_ok());
}

#[test]
fn valid_prefix_needs_independent_receipt_for_rollback_detection() {
    let dir = Dir::new();
    let path = dir.path("current.zwallet");
    let mut store = WalletStore::create(&path, PASSWORD).unwrap();
    let initial = store.receipt().unwrap();
    let mut pool = PoolStore::create(&dir.path("pool.journal")).unwrap();
    store.sync(&advance(&mut pool, 1)).unwrap();
    let last = store.receipt().unwrap();
    drop(store);
    let original = fs::read(&path).unwrap();
    let rollback = dir.path("rollback.zwallet");
    fs::write(&rollback, &original[..FILE_HEADER + RECORD]).unwrap();
    assert!(WalletStore::open(&rollback, PASSWORD, None).is_ok());
    assert!(matches!(
        WalletStore::open(&rollback, PASSWORD, Some(last)),
        Err(StoreError::Rollback)
    ));
    // Advancing from an older trusted pin remains valid, unlike exact-tip-only checks.
    assert!(WalletStore::open(&path, PASSWORD, Some(initial)).is_ok());
    let mut invalid = initial;
    invalid.journal_id[0] ^= 1;
    assert!(matches!(
        WalletStore::open(&path, PASSWORD, Some(invalid)),
        Err(StoreError::Rollback)
    ));
}

#[test]
fn bounds_padding_and_live_disk_drift_fail_closed() {
    let dir = Dir::new();
    let path = dir.path("drift.zwallet");
    let mut store = WalletStore::create(&path, PASSWORD).unwrap();
    let mut pool = PoolStore::create(&dir.path("pool.journal")).unwrap();
    let history = pool.wallet_history().unwrap();
    let real = store.receipt;
    store.receipt.generation = MAX_RECORDS;
    assert_eq!(store.sync(&history), Err(StoreError::Capacity));
    store.receipt = real;
    let length = store.file.metadata().unwrap().len();
    store.file.seek(SeekFrom::Start(length - 1)).unwrap();
    store.file.write_all(&[0x55]).unwrap();
    // Guaranteed change even if the last checksum byte happened to be 0x55.
    store.file.seek(SeekFrom::Start(0)).unwrap();
    store.file.write_all(b"BADMAGIC").unwrap();
    assert_eq!(store.sync(&history), Err(StoreError::Corrupt));
    assert_eq!(store.receipt(), Err(StoreError::Unavailable));
    let wallet = Wallet::create().unwrap();
    let mut raw = payload(&wallet, None).unwrap();
    raw[MAX_PAYLOAD - 1] = 1;
    assert!(decode_payload(&raw).is_err());
    raw[MAX_PAYLOAD - 1] = 0;
    raw[PLAIN..PLAIN + 4].fill(255);
    assert!(decode_payload(&raw).is_err());
    assert!(decode_payload(&[]).is_err());
}

#[test]
fn truncated_and_oversized_files_never_invoke_unbounded_reads() {
    let dir = Dir::new();
    let path = dir.path("good.zwallet");
    drop(WalletStore::create(&path, PASSWORD).unwrap());
    let original = fs::read(&path).unwrap();
    let bad = dir.path("bad.zwallet");
    for n in [0, 1, FILE_HEADER - 1, FILE_HEADER, original.len() - 1] {
        fs::write(&bad, &original[..n]).unwrap();
        assert!(WalletStore::open(&bad, PASSWORD, None).is_err());
        assert_eq!(fs::metadata(&bad).unwrap().len(), n as u64);
    }
    let oversized = File::create(&bad).unwrap();
    oversized.set_len(MAX_FILE_BYTES + 1).unwrap();
    drop(oversized);
    assert!(matches!(
        WalletStore::open(&bad, PASSWORD, None),
        Err(StoreError::Corrupt)
    ));
}

#[test]
fn legacy_snapshot_import_preserves_missing_outbox_reservation() {
    use crate::wallet::Pending;
    let dir = Dir::new();
    let mut pool = PoolStore::create(&dir.path("pool.journal")).unwrap();
    let history = pool.wallet_history().unwrap();
    let mut wallet = Wallet::create().unwrap();
    wallet.sync(&history).unwrap();
    // Synthetic private-state fixture only. It is not accepted by a verifier.
    wallet.pending = Some(Pending {
        expiry: 10,
        txid: [11; 32],
        nullifiers: vec![[12; 32]],
    });
    let old = super::super::seal(&wallet, PASSWORD).unwrap();
    assert_eq!(old.len(), super::super::SEALED_BYTES);
    let path = dir.path("import.zwallet");
    let mut store = WalletStore::import_snapshot_new(&path, &old, PASSWORD).unwrap();
    assert_eq!(
        store.view().unwrap().receive_address(7).unwrap(),
        wallet.receive_address(7).unwrap()
    );
    store.sync(&history).unwrap();
    assert_eq!(store.view().unwrap().pending_id(), Some([11; 32]));
    assert!(matches!(
        store.pending_payment(),
        Err(StoreError::MissingOutbox)
    ));
    assert!(WalletStore::import_snapshot_new(&path, &old, PASSWORD).is_err());
}
