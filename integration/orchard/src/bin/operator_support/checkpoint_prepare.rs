//! Explicit local checkpoint-bound preparation; never authenticates a remote tip.
use super::{
    checkpoint, ensure, export, hex, identity, intent, number, path, receipt, unhex, unused_output,
    Payment, Request, Result, TestGenesis, WalletStore,
};
use std::path::Path;
use zevune_orchard_lab::wallet::vault::store::MAX_RECORDS;

pub(super) fn execute(request: Request<'_>) -> Result<String> {
    execute_with_export(request, export)
}

// Private test seam can fail an export; it cannot alter the proving path or
// authorize a payment. Production always supplies the original create-only export.
fn execute_with_export(
    request: Request<'_>,
    write_export: impl FnOnce(&Path, &Payment) -> Result<()>,
) -> Result<String> {
    ensure(request.op == 12 && request.fields.len() == 11 && request.pin.is_some())?;
    let pin = request.pin.ok_or_else(super::bad)?;
    ensure(
        (1..=MAX_RECORDS).contains(&pin.generation)
            && pin.journal_id != [0; 32]
            && pin.digest != [0; 32],
    )?;
    let f = &request.fields;
    let source = path(f[0])?;
    let journal = path(f[1])?;
    let target = path(f[8])?;
    let height = number(f[9])?;
    let app_hash = unhex::<32>(f[10])?;
    ensure(app_hash != [0; 32])?;
    unused_output(target)?;
    let genesis = TestGenesis::read_pinned(path(f[2])?, unhex(f[3])?)?;
    let payment_intent = intent(f, &genesis)?;
    WalletStore::check_preparation_fee(payment_intent.amount, payment_intent.fee)?;
    let (mut pool, summary) = checkpoint::open_checked(&genesis, journal, height, app_hash)?;
    let history = genesis.wallet_history(&mut pool)?;
    ensure(pool.summary()? == summary)?;
    // Pool -> wallet lock order. No intermediate WalletStore::sync/persist.
    let mut wallet = WalletStore::open(source, request.password, Some(pin))?;
    let payment = wallet.prepare_payment_from_history(
        &history,
        &payment_intent.recipient,
        payment_intent.amount,
        payment_intent.fee,
        payment_intent.expiry,
    )?;
    // The single wallet record is already durable. An export error must leave
    // its pending reservation and exact bytes for explicit reconciliation.
    write_export(target, &payment)?;
    let body = format!(
        "{},\"result\":\"checkpoint_payment_saved_not_broadcast\",\"checkpoint_matched\":true,\"height\":{},\"app_hash\":\"{}\",\"txid\":\"{}\",\"receipt\":\"{}\",\"broadcast\":false",
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

#[cfg(test)]
#[path = "checkpoint_prepare_tests.rs"]
mod tests;
