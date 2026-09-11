# Orchard laboratory: real cryptography, durable state and local wallet

**NO FUNDS. No complete wallet application, public payment service, witness service or issuance API.** This Rust module uses genuine upstream cryptography. Cargo publishing is disabled. The original M3 application still rejects transactions; the separate M7 integration tests real zero-value protocol transactions.

## Fixed cryptographic scope

Pin `orchard = 0.15.5`, `BundleVersion::orchard_v2()` and the patched `OrchardCircuitVersion::FixedPostNu6_2`. Historical insecure V1 is rejected. This laboratory choice is NOT a claim about current Zcash activation rules or a final Zevune protocol. Orchard/Ironwood V3 migration, compatibility and long-term threat analysis remain separate decisions. No circuits are rewritten or verifying keys supplied by a transaction.

M4 uses upstream Halo 2, RedPallas signatures, note decryption and Orchard Merkle hashes. The experimental signing transcript is SHA-256 over a domain, fixed network, expiry, fee and upstream V5 bundle commitment; it is not ZIP-244 or an independently audited transaction protocol. Signature binding of ciphertexts does not establish that every sender-created ciphertext can be decrypted. Receiving uses upstream authenticated decryption.

The original M4 Verifier reads a caller-supplied trusted StateView and uses upstream batch verification. That remains a laboratory API, not a consensus decision. The M5 worker and M6 pool use individual upstream signature verification and the upstream single-proof verifier. Each still requires version, public-input, resource and state constraints; proof validity alone does not establish authorized issuance or absence of prior spends.

## Process boundaries and durable state

`wire` implements bounded canonical local transport (2–8 actions, at most 28,102 bytes), using upstream field and point parsing. `zevune-orchard-worker` accepts framed public authorization bytes through stdin/stdout. The Go caller in `internal/orchardbridge` checks an expected executable digest, validates framing, separates rejection from worker failure and closes on uncertain exchanges. A self-computed executable hash is not a release signature or sandbox.

`pool` uses `Frontier<MerkleHashOrchard,32>`, ordered commitments, spent-nullifier and output sets, bounded committed roots and a versioned state hash. Public constructors only create/reopen empty-genesis pools. Test-only callers seed nonempty synthetic fixtures; no arbitrary issuance API exists. M7 connects this store through `zevune-pool-worker`, `internal/poolbridge` and the separate CometBFT `poolapp`.

Prepare uses a private candidate. Commit checks the base, revalidates actual proofs and state, appends a bounded checksummed journal and synchronizes before advancing memory. Open locks and fully replays it. Corrupt journals are never silently repaired/truncated. Write failure poisons the instance, but a whole record can still exist after acknowledgement loss. A valid old prefix requires independent checkpoint comparison.

Limits: 16 transactions/block, 65,536 commitments, 10,000 records and 64 MiB journal. These are not production storage or light-client guarantees. See [state boundaries](../../docs/ORCHARD_STATE.zh-CN.md) and [M7 consensus integration](../../docs/ORCHARD_CONSENSUS.zh-CN.md). The four-node M7 tests are local, zero-value and not a complete wallet payment network.

## M8 local wallet core

`wallet` derives genuine test ZIP32 keys from local randomness, detects external receipts/internal change, selects actual unspent notes and builds genuine proofs/signatures. Several selected inputs share a single tree reduction for their authentication paths. This is bounded coin selection, not a claim of optimal privacy or measured network speed.

`pool::history` exports public signed history only after full local cryptographic replay against the open store's committed state. Wallet rescanning rebuilds notes and balances. Existing checkpoints must be ancestors of new history; short histories and longer forks are rejected. Local full-node trust is explicit: this is not authentication of a remote server's tip or a light client.

`wallet::vault` uses fixed Argon2id v19 (64 MiB, 3 passes, 1 lane) and XChaCha20-Poly1305. The 620-byte authenticated encrypted snapshot preserves the seed, checkpoint and pending-input reservation, not an authoritative balance. New salt/nonce per snapshot; wrong passwords, modified ciphertext and noncanonical formats are rejected. KDF parameters and file size are checked before expensive work. Password strength, old-backup rollback, multi-device coordination, Windows ACLs and directory durability remain application responsibilities.

One pending payment is allowed. Inputs remain reserved across a current snapshot restore until confirmed spent or a trusted synced height exceeds inclusive expiry. Building does not broadcast: application-level save-before-broadcast atomicity and recovery of complete pending transaction bytes remain incomplete. Only owned seed/key/plaintext buffers are zeroized; no complete upstream-object or operating-system erasure guarantee is made. No master key, witness server, plaintext seed export or telemetry is added.

## Automated verification

Fixed Rust toolchain 1.98.1, committed Cargo.lock and `--locked`. Final read-only CI checks formatting, locked metadata, release tests, strict Clippy and tracked-file stability. Additional workflows build actual workers for Go/ABCI integration. Missing real fixture/worker inputs cause integration failure, not a pass via skip.

```text
cargo test --locked --release -- --nocapture --test-threads=1
cargo clippy --locked --release --all-targets -- -D warnings
cargo build --locked --release --bin zevune-orchard-worker --bin zevune-pool-worker
```

M8 adds a private-test funded local flow with two receipts, multi-note payment, change, encrypted pending restore, inclusive expiry/release, onward payment and final balance/fee reconciliation. It tests checkpoint ancestry, journal cursor/append integrity, backup tampering, shared paths against upstream Frontier and an independent public Argon2 reference vector. The initial funded bootstrap remains inaccessible to public constructors.

Temporary M8 backup files contain encrypted test secrets and must not be published. Cross-language fixtures remain public signed envelopes only. No plaintext keys, seeds, decrypted notes or witnesses are logged or exported. Secret-bearing wallet objects have no Debug serialization. Random malformed input tests and single KDF vectors are not a cryptographic or side-channel audit.

## Remaining work

M8 local nonzero payments are NOT the same test as M7 four-node zero-value consensus. Nonzero multi-node wallet integration, constrained issuance/fee economics, user CLI/UI, authenticated network sync, atomic wallet persistence/broadcast, final protocol domains, network privacy, production persistence and independent audit remain incomplete. No end-to-end p95 or TPS is reported.

Old Go tree/ciphertext/journal formats are not reinterpreted or migrated. Original missing project documents remain missing. See [M8 detailed boundaries](../../docs/LOCAL_WALLET.zh-CN.md), repository SECURITY.md, LICENSE-STATUS.md and this directory's NOTICE.md; source publication is not an independent audit or a license decision for all Zevune code.

Primary sources: https://github.com/zcash/orchard/tree/0.15.5 ; https://docs.rs/incrementalmerkletree/0.8.1/incrementalmerkletree/frontier/struct.Frontier.html ; https://github.com/RustCrypto/password-hashes/tree/argon2-v0.5.3/argon2 ; https://docs.rs/chacha20poly1305/0.10.1/chacha20poly1305/ . Dependency locking is not a vulnerability audit.
