# M4: real Orchard cryptography integration laboratory

**NO FUNDS. No wallet application, payment network, RPC, witness server, issuance API, or private-data export.** This independent Rust module tests real upstream cryptography, not the Go prototype checksum verifier. Cargo publishing is disabled.

## Fixed scope

Pin `orchard = 0.15.5`, with `BundleVersion::orchard_v2()` and the patched `OrchardCircuitVersion::FixedPostNu6_2`. Insecure pre-NU6.2 bundles are explicitly rejected. This is a versioned laboratory choice, NOT a claim about current Zcash consensus activation rules or a finalized Zevune mainnet protocol. Orchard 0.15 also supports Orchard/Ironwood V3; compatibility, migration and long-term threat analysis remain separate design decisions. No circuit is rewritten and no caller can choose a verifying key.

Use upstream note creation, Sinsemilla Merkle hashing, Halo 2 proof generation/verification, RedPallas spend and binding signatures, and authenticated trial decryption. The lab additionally checks trusted anchors, spent nullifiers, output duplicates, fixed flags/action limits, expiry and `value_balance == nonnegative_fee`. Merely validating a bundle proof does NOT validate authorized issuance, global supply, historical membership or double-spend uniqueness.

The signing transcript is explicitly EXPERIMENTAL: SHA-256 over a lab domain, network, expiry, fee, and the upstream V5 bundle commitment. It is not ZIP-244, not an audited transaction format, and not connected to CometBFT. V5 is chosen because its commitment includes the anchor. Signatures bind ciphertexts through the upstream bundle commitment; this alone does not prove a sender made every ciphertext decryptable. Receiving notes uses the upstream authenticated decryption checks.

## Executed by automated tests, not by the user

The integration test creates fresh random keys and one synthetic starting note ONLY in test memory. It proves a transfer with change, checks both recipients, reconstructs a key in memory, and proves onward spending of the actually decrypted recipient note. A third genuine proof represents a negative shielded-pool delta: the upstream circuit can prove it, but this lab rejects it because no external funding/issuance path exists. Test funds are not real assets and have no network representation.

Negative cases cover a wrong owner/path, altered proof bytes, appended/truncated proofs, fake spend/binding signatures, changed ciphertext, altered fee/expiry/anchor, wrong network/version, repeated nullifiers/outputs and height overflow. Two upstream public empty-tree vectors cross-check Merkle encoding. This is not complete upstream vector coverage or an independent cryptographic audit.

The verification API is read-only. A `StateView` MUST come from the caller's trusted committed ledger, never from an untrusted transaction. The test harness advances its own in-memory state only after success. Upstream batch verification uses randomness: determinism/resource policy for use in consensus is still unreviewed. A future network implementation must atomically bind actual stored state and verified effects.

## Tooling and output

Pinned Rust toolchain: 1.98.1. Dedicated Windows/Linux CI compiles and tests this module independently of both Go modules. After bootstrap, Cargo.lock and `--locked` builds are required. `cargo test --release -- --nocapture --test-threads=1` reports phase results and aggregate timing only; keys, seeds, notes, addresses, memos and proof bytes are not printed. No user-side micro-validation is requested.

Timings separate public key construction, proof generation, full bundle validation and recipient scanning. These are small-sample, single-process cryptographic timings, NOT end-to-end payment latency, p95, TPS, WAN performance or anonymity measurements. No constant-time or secure-memory-erasure guarantee is claimed for this integration. No secret-bearing test artifacts should be published.

The Go v0 SHA-256 tree and 256-byte ciphertext slots are incompatible with real Orchard notes; they are NOT silently reinterpreted. M1/M2 data and M3 empty-block consensus remain unchanged. Production wallet storage, canonical wire parsing, receiving/scanning synchronization, safe genesis issuance, fee/reward rules, network privacy, durable Rust state, Go/Rust boundary and payment consensus are still absent.

## Primary references

- https://github.com/zcash/orchard/tree/0.15.5
- https://github.com/zcash/orchard/blob/0.15.5/CHANGELOG.md
- https://github.com/zcash/orchard/blob/0.15.5/src/builder.rs
- https://github.com/zcash/orchard/blob/0.15.5/src/bundle/batch.rs
- https://github.com/zcash/orchard/blob/0.15.5/src/test_vectors/commitment_tree.rs
- https://blog.rust-lang.org/releases/

Dependency locking is not a vulnerability audit. Upstream protocol research does not automatically audit this integration. Previously unpublished project documents are not republished or replaced by this module.
