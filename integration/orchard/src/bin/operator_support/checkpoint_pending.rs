//! Exact-checkpoint export of an existing outbox. No wallet sync or signing.
use super::{
    checkpoint, ensure, export, hex, identity, number, path, receipt, unhex, unused_output,
    Payment, Request, Result, TestGenesis, WalletStore,
};
use std::io;
use std::path::Path;
use zevune_orchard_lab::wallet::vault::store::MAX_RECORDS;

pub(super) fn execute(request: Request<'_>) -> Result<String> {
    execute_with_export(request, export)
}

// Private fault seam for the real export; production always uses create_new.
// There is no accepting proof, wallet, or network substitute in this path.
fn execute_with_export(
    request: Request<'_>,
    write_export: impl FnOnce(&Path, &Payment) -> Result<()>,
) -> Result<String> {
    ensure(request.op == 13 && request.fields.len() == 7 && request.pin.is_some())?;
    let pin = request.pin.ok_or_else(super::bad)?;
    ensure(
        (1..=MAX_RECORDS).contains(&pin.generation)
            && pin.journal_id != [0; 32]
            && pin.digest != [0; 32],
    )?;
    let f = &request.fields;
    let source = path(f[0])?;
    let journal = path(f[1])?;
    let target = path(f[4])?;
    let height = number(f[5])?;
    let app_hash = unhex::<32>(f[6])?;
    ensure(app_hash != [0; 32])?;
    unused_output(target)?;
    let manifest = path(f[2])?;
    output_outside_inputs(target, [source, journal, manifest])?;
    let genesis = TestGenesis::read_pinned(manifest, unhex(f[3])?)?;
    let (mut pool, summary) = checkpoint::open_checked(&genesis, journal, height, app_hash)?;
    let history = genesis.wallet_history(&mut pool)?;
    ensure(pool.summary()? == summary)?;
    // Keep the SAME pool lock and the wallet's original lock through export.
    // No opcode5/11 sync, room/persist, proving factory, or scan publication.
    let mut wallet = WalletStore::open(source, request.password, Some(pin))?;
    let original_receipt = wallet.receipt()?;
    let payment = wallet.pending_payment_from_history(&history)?;
    write_export(target, &payment)?;
    ensure(wallet.receipt()? == original_receipt)?;
    let body = format!(
        "{},\"result\":\"checkpoint_pending_exported_not_broadcast\",\"checkpoint_matched\":true,\"wallet_unchanged\":true,\"height\":{},\"app_hash\":\"{}\",\"txid\":\"{}\",\"receipt\":\"{}\",\"broadcast\":false",
        identity(&genesis),
        summary.height,
        hex(&summary.app_hash),
        hex(&payment.id()),
        receipt(&wallet)?,
    );
    drop(wallet);
    drop(pool);
    Ok(body)
}

// The CLI is callable without Python. A new output inside an active pool must
// not add a file to the supposedly unchanged input tree. Resolve the nearest
// existing parent so a missing OUTSIDE parent still exercises the real export
// error, while aliases into an existing input directory fail before Store open.
// This assumes trusted local parents; it is not an adversarial-filesystem lease.
fn output_outside_inputs(target: &Path, inputs: [&Path; 3]) -> Result<()> {
    let mut parent = target.parent().ok_or_else(super::bad)?;
    let resolved = loop {
        match std::fs::canonicalize(parent) {
            Ok(path) => break path,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                parent = parent.parent().ok_or_else(super::bad)?;
            }
            Err(error) => return Err(error.into()),
        }
    };
    for input in inputs {
        ensure(!resolved.starts_with(std::fs::canonicalize(input)?))?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "checkpoint_pending_tests.rs"]
mod tests;
