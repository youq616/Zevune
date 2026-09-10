use std::io::{self, Read};
use std::path::Path;
use zeroize::Zeroizing;
use zevune_payment_lab::{chain::{Export, Ledger, Verifier, MAX_EXPORT}, store::Store, wallet::{Wallet, create_genesis, decode_address, encode_address, read_bounded, write_new}, wire::MAX_TX, worker, Error, Result};

fn password(stdin: bool) -> Result<Zeroizing<Vec<u8>>> {
    if stdin {
        let mut data = Zeroizing::new(Vec::new()); io::stdin().take(1026).read_to_end(&mut data).map_err(|_| Error::Password)?;
        while data.last().is_some_and(|b| *b == b'\r' || *b == b'\n') { data.pop(); }
        if data.len() > 1024 { return Err(Error::Password); } Ok(data)
    } else {
        let text = Zeroizing::new(rpassword::prompt_password("Wallet password (never sent to nodes): ").map_err(|_| Error::Password)?);
        Ok(Zeroizing::new(text.as_bytes().to_vec()))
    }
}
fn load_export(path: &str, genesis: &str) -> Result<Ledger> {
    let export: Export = serde_json::from_slice(&read_bounded(Path::new(path), MAX_EXPORT)?).map_err(|_| Error::Encoding)?;
    Ledger::from_export(&export, &read_bounded(Path::new(genesis), MAX_TX)?, &Verifier::new())
}
fn run() -> Result<()> {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let stdin = args.iter().any(|v| v == "--password-stdin"); args.retain(|v| v != "--password-stdin");
    let values: Vec<&str> = args.iter().map(String::as_str).collect();
    match values.as_slice() {
        ["version"] => println!("Zevune 0.3.0-dev LOCAL TEST ASSETS ONLY"),
        ["wallet-new", path] => { let wallet = Wallet::create(Path::new(path), &password(stdin)?)?; println!("{}", encode_address(wallet.address())?); },
        ["address", path] => { let wallet = Wallet::open(Path::new(path), &password(stdin)?)?; println!("{}", encode_address(wallet.address())?); },
        ["backup", source, dest] | ["restore", source, dest] => { Wallet::backup(Path::new(source), Path::new(dest), &password(stdin)?)?; println!("encrypted copy created; destination was not overwritten"); },
        ["genesis", recipient, dest] if !stdin => { let bytes = create_genesis(decode_address(recipient)?)?; let ledger = Ledger::genesis(&bytes, &Verifier::new())?; write_new(Path::new(dest), &bytes)?; println!("{}", serde_json::to_string(&ledger.summary()).map_err(|_| Error::Encoding)?); },
        ["verify-genesis", path] if !stdin => { let ledger = Ledger::genesis(&read_bounded(Path::new(path), MAX_TX)?, &Verifier::new())?; println!("{}", serde_json::to_string(&ledger.summary()).map_err(|_| Error::Encoding)?); },
        ["balance", wallet, export, genesis] => { let wallet = Wallet::open(Path::new(wallet), &password(stdin)?)?; let ledger = load_export(export, genesis)?; println!("{}", wallet.balance(&ledger)?); },
        ["prepare", wallet, export, genesis, recipient, amount, destination] => {
            let wallet = Wallet::open(Path::new(wallet), &password(stdin)?)?; let ledger = load_export(export, genesis)?;
            let amount = amount.parse::<u64>().map_err(|_| Error::Funds)?;
            let bytes = wallet.prepare(&ledger, decode_address(recipient)?, amount)?; write_new(Path::new(destination), &bytes)?;
            println!("prepared_test_transaction; not submitted or confirmed");
        },
        ["serve", genesis, home] if !stdin => { let store = Store::open(Path::new(home), &read_bounded(Path::new(genesis), MAX_TX)?)?; worker::serve(store, io::stdin().lock(), io::stdout().lock())?; },
        _ => { eprintln!("LOCAL TEST ASSETS ONLY. Commands: version | wallet-new PATH | address PATH | backup SRC DEST | restore SRC DEST | genesis ADDRESS OUT | verify-genesis FILE | balance WALLET VERIFIED_EXPORT GENESIS | prepare WALLET VERIFIED_EXPORT GENESIS ADDRESS UNITS OUT | serve GENESIS DATA_DIR. Wallet commands optionally accept --password-stdin. Never supply passwords or seeds as arguments."); return Err(Error::Context); }
    } Ok(())
}
fn main() { if let Err(error) = run() { eprintln!("{error}"); std::process::exit(1); } }
