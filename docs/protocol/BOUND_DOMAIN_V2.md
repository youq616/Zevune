# ZEV-12: opt-in transaction-domain binding, revision 2

Status: implementation-backed laboratory specification, NOT an independently reviewed mainnet protocol. Only the explicitly created V2 Rust wallet and fixed-test-genesis store APIs use this format. The M11 command-line network, its existing V1 wire and its journals are NOT automatically upgraded. No public network is deployed by this change.

## Purpose and trust

Two distinct test networks may use identical initial notes, owners and commitment roots. A valid V1 signature was scoped to one fixed laboratory string, not a independently configured network instance. Merely adding a network label to an unsigned envelope does not prevent replay. V2 binds an immutable instance descriptor to authorization signatures, state initialization and the authenticated wallet snapshot.

An operator MUST independently select/pin the expected descriptor. A validator MUST NOT learn its accepted domain by copying a field from a submitted transaction. The descriptor is public, not a secret, master key, global viewing key or proof of operator independence. Copies with the same descriptor describe the SAME replay domain; deliberate reuse cannot be distinguished cryptographically. Keys/addresses are not currently derived differently by domain.

## 1. Canonical network descriptor

All byte arrays below have fixed length. Integers elsewhere in this specification are unsigned big-endian unless stated otherwise.

| Byte offsets, half-open | Length | Value |
|---|---:|---|
| `[0,8)` | 8 | ASCII `ZVDOMN02` |
| `[8,40)` | 32 | Nonzero public network instance identifier |
| `[40,72)` | 32 | Nonzero SHA-256 of the exact, canonical public test asset genesis manifest |
| `[72,104)` | 32 | SHA-256 of the immutable rule bytes below |

The parser rejects every other length, magic, zero identifier and rule fingerprint. There is no trailing padding, optional field, JSON normalization or unknown-version fallback. A V2 test pool constructor also checks that descriptor.asset_genesis equals the exact provided `TestGenesis::digest()` BEFORE it creates a file. A descriptor decoder alone does not check asset issuance.

Rule bytes are exactly the following ASCII, with `\x00` and `\x02` representing single bytes, not literal backslash text; there is no terminal newline:

```text
ZEVUNE-BOUND-LAB-RULES\x00\x02;orchard=0.15.5;bundle=orchard_v2;circuit=FixedPostNu6_2;commitment=v5;actions=2..8;flags=3;fee=value_balance>=0;expiry=inclusive;anchors=preblock;block_txs<=16;commitments<=65536;height<=10000;anchors<=64;test_supply=100000
```

Define:

```text
domain_id = SHA256(ASCII("ZEVUNE-NETWORK-DOMAIN") || 0x00 || 0x02 || descriptor[0:104])
```

A change to any listed acceptance rule requires a new rule/version definition and explicit network activation, not editing the interpretation of an existing descriptor. Operational resource policies and a complete future consensus specification are separate; this fingerprint is not a complete mainnet rule specification. Unknown descriptors fail closed today.

## 2. Transaction bytes and authorization

V1 remains exactly `ZVORLAB1 || body`. V2 is `ZVORLAB2 || domain_id[32] || body`, where the body uses the exact V1 canonical field layout, fixed Orchard V2 flag `3` and upstream field/point parsers. Its headers total 98 bytes instead of 66. Complete V2 transactions are at most 28,134 bytes, exactly 32 bytes more than V1. No proof or signature is changed by encoding alone.

V2 signature digest is:

```text
legacy_digest = the existing signing_digest(bundle, context)
bound_digest = SHA256(ASCII("ZEVUNE-ORCHARD-BOUND-SIGHASH") || 0x00 || 0x02
                      || domain_id[32] || legacy_digest[32])
```

The unchanged legacy digest includes the fixed library namespace, expiry height, fee and upstream `bundle.commitment(TxVersion::V5)`. This upstream commitment covers the bundle's effects. Every spend authorization signature and binding signature MUST verify over `bound_digest`. Real proof verification remains required with the fixed patched Orchard V2 verifying key. This is NOT ZIP-244's complete transaction digest and makes no Zcash transaction interoperability claim.

The exact authorizing bytes, including proof, signatures, version and domain, are identified by SHA-256. This remains the laboratory payload ID, not a finalized non-malleable mainnet txid scheme.

