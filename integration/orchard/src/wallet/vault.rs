//! Fixed-size encrypted wallet snapshots using upstream Argon2id and XChaCha20-
//! Poly1305. No plaintext seed export or password command-line interface.
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;

use argon2::{Algorithm, Argon2, Params, Version};
use chacha20poly1305::{
    aead::{Aead, Payload},
    KeyInit, XChaCha20Poly1305, XNonce,
};
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

use super::{Checkpoint, Pending, Wallet, WalletError, MAX_ACTIONS, NETWORK};

const MAGIC: &[u8; 8] = b"ZVWLT001";
const HEADER: usize = 92;
const PLAIN: usize = 512;
pub const SEALED_BYTES: usize = HEADER + PLAIN + 16;
const MEMORY_KIB: u32 = 65_536;
const PASSES: u32 = 3;
const LANES: u32 = 1;

fn derive(password: &[u8], salt: &[u8]) -> Result<Zeroizing<[u8; 32]>, WalletError> {
    if !(16..=1024).contains(&password.len()) {
        return Err(WalletError::Bounds);
    }
    let params = Params::new(MEMORY_KIB, PASSES, LANES, Some(32)).map_err(|_| WalletError::Key)?;
    let mut key = Zeroizing::new([0; 32]);
    Argon2::new(Algorithm::Argon2id, Version::V0x13, params)
        .hash_password_into(password, salt, key.as_mut())
        .map_err(|_| WalletError::Key)?;
    Ok(key)
}

/// Password strength is the caller's responsibility; length is not entropy.
/// The entire header is authenticated. Parameters are fixed and checked before
/// invoking the KDF, so an imported file cannot request unbounded memory/work.
pub fn seal(wallet: &Wallet, password: &[u8]) -> Result<Vec<u8>, WalletError> {
    let plaintext = snapshot(wallet)?;
    let mut out = Vec::with_capacity(SEALED_BYTES);
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&Sha256::digest(NETWORK.as_bytes()));
    for v in [MEMORY_KIB, PASSES, LANES] {
        out.extend_from_slice(&v.to_be_bytes());
    }
    out.resize(HEADER, 0);
    OsRng
        .try_fill_bytes(&mut out[52..HEADER])
        .map_err(|_| WalletError::Entropy)?;
    let key = derive(password, &out[52..68])?;
    let cipher = XChaCha20Poly1305::new_from_slice(key.as_ref()).map_err(|_| WalletError::Key)?;
    let ciphertext = cipher
        .encrypt(
            XNonce::from_slice(&out[68..92]),
            Payload {
                msg: plaintext.as_ref(),
                aad: &out,
            },
        )
        .map_err(|_| WalletError::Authentication)?;
    out.extend_from_slice(&ciphertext);
    Ok(out)
}

pub fn open(data: &[u8], password: &[u8]) -> Result<Wallet, WalletError> {
    if data.len() != SEALED_BYTES
        || &data[..8] != MAGIC
        || data[8..40] != Sha256::digest(NETWORK.as_bytes())[..]
    {
        return Err(WalletError::Backup);
    }
    for (i, v) in [MEMORY_KIB, PASSES, LANES].iter().enumerate() {
        if data[40 + i * 4..44 + i * 4] != v.to_be_bytes() {
            return Err(WalletError::Backup);
        }
    }
    let key = derive(password, &data[52..68])?;
    let cipher = XChaCha20Poly1305::new_from_slice(key.as_ref()).map_err(|_| WalletError::Key)?;
    let plaintext = Zeroizing::new(
        cipher
            .decrypt(
                XNonce::from_slice(&data[68..92]),
                Payload {
                    msg: &data[HEADER..],
                    aad: &data[..HEADER],
                },
            )
            .map_err(|_| WalletError::Authentication)?,
    );
    restore(&plaintext)
}

/// Create-only: never replace an existing backup, follow a final symlink, or
/// remove a previous file after a failure. A failed write can leave an unusable
/// new file. Directory fsync/Windows ACL policy and concurrent multi-process
/// wallet ownership remain application-level work, not guarantees of this API.
pub fn write_new(path: &Path, wallet: &Wallet, password: &[u8]) -> Result<(), WalletError> {
    let sealed = seal(wallet, password)?;
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).map_err(|_| WalletError::Storage)?;
    file.write_all(&sealed).map_err(|_| WalletError::Storage)?;
    file.sync_all().map_err(|_| WalletError::Storage)
}

