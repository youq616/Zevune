//! One original durable snapshot for an explicit rescan-and-prepare operation.
//! The supplied history is not a remote checkpoint authentication mechanism.
use super::{
    payload, restore, snapshot, Payment, StoreError, WalletHistory, WalletProver, WalletStore,
};
use crate::wallet::{address::Recipient, WalletError};

impl WalletStore {
    /// Conservative NO-FUNDS intent guard for the NEW preparation path only.
    /// Not a consensus fee rule, fee estimate, or a change to the legacy API.
    pub fn check_preparation_fee(amount: u64, fee: u64) -> Result<(), StoreError> {
        let maximum = (amount / 100).clamp(1, 100);
        if amount == 0 || fee == 0 || fee > maximum {
            return Err(StoreError::Wallet(WalletError::Bounds));
        }
        Ok(())
    }

    /// Rescan on a temporary wallet, then save checkpoint, reservation and exact
    /// signed outbox in ONE original journal record. The caller retains the
    /// locked, reexecuted pool that supplied history through this call.
    ///
    /// Existing pending is rejected BEFORE rescan, even if that history would
    /// reconcile/expire it. This method never clears or replaces an old payment.
    /// All pre-publication rejections leave the owned wallet unchanged. Original
    /// persist errors mark it unavailable and never return the signed Payment.
    pub fn prepare_payment_from_history(
        &mut self,
        history: &WalletHistory,
        recipient: &Recipient,
        amount: u64,
        fee: u64,
        expiry: u64,
    ) -> Result<Payment, StoreError> {
        self.prepare_from_history_with(history, recipient, amount, fee, expiry, WalletProver::new)
    }

    // Private seam returns only a REAL prover. Tests may observe/panic before
    // construction; no fake proof, pluggable verifier or public bypass exists.
    fn prepare_from_history_with(
        &mut self,
        history: &WalletHistory,
        recipient: &Recipient,
        amount: u64,
        fee: u64,
        expiry: u64,
        make_prover: impl FnOnce() -> WalletProver,
    ) -> Result<Payment, StoreError> {
        self.room()?;
        self.validate_storage()?;
        if self.wallet.pending_id().is_some() || self.outbox.is_some() {
            return Err(StoreError::Wallet(WalletError::Pending));
        }
        let before = snapshot(&self.wallet)?;
        let mut next = restore(before.as_ref())?;
        next.sync(history)?;
        Self::check_preparation_fee(amount, fee)?;
        next.check_payment_to(recipient, amount, fee, expiry)?;
        let destination = recipient
            .for_domain(next.signing_domain()?)
            .map_err(|_| StoreError::Wallet(WalletError::History))?;
        let prover = make_prover();
        Self::check_preparation_fee(amount, fee)?;
        // build_payment rechecks selection, bounds and authorization; neither
        // the earlier preflight nor cached proof validation grants permission.
        let payment = next.build_payment(destination, amount, fee, expiry, &prover)?;
        Self::check_preparation_fee(amount, fee)?;
        self.room()?;
        self.validate_storage()?;
        // Validate the exact existing snapshot/outbox shape before publication.
        // persist still repeats the original validation and synchronous write.
        let _ = payload(&next, Some(payment.bytes()))?;
        self.wallet = next;
        self.outbox = Some(payment.bytes().to_vec());
        self.persist()?;
        Ok(payment)
    }
}

#[cfg(all(test, feature = "local-funding-lab"))]
#[path = "checked_prepare_tests.rs"]
mod tests;
