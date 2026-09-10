//! A local, unlocked wallet session over the owning terminal's stdin/stdout.
//! Never a network or validator API. Caches PUBLIC proving parameters only.
use serde::Deserialize;
use serde_json::{json, Value};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::path::Path;
use zeroize::Zeroizing;
use zevune_payment_lab::{
    chain::{Export, Ledger, Verifier, MAX_EXPORT},
    wallet::{decode_address, proving_key, read_bounded, write_new, Wallet},
    wire::MAX_TX,
    Error, Result,
};

const MAX_COMMAND: u64 = 8192;
#[derive(Deserialize)]
#[serde(tag = "op", deny_unknown_fields)]
enum Command {
    #[serde(rename = "balance")]
    Balance { id: u64, history: String },
    #[serde(rename = "prepare")]
    Prepare {
        id: u64,
        history: String,
        recipient: String,
        units: u64,
        destination: String,
    },
    #[serde(rename = "exit")]
    Exit { id: u64 },
}
fn line(input: &mut impl BufRead, maximum: u64) -> Result<Option<Zeroizing<Vec<u8>>>> {
    let mut bytes = Zeroizing::new(Vec::new());
    let n = input
        .take(maximum + 1)
        .read_until(b'\n', &mut bytes)
        .map_err(|_| Error::Encoding)?;
    if n == 0 {
        return Ok(None);
    };
    if bytes.len() as u64 > maximum {
        return Err(Error::Limit);
    };
    while bytes.last().is_some_and(|v| *v == b'\r' || *v == b'\n') {
        bytes.pop();
    }
    Ok(Some(bytes))
}
fn emit(output: &mut impl Write, value: Value) -> Result<()> {
    serde_json::to_writer(&mut *output, &value).map_err(|_| Error::Encoding)?;
    output
        .write_all(b"\n")
        .and_then(|_| output.flush())
        .map_err(|_| Error::Storage)
}
fn load(history: &str, genesis: &[u8], verifier: &Verifier) -> Result<Ledger> {
    let export: Export = serde_json::from_slice(&read_bounded(Path::new(history), MAX_EXPORT)?)
        .map_err(|_| Error::Encoding)?;
    Ledger::from_export(&export, genesis, verifier)
}
fn run() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() < 2 || args.len() > 3 || (args.len() == 3 && args[2] != "--password-stdin") {
        eprintln!("Usage: zevune-wallet-session WALLET EXPECTED_GENESIS [--password-stdin]. Local unlocked TEST-ASSET wallet only. Commands are bounded JSON lines: balance, prepare, exit. No keys are sent to nodes.");
        return Err(Error::Context);
    }
    let interactive = if args.len() == 2 {
        Some(Zeroizing::new(
            rpassword::prompt_password("Local test-wallet password: ")
                .map_err(|_| Error::Password)?,
        ))
    } else {
        None
    };
    let stdin = io::stdin();
    let mut input = BufReader::new(stdin.lock());
    let password = match interactive {
        Some(p) => Zeroizing::new(p.as_bytes().to_vec()),
        None => line(&mut input, 1025)?.ok_or(Error::Password)?,
    };
    let wallet = Wallet::open(Path::new(&args[0]), &password)?;
    drop(password);
    let genesis = read_bounded(Path::new(&args[1]), MAX_TX)?;
    let verifier = Verifier::new();
    Ledger::genesis(&genesis, &verifier)?;
    // Startup is separately observable; it must not be silently subtracted from cold latency.
    let _ = proving_key();
    let stdout = io::stdout();
    let mut output = stdout.lock();
    emit(
        &mut output,
        json!({"ready":true,"local_unlocked_wallet":true,"real_funds_allowed":false}),
    )?;
    while let Some(bytes) = line(&mut input, MAX_COMMAND)? {
        let command: Command = serde_json::from_slice(&bytes).map_err(|_| Error::Encoding)?;
        let (id, result) = match command {
            Command::Exit { id } => {
                emit(&mut output, json!({"id":id,"ok":true,"closed":true}))?;
                return Ok(());
            }
            Command::Balance { id, history } => {
                let result = load(&history, &genesis, &verifier)
                    .and_then(|state| wallet.balance(&state))
                    .map(|balance| json!({"balance":balance}));
                (id, result)
            }
            Command::Prepare {
                id,
                history,
                recipient,
                units,
                destination,
            } => {
                let result = (|| {
                    let state = load(&history, &genesis, &verifier)?;
                    let tx = wallet.prepare(&state, decode_address(&recipient)?, units)?;
                    write_new(Path::new(&destination), &tx)?;
                    Ok(json!({"prepared":true,"submitted":false,"finality":false}))
                })();
                (id, result)
            }
        };
        match result {
            Ok(data) => emit(&mut output, json!({"id":id,"ok":true,"data":data}))?,
            Err(_) => emit(
                &mut output,
                json!({"id":id,"ok":false,"error":"request_failed"}),
            )?,
        }
    }
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1)
    }
}
