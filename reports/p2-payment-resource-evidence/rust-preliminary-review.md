# P2 payment-resource preliminary independent Rust review

- Reviewer/task: `/root/p2_resource_review`; independent of candidate authorship.
- Review date: 2026-09-17.
- Repository/base: `youq616/Zevune`, `8324ec8bd153d9502e3e6761d25bfe281a5f3b44`.
- Base tree: `38c3caff84bcd6ca626bd5b6d53212d9e4f8e2b2`.
- Exact scope: uncommitted `integration/orchard/src/bin/zevune-funded-scenario.rs` only.
- Reviewed Git blob: `5c666fa21d7a8023c52e9e1d5d4f18ab9890de70`.
- Reviewed file SHA-256: `2b568ca93dc29d6ecc1edcac17973fc00d840e76fc38c5900a4e15db09dfceaa`.
- Frozen design SHA-256: `f8fb0f009423f26afbfb84ad2293b13dbe9581032c31ba0bfc379d224a91789f`.
- Result: **NO_BLOCKER_IDENTIFIED in this preliminary Rust-only source scope. This is not final-stage PASS.**

## Work actually performed

Verified the source blob/hash twice during review, read the full diff against the stated base, and read the edited methods in context. Checked the real unchanged caller paths in TestGenesis create/open/history, PoolStore full replay with a new AuthorizationVerifier, Wallet largest-first selection and real Orchard construction/verification, WalletStore creation, sync, storage_status, backup_new and receipt-bound open. Reviewed the design, AGENTS.md and stage rules. Confirmed that this bin is the only file changed under integration/orchard relative to the base at this observation. No candidate/repository code was written or modified by this reviewer.

No cargo build, rustfmt, Clippy, native Rust/Go tests or CI jobs were executed by this reviewer. Those toolchains are unavailable locally. Go/Python implementation was not yet frozen and is outside this preliminary review; full source identities and actual native evidence will be reviewed separately.

## Source findings

No blocking source finding was identified in the exact Rust file above.

- The new Mode enum and explicit `--active-resource-v1` branch select two encrypted wallets and split the existing 100000-unit public test supply into two 50000-unit allocations. Active resource uses the existing explicit ZVTGEN03 generator. No production limit, storage/transaction format, verifier or worker API was changed.
- Payment preparation derives the next sender only from the actual committed height, uses fixed amount/fee 1000/1000 and expiry committed height plus 100, and rejects repeated prepare while an outbox is pending. It still uses recipient-domain checking followed by the real WalletStore::prepare_payment_to. Decoding checks exactly two actual Orchard actions, the pinned genesis domain, expiry and fee. There is no prebuilt payment, accepting double or direct mutation of ledger state.
- Resource apply requires exactly the next height, at most height 33, exactly one transaction, and equality with the sender's saved pending bytes; the other wallet must have no pending payment. It then calls the original PoolStore prepare/commit and checks the fixed commitment/nullifier/fee counts. Keeping scenario apply separate from status/sync makes separate coordinator timing possible, subject to the eventual Go implementation.
- Resource status performs full TestGenesis::wallet_history and WalletStore::sync, then checks actual storage_status against regular-file metadata. The balance, available-balance and saved-record formulas agree with this fixed schedule. Largest-first selection retains a change note of at least 16000 throughout the workload, larger than each 1000-unit received note. Therefore the pending reservation covers that entire selected change note; at committed height 32 with payment 33 pending, A's available balance is 16000 and wallet records are 51/50. After confirmation they become 52/51 and balances 32000/35000.
- Ledger and wallet restoration at height 32 must occur with no pending transaction and before resource_recovered is set. The code drops/opens the PoolStore, compares the entire saved Summary, restores both wallets using receipts, synchronizes the full history and validates final status. Only then does it permit construction of payment 33. Opening the PoolStore reaches unchanged code that constructs a fresh AuthorizationVerifier and fully replays history.
- The subsequent sender backup/open records the pre-backup receipt/storage, verifies the backup receipt, drops the old instance, opens the backup with that receipt, resynchronizes and checks byte-identical pending payment plus unchanged storage/receipt. Only the restored sender outbox at height 32 sets resource_pending_restored. Resource apply at height 33 requires both recovery flags, and still compares submitted bytes with the real pending payment. Finish requires height 33 and cleared pending payments, not just the flags.
- Path tracking follows the currently owned restored wallet file, so status metadata reads compare against the active backup after handover. It uses symlink_metadata/file-type checks and does not read an exclusively locked wallet file through a second handle. The unchanged WalletStore APIs retain their existing lock and trusted-directory assumptions.
- Legacy and ActiveBoundary retain three wallets, both original genesis allocations to wallet A, the phase-based 60000 A-to-B / 40000 B-to-C payments, the old final expected balances, op3 availability, and the 96+3*17 = 147-byte status body. Resource alone returns the two augmented wallet tuples, 96+2*33 = 162 bytes. The original ready frame remains the genesis digest plus initial Summary. Extra command-line forms still reject.
- Error reporting remains the fixed generic no-secret message. Existing proof/block bytes travel only over the bounded local scenario IPC; the file adds no output of keys, passwords or private wallet data to diagnostics. Whether the new supervisor correctly prevents raw IPC data from entering artifacts remains a separate cross-component review item.

## Remaining gates and interpretation limits

The source review does not demonstrate compilation, exact formatter output, Clippy success, memory attainability, the 90-second scenario response target, complete 32+1 execution, actual Windows lock behavior or old-mode runtime compatibility. Native CI must verify those. The new Go caller must enforce the frozen operation order, exact response lengths, full Summary and capacity comparisons, byte accounting, physical-frame inspection, rejection/non-mutation, PID handshakes and every required recovery step; the Python supervisor must enforce identity, metrics, deadlines and durable failure evidence. Those obligations are not satisfied by the Rust flags or formulas alone.

The reviewer will require the final full-candidate base/head/tree and recheck this file identity or review its changes. No main merge, completed-stage status or production/funds claim should be based solely on this preliminary result.
