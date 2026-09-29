# Source and specification provenance

> 2026-09-29 按已合入 C32 源码重建的当前规范；不是找回的历史原稿，不代表协议冻结、完整交付或安全审计通过。基线 merge `ae04190a57bff9ccfbeb056e749f30a9a62c2e02`，tree `7239d12b13b74919e4583cf05b66764994f23a7f`。

## Newly reconstructed current documents

The following paths were absent from the C32 Git tree and are reconstructed from actual current implementation, not recovered copies of unpublished historical originals:

- `ARCHITECTURE.zh-CN.md`
- `PROOF_CONTRACT.md`
- `THREAT_MODEL.zh-CN.md`
- `PERFORMANCE.zh-CN.md`
- `ROADMAP.md`
- this `SOURCES.md`

Their runtime baseline is merge `ae04190a57bff9ccfbeb056e749f30a9a62c2e02`, tree `7239d12b13b74919e4583cf05b66764994f23a7f`, the same source as C32. No new protocol or privacy implementation is implied. `PROJECT_STATUS.json` is retained byte-for-byte as the historical status record; `PROJECT_COMPLETION.json.specifications` separately records the new current paths and that historical originals remain unrecovered.

## Authoritative implementation map

| Claim | Local primary source |
|---|---|
| Fixed Orchard/circuit, LAB1/LAB2 signing transcript | `integration/orchard/Cargo.toml`, `Cargo.lock`, `src/lib.rs`, `src/wire.rs` |
| Domain and exact public wire fields | `docs/protocol/GENESIS_DOMAIN_V2.md`, `signing-domain-vectors.json` |
| Exact-byte authorization cache, separate state permission | `integration/orchard/src/wire/cache.rs`, `src/pool.rs`, `docs/AUTHORIZATION_CACHE.zh-CN.md` |
| Active journal bounds and recovery | `src/pool/active.rs`, `src/pool/replay.rs`, `docs/ACTIVE_ARCHIVE_V1.zh-CN.md` |
| Local operation and authenticated sync limits | `integration/cometbft/labnet/network.go`, `rpc.go`, `sync.go`, nested `go.mod` |
| Wallet private console and persistence | `scripts/zevune_wallet.py`, `docs/LOCAL_WALLET_CONSOLE.zh-CN.md`, `WALLET_DURABILITY.zh-CN.md` |
| Frozen whole-project scope | `docs/DELIVERY_PLAN.zh-CN.md` |
| Existing measured workloads and restrictions | `reports/p2-active-ledger-validation.md`, `reports/p2-payment-resource-validation.md`, `docs/ACTIVE_COMMIT_TIMING.zh-CN.md` |
| Independent stage review and rights boundaries | `AGENTS.md`, `SECURITY.md`, `LICENSE-STATUS.md`, exact PR review threads |

Paths shortened with `src/` in this table refer to the Orchard module, not root Go. A linked file is evidence of source content, not evidence that a new candidate passed every test. Root Go, nested Go and Rust commands have separate execution scopes. Derived documentation must be updated with reviewed runtime changes, not silently treated as immutable truth.

## Upstream primary references

- Orchard pinned0.15.5: https://docs.rs/orchard/0.15.5/orchard/ and https://github.com/zcash/orchard (match the dependency lock when inspecting code).
- Zcash ZIP244: https://zips.z.cash/zip-0244 . Zevune uses the upstream Orchard bundle commitment but not the complete ZIP244 transaction-ID algorithm.
- CometBFT pinned0.38.26 source: https://github.com/cometbft/cometbft/tree/v0.38.26 . Current documentation sites may redirect older URLs; the pinned dependency source and local call path control version-specific claims.
- Python threading: https://docs.python.org/3/library/threading.html ; Tk threading: https://docs.python.org/3/library/tkinter.html#threading-model . An Event or a started identifier alone does not establish real worker exit.
- Tor SOCKS extensions: https://spec.torproject.org/socks-extensions . Used only for the selected future private transport design; not evidence of a current Zevune Tor integration or global-observer resistance.

No upstream project endorses the engineering completion, security, economics, deadlines or deployment of Zevune. Dependency advisories, actual notices/licenses and platform support must be checked again before a release; a lockfile and source hash are not a signed release or a completed license review.

## New process artifacts

`PROJECT_COMPLETION.json` and `scripts/check_project_completion.py` record and validate completion bookkeeping. They cannot certify the truth of maintainer-provided experiment facts, independently identify the reviewer, or turn local/simulated tests into four real machines or30 real days. Empty final evidence slots preserve the incomplete status. Historical source availability is not rewritten by adding these new documents.
