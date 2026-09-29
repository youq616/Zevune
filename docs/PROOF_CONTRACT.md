# Current proof, signature and state contract

> 2026-09-29 按已合入 C32 源码重建的当前规范；不是找回的历史原稿，不代表协议冻结、完整交付或安全审计通过。基线 merge `ae04190a57bff9ccfbeb056e749f30a9a62c2e02`，tree `7239d12b13b74919e4583cf05b66764994f23a7f`。

## Status and ownership

This document describes the existing experimental implementation; it does not introduce a new circuit, production transaction format or activation rule. The root Go diagnostic protocol and the generic laboratory `Verifier` must not be confused with the production-shaped `wire::AuthorizationVerifier` used by the persistent pool. Adapting any real backend requires a separately reviewed change to this contract and genuine vectors.

## Fixed cryptographic context

`integration/orchard/Cargo.toml` and `Cargo.lock` pin Orchard 0.15.5. `src/lib.rs` fixes `OrchardCircuitVersion::FixedPostNu6_2` and `BundleVersion::orchard_v2()`. Transaction field/curve/proof interpretation is delegated to this upstream library. No caller-selected verifying key, always-valid verifier, proof-skip switch, master view key, trusted witness service or transparent fallback is permitted.

LAB2 uses the nonzero domain `D = SHA256(exact canonical ZVTGEN02 or explicitly selected ZVTGEN03 manifest bytes)`. The committed deployment, not the transaction, selects D. Copying an identical manifest deliberately preserves its identity; this does not distinguish a fork or malicious complete clone. The digest of a ZVOPOL03 pool header is a different commitment used in recovery checkpoints; it must not be confused with D.

## Encoding and signed semantics

The authoritative existing layout is `protocol/GENESIS_DOMAIN_V2.md` plus the explicit03 profile specifications. LAB2 magic is `ZVORLAB2`, D occupies8:40, expiry40:48, fee48:56, signed balance56:64, anchor64:96, action count96:97 and flags97:98. Integers are big-endian; actions are ordered. Two through eight actions, fixed default flags3 and the existing28134-byte maximum are enforced. Truncation, trailing data, invalid fields, zero D, duplicate nullifiers/outputs and incompatible versions are rejected, not normalized.

Let N be UTF-8 `zevune-orchard-lab-1` and C the upstream Orchard bundle commitment computed with `TxVersion::V5`. The existing LAB2 signature message is:

```text
SHA256("ZEVUNE-ORCHARD-LAB-SIGHASH" || 0x00 || 0x02 ||
       D[32] || U16BE(len(N)) || N || U64BE(expiry) || U64BE(fee) || C[32])
```

All spend authorization and binding signatures use that message. LAB1 retains its original suffix0x00,0x01 and no D. Relabelling LAB2 as LAB1 cannot make its signatures valid. This is Zevune's experimental context around upstream commitments, not a claim to implement the complete ZIP244 transaction-ID or sighash scheme. The local txid is SHA256 of all exact wire bytes, including proof and signatures.

`protocol/signing-domain-vectors.json` checks public SHA256 transcript construction only. It does not contain a successful Orchard proof substitute. Genuine tests reside under the Rust integration module and funded consensus tests; vector parity must not be counted as complete authorization.

## Actual authorization path

`wire::AuthorizationVerifier::verify` performs canonical decoding, then checks its bounded exact-byte success cache. On a cache miss it constructs the signed digest, verifies every randomized spend authorization key/signature, verifies the binding signature and calls the pinned bundle proof verifier. Only then may it remember the exact bytes. A process-global fixed immutable public key is reused; each verifier instance has its own initially empty authorization cache. The generic laboratory batch verifier in `lib.rs` has a different scope and is not the persistent pool's acceptance shortcut.

A cache hit proves at most that these exact bytes previously passed the fixed cryptographic checks in this process. It does not approve the current anchor, expiry, network policy, double-spend status, issuance, fee accounting or mutation. Hash equality alone is insufficient; the existing cache also compares exact bytes. No disk import or remote cache acceptance is allowed.

## State and commit obligations

`pool.rs::State::apply_transaction` checks the trusted signing domain on every invocation, including cache hits. It independently checks height/expiry, accepted anchors, already spent nullifiers, duplicate outputs and bounded arithmetic/capacity. The nonnegative transaction balance equals the public fee. Rejection must preserve committed state, durable bytes, reservations and pending commit ownership according to each API's documented failure state.

Prepare is not a reusable spend permission. Commit checks its actual base, capacity and resulting state, and publishes committed state only through the existing durable path. Replay uses a new verifier with an empty authorization cache and independently constrained genesis/checkpoint. A framed checksum, process health, valid proof, AppHash or local ApplyBlock is never called consensus finality.

## Required negative matrix and release limits

The existing regression matrix covers altered domain/network/expiry/fee/commitment, wrong flags/version, truncation, repeated spends/outputs, stale prepare, damaged/relabelled replay and wrong-domain restored outbox. It must use genuine proofs and signature failures, not an executable accepting double. See the tests in `wire`, `pool`, wallet and `integration/cometbft/poolapp` for exact executable cases; their existence does not assert that a particular build ran them.

Current production acceptance is false. Formal upgrade activation, complete signing-transcript specialist review, network privacy, open validator rules, side-channel assessment and final cross-platform acceptance remain separate gates. Unknown future versions must not be converted automatically or used to roll back finalized state.
