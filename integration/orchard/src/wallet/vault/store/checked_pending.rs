//! Recover the authenticated outbox, without publishing a scan or wallet write.
//! The supplied history must come from the caller's real locked pool replay;
//! this API does not authenticate a remote tip and never signs or broadcasts.
use super::{
    decode, restore, snapshot, Digest, Hash, Payment, Sha256, StoreError, WalletError,
    WalletHistory, WalletStore,
};

impl WalletStore {
    /// Return the SAME saved signed bytes only while they remain pending and
    /// unexpired for a block AFTER this verified history. No capacity slot,
    /// persist, prover, live scan-cache publication or pending clear is used.
    /// A failure is not confirmation, permission to re-sign, or retry authority.
    pub fn pending_payment_from_history(
        &mut self,
        history: &WalletHistory,
    ) -> Result<Payment, StoreError> {
        self.validate_storage()?;
        let (pending, raw) = match (&self.wallet.pending, &self.outbox) {
            (None, None) | (Some(_), None) => return Err(StoreError::MissingOutbox),
            (None, Some(_)) => return Err(StoreError::Corrupt),
            (Some(pending), Some(raw)) => (pending, raw),
        };
        // Open already authenticates the encrypted record and saved proof.
        // Recheck the original envelope/domain binding; never infer it from
        // a caller's height/hash or alter the bytes to fit a different network.
        let tx = decode(raw).map_err(|_| StoreError::Corrupt)?;
        if pending.txid != Hash::from(Sha256::digest(raw))
            || pending.expiry != tx.context.expiry_height
        {
            return Err(StoreError::Corrupt);
        }
        if tx.context.signing_domain != history.signing_domain {
            return Err(StoreError::Wallet(WalletError::History));
        }
        let original = snapshot(&self.wallet)?;
        let mut checked = restore(original.as_ref())?;
        checked.sync(history)?;
        let next_height = checked
            .height()
            .and_then(|height| height.checked_add(1))
            .ok_or(StoreError::Wallet(WalletError::History))?;
        // Original sync retains a pending at height == expiry. Such a payment
        // is already too old for the NEXT block, so recovery refuses equality
        // without changing that original rule or the durable wallet's pending.
        if checked.pending_id() != Some(pending.txid) || pending.expiry < next_height {
            return Err(StoreError::Wallet(WalletError::History));
        }
        let payment = Payment {
            bytes: raw.clone(),
            txid: pending.txid,
        };
        drop(checked);
        self.validate_storage()?;
        Ok(payment)
    }
}

#[cfg(all(test, feature = "local-funding-lab"))]
#[path = "checked_pending_tests.rs"]
mod tests;
