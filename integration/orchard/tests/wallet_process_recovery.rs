#![cfg(all(
    any(target_os = "linux", target_os = "windows"),
    feature = "local-funding-lab"
))]
//! Kill an actual process holding a real encrypted WalletStore after a completed
//! durable operation. This is NOT a kill during write/fsync, physical power loss,
//! a production CLI crash test, or a consensus signer/WAL recovery experiment.
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};
use zeroize::Zeroizing;
use zevune_orchard_lab::pool::testnet::{TestGenesis, MAX_GENESIS_BYTES, TEST_SUPPLY};
use zevune_orchard_lab::pool::{PoolError, PoolStore, Summary};
use zevune_orchard_lab::wallet::vault::store::{
    StoreError, StoreReceipt, WalletStore, MAX_FILE_BYTES,
};
use zevune_orchard_lab::wallet::{Wallet, WalletError, WalletProver};
use zevune_orchard_lab::wire::MAX_ENVELOPE_SIZE;

const CASE_ENV: &str = "ZEVUNE_WALLET_PROCESS_TEST_CASE";
const READY: &[u8; 6] = b"READY1";
const RECORD_BYTES: usize = 32_948;
const READY_LIMIT: Duration = Duration::from_secs(120);
const STOP_LIMIT: Duration = Duration::from_secs(5);
type PublicFiles = BTreeMap<String, Vec<u8>>;

fn digest(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn password() -> Zeroizing<[u8; 32]> {
    let mut value = Zeroizing::new([0; 32]);
    OsRng.fill_bytes(value.as_mut());
    value
}

// A test-owned, private directory. Never remove it while a child exit is unknown.
// This assumes a cooperative local filesystem, as does WalletStore itself.
struct Sandbox {
    root: PathBuf,
    removable: Arc<AtomicBool>,
}
impl Sandbox {
    fn new() -> Self {
        let mut nonce = [0; 16];
        OsRng.fill_bytes(&mut nonce);
        let suffix: String = nonce.iter().map(|byte| format!("{byte:02x}")).collect();
        let root = std::env::temp_dir()
            .canonicalize()
            .expect("test temporary root unavailable")
            .join(format!("zevune-wallet-process-{suffix}"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            fs::DirBuilder::new()
                .mode(0o700)
                .create(&root)
                .expect("test directory creation failed");
        }
        #[cfg(windows)]
        fs::create_dir(&root).expect("test directory creation failed");
        Self {
            root,
            removable: Arc::new(AtomicBool::new(true)),
        }
    }

    fn clean(&self) {
        assert!(self.removable.load(Ordering::SeqCst), "child exit unknown");
        fs::remove_dir_all(&self.root).expect("test directory cleanup failed");
        assert!(!self.root.exists(), "test directory remains");
    }
}
impl Drop for Sandbox {
    fn drop(&mut self) {
        if self.removable.load(Ordering::SeqCst) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }
}

struct OwnedChild {
    child: Child,
    removable: Arc<AtomicBool>,
    stop_deadline: Option<Instant>,
    kill_sent: bool,
}
impl OwnedChild {
    fn start(sandbox: &Sandbox, case: &str, password: &[u8]) -> Self {
        assert!(matches!(
            case,
            "prepare" | "sync" | "stall" | "exit" | "bad-ready"
        ));
        assert_eq!(password.len(), 32);
        assert!(sandbox.removable.swap(false, Ordering::SeqCst));
        // Only a fixed operation label enters the environment. The random test
        // password goes through a pipe, never argv, environment, files or logs.
        let spawned = Command::new(std::env::current_exe().unwrap())
            .args([
                "--ignored",
                "--exact",
                "wallet_process_helper",
                "--nocapture",
            ])
            .current_dir(&sandbox.root)
            .env(CASE_ENV, case)
            .env("RAYON_NUM_THREADS", "2")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();
        let child = match spawned {
            Ok(child) => child,
            Err(_) => {
                sandbox.removable.store(true, Ordering::SeqCst);
                panic!("wallet helper could not start");
            }
        };
        let mut result = Self {
            child,
            removable: sandbox.removable.clone(),
            stop_deadline: None,
            kill_sent: false,
        };
        let mut input = result.child.stdin.take().expect("helper input missing");
        input.write_all(password).expect("helper input failed");
        drop(input);
        result
    }

    fn poll(&mut self) -> Result<Option<ExitStatus>, &'static str> {
        let result = self
            .child
            .try_wait()
            .map_err(|_| "child observation failed")?;
        if result.is_some() {
            self.removable.store(true, Ordering::SeqCst);
        }
        Ok(result)
    }

    fn ready(&mut self, root: &Path, timeout: Duration) -> Result<(), &'static str> {
        let deadline = Instant::now() + timeout;
        loop {
            if self.poll()?.is_some() {
                return Err("helper exited before readiness");
            }
            match fs::symlink_metadata(root.join("ready")) {
                Ok(metadata) => {
                    if !metadata.is_file() || metadata.len() > READY.len() as u64 {
                        return Err("invalid readiness marker");
                    }
                    if metadata.len() == READY.len() as u64 {
                        if read_bounded(&root.join("ready"), READY.len()) != READY {
                            return Err("invalid readiness marker");
                        }
                        return Ok(());
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(_) => return Err("readiness inspection failed"),
            }
            if Instant::now() >= deadline {
                return Err("helper readiness timed out");
            }
            thread::sleep(Duration::from_millis(10));
        }
    }

    fn stop(&mut self) -> Result<ExitStatus, &'static str> {
        if let Some(status) = self.poll()? {
            return Ok(status);
        }
        // Do not restart this budget if explicit shutdown failed and Drop runs.
        if self.stop_deadline.is_none() {
            self.stop_deadline = Some(Instant::now() + STOP_LIMIT);
            self.kill_sent = self.child.kill().is_ok();
        }
        loop {
            if let Some(status) = self.poll()? {
                return Ok(status);
            }
            if Instant::now() >= self.stop_deadline.unwrap() {
                return Err("child termination unconfirmed; test directory retained");
            }
            thread::sleep(Duration::from_millis(10));
        }
    }
}
impl Drop for OwnedChild {
    fn drop(&mut self) {
        let _ = self.stop();
    }
}

fn assert_killed(status: ExitStatus) {
    assert!(
        !status.success(),
        "helper exited successfully instead of being killed"
    );
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt;
        assert_eq!(status.signal(), Some(9), "expected actual SIGKILL");
    }
    #[cfg(windows)]
    assert!(status.code().is_some(), "missing native termination status");
}

