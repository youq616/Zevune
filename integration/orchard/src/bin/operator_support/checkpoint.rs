//! Exact local reference-state handoff into the existing encrypted wallet scan.
//! The caller must independently authenticate the checkpoint (e.g. full trusted
//! network sync). A matching hash alone is NOT a consensus certificate.
use super::{bad, ensure, hex, identity, number, path, receipt, unhex, Request, Result};
use std::fmt;
use zevune_orchard_lab::pool::testnet::TestGenesis;
use zevune_orchard_lab::pool::{PoolStore, Summary};
use zevune_orchard_lab::wallet::vault::store::WalletStore;

#[derive(Debug)]
struct CheckpointMismatch;
impl fmt::Display for CheckpointMismatch {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("local wallet reference checkpoint mismatch")
    }
}
impl std::error::Error for CheckpointMismatch {}

// Return the SAME fully replayed, locked pool that was checked. Do not check a
// summary using one handle and then reopen the path for the wallet history.
fn open_checked(
    genesis: &TestGenesis,
    journal: &std::path::Path,
    height: u64,
    app_hash: [u8; 32],
) -> Result<(PoolStore, Summary)> {
    let pool = genesis.open_pool(journal)?;
    let summary = pool.summary()?;
    if summary.height != height || summary.app_hash != app_hash {
        return Err(CheckpointMismatch.into());
    }
    Ok((pool, summary))
}

