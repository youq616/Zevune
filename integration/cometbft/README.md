# Zevune M3: local CometBFT laboratory

Version `0.2.0-consensus-dev`. **NO FUNDS, NO PAYMENTS, NO WALLET, NO NETWORK PRIVACY.**

This optional nested module pins CometBFT v0.38.26 with committed go.mod/go.sum. The dependency-free M2 program and its ledger format are unchanged. This is a consensus integration laboratory, not a mainnet or test-asset payment network.

## What runs

Four locally generated, equal-power validators communicate over actual loopback TCP using CometBFT. The launcher uses four OS processes. RPC and P2P addresses are always numeric loopback. Public listeners, unsafe RPC, PEX, state sync, vote extensions and transaction indexing are not enabled. Internal ABCI connections expose no separate ABCI socket. All transactions are rejected, including through the CometBFT mempool and finalization path.

The adapter checks InitChain, reports durable height/hash through Info, proposes only empty blocks, rejects nonempty proposals, stages FinalizeBlock without disk writes, and persists via CommitPreview during Commit. Queries expose only committed public status and make no proof claim. Snapshots are rejected. Validator/signing state is never reset on restart. Generated private keys and network data must never be committed.

The M1 journal remains bounded to 10,000 block records/64 MiB. This laboratory stops at its storage limits; it is not a permanently running service. Do not delete signing/state files to work around a limit. Deliberately starting a new experiment requires a new independent laboratory directory.

## Automated checks

From this directory: `go mod verify`, `go test -mod=readonly ./... -count=1 -timeout=8m -v`, `go vet -mod=readonly ./...`, and `go build -mod=readonly ./cmd/zevune-devnet`. Dedicated CI checks this module on Windows/Linux, verifies formatting and dependency locks, and runs adapter race checks on Linux. Root-level go test ./... does not traverse this nested module: the original core CI is also required.

Dependencies require access to the Go module proxy or an approved internal mirror. Do not disable checksum verification. No Docker engine or Docker Hub image is needed. The pinned CI toolchain is Go 1.27.1; this records the integration environment, not a perpetual production version recommendation.

## Optional local launcher

User-by-user micro-validation is not required. The following commands document eventual usage, not a request to repeat the developer's tests. Use a NEW, SEPARATE directory, never an existing M1/M2 ledger or wallet directory. Initialization refuses any existing directory and leaves partial initialization intact for investigation. On Windows, build and run:

```powershell
go build -mod=readonly -o zevune-devnet.exe ./cmd/zevune-devnet
.\zevune-devnet.exe -action init -home "$env:LOCALAPPDATA\Zevune\consensus-lab"
.\zevune-devnet.exe -action start -home "$env:LOCALAPPDATA\Zevune\consensus-lab"
```

Ctrl+C requests shutdown of all children through their stdin lifecycle channel. The parent imposes a shutdown timeout; killing a child does not delete state. RPC ports are 28650, 28652, 28654, 28656; P2P uses adjacent odd ports. Port conflicts cause failure, not rebinding to another interface. Restart with start, not init. Do not open router/firewall ports or expose RPC.

## Scope and limitations

The four-process test checks common block/app hashes, verifies real commit signatures against the initialized validator set, rejects a transaction through RPC, checks progress with one validator down, observes a halt with two down, restores quorum, catches up a lagging validator, abruptly terminates/restarts one process, then restarts the whole network. A separate restart test requires every node to advance BEYOND the highest height recovered from all stopped journals. Missing anti-double-sign state must be rejected, not regenerated.

All processes run on a single CI host. This does not establish geographic decentralization, WAN performance, privacy, resistance to a malicious local administrator, or production Byzantine-fault coverage. The 2/4 halt check is a bounded observation, not a proof. Empty-block cadence is not payment latency or TPS. A local ledger hash alone is not a finality certificate. Four keys controlled by one owner are not four independent organizations.

The application state hash currently excludes validator/configuration history; CometBFT commits separately bind consensus headers. Genesis checksums detect accidental mismatch but are not authentication against someone who can rewrite all files. File/key handling inherits upstream behavior and local filesystem trust. No key recovery, staking economics, slashing policy, issuance or upgrade mechanism is implemented. Full security and transitive-dependency vulnerability review remain outstanding. Do not put real funds in this project.

## Primary references

- https://github.com/cometbft/cometbft/releases/tag/v0.38.26 (published 2026-08-13)
- https://github.com/cometbft/cometbft/blob/v0.38.26/abci/types/application.go
- https://github.com/cometbft/cometbft/blob/v0.38.26/node/node.go
- https://docs.cosmos.network/cometbft/latest/spec/abci/Requirements-for-the-Application

Only the consensus interface is integrated here, not a cryptographic payment backend. The six previously unpublished technical documents are not silently replaced by this laboratory README.