`AuthorizationVerifier::new()` accepts only V1. `AuthorizationVerifier::for_domain(expected)` accepts only V2 with that expected ID. The expected ID is checked before expensive cryptographic validation and before any cache hit. The bounded cache is per verifier and stores only previously validated exact bytes, not current ledger permission. There is no default V2 acceptance or V1 fallback. Removing the V2 domain header, relabeling it or wrapping a V1 transaction does not generate new signatures.

Go's `networkdomain.DecodeEnvelope` checks framing only. It does not validate curve points, digital signatures, ZK proofs, ownership or committed state. Cross-language fixtures verify canonical encoding equivalence, not an independent cryptographic proof implementation.

## 3. State and storage binding

A V2 pool header is:

```text
"ZVOPOL02" || domain_id[32] || SHA256(legacy_library_namespace)[32]
            || initial_commitment_count[u32] || commitments[count * 32]
```

The state genesis digest is SHA-256 of the complete header and remains part of every application summary. Identical initial Merkle roots in different domains therefore have different application hashes. On reopen, the EXPECTED header is constructed from independently provided descriptor and canonical genesis; file contents do not choose the accepted domain.

Record contents keep `ZVOBLK01`. Their base/result app hashes bind the versioned genesis. Replay rechecks the proper-domain signatures/proofs, historical anchors, fees, expiry and spent/output sets. It is insufficient to recompute only record checksums. Wrong-domain or mixed-version candidates leave committed state unchanged, including when an earlier transaction in that candidate was valid.

Legacy `TestGenesis::create_pool/open_pool/wallet_history` remain V1. New `*_bound` APIs require a descriptor matching the canonical manifest. A V1 reader rejects a V2 header; a V2 reader rejects a V1 header. There is no automatic migration, rewriting, truncation or reset.

## 4. Wallet and encrypted recovery

`Wallet::create_for_domain` and `WalletStore::create_for_domain` explicitly select V2. `bind_domain_once` can bind an UNUSED legacy-mode wallet whose public address was needed to create the genesis manifest. It requires no earlier domain, sync/checkpoint or pending payment. For the durable store, successful binding is persisted before return. It is not permission to migrate an existing wallet or change networks. Retained old copies remain separate wallet copies and must not be operated concurrently.

The encrypted snapshot container and 512-byte plaintext length remain unchanged. Plaintext version 1 preserves the original encoding. Plaintext version 2 stores the nonzero domain ID at `[480,512)`; the preceding unused bytes remain zero and are checked. This field is protected by the existing authenticated encryption. Old software rejects unknown plaintext version 2 rather than interpreting it as V1. This is a versioned payload extension, not silent rewriting of existing files.

Before scanning, wallet.domain MUST match history.domain. Before proving, the prover verifier domain MUST match wallet.domain. The signed outbox is decoded and cryptographically revalidated under the domain recovered from the authenticated wallet, never under an ID inferred from the outbox. After restoring a backup, correct-domain history must be rescanned before any pending payment bytes can be retrieved. Expected genesis/checkpoint ancestry is still required. Network mismatch must not release reserved funds or overwrite a valid balance.

Amounts remain hidden in ordinary encrypted payments, but test genesis allocations/openings are PUBLIC. Addresses have not gained a production network-specific user representation. Full key derivation policy, address UX, mnemonic recovery and privacy against network metadata remain unfinished.

## 5. Activation boundary

This revision supplies working domain-aware Rust payments, pool persistence, wallet snapshots/outbox recovery, an independent Go descriptor/framing codec and adversarial tests. M11 Go consensus, IPC maximum/fingerprint and wallet CLI continue V1. They refuse new V2 transactions rather than routing them into a legacy verifier. A subsequent explicitly versioned network/IPC activation must connect the independently pinned descriptor through genesis, node startup, wallet operations and signed consensus headers before this is a V2 network product.

Do not hand-edit old logs, reinterpret old encrypted backups or raise constants to activate V2. No mainnet launch, public connectivity, real-value issuance or audited privacy guarantee is authorized by these APIs.

## Primary references

- ZIP 244, digest roles and consensus-branch binding: https://zips.z.cash/zip-0244
- Orchard 0.15.5 commitment interface: https://docs.rs/orchard/0.15.5/orchard/bundle/enum.CommitmentError.html
- Repository implementations: `src/domain.rs`, `src/wire.rs`, `src/pool.rs`, `src/wallet.rs`, `src/wallet/vault.rs`, `src/wallet/vault/store.rs`; Go: `internal/networkdomain`.

These references explain upstream interfaces; they do not constitute an external review or endorsement of Zevune's transcript.