pub(super) fn execute(request: Request<'_>) -> Result<String> {
    ensure(request.op == 11 && request.fields.len() == 6 && request.pin.is_some())?;
    let f = &request.fields;
    // Syntax is checked before files, wallet unlock or any persistent mutation.
    let height = number(f[4])?;
    let app_hash = unhex::<32>(f[5])?;
    ensure(app_hash != [0; 32])?;
    let source = path(f[0])?;
    let journal = path(f[1])?;
    let genesis = TestGenesis::read_pinned(path(f[2])?, unhex(f[3])?)?;
    let (mut pool, summary) = open_checked(&genesis, journal, height, app_hash)?;
    let history = genesis.wallet_history(&mut pool)?;
    ensure(pool.summary()? == summary)?;
    // No wallet has been opened on a failed reference checkpoint. The pool
    // lock remains held through history extraction AND wallet persistence.
    let mut wallet = WalletStore::open(source, request.password, request.pin)?;
    wallet.sync(&history)?;
    let view = wallet.view()?;
    ensure(view.height().ok_or_else(bad)? == summary.height)?;
    let body = format!(
        "{},\"result\":\"checkpoint_matched_wallet_scanned\",\"checkpoint_matched\":true,\"height\":{},\"app_hash\":\"{}\",\"balance\":{},\"available\":{},\"pending\":{},\"receipt\":\"{}\"",
        identity(&genesis),
        summary.height,
        hex(&summary.app_hash),
        view.balance()?,
        view.available_balance()?,
        view.pending_id().is_some(),
        receipt(&wallet)?,
    );
    drop(wallet);
    drop(pool);
    Ok(body)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parse;
    use std::fs;
    use zevune_orchard_lab::pool::testnet::TEST_SUPPLY;
    use zevune_orchard_lab::pool::PoolError;
    use zevune_orchard_lab::wallet::vault::store::{StoreError, StoreReceipt};
    use zevune_orchard_lab::wallet::{Wallet, WalletError, WalletProver};

    struct Home(std::path::PathBuf);
    impl Home {
        fn new() -> Self {
            let p = std::env::temp_dir().join(format!(
                "zevune-wallet-checkpoint-{:032x}",
                rand::random::<u128>()
            ));
            fs::create_dir(&p).unwrap();
            Self(p)
        }
    }
    impl Drop for Home {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn fields(home: &Home, genesis: &TestGenesis, summary: &Summary) -> Vec<String> {
        vec![
            home.0.join("wallet").to_str().unwrap().to_owned(),
            home.0.join("pool").to_str().unwrap().to_owned(),
            home.0.join("genesis").to_str().unwrap().to_owned(),
            hex(&genesis.digest()),
            summary.height.to_string(),
            hex(&summary.app_hash),
        ]
    }
    fn call(fields: &[String], password: &[u8], pin: StoreReceipt) -> Result<String> {
        execute(Request {
            op: 11,
            password,
            pin: Some(pin),
            fields: fields.iter().map(String::as_str).collect(),
        })
    }

    #[test]
    fn exact_frame_requires_pin_six_fields_and_no_trailing_bytes() {
        let password = b"synthetic-checkpoint-parser-password";
        let mut raw = b"ZVWCLI01".to_vec();
        raw.push(11);
        raw.extend_from_slice(&(password.len() as u16).to_be_bytes());
        raw.extend_from_slice(password);
        let offset = raw.len();
        raw.push(1);
        raw.extend_from_slice(&[1; 32]);
        raw.extend_from_slice(&1u64.to_be_bytes());
        raw.extend_from_slice(&[2; 32]);
        raw.push(6);
        for f in [
            "/wallet",
            "/pool",
            "/genesis",
            &"1".repeat(64),
            "0",
            &"2".repeat(64),
        ] {
            raw.extend_from_slice(&(f.len() as u16).to_be_bytes());
            raw.extend_from_slice(f.as_bytes());
        }
        assert_eq!(parse(&raw).unwrap().op, 11);
        for end in 0..raw.len() {
            assert!(parse(&raw[..end]).is_err());
        }
        let mut missing_pin = raw.clone();
        missing_pin[offset] = 0;
        missing_pin.drain(offset + 1..offset + 73);
        assert!(parse(&missing_pin).is_err());
        let mut wrong_count = raw.clone();
        wrong_count[offset + 73] = 5;
        assert!(parse(&wrong_count).is_err());
        raw.push(0);
        assert!(parse(&raw).is_err());
    }

    #[test]
    fn both_storage_profiles_keep_checked_handle_locked_and_reject_changed_tip() {
        for active in [false, true] {
            let home = Home::new();
            let owner = Wallet::create().unwrap().receive_address(0).unwrap();
            let genesis = if active {
                TestGenesis::generate_active(&[(owner, TEST_SUPPLY)]).unwrap()
            } else {
                TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap()
            };
            let p = home.0.join("pool");
            let mut created = genesis.create_pool(&p).unwrap();
            let original = created.summary().unwrap();
            drop(created);
            let (held, summary) = open_checked(&genesis, &p, 0, original.app_hash).unwrap();
            assert_eq!(summary, original);
            assert!(matches!(genesis.open_pool(&p), Err(PoolError::Locked)));
            drop(held);
            let mut changed = original.app_hash;
            changed[0] ^= 1;
            let error = match open_checked(&genesis, &p, 0, changed) {
                Ok(_) => panic!("wrong state accepted"),
                Err(e) => e,
            };
            assert!(error.downcast_ref::<CheckpointMismatch>().is_some());
            created = genesis.open_pool(&p).unwrap();
            let next = created.prepare(1, [7; 32], &[]).unwrap();
            created.commit(next).unwrap();
            drop(created);
            assert!(open_checked(&genesis, &p, 0, original.app_hash).is_err());
        }
    }

    #[test]
    fn mismatch_is_detected_before_attempting_to_open_or_unlock_wallet() {
        let home = Home::new();
        let owner = Wallet::create().unwrap().receive_address(0).unwrap();
        let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
        genesis.write_new(&home.0.join("genesis")).unwrap();
        let pool = genesis.create_pool(&home.0.join("pool")).unwrap();
        let summary = pool.summary().unwrap();
        drop(pool);
        let mut f = fields(&home, &genesis, &summary);
        f[4] = "1".to_owned();
        let synthetic_pin = StoreReceipt {
            journal_id: [1; 32],
            generation: 1,
            digest: [2; 32],
        };
        for corrupt_wallet in [false, true] {
            if corrupt_wallet {
                fs::write(home.0.join("wallet"), b"not an encrypted wallet").unwrap();
            }
            let e = call(&f, b"unused-test-password", synthetic_pin).unwrap_err();
            assert!(e.downcast_ref::<CheckpointMismatch>().is_some());
            if corrupt_wallet {
                assert!(fs::read(home.0.join("wallet")).unwrap() == b"not an encrypted wallet");
            } else {
                assert!(!home.0.join("wallet").exists());
            }
        }
    }

    #[test]
    fn real_pending_is_unchanged_on_mismatch_and_reconciles_only_at_matching_state() {
        let home = Home::new();
        let password = zeroize::Zeroizing::new(rand::random::<[u8; 32]>());
        let wallet_path = home.0.join("wallet");
        let pool_path = home.0.join("pool");
        let mut wallet = WalletStore::create(&wallet_path, password.as_ref()).unwrap();
        let owner = wallet.view().unwrap().receive_address(0).unwrap();
        let genesis = TestGenesis::generate(&[(owner, TEST_SUPPLY)]).unwrap();
        genesis.write_new(&home.0.join("genesis")).unwrap();
        let mut pool = genesis.create_pool(&pool_path).unwrap();
        wallet
            .sync(&genesis.wallet_history(&mut pool).unwrap())
            .unwrap();
        let recipient = wallet.view().unwrap().receive_recipient(0).unwrap();
        let tx = wallet
            .prepare_payment_to(&recipient, 1_000, 1, 10, &WalletProver::new())
            .unwrap();
        let pending = tx.bytes().to_vec();
        let pending_id = tx.id();
        let pin = wallet.receipt().unwrap();
        let initial = pool.summary().unwrap();
        let f = fields(&home, &genesis, &initial);
        drop(wallet);
        drop(pool);
        let before = fs::read(&wallet_path).unwrap();
        let reference = fs::read(&pool_path).unwrap();
        let mut bad_fields = f.clone();
        bad_fields[5] = "ff".repeat(32);
        let e = call(&bad_fields, password.as_ref(), pin).unwrap_err();
        assert!(e.downcast_ref::<CheckpointMismatch>().is_some());
        assert!(fs::read(&wallet_path).unwrap() == before);
        assert!(fs::read(&pool_path).unwrap() == reference);
        // Reopen the encrypted store, not merely an old in-process view.
        wallet = WalletStore::open(&wallet_path, password.as_ref(), Some(pin)).unwrap();
        assert_eq!(wallet.view().unwrap().pending_id(), Some(pending_id));
        // Decryption restores durable checkpoint/outbox, never a spendability
        // cache. First prove reopen and the rejected operation changed no bytes;
        // do not use pending_payment as an unscanned outbox accessor.
        assert_eq!(
            wallet.view().unwrap().balance(),
            Err(WalletError::NotSynced)
        );
        assert!(matches!(
            wallet.pending_payment(),
            Err(StoreError::Wallet(WalletError::NotSynced))
        ));
        assert_eq!(
            wallet.view().unwrap().available_balance(),
            Err(WalletError::NotSynced)
        );
        assert_eq!(wallet.receipt().unwrap(), pin);
        assert!(fs::read(&wallet_path).unwrap() == before);
        assert!(fs::read(&pool_path).unwrap() == reference);
        // Only now reconstruct the SAME validated history explicitly. This
        // cannot clear the uncommitted payment or append a different checkpoint.
        pool = genesis.open_pool(&pool_path).unwrap();
        assert_eq!(pool.summary().unwrap(), initial);
        let history = genesis.wallet_history(&mut pool).unwrap();
        wallet.sync(&history).unwrap();
        assert!(wallet.pending_payment().unwrap().unwrap().bytes() == pending.as_slice());
        assert_eq!(wallet.view().unwrap().pending_id(), Some(pending_id));
        assert_eq!(wallet.view().unwrap().available_balance(), Ok(0));
        assert_eq!(wallet.receipt().unwrap(), pin);
        assert!(fs::read(&wallet_path).unwrap() == before);
        assert!(fs::read(&pool_path).unwrap() == reference);
        drop(pool);
        drop(wallet);
        let result = call(&f, password.as_ref(), pin).unwrap();
        assert!(result.contains("\"pending\":true"));
        assert!(result.contains("\"available\":0"));
        assert!(result.contains("\"checkpoint_matched\":true"));
        pool = genesis.open_pool(&pool_path).unwrap();
        let prepared = pool.prepare(1, [9; 32], &[pending]).unwrap();
        let committed = pool.commit(prepared).unwrap();
        drop(pool);
        let current_wallet = fs::read(&wallet_path).unwrap();
        assert!(call(&f, password.as_ref(), pin).is_err());
        assert!(fs::read(&wallet_path).unwrap() == current_wallet);
        let next = fields(&home, &genesis, &committed);
        let result = call(&next, password.as_ref(), pin).unwrap();
        assert!(result.contains("\"height\":1"));
        assert!(result.contains("\"pending\":false"));
        assert!(result.contains("\"balance\":99999"));
        let reconciled_wallet = fs::read(&wallet_path).unwrap();
        wallet = WalletStore::open(&wallet_path, password.as_ref(), Some(pin)).unwrap();
        // The persisted pending identity is readable without scanning. Reopen
        // still must not populate the trusted balance cache just to inspect it.
        assert!(wallet.view().unwrap().pending_id().is_none());
        assert_eq!(
            wallet.view().unwrap().balance(),
            Err(WalletError::NotSynced)
        );
        assert_eq!(wallet.view().unwrap().height(), Some(1));
        assert!(wallet.receipt().unwrap() != pin);
        assert!(fs::read(&wallet_path).unwrap() == reconciled_wallet);
    }
}
