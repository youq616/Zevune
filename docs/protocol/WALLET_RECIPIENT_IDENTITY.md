# P1: network-aware local wallet recipients

Status: implemented **NO-FUNDS laboratory presentation and pre-sign checks**.
Not a mainnet address standard, new cryptographic protocol, complete P1 upgrade
system, public network, or evidence of network anonymity.

## Identity and exact encoding

Continue using the already implemented LAB2 domain:
`D = SHA256(exact independently pinned ZVTGEN02 manifest bytes)`.
A recipient cannot choose the domain accepted by the wallet or ledger. For legacy
LAB1 the expected domain is explicitly absent, not an all-zero placeholder.

| Format | Exact ASCII text | Length |
|---|---|---:|
| Legacy | `zvlab:HEX(receiver[43]):HEX(checksum[4])` | 101 |
| Bound | `zvlab2:HEX(D[32]):HEX(receiver[43]):HEX(checksum[8])` | 175 |

HEX is lowercase with exactly two characters per byte. No whitespace, Unicode,
alternative prefix, extra fields, zero D, truncation or trailing bytes is accepted.
Rust parses the raw receiver with the existing upstream Orchard Address parser.
Python only checks text, checksum and public manifest framing, not curve validity.

The old checksum is unchanged: the first four bytes of
`SHA256(UTF8("ZEVUNE-LOCAL-ADDRESS") || 0x00 || 0x01 || receiver)`.
The bound checksum is the first eight bytes of
`SHA256(UTF8("ZEVUNE-LOCAL-ADDRESS") || 0x00 || 0x02 || D || receiver)`.
These are typo-detection checksums, **not signatures or payee authentication**.
An attacker can relabel a receiver and recompute a checksum. Confirm the intended
payee through a trusted channel; do not repair a mismatched address by relabelling.
Completely cloned genesis manifests intentionally share D, so this presentation
does not distinguish those deployments or forks.

## Actual checked flow

1. The frontend reads a bounded public genesis and checks its independent pin,
   profile and framing; it shows the public identity before requesting intent.
2. A wrong-domain or legacy recipient for LAB2 fails before the password prompt
   and before the backend is invoked. No automatic conversion is provided.
3. The backend independently reads and fully decodes the pinned TestGenesis and
   checks the recipient against its signing domain **before opening the wallet,
   writing a checkpoint, reserving notes or constructing proving parameters**.
4. The same decoded manifest opens the journal; its fully validated history is
   scanned and checked against the wallet's existing authenticated checkpoint.
   A restored wallet cannot silently change network by being rescanned.
5. `WalletStore::prepare_payment_to` also checks the recipient against the domain
   of the wallet's scanned history, then delegates to the existing real prover and
   persist-before-return path. Raw Address APIs remain low-level primitives and do
   not claim to protect an address label removed by their caller.
6. The exact signed transaction and reservation are saved before export. `pending`
   recovers the same bytes after rescan; failure or timeout is still not cancellation.

This check prevents accidental network/profile mismatch. It does not verify a
remote server's newest tip, prove that a recipient will monitor the network, or
change what cryptography protects against endpoint compromise.

## Display and IPC compatibility

New `network-address` command uses existing bounded `ZVWCLI01` framing and opcode 8
with exactly five fields: wallet path, journal path, genesis path, independent
genesis SHA-256, canonical u32 address index. Password/optional wallet receipt keep
their existing private-stdin representation. This operation synchronizes validated
local history and may persist a new wallet checkpoint; it is not a read-only file
inspector. Creating keys or restoring a backup alone does not establish identity.

`network-address`, `status`, `prepare`, `pending` and `init-test-ledger` return
`payment_profile`, `signing_domain` (null for LAB1), and `genesis_sha256`. The old
`address` and create-before-genesis paths explicitly return `address_network_bound:
false`. Init-test-ledger emits a new bound receiving address for its new LAB2 network.
The frontend checks response identity against its independent selection; a reply
mismatch is an uncertain operation result, not proof that no state was saved.

No new consensus activation, transaction version, curve, signature, fee rule,
issuance path, worker permission, encrypted-wallet format or journal migration is
introduced. Update frontend and backend together. Unknown opcode 8 fails on old
backends; there is no downgrade/retry fallback. Existing LAB1 payment and replay
regressions remain mandatory. Keep old wallets and nodes unchanged.

## Acceptance matrix

- Both canonical formats round-trip; invalid text, checksum, bounds and zero D fail.
- Wrong-domain checks cover frontend, direct backend bypass and checked wallet API.
- A direct wrong-domain backend request returns the domain error even with a
  nonexistent wallet file, proving the check precedes wallet file access.
- Rejected preflight leaves wallet/ledger bytes, receipt and outbox unchanged.
- A matching recipient uses a real proof/signature, commits to the real local pool,
  receives the correct amount and change, and is rejected on duplicate spending.
- Backup/reopen restores the same pending bytes; network display requires rescan.
- Python and Rust process interoperability checks the same actual address and bytes.
- Existing root Go, consensus, crypto and local operator regressions still run.

Passing tests must be recorded against the actual source commit. Unit-test loops
and subcases are not counted as independent top-level tests. Multi-node regression
and local console tests are distinct; do not call them a completed online wallet.
