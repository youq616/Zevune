# Zevune experimental genesis-bound payment profile V2

Status: implemented laboratory protocol candidate; **not a frozen mainnet protocol,
independent cryptographic review, or approval for real value**. The Orchard V2
circuit and RedPallas primitives are unchanged. This specification defines the
additional chain-identity binding around them. The root Go diagnostic protocol is
unaffected. Legacy LAB1 encoding and existing legacy storage remain readable as
legacy; they do not acquire V2 protection by being reopened.

## 1. Threat and identity

A payment must not become valid on a different deployment merely because the
same initial notes, commitment root, balances, keys, and expiry are present there.
Membership in a note tree is not by itself an explicit authorization to spend on
a particular chain. V2 signs an independently pinned genesis-manifest digest and
checks it against the local committed policy on every execution and replay.

`D = SHA256(the exact canonical ZVTGEN02 manifest bytes)` is the 32-byte payment
signing domain. All-zero domains are invalid. The manifest is an external trust
anchor pinned by the network configuration; the transaction cannot select or
replace it. An identical manifest intentionally denotes the identical domain.
Copying it to another deployment, a chain split reusing it, or quorum/key compromise
is **not** prevented by this binding. A new deployment needs a fresh nonce and a
separately distributed trusted manifest. Validator rotation, chain forks and
mainnet upgrade activation remain separate design/review work.

No new administrator key, global viewing key, mint authority, remote witness
service, or transparent-payment fallback is introduced.

## 2. Canonical public test genesis

All integers below use big-endian unsigned encoding. These are **public, valueless
laboratory allocations**, not a private issuance policy or mainnet economics.

| Offset | Bytes | V2 field |
|---:|---:|---|
| 0 | 8 | ASCII `ZVTGEN02` |
| 8 | 32 | SHA256 of UTF-8 `zevune-orchard-lab-1` |
| 40 | 8 | fixed supply `100000` |
| 48 | 2 | allocation count, from 1 through 16 |
| 50 | 32 | nonzero deployment nonce from operating-system randomness |
| 82 | 115 × count | canonical public note openings |

Each opening is raw Orchard address (43), positive value (8), rho (32), rseed (32).
Canonical upstream parsing, unique rho and commitments, checked arithmetic, and
exact total supply remain mandatory. No trailing bytes or alternative integer
encodings are accepted. Size is exactly `82 + 115*count`, at most 1922 bytes.
Generation emits V2. Legacy `ZVTGEN01` retains a 50-byte header and has no nonce;
its exact parsing rules, domain `None`, and old storage format are kept solely as
an explicit compatibility profile. Unknown magic/version is rejected.

## 3. Transaction wire encoding

V2 is `ZVORLAB2 || D || payload`, where payload is the original LAB1 payload after
its 8-byte magic. There is no implicit conversion to or fallback from V1.

| Offset | Bytes | V2 field |
|---:|---:|---|
| 0 | 8 | ASCII `ZVORLAB2` |
| 8 | 32 | nonzero signing domain D |
| 40 | 8 | expiry height |
| 48 | 8 | public fee |
| 56 | 8 | signed value balance, big-endian i64 |
| 64 | 32 | Orchard anchor |
| 96 | 1 | action count n, from 2 through 8 |
| 97 | 1 | fixed Orchard V2 default flags (3) |
| 98 | 884 × n | ordered actions |
| next | 4 | proof byte length |
| next | 2720 + 2272 × n | upstream proof bytes |
| last | 64 | binding signature |

An action contains cv_net, nullifier, randomized spend verification key, cmx,
ephemeral key (32 bytes each); recipient ciphertext (580); outgoing ciphertext
(80); spend signature (64). Field/curve parsing remains delegated to the pinned
upstream library. The signed balance is nonnegative and equals fee. Fee is at
most i64::MAX, expiry is nonzero, and repeated nullifiers/outputs are invalid.
Two-action transactions occupy 9198 bytes; maximum is 28134. Length is checked
before variable allocations. Unknown flags, versions, zero domain, truncation and
trailing bytes are rejected. LAB1 still uses its exact original 66-byte header,
9166-byte two-action size, and 28102-byte maximum.

The existing transaction identifier remains SHA256 of **all exact wire bytes**,
including proof/signatures and D. This is not ZIP-244's non-malleable transaction
ID design and is not claimed to be the final mainnet ID rule.