fn write_new(path: &Path, bytes: &[u8]) {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).expect("test file creation failed");
    file.write_all(bytes).expect("test file write failed");
    file.sync_all().expect("test file synchronization failed");
}

fn read_bounded(path: &Path, limit: usize) -> Vec<u8> {
    let metadata = fs::symlink_metadata(path).expect("test file inspection failed");
    assert!(metadata.is_file() && metadata.len() <= limit as u64);
    let file = File::open(path).expect("test file open failed");
    let mut bytes = Vec::new();
    file.take(limit as u64 + 1)
        .read_to_end(&mut bytes)
        .expect("test file read failed");
    assert!(bytes.len() <= limit);
    assert_eq!(bytes.len() as u64, metadata.len());
    bytes
}

fn pin_bytes(pin: StoreReceipt) -> [u8; 72] {
    let mut bytes = [0; 72];
    bytes[..32].copy_from_slice(&pin.journal_id);
    bytes[32..40].copy_from_slice(&pin.generation.to_be_bytes());
    bytes[40..].copy_from_slice(&pin.digest);
    bytes
}

fn read_pin(path: &Path) -> StoreReceipt {
    let bytes = read_bounded(path, 72);
    assert_eq!(bytes.len(), 72);
    StoreReceipt {
        journal_id: bytes[..32].try_into().unwrap(),
        generation: u64::from_be_bytes(bytes[32..40].try_into().unwrap()),
        digest: bytes[40..].try_into().unwrap(),
    }
}

fn wallet_bytes(root: &Path) -> Vec<u8> {
    read_bounded(&root.join("wallet.journal"), MAX_FILE_BYTES as usize)
}

// Inspect owned bytes through the existing handle; do not bypass Windows byte
// range locks with a second File handle, even inside the same process.
fn saved_wallet_bytes(store: &mut WalletStore, root: &Path) -> Vec<u8> {
    let before = store.receipt().unwrap();
    let target = root.join("wallet-observation.journal");
    assert!(!target.exists());
    assert_eq!(store.backup_new(&target).unwrap(), before);
    let bytes = read_bounded(&target, MAX_FILE_BYTES as usize);
    fs::remove_file(target).unwrap();
    assert_eq!(store.receipt().unwrap(), before);
    bytes
}

