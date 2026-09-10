//! Local encrypted seed and authenticated output scanning. No key RPC exists.
use crate::chain::Ledger;
use crate::wire::{signing_digest, Transaction, MAX_ACTIONS};
use crate::{Error, Result, FEE, SUPPLY};
use argon2::{Algorithm, Argon2, Params, Version};
use chacha20poly1305::{
    aead::{Aead, KeyInit, Payload},
    XChaCha20Poly1305, XNonce,
};
use orchard::builder::{Builder, BundleType};
use orchard::bundle::Flags;
use orchard::circuit::ProvingKey;
use orchard::keys::{FullViewingKey, Scope, SpendAuthorizingKey, SpendingKey};
use orchard::value::NoteValue;
use orchard::{Address, Anchor, Note};
use rand::{rngs::OsRng, RngCore};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;
use std::sync::OnceLock;
use zeroize::Zeroizing;
use zevune_orchard_lab::{CIRCUIT, VERSION};

const MAGIC: &[u8; 4] = b"ZVW1";
const WALLET_SIZE: usize = 4 + 16 + 24 + 48;
static PROVING_KEY: OnceLock<ProvingKey> = OnceLock::new();
pub fn proving_key() -> &'static ProvingKey {
    PROVING_KEY.get_or_init(|| ProvingKey::build(CIRCUIT))
}

pub struct Wallet {
    seed: Zeroizing<[u8; 32]>,
}
pub struct OwnedNote {
    pub note: Note,
    pub position: usize,
}
impl Wallet {
    pub fn generate() -> Self {
        loop {
            let mut seed = Zeroizing::new([0; 32]);
            OsRng.fill_bytes(seed.as_mut());
            if bool::from(SpendingKey::from_bytes(*seed).is_some()) {
                return Self { seed };
            }
        }
    }
    fn key(&self) -> SpendingKey {
        SpendingKey::from_bytes(*self.seed).unwrap()
    }
    pub fn viewing_key(&self) -> FullViewingKey {
        FullViewingKey::from(&self.key())
    }
    pub fn address(&self) -> Address {
        self.viewing_key().address_at(0u32, Scope::External)
    }
    pub fn create(path: &Path, password: &[u8]) -> Result<Self> {
        if !(12..=1024).contains(&password.len()) {
            return Err(Error::Password);
        }
        let wallet = Self::generate();
        let mut salt = [0; 16];
        let mut nonce = [0; 24];
        OsRng.fill_bytes(&mut salt);
        OsRng.fill_bytes(&mut nonce);
        let key = password_key(password, &salt)?;
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(&salt);
        header.extend_from_slice(&nonce);
        let cipher =
            XChaCha20Poly1305::new_from_slice(key.as_ref()).map_err(|_| Error::Password)?;
        let encrypted = cipher
            .encrypt(
                XNonce::from_slice(&nonce),
                Payload {
                    msg: wallet.seed.as_ref(),
                    aad: &header,
                },
            )
            .map_err(|_| Error::Password)?;
        header.extend_from_slice(&encrypted);
        write_new(path, &header)?;
        Ok(wallet)
    }
    pub fn open(path: &Path, password: &[u8]) -> Result<Self> {
        if password.len() > 1024 {
            return Err(Error::Password);
        }
        let data = read_bounded(path, WALLET_SIZE)?;
        if data.len() != WALLET_SIZE || &data[..4] != MAGIC {
            return Err(Error::Encoding);
        }
        let key = password_key(password, &data[4..20])?;
        let cipher =
            XChaCha20Poly1305::new_from_slice(key.as_ref()).map_err(|_| Error::Password)?;
        let plaintext = Zeroizing::new(
            cipher
                .decrypt(
                    XNonce::from_slice(&data[20..44]),
                    Payload {
                        msg: &data[44..],
                        aad: &data[..44],
                    },
                )
                .map_err(|_| Error::Password)?,
        );
        let mut seed = Zeroizing::new([0; 32]);
        if plaintext.len() != 32 {
            return Err(Error::Password);
        }
        seed.copy_from_slice(&plaintext);
        if !bool::from(SpendingKey::from_bytes(*seed).is_some()) {
            return Err(Error::Password);
        }
        Ok(Self { seed })
    }
    pub fn backup(source: &Path, destination: &Path, password: &[u8]) -> Result<()> {
        // Verify the encrypted source before copying; never overwrite a destination.
        let _ = Self::open(source, password)?;
        write_new(destination, &read_bounded(source, WALLET_SIZE)?)
    }
    pub fn scan(&self, ledger: &Ledger) -> Result<Vec<OwnedNote>> {
        let fvk = self.viewing_key();
        let ivks = [fvk.to_ivk(Scope::External), fvk.to_ivk(Scope::Internal)];
        let mut position = 0;
        let mut found = vec![];
        for tx in ledger.transactions()? {
            for (i, _, note, _, _) in tx.bundle.decrypt_outputs_with_keys(&ivks) {
                if note.value().inner() > 0
                    && !ledger.spent.contains(&note.nullifier(&fvk).to_bytes())
                {
                    found.push(OwnedNote {
                        note,
                        position: position + i,
                    });
                }
            }
            position += tx.bundle.actions().len();
        }
        if position != ledger.leaves.len() {
            return Err(Error::State);
        }
        Ok(found)
    }
    pub fn balance(&self, ledger: &Ledger) -> Result<u64> {
        self.scan(ledger)?.iter().try_fold(0u64, |sum, owned| {
            sum.checked_add(owned.note.value().inner())
                .ok_or(Error::Funds)
        })
    }
    pub fn prepare(&self, ledger: &Ledger, recipient: Address, amount: u64) -> Result<Vec<u8>> {
        if amount == 0 || amount > SUPPLY {
            return Err(Error::Funds);
        }
        let needed = amount.checked_add(FEE).ok_or(Error::Funds)?;
        let fvk = self.viewing_key();
        let mut total = 0u64;
        let mut notes = vec![];
        for owned in self.scan(ledger)? {
            total = total
                .checked_add(owned.note.value().inner())
                .ok_or(Error::Funds)?;
            notes.push(owned);
            if total >= needed {
                break;
            }
            if notes.len() >= MAX_ACTIONS {
                return Err(Error::Limit);
            }
        }
        if total < needed || notes.len() > MAX_ACTIONS {
            return Err(Error::Funds);
        }
        let anchor =
            Option::<Anchor>::from(Anchor::from_bytes(ledger.root())).ok_or(Error::State)?;
        let mut builder = Builder::new(
            BundleType::DEFAULT,
            VERSION,
            VERSION.default_flags(),
            anchor,
        )
        .map_err(|_| Error::State)?;
        for owned in notes {
            let path = ledger.witness(owned.position, &owned.note)?;
            builder
                .add_spend(fvk.clone(), owned.note, path)
                .map_err(|_| Error::State)?;
        }
        builder
            .add_output(
                Some(fvk.to_ovk(Scope::External)),
                recipient,
                NoteValue::from_raw(amount),
                [0; 512],
            )
            .map_err(|_| Error::State)?;
        if total > needed {
            builder
                .add_output(
                    Some(fvk.to_ovk(Scope::Internal)),
                    fvk.address_at(0u32, Scope::Internal),
                    NoteValue::from_raw(total - needed),
                    [0; 512],
                )
                .map_err(|_| Error::State)?;
        }
        let expiry = ledger.height.checked_add(256).ok_or(Error::Limit)?;
        let bundle = builder
            .build::<i64>(OsRng)
            .map_err(|_| Error::Authorization)?
            .ok_or(Error::State)?
            .0;
        let digest = signing_digest(&bundle, 1, ledger.genesis_id, expiry, FEE)?;
        let bundle = bundle
            .create_proof(proving_key(), OsRng)
            .map_err(|_| Error::Authorization)?
            .apply_signatures(OsRng, digest, &[SpendAuthorizingKey::from(&self.key())])
            .map_err(|_| Error::Authorization)?;
        Transaction {
            kind: 1,
            genesis: ledger.genesis_id,
            expiry,
            fee: FEE,
            bundle,
        }
        .encode()
    }
}

