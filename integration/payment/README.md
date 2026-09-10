# Zevune M5 · integrated local payment laboratory

**0.3.0-dev. Valueless local test assets only. Not mainnet, not audited, not network-anonymous.**

This module connects actual Orchard proof generation/verification and encrypted-seed wallets to four CometBFT validator processes through private worker pipes. Each validator runs its own Rust worker, verifying public transaction bytes and independently persisting a public ledger. The old M2 diagnostic, M3 empty-block network and M4 cryptography tests remain separate and unchanged. Check the dedicated M5 workflow for the exact source commit before describing the integration as verified.

## Components and security boundary

`zevune-crypto`: local wallet creation, encrypted backup/restore, address, proof construction and rescan; or public-state-only worker mode. Worker mode accepts no password, seed, viewing key, recipient note plaintext or membership witness request. Proofs are generated inside the user's local wallet process. Public proving/verifying parameters are not a master spending or viewing key.

`zevune-paynet`: initialize a NEW local network, launch four separate node processes, status, authenticated public-history export and test-transaction submission. Listeners are numeric 127.0.0.1 only, without public ABCI sockets or unsafe RPC. The supervisor stops the cluster on child exit and never resets validator signing state.

A receipt requires a real CometBFT checkpoint with >2/3 of the original local genesis voting power. The header at H+1 authenticates the application state at H. Exact ordered history bytes are committed into an accumulator included in the app hash; balances alone would not authenticate exported ciphertexts. The wallet independently replays that public history and proofs against its original payment genesis. Original genesis files, the binaries, exported files and local filesystem remain trust boundaries: this is not an authenticated dynamic-validator Internet light wallet, and exports do not carry a portable standalone finality certificate.

The Rust verifier individually checks authorization signatures, binding signature and the actual proof. There is no accepting stub, skip-verification mode, caller-selected circuit or remote proving service. The circuit is the fixed Orchard V2 variant used in M4, not a declaration of present Zcash consensus activation rules.

## Fixed test economics, not proposed mainnet economics

Initialization generates a genuine output-only proof distributing exactly 1000000 test units to one supplied local address. Ordinary payments use a 1000-unit fee, which is burned. Initial allocation is not private from the initializer. The running network cannot mint, accept an additional genesis, bridge external tokens or credit an administrator. No exchange rate, reward, staking or token sale is implemented.

## Limits and unresolved production requirements

At most 8 actions per transaction, 32768 transaction bytes, 8 transactions per block, 4096 blocks, 32768 notes and 8 MiB of raw transaction history. Journal size is bounded to 64 MiB; export to 32 MiB. At a limit the laboratory refuses further progress rather than deleting state. It is not suitable for long-running unattended use. Four local validators controlled by one owner are not decentralized independent operators.

Public data still includes transaction existence/size, fees, expiration height, timing/height, ciphertext and nullifiers. There is no IP anonymity, metadata traffic protection, independent side-channel assessment or guarantee that a transaction counterparty cannot disclose its own records. The wallet protects the seed at rest with Argon2id and XChaCha20Poly1305, but does not protect an unlocked or compromised machine, weak passwords, malicious binaries or all memory copies. Zeroizing selected buffers is not a secure-erasure guarantee. Filesystem checks are not a sandbox against a malicious local administrator.

Journals are locked and synced. A torn/corrupted journal is rejected and retained, not automatically truncated or silently replaced. This does not establish power-loss safety across every disk/filesystem. Checkpointing, authenticated state snapshots, pruning, robust recovery tooling, sustained performance, stronger local-wallet UX, network privacy, dependency/side-channel review, mainnet economics and external protocol audit remain open. The production release is blocked until these conditions are addressed.

## Developer acceptance, no repeated user micro-testing

Pinned tools: Go 1.27.1 for the integration CI; Rust 1.98.1 with host linker/MSVC build tools on Windows. Dependency downloads require Go/Cargo registry access, not Docker Hub. Do not disable checksum verification. From the repository root, `pwsh -File scripts/Build-PaymentLab.ps1` builds both binaries into bin. It does not install tools, overwrite a network directory or create assets. Other CI suites run M2/M3/M4 separately.

M5 acceptance uses genuine CLI wallets, encrypted backup restoration, proof-bearing genesis, four validator processes each with its own crypto worker, two consecutive transfers, tamper/replay/extra-genesis rejection, authenticated exact-history export, state convergence and abrupt/all-node restarts. No successful response is fabricated by a mock consensus/proof service. Root-level go test ./... does not traverse nested modules; a skipped M5 test outside its dedicated job is not an M5 pass.

## Optional eventual local use

These are usage instructions, not a request that the owner repeat developer tests. Use a new directory that is separate from all old M1/M2/M3 data. Keep wallet files out of the repository and back them up encrypted. Do not upload wallet files, passwords or validator keys.

```powershell
# After a successful build, create an independent personal directory.
$work = Join-Path $env:LOCALAPPDATA 'Zevune/payment-demo'
New-Item -ItemType Directory -Path $work -ErrorAction Stop
# Hidden password prompt; at least 12 UTF-8 bytes. Record it securely.
.\bin\zevune-crypto.exe wallet-new "$work/alice.wallet"
# Obtain a zvtest address from the preceding output, then use that actual value.
.\bin\zevune-crypto.exe genesis YOUR_ZVTEST_ADDRESS "$work/genesis.bin"
.\bin\zevune-paynet.exe -action init -home "$work/network" -crypto "$PWD/bin/zevune-crypto.exe" -genesis "$work/genesis.bin"
.\scripts\Start-PaymentLab.ps1 -NetworkHome "$work/network"
```

A second terminal can use Wallet-PaymentLab.ps1 with New, Address, Backup, Restore, Balance or Send. Balance/Send take Wallet and NetworkHome; Send additionally takes Recipient and Units. Passwords are entered directly in a hidden Rust prompt, never command-line parameters. `--password-stdin` is an explicit automation mode used only with synthetic test credentials in CI. Backup and Restore create a non-overwriting encrypted copy; neither is a mnemonic or lost-password recovery service.

The wrapper authenticates a public-history checkpoint before local preparation, retains the public transaction file, and waits for signed-checkpoint confirmation. A timeout has an unknown submission outcome: preserve the transaction and inspect history before preparing a replacement. Startup/CLI parameter generation, proof time, network confirmation and recipient scan are separate costs. No p95, TPS or sub-5-second end-to-end target is asserted by this laboratory.

Protocol draft: ../../docs/PAYMENT_LAB_SPEC.zh-CN.md. It describes this implementation, not an independent security approval. Historic unpublished documents have not been relabeled as completed.