// Direct physical snapshots require that all PoolStore handles are closed.
fn pool_bytes(root: &Path) -> PublicFiles {
    let mut files = BTreeMap::new();
    for entry in fs::read_dir(root.join("pool")).unwrap() {
        let entry = entry.unwrap();
        assert!(files.len() < 2);
        let name = entry.file_name().into_string().unwrap();
        assert!(matches!(name.as_str(), "genesis" | "00000000.journal"));
        assert!(files
            .insert(name, read_bounded(&entry.path(), 1024 * 1024))
            .is_none());
    }
    files
}

fn block_id(height: u64) -> [u8; 32] {
    let mut value = [1; 32];
    value[..8].copy_from_slice(&height.to_be_bytes());
    value
}

fn commit(pool: &mut PoolStore, bytes: &[u8]) -> Summary {
    let height = pool.summary().unwrap().height + 1;
    let prepared = pool
        .prepare(height, block_id(height), &[bytes.to_vec()])
        .unwrap();
    let expected = prepared.result().clone();
    let actual = pool.commit(prepared).unwrap();
    assert_eq!(actual, expected);
    actual
}

fn assert_cold(store: &WalletStore) {
    assert_eq!(store.view().unwrap().balance(), Err(WalletError::NotSynced));
    assert_eq!(
        store.view().unwrap().available_balance(),
        Err(WalletError::NotSynced),
    );
    assert_eq!(
        store.pending_payment().err(),
        Some(StoreError::Wallet(WalletError::NotSynced)),
    );
}

// This witness is intentionally NOT run by a native hard kill. Parent-side
// assertions also prove the helper was alive and still owned its wallet lock.
struct GracefulExit;
impl Drop for GracefulExit {
    fn drop(&mut self) {
        write_new(Path::new("graceful-exit"), b"DROPPED");
    }
}

#[test]
#[ignore = "subprocess helper; parent tests explicitly launch and supervise it"]
fn wallet_process_helper() {
    let case = std::env::var(CASE_ENV).expect("helper needs explicit parent context");
    let mut password = Zeroizing::new([0; 32]);
    let mut input = std::io::stdin().lock();
    input
        .read_exact(password.as_mut())
        .expect("missing test password");
    let mut trailing = [0; 1];
    assert_eq!(input.read(&mut trailing).unwrap(), 0);
    let _exit = GracefulExit;
    match case.as_str() {
        "exit" => return,
        "stall" => loop {
            thread::park();
        },
        "bad-ready" => {
            write_new(Path::new("ready"), b"WRONG1");
            loop {
                thread::park();
            }
        }
        "prepare" | "sync" => {}
        _ => panic!("unknown helper operation"),
    }
    let genesis =
        TestGenesis::decode(&read_bounded(Path::new("genesis.bin"), MAX_GENESIS_BYTES)).unwrap();
    let pin = read_pin(Path::new("before.pin"));
    let mut store =
        WalletStore::open(Path::new("wallet.journal"), password.as_ref(), Some(pin)).unwrap();
    assert_eq!(store.receipt().unwrap(), pin);
    assert_cold(&store);
    let root = std::env::current_dir().unwrap();
    let mut pool = genesis.open_pool(&root.join("pool")).unwrap();
    let history = genesis.wallet_history(&mut pool).unwrap();
    store.sync(&history).unwrap();
    if case == "prepare" {
        assert_eq!(history.tip().height, 0);
        assert_eq!(store.receipt().unwrap(), pin);
        let raw: [u8; 43] = read_bounded(Path::new("recipient.bin"), 43)
            .try_into()
            .unwrap();
        let recipient =
            Option::<orchard::Address>::from(orchard::Address::from_raw_address_bytes(&raw))
                .unwrap();
        let payment = store
            .prepare_payment(recipient, 60_000, 1_000, 10, &WalletProver::new())
            .unwrap();
        assert_eq!(store.view().unwrap().available_balance().unwrap(), 0);
        assert!(store.pending_payment().unwrap().unwrap().bytes() == payment.bytes());
        // Public signed envelope only: this observer file is NOT a CLI export,
        // confirmation or broadcast, and is never included in CI artifacts.
        write_new(Path::new("observed-payment.bin"), payment.bytes());
    } else {
        assert_eq!(history.tip().height, 1);
        assert_eq!(store.view().unwrap().balance().unwrap(), 39_000);
        assert!(store.view().unwrap().pending_id().is_none());
        assert!(store.pending_payment().unwrap().is_none());
    }
    let after = store.receipt().unwrap();
    assert_eq!(after.generation, pin.generation + 1);
    assert!(after.journal_id == pin.journal_id);
    write_new(Path::new("observed.pin"), &pin_bytes(after));
    // A second handle cannot read the locked live wallet on Windows. Capture
    // its exact bytes through the already owned handle, then close the copy.
    assert_eq!(
        store
            .backup_new(Path::new("observed-backup.journal"))
            .unwrap(),
        after,
    );
    drop(history);
    drop(pool);
    write_new(Path::new("ready"), READY);
    // Keep the real WalletStore (and its OS lock) live; parent kills this host.
    loop {
        thread::park();
        assert_eq!(store.receipt().unwrap(), after);
    }
}

