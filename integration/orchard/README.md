# Orchard laboratory: M4 cryptography, M5 local worker, M6 pool state

**NO FUNDS. No wallet application, payment network, public RPC, witness service or issuance API.** This Rust module uses genuine upstream cryptography. Cargo publishing is disabled. M3 network transactions remain disabled.

## Fixed cryptographic scope

Pin `orchard = 0.15.5`, `BundleVersion::orchard_v2()` and the patched `OrchardCircuitVersion::FixedPostNu6_2`. Historical insecure V1 is rejected. This laboratory choice is NOT a claim about current Zcash activation rules or a final Zevune protocol. Orchard/Ironwood V3 migration, compatibility and long-term threat analysis remain separate decisions. No circuits are rewritten or verifying keys supplied by a transaction.

M4 uses upstream Halo 2, RedPallas signatures, note decryption and Orchard Merkle hashes. The experimental signing transcript is SHA-256 over a domain, fixed network, expiry, fee and upstream V5 bundle commitment; it is not ZIP-244 or an independently audited transaction protocol. Signature binding of ciphertexts does not establish that every sender-created ciphertext can be decrypted. Receiving uses upstream authenticated decryption.

The original M4 Verifier reads a caller-supplied trusted StateView and uses upstream batch verification. That remains a laboratory API, not a consensus decision. The M5 worker and M6 pool use individual upstream signature verification and the upstream single-proof verifier. Each still requires version, public-input, resource and state constraints; proof validity alone does not establish authorized issuance or absence of prior spends.

## M5 local process boundary

`wire` implements bounded canonical local transport (2–8 actions, at most 28,102 bytes), using upstream field and point parsing. `zevune-orchard-worker` accepts only framed public authorization bytes through stdin/stdout. It retains a fixed public verification key, binds responses to monotonic IDs and full-payload hashes, and exposes no wallet, network listener, file-loading command, arbitrary executable command or secret-input service.

The Go caller in `internal/orchardbridge` verifies an expected executable digest, validates framing, separates rejection from worker failure, closes on uncertain exchanges and independently checks a trusted committed-state view. A self-computed executable hash is not a release signature or sandbox. Local OS/filesystem trust and caller ownership assumptions remain explicit.

## M6 state and storage

`pool` uses `Frontier<MerkleHashOrchard,32>`, ordered commitment appends, spent-nullifier and output sets, bounded committed roots and a versioned state hash. Public constructors only create/reopen empty-genesis pools. Test-only callers can seed nonempty synthetic fixtures; there is no arbitrary issuance API. The pool is a Rust library, not yet driven by Go or M3 consensus.

Prepare executes on a private candidate. Commit checks the base, revalidates actual proofs and state, appends a bounded checksummed journal and synchronizes it before advancing memory. Open locks the file and fully replays authorization and state checks. It never repairs/truncates a corrupt journal or resets signing state. Write failure poisons the live instance; a whole record may nevertheless be recoverable after lost acknowledgement. A valid old journal prefix is detectable only against an independently trusted checkpoint, not from checksums alone.

Limits: 16 transactions/block, 65,536 commitments, 10,000 records, 64 MiB journal. Filesystem, directory durability, malicious local administrator and full historical replay costs are not solved by these bounds. This is not production storage or a light-client proof. Full details: [Chinese boundary specification](../../docs/ORCHARD_STATE.zh-CN.md).

## Automated verification

Fixed Rust toolchain 1.98.1, committed Cargo.lock and `--locked`. The ordinary read-only CI runs formatting, metadata lock checks, release tests and strict Clippy, and fails if tracked files change. `orchard-bridge` additionally builds the actual worker and runs Go against public signed bytes produced by actual proof tests. Missing real artifacts cause failure, not skips.

```text
cargo test --locked --release -- --nocapture --test-threads=1
cargo clippy --locked --release --all-targets -- -D warnings
cargo build --locked --release --bin zevune-orchard-worker
```

M4 tests generate keys and a synthetic note in memory, prove A→B with change, decrypt, and spend the actual received note onward to C. M5 checks canonical wire, individual authorization and framed serving. M6 adds real two-hop commit/reopen/replay, duplicate rejection, atomic candidate failure, write fault injection, corrupted proofs with recomputed outer checksums, and the valid-prefix rollback boundary. Only public commitments and signed envelopes are written in temporary test storage; no keys, seeds, decrypted notes or witnesses are exported. Public cross-language fixtures are not secret-bearing wallet artifacts.

Random malformed-input and truncation tests are not coverage-guided Rust fuzzing. Linux Go race/fuzz coverage is not a Windows race result. Tiny phase timings and a warm worker do not establish p95, TPS, WAN performance or anonymous end-to-end payment speed. No secure-memory-erasure or side-channel audit is claimed. Users need not repeat micro-validation.

## Remaining work

M5 stateless IPC, M6 local state and M3 consensus are not connected into a wallet/payment service. Consensus recovery/checkpoint binding, wallet storage/sync/recovery, canonical final network protocol, issuance and economics, network privacy, production persistence and independent audit remain incomplete. Old Go tree/ciphertext/journal formats are not reinterpreted or migrated. Original missing project documents remain missing; these notes do not replace them.

Primary sources: https://github.com/zcash/orchard/tree/0.15.5 ; https://docs.rs/incrementalmerkletree/0.8.1/incrementalmerkletree/frontier/struct.Frontier.html ; https://doc.rust-lang.org/stable/std/fs/struct.File.html . Dependency integrity is not a vulnerability audit. See NOTICE.md for prior borrowed public vector attribution.
