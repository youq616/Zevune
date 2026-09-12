//! Local, NO-FUNDS durable-state worker. Public inputs only; no network listener.
//! Initialization and reopening are distinct: missing data is never recreated.
#![forbid(unsafe_code)]
use sha2::{Digest, Sha256};
use std::io::{self, Read, Write};
use std::path::Path;
use zevune_orchard_lab::pool::{PoolError, PoolStore, PreparedBlock, Summary};
use zevune_orchard_lab::wire::MAX_ENVELOPE_SIZE;
const MAX_FRAME: usize = 524_288;
const DOMAIN: &[u8] = b"ZEVUNE-POOL-IPC-2:zevune-orchard-lab-1:16:28134:genesis-bound-v2";
type Hash = [u8; 32];
type Block = (u64, Hash, Vec<Vec<u8>>);
fn bad() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "invalid pool protocol")
}
fn frame(r: &mut impl Read) -> io::Result<Option<Vec<u8>>> {
    let mut size = [0u8; 4];
    loop {
        match r.read(&mut size[..1]) {
            Ok(0) => return Ok(None),
            Ok(_) => break,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    r.read_exact(&mut size[1..])?;
    let n = u32::from_be_bytes(size) as usize;
    if !(1..=MAX_FRAME).contains(&n) {
        return Err(bad());
    }
    let mut b = vec![0; n];
    r.read_exact(&mut b)?;
    Ok(Some(b))
}
fn write_frame(w: &mut impl Write, b: &[u8]) -> io::Result<()> {
    if b.is_empty() || b.len() > MAX_FRAME {
        return Err(bad());
    }
    w.write_all(&(b.len() as u32).to_be_bytes())?;
    w.write_all(b)?;
    w.flush()
}
struct Reader<'a>(&'a [u8]);
impl Reader<'_> {
    fn take<const N: usize>(&mut self) -> Result<[u8; N], PoolError> {
        let b = self.0.get(..N).ok_or(PoolError::Bounds)?;
        let out = b.try_into().map_err(|_| PoolError::Bounds)?;
        self.0 = &self.0[N..];
        Ok(out)
    }
}
fn block(data: &[u8]) -> Result<Block, PoolError> {
    let mut r = Reader(data);
    let height = u64::from_be_bytes(r.take()?);
    let hash = r.take()?;
    let count = u16::from_be_bytes(r.take()?) as usize;
    if count > 16 {
        return Err(PoolError::Bounds);
    }
    let mut txs = Vec::with_capacity(count);
    for _ in 0..count {
        let n = u32::from_be_bytes(r.take()?) as usize;
        if n == 0 || n > MAX_ENVELOPE_SIZE || n > r.0.len() {
            return Err(PoolError::Bounds);
        }
        txs.push(r.0[..n].to_vec());
        r.0 = &r.0[n..];
    }
    if !r.0.is_empty() {
        return Err(PoolError::Bounds);
    }
    Ok((height, hash, txs))
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
struct Session {
    store: PoolStore,
    pending: Option<(Hash, PreparedBlock)>,
}
impl Session {
    fn apply(&mut self, op: u8, data: &[u8]) -> Result<Summary, PoolError> {
        match op {
            0 if data.is_empty() => self.store.summary(),
            1 | 2 => {
                let (height, hash, txs) = block(data)?;
                let tag: Hash = Sha256::digest(data).into();
                // Finalization is idempotent ONLY for byte-identical candidates.
                if op == 2 {
                    if let Some((old, prepared)) = &self.pending {
                        return if old == &tag {
                            Ok(prepared.result().clone())
                        } else {
                            Err(PoolError::Stale)
                        };
                    }
                }
                let prepared = self.store.prepare(height, hash, &txs)?;
                let out = prepared.result().clone();
                if op == 2 {
                    self.pending = Some((tag, prepared));
                }
                Ok(out)
            }
            3 if data.len() == 32 => {
                let Some((tag, _)) = &self.pending else {
                    return Err(PoolError::Stale);
                };
                if data != tag {
                    return Err(PoolError::Stale);
                }
                let (_, prepared) = self.pending.take().ok_or(PoolError::Stale)?;
                // No automatic retry: a failed write may have reached disk.
                self.store.commit(prepared)
            }
            4 if !data.is_empty() && data.len() <= MAX_ENVELOPE_SIZE => {
                let s = self.store.summary()?;
                self.store.prepare(
                    s.height.checked_add(1).ok_or(PoolError::Height)?,
                    Sha256::digest(b"ZEVUNE-READ-ONLY-CHECK").into(),
                    &[data.to_vec()],
                )?;
                Ok(s)
            }
            _ => Err(PoolError::Bounds),
        }
    }
}
fn serve(mut session: Session, r: &mut impl Read, w: &mut impl Write) -> io::Result<()> {
    let mut hello = b"ZVPLHEL1".to_vec();
    hello.extend_from_slice(&Sha256::digest(DOMAIN));
    write_frame(w, &hello)?;
    let mut previous = 0u64;
    while let Some(b) = frame(r)? {
        if b.len() < 17 || &b[..8] != b"ZVPLREQ1" {
            return Err(bad());
        }
        let id = u64::from_be_bytes(b[8..16].try_into().map_err(|_| bad())?);
        if previous.checked_add(1) != Some(id) || b[16] > 4 {
            return Err(bad());
        }
        previous = id;
        let result = session.apply(b[16], &b[17..]);
        // Storage uncertainty is fatal. EOF is not a negative transaction vote.
        if matches!(
            result,
            Err(PoolError::Storage
                | PoolError::Unavailable
                | PoolError::Corrupt
                | PoolError::Locked)
        ) {
            return Err(io::Error::other("pool storage unavailable"));
        }
        let mut response = b"ZVPLRSP1".to_vec();
        response.extend_from_slice(&id.to_be_bytes());
        response.push(u8::from(result.is_err()));
        response.extend_from_slice(&Sha256::digest(&b));
        let state = match result {
            Ok(s) => s,
            Err(_) => session.store.summary().map_err(|_| bad())?,
        };
        response.extend_from_slice(&summary(&state));
        write_frame(w, &response)?;
    }
    Ok(())
}
fn requested_store(args: &[std::ffi::OsString]) -> Result<PoolStore, PoolError> {
    if ![3, 5].contains(&args.len()) || !Path::new(&args[2]).is_absolute() {
        return Err(PoolError::Bounds);
    }
    let create = if args[1] == "create" {
        true
    } else if args[1] == "open" {
        false
    } else {
        return Err(PoolError::Bounds);
    };
    let path = Path::new(&args[2]);
    if args.len() == 3 {
        return if create {
            PoolStore::create(path)
        } else {
            PoolStore::open(path)
        };
    }
    #[cfg(feature = "local-funding-lab")]
    {
        use zevune_orchard_lab::pool::testnet::TestGenesis;
        let manifest = Path::new(&args[3]);
        if !manifest.is_absolute() {
            return Err(PoolError::Genesis);
        }
        let text = args[4].to_str().ok_or(PoolError::Genesis)?;
        if text.len() != 64
            || !text
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        {
            return Err(PoolError::Genesis);
        }
        let mut digest = [0; 32];
        for (i, item) in digest.iter_mut().enumerate() {
            *item =
                u8::from_str_radix(&text[i * 2..i * 2 + 2], 16).map_err(|_| PoolError::Genesis)?;
        }
        let genesis = TestGenesis::read_pinned(manifest, digest)?;
        if create {
            genesis.create_pool(path)
        } else {
            genesis.open_pool(path)
        }
    }
    #[cfg(not(feature = "local-funding-lab"))]
    Err(PoolError::Genesis)
}
fn run() -> io::Result<()> {
    let args: Vec<_> = std::env::args_os().collect();
    let store = requested_store(&args).map_err(|_| io::Error::other("pool could not be opened"))?;
    serve(
        Session {
            store,
            pending: None,
        },
        &mut io::stdin().lock(),
        &mut io::stdout().lock(),
    )
}
fn main() {
    if run().is_err() {
        // Never print request bytes, filesystem paths, keys or decrypted notes.
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn block_decoder_bounds() {
        let mut b = 1u64.to_be_bytes().to_vec();
        b.extend_from_slice(&[1; 32]);
        b.extend_from_slice(&0u16.to_be_bytes());
        assert!(block(&b).is_ok());
        for n in 0..b.len() {
            assert!(block(&b[..n]).is_err());
        }
        b.push(0);
        assert!(block(&b).is_err());
        b.truncate(42);
        b[41] = 17;
        assert!(block(&b).is_err());
        b[41] = 1;
        b.extend_from_slice(&u32::MAX.to_be_bytes());
        assert!(block(&b).is_err());
    }
    #[test]
    fn frame_truncation_and_bombs() {
        assert!(frame(&mut &[][..]).unwrap().is_none());
        for b in [vec![0], vec![0, 0, 0, 0], vec![255; 4], vec![0, 0, 0, 2, 1]] {
            assert!(frame(&mut b.as_slice()).is_err());
        }
        let mut b = Vec::new();
        write_frame(&mut b, b"test").unwrap();
        assert_eq!(frame(&mut b.as_slice()).unwrap(), Some(b"test".to_vec()));
    }
}
