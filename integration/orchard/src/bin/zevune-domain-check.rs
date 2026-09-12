//! One public transaction per process; not a wallet, node or consensus endpoint.
use std::io::{self, Read};
use zevune_orchard_lab::domain::{Domain, Verifier, DOMAIN_SIZE, MAX_TRANSACTION_SIZE};

fn hex(raw: &[u8]) -> String {
    raw.iter().map(|v| format!("{v:02x}")).collect()
}
fn unhex(raw: &str) -> Result<Vec<u8>, ()> {
    if raw.len() != DOMAIN_SIZE * 2
        || !raw
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(());
    }
    (0..raw.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&raw[i..i + 2], 16).map_err(|_| ()))
        .collect()
}
fn run() -> Result<(), ()> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 3 || args[0] != "--no-real-funds" || args[1] != "--domain-hex" {
        return Err(());
    }
    // Public descriptor must be independently authenticated by the operator.
    let domain = Domain::decode(&unhex(&args[2])?).map_err(|_| ())?;
    let mut raw = Vec::new();
    io::stdin()
        .lock()
        .take(MAX_TRANSACTION_SIZE as u64 + 1)
        .read_to_end(&mut raw)
        .map_err(|_| ())?;
    if raw.len() > MAX_TRANSACTION_SIZE {
        return Err(());
    }
    // Reject wrong context and malformed encodings before building expensive keys.
    zevune_orchard_lab::domain::decode(&raw, &domain).map_err(|_| ())?;
    let id = domain.id();
    let payload = Verifier::new(domain).verify(&raw).map_err(|_| ())?;
    println!("{{\"authorization_verified\":true,\"ledger_checked\":false,\"confirmed\":false,\"real_funds_allowed\":false,\"domain_id\":\"{}\",\"payload_digest\":\"{}\"}}", hex(&id), hex(&payload));
    Ok(())
}
fn main() {
    if run().is_err() {
        eprintln!("Candidate domain authorization failed. No ledger checked or changed.");
        std::process::exit(1);
    }
}
