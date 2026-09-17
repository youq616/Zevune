//! Interactive, bounded NO-FUNDS integration driver, not a general wallet CLI.
//! Creates ephemeral encrypted wallets. Secrets remain in this process;
//! the Go test coordinator exchanges only public blocks, proofs and test results.
//! The optional --active-segments-v1 argument creates a distinct new genesis.
//! --active-resource-v1 selects a separate fixed two-wallet, 32+1-payment test.
#![forbid(unsafe_code)]
use rand::{rngs::OsRng, RngCore};
use std::error::Error;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use zeroize::Zeroizing;
use zevune_orchard_lab::pool::testnet::TestGenesis;
use zevune_orchard_lab::pool::{PoolStore, Summary};
use zevune_orchard_lab::wallet::address::Recipient;
use zevune_orchard_lab::wallet::vault::store::{StorageStatus, StoreError, WalletStore};
use zevune_orchard_lab::wallet::{WalletError, WalletProver};
use zevune_orchard_lab::wire::{decode, MAX_ENVELOPE_SIZE};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const LIMIT: usize = 524_288;
const RESOURCE_RECOVERY_HEIGHT: u64 = 32;
const RESOURCE_FINAL_HEIGHT: u64 = 33;

#[derive(Clone, Copy, Eq, PartialEq)]
enum Mode {
    Legacy,
    ActiveBoundary,
    ActiveResource,
}
fn bad() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidData,
        "funded laboratory protocol failure",
    )
}
fn ensure(ok: bool) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(bad().into())
    }
}
fn read_frame(r: &mut impl Read) -> Result<Option<Vec<u8>>> {
    let mut p = [0; 4];
    loop {
        match r.read(&mut p[..1]) {
            Ok(0) => return Ok(None),
            Ok(_) => break,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e.into()),
        }
    }
    r.read_exact(&mut p[1..])?;
    let n = u32::from_be_bytes(p) as usize;
    ensure((1..=LIMIT).contains(&n))?;
    let mut b = vec![0; n];
    r.read_exact(&mut b)?;
    Ok(Some(b))
}
fn write_frame(w: &mut impl Write, b: &[u8]) -> Result<()> {
    ensure(!b.is_empty() && b.len() <= LIMIT)?;
    w.write_all(&(b.len() as u32).to_be_bytes())?;
    w.write_all(b)?;
    w.flush()?;
    Ok(())
}
fn summary(s: &Summary) -> Vec<u8> {
    let mut b = s.height.to_be_bytes().to_vec();
    b.extend_from_slice(&s.app_hash);
    b.extend_from_slice(&s.root);
    for n in [s.commitments, s.nullifiers, s.fees] {
        b.extend_from_slice(&n.to_be_bytes());
    }
    b
}
struct Scenario {
    mode: Mode,
    root: PathBuf,
    genesis: TestGenesis,
    pool: Option<PoolStore>,
    wallets: Vec<Option<WalletStore>>,
    wallet_paths: Vec<PathBuf>,
    passwords: Vec<Zeroizing<[u8; 32]>>,
    prover: WalletProver,
    phase: u8,
    backup_counter: u64,
    resource_recovered: bool,
    resource_pending_restored: bool,
}
impl Scenario {
    fn new(root: &Path, mode: Mode) -> Result<Self> {
        ensure(root.is_absolute() && fs::symlink_metadata(root)?.file_type().is_dir())?;
        ensure(fs::read_dir(root)?.next().is_none())?;
        let mut wallets = Vec::new();
        let mut wallet_paths = Vec::new();
        let mut passwords = Vec::new();
        let wallet_count = if mode == Mode::ActiveResource { 2 } else { 3 };
        for i in 0..wallet_count {
            let mut password = Zeroizing::new([0; 32]);
            OsRng.try_fill_bytes(password.as_mut())?;
            let path = root.join(format!("actor-{i}.zwallet"));
            wallets.push(Some(WalletStore::create(&path, password.as_ref())?));
            wallet_paths.push(path);
            passwords.push(password);
        }
        let w = wallets[0].as_ref().ok_or_else(bad)?.view()?;
        let allocations = [
            (w.receive_address(0)?, 50_000),
            (
                if mode == Mode::ActiveResource {
                    wallets[1]
                        .as_ref()
                        .ok_or_else(bad)?
                        .view()?
                        .receive_address(0)?
                } else {
                    w.receive_address(1)?
                },
                50_000,
            ),
        ];
        // This is an explicit new laboratory genesis, never a migration or a
        // capacity override for an existing deployment. All modes retain real
        // Orchard payments and the fixed public test supply.
        let genesis = if mode == Mode::Legacy {
            TestGenesis::generate(&allocations)?
        } else {
            TestGenesis::generate_active(&allocations)?
        };
        genesis.write_new(&root.join("test-genesis.bin"))?;
        let pool = genesis.create_pool(&root.join("replay.journal"))?;
        let mut s = Self {
            mode,
            root: root.into(),
            genesis,
            pool: Some(pool),
            wallets,
            wallet_paths,
            passwords,
            prover: WalletProver::new(),
            phase: 0,
            backup_counter: 0,
            resource_recovered: false,
            resource_pending_restored: false,
        };
        s.sync_wallets()?;
        Ok(s)
    }
    fn sync_wallets(&mut self) -> Result<()> {
        let history = self
            .genesis
            .wallet_history(self.pool.as_mut().ok_or_else(bad)?)?;
        for w in &mut self.wallets {
            w.as_mut().ok_or_else(bad)?.sync(&history)?;
        }
        Ok(())
    }
    fn checked_wallet_storage(&mut self, index: usize) -> Result<StorageStatus> {
        let status = self.wallets[index]
            .as_mut()
            .ok_or_else(bad)?
            .storage_status()?;
        let metadata = fs::symlink_metadata(&self.wallet_paths[index])?;
        ensure(metadata.file_type().is_file() && metadata.len() == status.file_bytes)?;
        Ok(status)
    }
    fn check_resource_summary(state: &Summary) -> Result<()> {
        ensure(
            state.height <= RESOURCE_FINAL_HEIGHT
                && state.commitments == 2 + 2 * state.height
                && state.nullifiers == 2 * state.height
                && state.fees == 1_000 * state.height,
        )
    }
    fn status(&mut self) -> Result<Vec<u8>> {
        self.sync_wallets()?;
        let state = self.pool.as_ref().ok_or_else(bad)?.summary()?;
        let resource = self.mode == Mode::ActiveResource;
        if resource {
            Self::check_resource_summary(&state)?;
        }
        let mut b = summary(&state);
        for index in 0..self.wallets.len() {
            let storage = if resource {
                Some(self.checked_wallet_storage(index)?)
            } else {
                None
            };
            let w = self.wallets[index].as_ref().ok_or_else(bad)?.view()?;
            let balance = w.balance()?;
            let available = w.available_balance()?;
            let pending = w.pending_id().is_some();
            b.extend_from_slice(&balance.to_be_bytes());
            b.extend_from_slice(&available.to_be_bytes());
            b.push(u8::from(pending));
            if let Some(storage) = storage {
                let sent = (state.height + u64::from(index == 0)) / 2;
                let received = state.height - sent;
                let expected_balance = 50_000 + 1_000 * received - 2_000 * sent;
                // Pending reserves the entire selected large note, not only
                // the transfer and fee. The smaller received notes stay free.
                let expected_available = if pending {
                    ensure(
                        state.height < RESOURCE_FINAL_HEIGHT
                            && index == (state.height % 2) as usize,
                    )?;
                    expected_balance - (50_000 - 2_000 * sent)
                } else {
                    expected_balance
                };
                ensure(
                    balance == expected_balance
                        && available == expected_available
                        && storage.records_used == 2 + state.height + sent + u64::from(pending),
                )?;
                // Only resource mode appends these fields to each wallet's
                // legacy balance/available/pending tuple: 96 + 2 * 33 bytes.
                b.extend_from_slice(&storage.records_used.to_be_bytes());
                b.extend_from_slice(&storage.file_bytes.to_be_bytes());
            }
        }
        Ok(b)
    }
    fn payment(&mut self, op: u8) -> Result<Vec<u8>> {
        self.sync_wallets()?;
        let resource = self.mode == Mode::ActiveResource;
        let height = self.pool.as_ref().ok_or_else(bad)?.summary()?.height;
        let (sender, recipient, value) = if resource {
            ensure(op == 1 && height < RESOURCE_FINAL_HEIGHT)?;
            if height == RESOURCE_RECOVERY_HEIGHT {
                ensure(self.resource_recovered)?;
            }
            let sender = (height % 2) as usize;
            (sender, 1 - sender, 1_000)
        } else if op == 1 {
            ensure(self.phase == 0)?;
            (0, 1, 60_000)
        } else {
            ensure(op == 3 && self.phase == 1)?;
            (1, 2, 40_000)
        };
        let destination = self.wallets[recipient]
            .as_ref()
            .ok_or_else(bad)?
            .view()?
            .receive_recipient(0)?;
        // Exercise the same checked presentation API as a real wallet caller.
        let destination = Recipient::decode(&destination.encode())?;
        let expiry = self
            .pool
            .as_ref()
            .ok_or_else(bad)?
            .summary()?
            .height
            .checked_add(100)
            .ok_or_else(bad)?;
        let sender = self.wallets[sender].as_mut().ok_or_else(bad)?;
        if resource {
            // No prepare counter advances: only a committed height selects
            // the next sender. A repeated prepare cannot skip the outbox.
            ensure(sender.pending_payment()?.is_none())?;
        }
        let domain = sender.view()?.signing_domain()?.ok_or_else(bad)?;
        let receiver = destination.for_domain(Some(domain))?;
        let mut other = domain;
        other[0] ^= 1;
        if other == [0; 32] {
            other[1] = 1;
        }
        let before = sender.receipt()?;
        // Wrong domain and legacy downgrades must fail before a new reservation.
        for wrong in [
            Recipient::new(receiver, Some(other))?,
            Recipient::new(receiver, None)?,
        ] {
            ensure(matches!(
                sender.check_payment_to(&wrong, value, 1_000, expiry),
                Err(StoreError::Wallet(WalletError::History))
            ))?;
            ensure(sender.receipt()? == before && sender.pending_payment()?.is_none())?;
        }
        let tx = sender.prepare_payment_to(&destination, value, 1_000, expiry, &self.prover)?;
        if resource {
            let decoded = decode(tx.bytes())?;
            ensure(
                decoded.bundle.actions().len() == 2
                    && decoded.context.signing_domain == Some(self.genesis.digest())
                    && decoded.context.expiry_height == expiry
                    && decoded.context.fee == 1_000,
            )?;
            if height == RESOURCE_RECOVERY_HEIGHT {
                self.resource_pending_restored = false;
            }
        } else {
            self.phase += 1;
        }
        Ok(tx.bytes().to_vec())
    }
    fn apply(&mut self, raw: &[u8]) -> Result<Vec<u8>> {
        ensure(raw.len() >= 42)?;
        let height = u64::from_be_bytes(raw[..8].try_into()?);
        let hash = raw[8..40].try_into()?;
        let count = u16::from_be_bytes(raw[40..42].try_into()?) as usize;
        ensure(count <= 16)?;
        let resource = self.mode == Mode::ActiveResource;
        if resource {
            let committed = self.pool.as_ref().ok_or_else(bad)?.summary()?;
            ensure(
                height == committed.height.checked_add(1).ok_or_else(bad)?
                    && height <= RESOURCE_FINAL_HEIGHT
                    && count == 1,
            )?;
            if height == RESOURCE_FINAL_HEIGHT {
                ensure(self.resource_recovered && self.resource_pending_restored)?;
            }
        }
        let mut p = 42;
        let mut txs = Vec::with_capacity(count);
        for _ in 0..count {
            let n = u32::from_be_bytes(raw.get(p..p + 4).ok_or_else(bad)?.try_into()?) as usize;
            p += 4;
            ensure(n > 0 && n <= MAX_ENVELOPE_SIZE)?;
            let end = p.checked_add(n).ok_or_else(bad)?;
            txs.push(raw.get(p..end).ok_or_else(bad)?.to_vec());
            p = end;
        }
        ensure(p == raw.len())?;
        if resource {
            let sender = ((height - 1) % 2) as usize;
            let pending = self.wallets[sender]
                .as_ref()
                .ok_or_else(bad)?
                .pending_payment()?
                .ok_or_else(bad)?;
            ensure(pending.bytes() == txs[0].as_slice())?;
            ensure(
                self.wallets[1 - sender]
                    .as_ref()
                    .ok_or_else(bad)?
                    .pending_payment()?
                    .is_none(),
            )?;
        }
        let pool = self.pool.as_mut().ok_or_else(bad)?;
        let prepared = pool.prepare(height, hash, &txs)?;
        let committed = pool.commit(prepared)?;
        if resource {
            Self::check_resource_summary(&committed)?;
        }
        // Wallet sync is a separate operation so the coordinator can measure
        // independent ledger execution and full wallet history costs separately.
        Ok(summary(&committed))
    }
    fn restore(&mut self, index: usize) -> Result<Vec<u8>> {
        ensure(index < self.wallets.len())?;
        self.sync_wallets()?;
        let resource = self.mode == Mode::ActiveResource;
        let before_storage = if resource {
            Some(self.checked_wallet_storage(index)?)
        } else {
            None
        };
        let old = self.wallets[index].as_mut().ok_or_else(bad)?;
        let before_receipt = if resource { Some(old.receipt()?) } else { None };
        let pending = old.pending_payment()?.map(|p| p.bytes().to_vec());
        self.backup_counter += 1;
        let path = self
            .root
            .join(format!("backup-{}-{index}.zwallet", self.backup_counter));
        let receipt = old.backup_new(&path)?;
        if let Some(before) = before_receipt {
            ensure(before == receipt)?;
        }
        drop(self.wallets[index].take());
        self.wallets[index] = Some(WalletStore::open(
            &path,
            self.passwords[index].as_ref(),
            Some(receipt),
        )?);
        self.wallet_paths[index] = path;
        self.sync_wallets()?;
        let restored = self.wallets[index]
            .as_ref()
            .ok_or_else(bad)?
            .pending_payment()?
            .map(|p| p.bytes().to_vec());
        ensure(pending == restored)?;
        if let Some(before) = before_storage {
            ensure(self.checked_wallet_storage(index)? == before)?;
            ensure(self.wallets[index].as_ref().ok_or_else(bad)?.receipt()? == receipt)?;
            if index == 0
                && self.pool.as_ref().ok_or_else(bad)?.summary()?.height == RESOURCE_RECOVERY_HEIGHT
                && restored.is_some()
            {
                ensure(self.resource_recovered)?;
                self.resource_pending_restored = true;
            }
        }
        Ok(restored.unwrap_or_default())
    }
    fn reopen(&mut self) -> Result<Vec<u8>> {
        let before = self.pool.as_ref().ok_or_else(bad)?.summary()?;
        let resource = self.mode == Mode::ActiveResource;
        if resource {
            ensure(before.height == RESOURCE_RECOVERY_HEIGHT && !self.resource_recovered)?;
            self.sync_wallets()?;
            for wallet in &self.wallets {
                ensure(
                    wallet
                        .as_ref()
                        .ok_or_else(bad)?
                        .pending_payment()?
                        .is_none(),
                )?;
            }
        }
        drop(self.pool.take());
        self.pool = Some(self.genesis.open_pool(&self.root.join("replay.journal"))?);
        ensure(self.pool.as_ref().ok_or_else(bad)?.summary()? == before)?;
        for i in 0..self.wallets.len() {
            self.restore(i)?;
        }
        let result = self.status()?;
        if resource {
            self.resource_recovered = true;
        }
        Ok(result)
    }
    fn finish(&mut self) -> Result<Vec<u8>> {
        if self.mode == Mode::ActiveResource {
            ensure(self.resource_recovered && self.resource_pending_restored)?;
            ensure(self.pool.as_ref().ok_or_else(bad)?.summary()?.height == RESOURCE_FINAL_HEIGHT)?;
            let result = self.status()?;
            for wallet in &self.wallets {
                ensure(
                    wallet
                        .as_ref()
                        .ok_or_else(bad)?
                        .pending_payment()?
                        .is_none(),
                )?;
            }
            return Ok(result);
        }
        ensure(self.phase == 2)?;
        let result = self.status()?;
        for (i, expected) in [39_000, 19_000, 40_000].iter().enumerate() {
            let wallet = self.wallets[i].as_ref().ok_or_else(bad)?.view()?;
            ensure(
                wallet.balance()? == *expected
                    && wallet.available_balance()? == *expected
                    && wallet.pending_id().is_none(),
            )?;
        }
        let s = self.pool.as_ref().ok_or_else(bad)?.summary()?;
        ensure(s.fees == 2_000 && s.commitments == 6 && s.nullifiers == 4)?;
        Ok(result)
    }
}
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args_os().collect();
    let mode = match args.as_slice() {
        [_, _] => Mode::Legacy,
        [_, _, flag] if flag == "--active-segments-v1" => Mode::ActiveBoundary,
        [_, _, flag] if flag == "--active-resource-v1" => Mode::ActiveResource,
        _ => return Err(bad().into()),
    };
    let mut scenario = Scenario::new(Path::new(&args[1]), mode)?;
    let mut ready = scenario.genesis.digest().to_vec();
    ready.extend_from_slice(&summary(&scenario.genesis.initial_summary()?));
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut r = stdin.lock();
    let mut w = stdout.lock();
    write_frame(&mut w, &ready)?;
    while let Some(request) = read_frame(&mut r)? {
        let (op, data) = (request[0], &request[1..]);
        let body = match op {
            0 if data.is_empty() => scenario.status()?,
            1 if data.is_empty() => scenario.payment(op)?,
            3 if data.is_empty() && mode != Mode::ActiveResource => scenario.payment(op)?,
            2 => scenario.apply(data)?,
            4 if data.len() == 1 => scenario.restore(data[0] as usize)?,
            5 if data.is_empty() => scenario.reopen()?,
            6 if data.is_empty() => scenario.finish()?,
            _ => return Err(bad().into()),
        };
        let mut response = vec![op];
        response.extend_from_slice(&body);
        write_frame(&mut w, &response)?;
    }
    Ok(())
}
fn main() {
    if run().is_err() {
        eprintln!("NO-FUNDS integration scenario failed; no secret diagnostics emitted");
        std::process::exit(1);
    }
}