fn run_case(case: &str) {
    let sandbox = Sandbox::new();
    run_case_in(&sandbox, case);
    sandbox.clean();
}

fn run_case_in(sandbox: &Sandbox, case: &str) {
    let root = &sandbox.root;
    let password = password();
    let wallet_path = root.join("wallet.journal");
    let backup_path = root.join("before-backup.journal");
    let mut wallet = WalletStore::create(&wallet_path, password.as_ref()).unwrap();
    let owner = wallet.view().unwrap().receive_address(0).unwrap();
    let mut bob = Wallet::create().unwrap();
    let mut carol = Wallet::create().unwrap();
    let genesis = TestGenesis::generate_active(&[(owner, TEST_SUPPLY)]).unwrap();
    genesis.write_new(&root.join("genesis.bin")).unwrap();
    write_new(
        &root.join("recipient.bin"),
        &bob.receive_address(0).unwrap().to_raw_address_bytes(),
    );
    let mut pool = genesis.create_pool(&root.join("pool")).unwrap();
    wallet
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert_eq!(wallet.receipt().unwrap().generation, 2);
    let prover = WalletProver::new();
    let mut first = Vec::new();
    if case == "sync" {
        let payment = wallet
            .prepare_payment(bob.receive_address(0).unwrap(), 60_000, 1_000, 10, &prover)
            .unwrap();
        first = payment.bytes().to_vec();
        commit(&mut pool, &first);
        // Ledger confirmation exists, but the wallet still has its exact outbox.
        assert!(wallet.pending_payment().unwrap().unwrap().bytes() == first);
        assert_eq!(wallet.view().unwrap().available_balance().unwrap(), 0);
    }
    let before = wallet.receipt().unwrap();
    write_new(&root.join("before.pin"), &pin_bytes(before));
    assert_eq!(wallet.backup_new(&backup_path).unwrap(), before);
    let before_bytes = read_bounded(&backup_path, MAX_FILE_BYTES as usize);
    let pool_before = pool.summary().unwrap();
    drop(wallet);
    drop(pool);
    assert!(wallet_bytes(root) == before_bytes);
    let pool_before_bytes = pool_bytes(root);

    let mut process = OwnedChild::start(sandbox, case, password.as_ref());
    process
        .ready(root, READY_LIMIT)
        .expect("wallet operation did not reach its durable boundary");
    assert!(process.poll().unwrap().is_none());
    let observed = read_pin(&root.join("observed.pin"));
    assert_eq!(observed.generation, before.generation + 1);
    assert!(observed.journal_id == before.journal_id && observed.digest != before.digest);
    let after_bytes = read_bounded(
        &root.join("observed-backup.journal"),
        MAX_FILE_BYTES as usize,
    );
    assert!(after_bytes.starts_with(&before_bytes));
    assert_eq!(after_bytes.len(), before_bytes.len() + RECORD_BYTES);
    assert_eq!(
        WalletStore::open(&wallet_path, password.as_ref(), Some(observed)).err(),
        Some(StoreError::Locked),
    );
    assert!(!root.join("graceful-exit").exists());
    if case == "prepare" {
        first = read_bounded(&root.join("observed-payment.bin"), MAX_ENVELOPE_SIZE);
        assert!(!first.is_empty());
    } else {
        assert!(!root.join("observed-payment.bin").exists());
    }
    assert_killed(
        process
            .stop()
            .expect("wallet helper termination was not confirmed"),
    );
    assert!(process.kill_sent, "no successful native kill request");
    assert!(sandbox.removable.load(Ordering::SeqCst));
    assert!(!root.join("graceful-exit").exists());
    assert!(wallet_bytes(root) == after_bytes);
    assert!(pool_bytes(root) == pool_before_bytes);
    assert!(read_bounded(&backup_path, MAX_FILE_BYTES as usize) == before_bytes);
    assert_eq!(read_pin(&root.join("before.pin")), before);

    // The newer independent receipt rejects the complete, authenticated OLD
    // backup. An older receipt is an ancestry minimum, not an exact-tip demand.
    assert_eq!(
        WalletStore::open(&backup_path, password.as_ref(), Some(observed)).err(),
        Some(StoreError::Rollback),
    );
    assert!(read_bounded(&backup_path, MAX_FILE_BYTES as usize) == before_bytes);
    let ancestry = WalletStore::open(&wallet_path, password.as_ref(), Some(before)).unwrap();
    assert_eq!(ancestry.receipt().unwrap(), observed);
    assert_cold(&ancestry);
    drop(ancestry);
    assert!(wallet_bytes(root) == after_bytes);

    let mut wallet = WalletStore::open(&wallet_path, password.as_ref(), Some(observed)).unwrap();
    assert_eq!(wallet.receipt().unwrap(), observed);
    assert_cold(&wallet);
    assert!(wallet.view().unwrap().receive_address(0).unwrap() == owner);
    let mut pool = genesis.open_pool(&root.join("pool")).unwrap();
    assert_eq!(pool.summary().unwrap(), pool_before);
    drop(pool);
    assert!(pool_bytes(root) == pool_before_bytes);
    let mut pool = genesis.open_pool(&root.join("pool")).unwrap();
    wallet
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert_eq!(wallet.receipt().unwrap(), observed);
    assert!(saved_wallet_bytes(&mut wallet, root) == after_bytes);
    if case == "prepare" {
        let pending = wallet.pending_payment().unwrap().unwrap();
        assert!(pending.bytes() == first && pending.id() == digest(&first));
        assert!(wallet.view().unwrap().pending_id() == Some(pending.id()));
        assert_eq!(wallet.view().unwrap().balance().unwrap(), TEST_SUPPLY);
        assert_eq!(wallet.view().unwrap().available_balance().unwrap(), 0);
        assert_eq!(
            wallet
                .prepare_payment(bob.receive_address(0).unwrap(), 1, 1, 10, &prover)
                .err(),
            Some(StoreError::Wallet(WalletError::Pending)),
        );
        assert_eq!(wallet.receipt().unwrap(), observed);
        assert!(saved_wallet_bytes(&mut wallet, root) == after_bytes);
        commit(&mut pool, &first);
        assert!(wallet.pending_payment().unwrap().unwrap().bytes() == first);
        wallet
            .sync(&genesis.wallet_history(&mut pool).unwrap())
            .unwrap();
    }
    let paid = pool.summary().unwrap();
    assert_eq!(
        (paid.height, paid.commitments, paid.nullifiers, paid.fees),
        (1, 3, 2, 1_000),
    );
    assert_eq!(wallet.view().unwrap().balance().unwrap(), 39_000);
    assert_eq!(wallet.view().unwrap().available_balance().unwrap(), 39_000);
    assert!(wallet.pending_payment().unwrap().is_none());
    assert!(wallet.view().unwrap().pending_id().is_none());
    assert_eq!(wallet.receipt().unwrap().generation, 4);

    let history = genesis.wallet_history(&mut pool).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    assert_eq!(bob.balance().unwrap(), 60_000);
    let second = bob
        .build_payment(
            carol.receive_address(0).unwrap(),
            40_000,
            1_000,
            10,
            &prover,
        )
        .unwrap()
        .bytes()
        .to_vec();
    drop(history);
    let final_state = commit(&mut pool, &second);
    let history = genesis.wallet_history(&mut pool).unwrap();
    wallet.sync(&history).unwrap();
    bob.sync(&history).unwrap();
    carol.sync(&history).unwrap();
    assert_eq!(
        (
            wallet.view().unwrap().balance().unwrap(),
            bob.balance().unwrap(),
            carol.balance().unwrap()
        ),
        (39_000, 19_000, 40_000),
    );
    assert_eq!(final_state.fees, 2_000);
    assert_eq!(
        wallet.view().unwrap().balance().unwrap()
            + bob.balance().unwrap()
            + carol.balance().unwrap()
            + final_state.fees,
        TEST_SUPPLY,
    );
    assert!(bob.pending_id().is_none());
    drop(history);
    drop(pool);
    let final_bytes = pool_bytes(root);
    let mut pool = genesis.open_pool(&root.join("pool")).unwrap();
    for payment in [&first, &second] {
        assert_eq!(
            pool.prepare(3, block_id(3), &[payment.to_vec()]).err(),
            Some(PoolError::DoubleSpend),
        );
        assert_eq!(pool.summary().unwrap(), final_state);
        drop(pool);
        assert!(pool_bytes(root) == final_bytes);
        pool = genesis.open_pool(&root.join("pool")).unwrap();
        assert_eq!(pool.summary().unwrap(), final_state);
    }
    let final_receipt = wallet.receipt().unwrap();
    let final_wallet_bytes = saved_wallet_bytes(&mut wallet, root);
    drop(wallet);
    drop(pool);
    assert!(wallet_bytes(root) == final_wallet_bytes);
    let mut pool = genesis.open_pool(&root.join("pool")).unwrap();
    assert_eq!(pool.summary().unwrap(), final_state);
    let mut wallet =
        WalletStore::open(&wallet_path, password.as_ref(), Some(final_receipt)).unwrap();
    assert_cold(&wallet);
    wallet
        .sync(&genesis.wallet_history(&mut pool).unwrap())
        .unwrap();
    assert_eq!(wallet.receipt().unwrap(), final_receipt);
    assert_eq!(wallet.view().unwrap().available_balance().unwrap(), 39_000);
    assert!(wallet.pending_payment().unwrap().is_none());
    drop(wallet);
    drop(pool);
    assert!(wallet_bytes(root) == final_wallet_bytes);
    assert!(pool_bytes(root) == final_bytes);
    assert!(read_bounded(&backup_path, MAX_FILE_BYTES as usize) == before_bytes);
    assert_eq!(read_pin(&root.join("observed.pin")), observed);
}