// Initialization only; this function is not reachable through the worker/network.
pub fn create_genesis(recipient: Address) -> Result<Vec<u8>> {
    let mut b = Builder::new(
        BundleType::Coinbase,
        VERSION,
        Flags::SPENDS_DISABLED,
        Anchor::empty_tree(),
    )
    .map_err(|_| Error::State)?;
    b.add_output(None, recipient, NoteValue::from_raw(SUPPLY), [0; 512])
        .map_err(|_| Error::State)?;
    let bundle = b
        .build::<i64>(OsRng)
        .map_err(|_| Error::Authorization)?
        .ok_or(Error::State)?
        .0;
    let digest = signing_digest(&bundle, 0, [0; 32], 0, 0)?;
    let bundle = bundle
        .create_proof(proving_key(), OsRng)
        .map_err(|_| Error::Authorization)?
        .apply_signatures(OsRng, digest, &[])
        .map_err(|_| Error::Authorization)?;
    Transaction {
        kind: 0,
        genesis: [0; 32],
        expiry: 0,
        fee: 0,
        bundle,
    }
    .encode()
}
fn password_key(password: &[u8], salt: &[u8]) -> Result<Zeroizing<[u8; 32]>> {
    let params = Params::new(64 * 1024, 3, 1, Some(32)).map_err(|_| Error::Password)?;
    let mut key = Zeroizing::new([0; 32]);
    Argon2::new(Algorithm::Argon2id, Version::V0x13, params)
        .hash_password_into(password, salt, key.as_mut())
        .map_err(|_| Error::Password)?;
    Ok(key)
}
pub fn encode_address(address: Address) -> Result<String> {
    bech32::encode::<bech32::Bech32m>(
        bech32::Hrp::parse("zvtest").map_err(|_| Error::Address)?,
        &address.to_raw_address_bytes(),
    )
    .map_err(|_| Error::Address)
}
pub fn decode_address(text: &str) -> Result<Address> {
    if text.len() > 120 {
        return Err(Error::Address);
    }
    let (hrp, bytes) = bech32::decode(text).map_err(|_| Error::Address)?;
    if hrp.as_str() != "zvtest" || bytes.len() != 43 {
        return Err(Error::Address);
    }
    let address = Option::<Address>::from(Address::from_raw_address_bytes(
        &bytes.try_into().map_err(|_| Error::Address)?,
    ))
    .ok_or(Error::Address)?;
    if encode_address(address)? != text {
        return Err(Error::Address);
    }
    Ok(address)
}
pub fn read_bounded(path: &Path, max: usize) -> Result<Vec<u8>> {
    let meta = fs::symlink_metadata(path).map_err(|_| Error::Storage)?;
    if !meta.is_file() || meta.file_type().is_symlink() || meta.len() > max as u64 {
        return Err(Error::Storage);
    }
    let file = std::fs::File::open(path).map_err(|_| Error::Storage)?;
    let mut bytes = Vec::new();
    file.take(max as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| Error::Storage)?;
    if bytes.len() > max {
        return Err(Error::Limit);
    }
    Ok(bytes)
}
pub fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).map_err(|_| Error::Storage)?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|_| Error::Storage)
}
