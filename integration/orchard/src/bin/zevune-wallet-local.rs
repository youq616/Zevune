//! Opt-in NO-FUNDS local wallet operator. No network connection or auto-broadcast.
//! Passwords and payment intent arrive only through a bounded private stdin pipe.
#![forbid(unsafe_code)]
use std::error::Error;
use std::fs::OpenOptions;
use std::io::{self, IsTerminal, Read, Write};
use std::path::Path;
use zeroize::Zeroizing;
use zevune_orchard_lab::pool::testnet::{TestGenesis, TEST_SUPPLY};
use zevune_orchard_lab::wallet::vault::store::{StoreReceipt, WalletStore};
use zevune_orchard_lab::wallet::{address::Recipient, Payment, WalletProver};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const MAX_REQUEST: usize = 16_384;
fn bad() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "invalid local wallet request")
}
fn ensure(ok: bool) -> Result<()> {
    if !ok {
        return Err(bad().into());
    }
    Ok(())
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn unhex<const N: usize>(text: &str) -> Result<[u8; N]> {
    ensure(text.len() == N * 2 && text.bytes().all(|b| b.is_ascii_hexdigit()))?;
    let mut result = [0; N];
    for (i, pair) in text.as_bytes().as_chunks::<2>().0.iter().enumerate() {
        result[i] = u8::from_str_radix(std::str::from_utf8(pair)?, 16)?;
    }
    Ok(result)
}
fn number(text: &str) -> Result<u64> {
    let n: u64 = text.parse()?;
    ensure(n.to_string() == text)?;
    Ok(n)
}
fn path(text: &str) -> Result<&Path> {
    let path = Path::new(text);
    ensure(path.is_absolute())?;
    Ok(path)
}
fn take<'a>(raw: &mut &'a [u8], length: usize) -> Result<&'a [u8]> {
    let value = raw.get(..length).ok_or_else(bad)?;
    *raw = &raw[length..];
    Ok(value)
}
struct Request<'a> {
    op: u8,
    password: &'a [u8],
    pin: Option<StoreReceipt>,
    fields: Vec<&'a str>,
}
fn parse(mut raw: &[u8]) -> Result<Request<'_>> {
    ensure(take(&mut raw, 8)? == b"ZVWCLI01")?;
    let op = take(&mut raw, 1)?[0];
    let n = u16::from_be_bytes(take(&mut raw, 2)?.try_into()?) as usize;
    ensure((16..=1024).contains(&n))?;
    let password = take(&mut raw, n)?;
    let pin = match take(&mut raw, 1)?[0] {
        0 => None,
        1 => Some(StoreReceipt {
            journal_id: take(&mut raw, 32)?.try_into()?,
            generation: u64::from_be_bytes(take(&mut raw, 8)?.try_into()?),
            digest: take(&mut raw, 32)?.try_into()?,
        }),
        _ => return Err(bad().into()),
    };
    let count = take(&mut raw, 1)?[0] as usize;
    let expected = match op {
        0 => 1,
        1 | 2 | 6 => 2,
        3 => 4,
        4 => 9,
        5 => 5,
        7 => 3,
        8 => 5,
        _ => return Err(bad().into()),
    };
    ensure(count == expected && !(op == 0 && pin.is_some()))?;
    let mut fields = Vec::with_capacity(count);
    for _ in 0..count {
        let n = u16::from_be_bytes(take(&mut raw, 2)?.try_into()?) as usize;
        ensure((1..=4096).contains(&n))?;
        let value = std::str::from_utf8(take(&mut raw, n)?)?;
        ensure(!value.contains('\0'))?;
        fields.push(value);
    }
    ensure(raw.is_empty())?;
    Ok(Request {
        op,
        password,
        pin,
        fields,
    })
}
fn receipt(wallet: &WalletStore) -> Result<String> {
    let r = wallet.receipt()?;
    Ok(format!(
        "{}{}{}",
        hex(&r.journal_id),
        hex(&r.generation.to_be_bytes()),
        hex(&r.digest)
    ))
}
fn sync(wallet: &mut WalletStore, fields: &[&str], genesis: &TestGenesis) -> Result<()> {
    let mut pool = genesis.open_pool(path(fields[1])?)?;
    wallet.sync(&genesis.wallet_history(&mut pool)?)?;
    Ok(())
}
fn identity(genesis: &TestGenesis) -> String {
    let (profile, domain) = if let Some(domain) = genesis.signing_domain() {
        ("LAB2", format!("\"{}\"", hex(&domain)))
    } else {
        ("LAB1", "null".to_owned())
    };
    format!(
        "\"payment_profile\":\"{profile}\",\"signing_domain\":{domain},\"genesis_sha256\":\"{}\"",
        hex(&genesis.digest())
    )
}
struct Intent {
    recipient: Recipient,
    amount: u64,
    fee: u64,
    expiry: u64,
}
fn intent(fields: &[&str], genesis: &TestGenesis) -> Result<Intent> {
    let recipient = Recipient::decode(fields[4])?;
    recipient.for_domain(genesis.signing_domain())?;
    Ok(Intent {
        recipient,
        amount: number(fields[5])?,
        fee: number(fields[6])?,
        expiry: number(fields[7])?,
    })
}
fn export(path: &Path, payment: &Payment) -> Result<()> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(payment.bytes())?;
    file.sync_all()?;
    Ok(())
}
fn unused_output(path: &Path) -> Result<()> {
    match std::fs::symlink_metadata(path) {
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
        _ => Err(bad().into()),
    }
}
fn execute(request: Request<'_>) -> Result<String> {
    let f = &request.fields;
    let source = path(f[0])?;
    if request.op == 0 {
        let wallet = WalletStore::create(source, request.password)?;
        return Ok(format!(
            "\"result\":\"created\",\"address_network_bound\":false,\"address\":\"{}\",\"receipt\":\"{}\"",
            Recipient::new(wallet.view()?.receive_address(0)?, None)?.encode(),
            receipt(&wallet)?
        ));
    }
    // Load and retain one pinned, fully decoded public manifest. A mismatched
    // recipient is rejected BEFORE opening/unlocking or updating the wallet and
    // BEFORE constructing expensive proving parameters. No manifest re-read.
    let genesis = if matches!(request.op, 3 | 4 | 5 | 8) {
        Some(TestGenesis::read_pinned(path(f[2])?, unhex(f[3])?)?)
    } else {
        None
    };
    let payment_intent = if request.op == 4 {
        Some(intent(f, genesis.as_ref().ok_or_else(bad)?)?)
    } else {
        None
    };
    let mut wallet = WalletStore::open(source, request.password, request.pin)?;
    let body = match request.op {
        1 => {
            let index = u32::try_from(number(f[1])?)?;
            format!(
                "\"address_network_bound\":false,\"address\":\"{}\",\"receipt\":\"{}\"",
                Recipient::new(wallet.view()?.receive_address(index)?, None)?.encode(),
                receipt(&wallet)?
            )
        }
        2 | 6 => {
            wallet.backup_new(path(f[1])?)?;
            format!(
                "\"result\":\"encrypted_copy_created\",\"receipt\":\"{}\"",
                receipt(&wallet)?
            )
        }
        3 => {
            let genesis = genesis.as_ref().ok_or_else(bad)?;
            sync(&mut wallet, f, genesis)?;
            let view = wallet.view()?;
            format!(
                "{},\"height\":{},\"balance\":{},\"available\":{},\"pending\":{},\"receipt\":\"{}\"",
                identity(genesis),
                view.height().ok_or_else(bad)?,
                view.balance()?,
                view.available_balance()?,
                view.pending_id().is_some(),
                receipt(&wallet)?
            )
        }
        4 | 5 => {
            let target = path(f[if request.op == 4 { 8 } else { 4 }])?;
            unused_output(target)?;
            let genesis = genesis.as_ref().ok_or_else(bad)?;
            sync(&mut wallet, f, genesis)?;
            let payment = if let Some(intent) = payment_intent {
                wallet.prepare_payment_to(
                    &intent.recipient,
                    intent.amount,
                    intent.fee,
                    intent.expiry,
                    &WalletProver::new(),
                )?
            } else {
                wallet.pending_payment()?.ok_or_else(bad)?
            };
            // The encrypted reservation is durable BEFORE any export. A failed
            // export never clears it or silently creates a replacement payment.
            export(target, &payment)?;
            format!(
                "{},\"result\":\"signed_transaction_exported_not_broadcast\",\"txid\":\"{}\",\"receipt\":\"{}\"",
                identity(genesis),
                hex(&payment.id()),
                receipt(&wallet)?
            )
        }
        7 => {
            let journal = path(f[1])?;
            let manifest = path(f[2])?;
            unused_output(journal)?;
            unused_output(manifest)?;
            ensure(journal != manifest)?;
            let genesis =
                TestGenesis::generate(&[(wallet.view()?.receive_address(0)?, TEST_SUPPLY)])?;
            genesis.write_new(manifest)?;
            let mut pool = genesis.create_pool(journal)?;
            wallet.sync(&genesis.wallet_history(&mut pool)?)?;
            format!(
                "{},\"result\":\"public_test_genesis_created\",\"address_network_bound\":true,\"address\":\"{}\",\"receipt\":\"{}\"",
                identity(&genesis),
                wallet.view()?.receive_recipient(0)?.encode(),
                receipt(&wallet)?
            )
        }
        8 => {
            let index = u32::try_from(number(f[4])?)?;
            let genesis = genesis.as_ref().ok_or_else(bad)?;
            sync(&mut wallet, f, genesis)?;
            format!(
                "{},\"address_network_bound\":{},\"address\":\"{}\",\"receipt\":\"{}\"",
                identity(genesis),
                genesis.signing_domain().is_some(),
                wallet.view()?.receive_recipient(index)?.encode(),
                receipt(&wallet)?,
            )
        }
        _ => return Err(bad().into()),
    };
    Ok(body)
}
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args_os().collect();
    ensure(args.len() == 2 && args[1] == "--no-real-funds")?;
    let stdin = io::stdin();
    ensure(!stdin.is_terminal())?;
    let mut raw = Zeroizing::new(Vec::new());
    stdin
        .lock()
        .take(MAX_REQUEST as u64 + 1)
        .read_to_end(&mut raw)?;
    ensure(raw.len() <= MAX_REQUEST)?;
    let body = execute(parse(&raw)?)?;
    println!("{{\"ok\":true,\"scope\":\"local_journal_only_no_funds\",{body}}}");
    Ok(())
}
fn main() {
    if run().is_err() {
        eprintln!("Local wallet operation failed. No automatic reset, retry or broadcast was performed; saved payment state may require reconciliation.");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parser_rejects_every_truncation_unknown_operation_and_trailing_byte() {
        let password = b"synthetic-parser-test-password";
        let mut raw = b"ZVWCLI01".to_vec();
        raw.push(1);
        raw.extend_from_slice(&(password.len() as u16).to_be_bytes());
        raw.extend_from_slice(password);
        raw.extend_from_slice(&[0, 2]);
        for value in ["/synthetic.zwallet", "0"] {
            raw.extend_from_slice(&(value.len() as u16).to_be_bytes());
            raw.extend_from_slice(value.as_bytes());
        }
        assert_eq!(parse(&raw).unwrap().fields.len(), 2);
        for end in 0..raw.len() {
            assert!(parse(&raw[..end]).is_err());
        }
        let mut bad = raw.clone();
        bad.push(0);
        assert!(parse(&bad).is_err());
        bad = raw.clone();
        bad[8] = 255;
        assert!(parse(&bad).is_err());
        bad = raw.clone();
        bad[11 + password.len()] = 2;
        assert!(parse(&bad).is_err());
        bad = raw;
        bad[9..11].copy_from_slice(&u16::MAX.to_be_bytes());
        assert!(parse(&bad).is_err());
    }

    #[test]
    fn experimental_address_and_numbers_require_canonical_encoding() {
        let owner = zevune_orchard_lab::wallet::Wallet::create().unwrap();
        let receive = owner.receive_address(7).unwrap();
        let text = Recipient::new(receive, None).unwrap().encode();
        assert!(Recipient::decode(&text).unwrap().for_domain(None).unwrap() == receive);
        assert!(Recipient::decode(&text.to_uppercase()).is_err());
        assert!(Recipient::decode(&(text.clone() + ":extra")).is_err());
        let mut changed = text;
        changed.pop();
        assert!(Recipient::decode(&changed).is_err());
        for bad in ["01", "+1", "-1", " 1", "1.0", "18446744073709551616"] {
            assert!(number(bad).is_err());
        }
        assert_eq!(number("0").unwrap(), 0);
        assert_eq!(number("18446744073709551615").unwrap(), u64::MAX);
    }
    #[test]
    fn network_address_operation_has_exact_bounded_fields() {
        let password = b"synthetic-parser-test-password";
        let mut raw = b"ZVWCLI01".to_vec();
        raw.push(8);
        raw.extend_from_slice(&(password.len() as u16).to_be_bytes());
        raw.extend_from_slice(password);
        raw.extend_from_slice(&[0, 5]);
        for field in ["/wallet", "/journal", "/genesis", &"1".repeat(64), "0"] {
            raw.extend_from_slice(&(field.len() as u16).to_be_bytes());
            raw.extend_from_slice(field.as_bytes());
        }
        assert_eq!(parse(&raw).unwrap().op, 8);
        for end in 0..raw.len() {
            assert!(parse(&raw[..end]).is_err());
        }
        raw.push(0);
        assert!(parse(&raw).is_err());
    }

    #[test]
    fn wrong_network_is_rejected_before_wallet_file_open() {
        use zevune_orchard_lab::wallet::{address::AddressError, Wallet};
        struct Dir(std::path::PathBuf);
        impl Drop for Dir {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
        let dir =
            Dir(std::env::temp_dir()
                .join(format!("zevune-preflight-{:032x}", rand::random::<u128>())));
        std::fs::create_dir(&dir.0).unwrap();
        let receive = Wallet::create().unwrap().receive_address(0).unwrap();
        let genesis = TestGenesis::generate(&[(receive, TEST_SUPPLY)]).unwrap();
        let manifest = dir.0.join("genesis");
        genesis.write_new(&manifest).unwrap();
        let mut other = genesis.digest();
        other[0] ^= 1;
        other[1] |= 1;
        for destination in [
            Recipient::new(receive, Some(other)).unwrap(),
            Recipient::new(receive, None).unwrap(),
        ] {
            let fields = [
                dir.0
                    .join("never-created-wallet")
                    .to_str()
                    .unwrap()
                    .to_owned(),
                dir.0
                    .join("never-created-journal")
                    .to_str()
                    .unwrap()
                    .to_owned(),
                manifest.to_str().unwrap().to_owned(),
                hex(&genesis.digest()),
                destination.encode(),
                "1".to_owned(),
                "1".to_owned(),
                "10".to_owned(),
                dir.0
                    .join("never-created-output")
                    .to_str()
                    .unwrap()
                    .to_owned(),
            ];
            let error = execute(Request {
                op: 4,
                password: b"synthetic-unused-password",
                pin: None,
                fields: fields.iter().map(String::as_str).collect(),
            })
            .unwrap_err();
            assert_eq!(
                error.downcast_ref::<AddressError>(),
                Some(&AddressError::Network)
            );
            assert_eq!(std::fs::read_dir(&dir.0).unwrap().count(), 1);
        }
    }
}