#[test]
fn killed_wallet_after_prepare_recovers_exact_outbox_and_reservation() {
    run_case("prepare");
}

#[test]
fn killed_wallet_after_confirmed_sync_does_not_resurrect_outbox() {
    run_case("sync");
}

#[test]
fn supervisor_reaps_stalled_child_without_readiness() {
    let sandbox = Sandbox::new();
    let mut process = OwnedChild::start(&sandbox, "stall", password().as_ref());
    assert_eq!(
        process.ready(&sandbox.root, Duration::from_millis(150)),
        Err("helper readiness timed out"),
    );
    assert_killed(process.stop().unwrap());
    assert!(process.kill_sent, "no successful native kill request");
    sandbox.clean();
}

#[test]
fn supervisor_rejects_successful_exit_without_readiness() {
    let sandbox = Sandbox::new();
    let mut process = OwnedChild::start(&sandbox, "exit", password().as_ref());
    assert_eq!(
        process.ready(&sandbox.root, Duration::from_secs(10)),
        Err("helper exited before readiness"),
    );
    assert!(process.stop().unwrap().success());
    assert!(sandbox.root.join("graceful-exit").exists());
    sandbox.clean();
}

#[test]
fn supervisor_rejects_malformed_readiness_then_reaps_child() {
    let sandbox = Sandbox::new();
    let mut process = OwnedChild::start(&sandbox, "bad-ready", password().as_ref());
    assert_eq!(
        process.ready(&sandbox.root, Duration::from_secs(10)),
        Err("invalid readiness marker"),
    );
    assert_killed(process.stop().unwrap());
    assert!(process.kill_sent, "no successful native kill request");
    sandbox.clean();
}