pub fn read(path: &Path, password: &[u8]) -> Result<Wallet, WalletError> {
    let meta = fs::symlink_metadata(path).map_err(|_| WalletError::Storage)?;
    if !meta.file_type().is_file() || meta.len() != SEALED_BYTES as u64 {
        return Err(WalletError::Backup);
    }
    let file = OpenOptions::new()
        .read(true)
        .open(path)
        .map_err(|_| WalletError::Storage)?;
    if !file.metadata().map_err(|_| WalletError::Storage)?.is_file() {
        return Err(WalletError::Backup);
    }
    let mut bytes = Vec::with_capacity(SEALED_BYTES);
    file.take(SEALED_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| WalletError::Storage)?;
    open(&bytes, password)
}

fn snapshot(wallet: &Wallet) -> Result<Zeroizing<[u8; PLAIN]>, WalletError> {
    let mut raw = Zeroizing::new([0; PLAIN]);
    raw[0] = 1;
    raw[1..33].copy_from_slice(wallet.seed.as_ref());
    let mut p = 34;
    if let Some(c) = wallet.checkpoint {
        raw[33] = 1;
        raw[p..p + 32].copy_from_slice(&c.genesis);
        p += 32;
        raw[p..p + 8].copy_from_slice(&c.height.to_be_bytes());
        p += 8;
        raw[p..p + 32].copy_from_slice(&c.app_hash);
        p += 32;
    }
    if let Some(pending) = &wallet.pending {
        if wallet.checkpoint.is_none()
            || pending.nullifiers.is_empty()
            || pending.nullifiers.len() > MAX_ACTIONS
        {
            return Err(WalletError::Backup);
        }
        raw[p] = 1;
        p += 1;
        raw[p..p + 8].copy_from_slice(&pending.expiry.to_be_bytes());
        p += 8;
        raw[p..p + 32].copy_from_slice(&pending.txid);
        p += 32;
        raw[p] = pending.nullifiers.len() as u8;
        p += 1;
        for nf in &pending.nullifiers {
            raw[p..p + 32].copy_from_slice(nf);
            p += 32;
        }
    }
    Ok(raw)
}

fn take<const N: usize>(raw: &[u8], p: &mut usize) -> Result<[u8; N], WalletError> {
    let end = p.checked_add(N).ok_or(WalletError::Backup)?;
    let value = raw
        .get(*p..end)
        .ok_or(WalletError::Backup)?
        .try_into()
        .map_err(|_| WalletError::Backup)?;
    *p = end;
    Ok(value)
}
fn restore(raw: &[u8]) -> Result<Wallet, WalletError> {
    if raw.len() != PLAIN || raw[0] != 1 {
        return Err(WalletError::Backup);
    }
    let seed = Zeroizing::new(raw[1..33].try_into().map_err(|_| WalletError::Backup)?);
    let mut p = 34;
    let checkpoint = match raw[33] {
        0 => None,
        1 => Some(Checkpoint {
            genesis: take(raw, &mut p)?,
            height: u64::from_be_bytes(take(raw, &mut p)?),
            app_hash: take(raw, &mut p)?,
        }),
        _ => return Err(WalletError::Backup),
    };
    let pending = match take::<1>(raw, &mut p)?[0] {
        0 => None,
        1 => {
            let expiry = u64::from_be_bytes(take(raw, &mut p)?);
            let txid = take(raw, &mut p)?;
            let count = take::<1>(raw, &mut p)?[0] as usize;
            if checkpoint.is_none()
                || !(1..=MAX_ACTIONS).contains(&count)
                || expiry < checkpoint.ok_or(WalletError::Backup)?.height
            {
                return Err(WalletError::Backup);
            }
            let mut nullifiers = Vec::with_capacity(count);
            for _ in 0..count {
                let nf = take(raw, &mut p)?;
                if nullifiers.contains(&nf) {
                    return Err(WalletError::Backup);
                }
                nullifiers.push(nf);
            }
            Some(Pending {
                expiry,
                txid,
                nullifiers,
            })
        }
        _ => return Err(WalletError::Backup),
    };
    if raw[p..].iter().any(|b| *b != 0) {
        return Err(WalletError::Backup);
    }
    let wallet = Wallet {
        seed,
        checkpoint,
        scanned: None,
        pending,
    };
    wallet.spending_key()?;
    Ok(wallet)
}