## 4. Signed transcript

Let `C` be the pinned upstream Orchard V2 bundle commitment computed with
`TxVersion::V5`. Signature message for V2 is SHA256 of this unambiguous sequence:

```text
UTF8("ZEVUNE-ORCHARD-LAB-SIGHASH") || 0x00 || 0x02 ||
D[32] || U16BE(len(N)) || N || U64BE(expiry) || U64BE(fee) || C[32]
N = UTF8("zevune-orchard-lab-1")
```

All spend authorization signatures and the binding signature use that message.
Legacy V1 has suffix `0x00 || 0x01` instead and has **no D field**. The V1 digest
is unchanged. A V2→V1 relabelling or editing D without resigning must fail real
signature verification, even when the proof itself remains valid. This is a new
experimental transaction context, not a claim that the complete ZIP-244 algorithm
has been implemented. Public, independent SHA-256 examples live in
`signing-domain-vectors.json`; those examples are not real proof fixtures.

The generic authorization verifier checks encoded cryptography only. Its success
cache includes all exact bytes (therefore D), is process-local and bounded, and
never authorizes a spend against current state. The separate original V1 Go/Rust
authorization-worker protocol stays V1-only and does not advertise LAB2 support.

## 5. Trusted state, durability and wallet integration

A V2 pool must require `decoded.signing_domain == pinned_manifest.digest()` before
expiry, anchor, double-spend, output, fee or authorization-cache decisions.
A legacy pool must require `None`. This equality is repeated at preflight, commit
and log replay. A successful cached proof cannot override it.

V2 journal header is `ZVOPOL02 || SHA256(N) || D || U32BE(commitment_count) ||
ordered_commitments`. Its exact bytes contribute to the genesis identity used in
the application-state digest. Thus identical note roots on two deployments have
different application states. Block record framing `ZVOBLK01` is unchanged; its
base/result hashes refer to the policy-bound state. Reopening requires the exact
externally selected header. It must not reinterpret, truncate, reset or migrate
an incompatible file.

Wallets obtain D only from fully replayed local history. The saved checkpoint's
genesis digest already commits to the new header, so no encrypted-wallet format
migration is needed. Restored balances still require a scan. A stored outbox with
a different D must be rejected before mutating the wallet or clearing reservations.
The same signed bytes must survive backup/reopen; timeout is not cancellation.

The durable Go/Rust pool IPC fingerprint changes to:

```text
ZEVUNE-POOL-IPC-2:zevune-orchard-lab-1:16:28134:genesis-bound-v2
```

Clients and workers of different IPC generations fail the handshake. Update
these components together; do not weaken the fingerprint or edit saved headers.
This is not automatic chain migration. The root diagnostic application is separate.

## 6. Activation and non-goals

New opt-in local-funding manifests use V2; opening an existing V1 manifest keeps
V1. There is no in-place upgrade, retroactive replay protection, production
activation height, signature-free conversion, or arbitrary future-version support.
To exercise V2 use a separate new valueless test network; retain old wallet/ledger
files. Current CLI address presentation does not yet identify the network, so
cross-network address UX remains unfinished.

Chain identifiers in CometBFT remain laboratory identifiers; V2 here binds the
payment domain to the full asset manifest, not to a complete future consensus
constitution. Network transport anonymity, public-network deployment, economic
rules, storage expansion, malicious-host protection and external review are not
solved by these changes. A full cloned genesis remains the same identity by design.

## 7. Verification and primary references

Required tests: unchanged legacy vector and legacy payment/replay; new fixed
vectors; identical note roots with different nonce; cross-domain rejection without
state mutation; signature relabelling/downgrade rejection; replay under a rewritten
header/checksum; encrypted outbox restore on the wrong domain; real four-node A→B→C
under V2 with duplicate rejection and restart. Tests use real pinned Orchard proofs
and signatures; synthetic context vectors are labelled separately.

References for integration semantics, not external approval of this profile:

- Zcash ZIP 244, transaction/signature commitments and consensus-branch separation:
  https://zips.z.cash/zip-0244
- CometBFT v0.38 ABCI methods, deterministic execution and next-header AppHash:
  https://docs.cosmos.network/cometbft/v0.38/spec/abci/Methods

Do not infer mainnet safety, anonymity or performance from unit-test success.
