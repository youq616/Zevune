//! Explicit create-only compaction; the old file is never rewritten or deleted.
//! A new receipt starts a NEW ancestry. The receipt pair is an operator handover
//! record, not a portable proof of lineage, global copy lock or blockchain proof.
use super::*;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CompactionReceipt {
    pub source: StoreReceipt,
    pub target: StoreReceipt,
}

impl WalletStore {
    /// Re-encrypt the current authenticated snapshot AND exact pending outbox
    /// into one record of a new file. Requires the exact current source receipt,
    /// not merely an ancestor. Supports a full journal without raising limits.
    ///
    /// Success retires this in-process source instance and returns an owned,
    /// locked target that must rescan history before it may report a balance or
    /// prepare a payment. Failure preserves the source; a partial or even fully
    /// written target may remain, so never automatically retry/overwrite it.
    ///
    /// The same password and existing ZVWJNL01 codec are used. Old receipt pins
    /// do NOT authenticate the new ancestry; retain the returned target receipt
    /// independently. Keep the old file as an offline recovery copy, not a second
    /// active wallet. Another copy or process can still reopen it: retirement is
    /// not persisted and cannot revoke already copied keys.
    pub fn compact_copy_new(
        &mut self,
        path: &Path,
        expected: StoreReceipt,
    ) -> Result<(WalletStore, CompactionReceipt), StoreError> {
        self.validate_storage()?;
        if expected != self.receipt {
            return Err(StoreError::Rollback);
        }
        let before = payload(&self.wallet, self.outbox.as_deref())?;
        let header = new_header()?;
        let id: Hash = Sha256::digest(header).into();
        if id == expected.journal_id {
            return Err(StoreError::Wallet(WalletError::Entropy));
        }
        let bytes = record(
            &header,
            1,
            id,
            &self.wallet,
            self.outbox.as_deref(),
            self.password.as_ref(),
        )?;
        let receipt = StoreReceipt {
            journal_id: id,
            generation: 1,
            digest: bytes[RECORD - 32..].try_into().unwrap(),
        };
        let mut file = create_file(path)?;
        io(file.write_all(&header))?;
        #[cfg(test)]
        if self.fault == 3 {
            io(file.write_all(&bytes[..RECORD / 2]))?;
            return Err(StoreError::Io);
        }
        io(file.write_all(&bytes))?;
        io(file.sync_all())?;
        sync_parent(path)?;
        #[cfg(test)]
        if self.fault == 4 {
            // Acknowledgement can be lost after a complete durable copy exists.
            return Err(StoreError::Io);
        }
        // Verify through the OWNING lock handle (including on Windows). Do not
        // close/reopen by path or trust only an outer checksum. Compare every
        // authenticated snapshot/outbox byte before reporting successful handover.
        let checked = scan(&mut file, Some(receipt))?;
        let plain = decrypt_payload(&checked.sealed, self.password.as_ref(), &checked.binding)?;
        if checked.header != header || checked.receipt != receipt || plain[..] != before[..] {
            return Err(StoreError::Corrupt);
        }
        let (wallet, outbox) = decode_payload(plain.as_ref())?;
        self.validate_storage()?;
        let target = WalletStore {
            file,
            header,
            receipt,
            password: Zeroizing::new(self.password.to_vec()),
            wallet,
            outbox,
            healthy: true,
            #[cfg(test)]
            fault: 0,
        };
        self.healthy = false;
        Ok((
            target,
            CompactionReceipt {
                source: expected,
                target: receipt,
            },
        ))
    }
}