#[cfg(test)]
mod tests {
    use super::*;
    const PASSWORD: &[u8] = b"only-a-synthetic-test-password";
    #[test]
    fn encrypted_roundtrip_randomization_and_wrong_password() {
        let wallet = Wallet::create().unwrap();
        let a = seal(&wallet, PASSWORD).unwrap();
        let b = seal(&wallet, PASSWORD).unwrap();
        assert_eq!(a.len(), SEALED_BYTES);
        assert_ne!(a, b);
        assert!(!a.windows(32).any(|v| v == wallet.seed.as_ref()));
        let restored = open(&a, PASSWORD).unwrap();
        assert_eq!(
            wallet.receive_address(17).unwrap(),
            restored.receive_address(17).unwrap()
        );
        assert_eq!(restored.balance(), Err(WalletError::NotSynced));
        assert!(matches!(
            open(&a, b"another-synthetic-wrong-password"),
            Err(WalletError::Authentication)
        ));
        for index in [52, 68, HEADER, SEALED_BYTES - 1] {
            let mut altered = a.clone();
            altered[index] ^= 1;
            assert!(matches!(
                open(&altered, PASSWORD),
                Err(WalletError::Authentication)
            ));
        }
    }
    #[test]
    fn rejects_lengths_versions_and_kdf_bombs_before_derivation() {
        let mut raw = vec![0; SEALED_BYTES];
        raw[..8].copy_from_slice(MAGIC);
        raw[8..40].copy_from_slice(&Sha256::digest(NETWORK.as_bytes()));
        raw[40..52].fill(255);
        assert!(matches!(open(&raw, PASSWORD), Err(WalletError::Backup)));
        for n in [0, 1, HEADER, SEALED_BYTES - 1, SEALED_BYTES + 1] {
            assert!(matches!(
                open(&vec![0; n], PASSWORD),
                Err(WalletError::Backup)
            ));
        }
        assert!(matches!(
            seal(&Wallet::create().unwrap(), b"short"),
            Err(WalletError::Bounds)
        ));
    }
    #[test]
    fn snapshot_rejects_noncanonical_flags_padding_and_duplicate_reservations() {
        let mut wallet = Wallet::create().unwrap();
        let mut s = snapshot(&wallet).unwrap();
        s[511] = 1;
        assert!(matches!(restore(s.as_ref()), Err(WalletError::Backup)));
        s[511] = 0;
        s[33] = 2;
        assert!(matches!(restore(s.as_ref()), Err(WalletError::Backup)));
        wallet.checkpoint = Some(Checkpoint {
            genesis: [1; 32],
            height: 1,
            app_hash: [2; 32],
        });
        wallet.pending = Some(Pending {
            expiry: 20,
            txid: [3; 32],
            nullifiers: vec![[4; 32], [4; 32]],
        });
        assert!(matches!(
            restore(snapshot(&wallet).unwrap().as_ref()),
            Err(WalletError::Backup)
        ));
    }
}

#[cfg(test)]
mod independent_kdf_vector {
    use super::*;
    #[test]
    fn argon2id_matches_independent_argon2_cffi_reference() {
        // Public primitive vector only; no wallet seed, user password or asset.
        // Reference: argon2-cffi, Type.ID, version=19, m=65536, t=3, p=1.
        let salt: Vec<u8> = (0..16).collect();
        let key = derive(b"zevune-public-interop-password", &salt).unwrap();
        let actual: String = key.iter().map(|b| format!("{b:02x}")).collect();
        assert_eq!(
            actual,
            "8206a50e7b842499349d8c6b93461a0068277af5bfde4d262536d4506c91be02"
        );
    }
}
