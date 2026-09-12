//! Interactive, bounded NO-FUNDS integration driver, not a general wallet CLI.
//! Creates three ephemeral encrypted wallets. Secrets remain in this process;
//! the Go test coordinator exchanges only public blocks, proofs and test results.
#![forbid(unsafe_code)]
use rand::{rngs::OsRng, RngCore};
use std::error::Error;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use zeroize::Zeroizing;
use zevune_orchard_lab::pool::testnet::TestGenesis;
use zevune_orchard_lab::pool::{PoolStore, Summary};
use zevune_orchard_lab::wallet::vault::store::WalletStore;
use zevune_orchard_lab::wallet::WalletProver;
use zevune_orchard_lab::wire::MAX_ENVELOPE_SIZE;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const LIMIT: usize = 524_288;
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
    root: PathBuf,
    genesis: TestGenesis,
    pool: Option<PoolStore>,
    wallets: Vec<Option<WalletStore>>,
    passwords: Vec<Zeroizing<[u8; 32]>>,
    prover: WalletProver,
    phase: u8,
    backup_counter: u64,
}
impl Scenario {
    fn new(root: &Path) -> Result<Self> {
        ensure(root.is_absolute() && fs::symlink_metadata(root)?.file_type().is_dir())?;
        ensure(fs::read_dir(root)?.next().is_none())?;
        let mut wallets = Vec::new();
        let mut passwords = Vec::new();
        for i in 0..3 {
            let mut password = Zeroizing::new([0; 32]);
            OsRng.try_fill_bytes(password.as_mut())?;
            let path = root.join(format!("actor-{i}.zwallet"));
            wallets.push(Some(WalletStore::create(&path, password.as_ref())?));
            passwords.push(password);
        }
        let w = wallets[0].as_ref().ok_or_else(bad)?.view()?;
        let genesis = TestGenesis::generate(&[
            (w.receive_address(0)?, 50_000),
            (w.receive_address(1)?, 50_000),
        ])?;
        genesis.write_new(&root.join("test-genesis.bin"))?;
        let pool = genesis.create_pool(&root.join("replay.journal"))?;
        let mut s = Self {
            root: root.into(),
            genesis,
            pool: Some(pool),
            wallets,
            passwords,
            prover: WalletProver::new(),
            phase: 0,
            backup_counter: 0,
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
    fn status(&mut self) -> Result<Vec<u8>> {
        self.sync_wallets()?;
        let mut b = summary(&self.pool.as_ref().ok_or_else(bad)?.summary()?);
        for w in &self.wallets {
            let w = w.as_ref().ok_or_else(bad)?.view()?;
            b.extend_from_slice(&w.balance()?.to_be_bytes());
            b.extend_from_slice(&w.available_balance()?.to_be_bytes());
            b.push(u8::from(w.pending_id().is_some()));
        }
        Ok(b)
    }
    fn payment(&mut self, op: u8) -> Result<Vec<u8>> {
        self.sync_wallets()?;
        let (sender, recipient, value) = if op == 1 {
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
            .receive_address(0)?;
        let expiry = self
            .pool
            .as_ref()
            .ok_or_else(bad)?
            .summary()?
            .height
            .checked_add(100)
            .ok_or_else(bad)?;
        let tx = self.wallets[sender]
            .as_mut()
            .ok_or_else(bad)?
            .prepare_payment(destination, value, 1_000, expiry, &self.prover)?;
        self.phase += 1;
        Ok(tx.bytes().to_vec())
    }
    fn apply(&mut self, raw: &[u8]) -> Result<Vec<u8>> {
        ensure(raw.len() >= 42)?;
        let height = u64::from_be_bytes(raw[..8].try_into()?);
        let hash = raw[8..40].try_into()?;
        let count = u16::from_be_bytes(raw[40..42].try_into()?) as usize;
        ensure(count <= 16)?;
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
        let pool = self.pool.as_mut().ok_or_else(bad)?;
        let prepared = pool.prepare(height, hash, &txs)?;
        Ok(summary(&pool.commit(prepared)?))
    }
    fn restore(&mut self, index: usize) -> Result<Vec<u8>> {
        ensure(index < 3)?;
        self.sync_wallets()?;
        let old = self.wallets[index].as_mut().ok_or_else(bad)?;
        let pending = old.pending_payment()?.map(|p| p.bytes().to_vec());
        self.backup_counter += 1;
        let path = self
            .root
            .join(format!("backup-{}-{index}.zwallet", self.backup_counter));
        let receipt = old.backup_new(&path)?;
        drop(self.wallets[index].take());
        self.wallets[index] = Some(WalletStore::open(
            &path,
            self.passwords[index].as_ref(),
            Some(receipt),
        )?);
        self.sync_wallets()?;
        let restored = self.wallets[index]
            .as_ref()
            .ok_or_else(bad)?
            .pending_payment()?
            .map(|p| p.bytes().to_vec());
        ensure(pending == restored)?;
        Ok(restored.unwrap_or_default())
    }
    fn reopen(&mut self) -> Result<Vec<u8>> {
        let before = self.pool.as_ref().ok_or_else(bad)?.summary()?;
        drop(self.pool.take());
        self.pool = Some(self.genesis.open_pool(&self.root.join("replay.journal"))?);
        ensure(self.pool.as_ref().ok_or_else(bad)?.summary()? == before)?;
        for i in 0..3 {
            self.restore(i)?;
        }
        self.status()
    }
    fn finish(&mut self) -> Result<Vec<u8>> {
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
    ensure(args.len() == 2)?;
    let mut scenario = Scenario::new(Path::new(&args[1]))?;
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
            1 | 3 if data.is_empty() => scenario.payment(op)?,
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
