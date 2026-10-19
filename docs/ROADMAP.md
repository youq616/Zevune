# Frozen project closure roadmap

> 2026-09-29 按已合入 C32 源码重建的当前规范；不是找回的历史原稿，不代表协议冻结、完整交付或安全审计通过。基线 merge `ae04190a57bff9ccfbeb056e749f30a9a62c2e02`，tree `7239d12b13b74919e4583cf05b66764994f23a7f`。

The authoritative product scope remains `DELIVERY_PLAN.zh-CN.md`: A multi-machine internal version, B a complete valueless testnet including privacy, and C a reviewed mainnet candidate. C does not authorize actual funding or public deployment. These are not interchangeable completion definitions. No further handoff/export/viewer milestones are added to postpone the unfinished core product.

## Delegated engineering decisions

The owner delegated routine decisions on2026-09-29. Keep the single independent chain and existing Orchard/CometBFT implementation, preserve legacy formats and the no-funds boundary, favor a full-verification wallet, and keep the original development branch. Do not rewrite cryptography, delete history, trust a server balance, add a master viewing key, switch to a rollup, or add contracts/DEX/bridges/mobile clients in this scope.

For network privacy, select a reviewed Tor v3/onion plus explicit local SOCKS transport design with no silent direct fallback. For the mainnet economic design, select a fixed, explicitly disclosed initial supply with no discretionary mint authority; use an open bonded-validator design, deterministic admission/exit and an evidence-based double-sign penalty, rather than a permanently permissioned four-key network. Supply allocation, fee/security-budget sustainability, bond/exit windows and governance activation parameters require deterministic modelling and independent protocol review before implementation. They are engineering decisions to be finalized through that process, not a request for the owner to choose every parameter, and not currently active consensus rules. Do not modify the existing public100000 test-unit genesis or advertise it as mainnet allocation.

Use phase-scoped development PRs with exact source pins, genuine tests and separate nonauthor review. Merge passing stages instead of accumulating endless versions on an unmerged PR. CI/agent review do not replace the required external specialist audit or physical observations. Paid/public resources and real funds remain excluded.

## Critical path and definition of done

| Work package | Current progress to retain | Remaining delivery |
|---|---|---|
| P1 | LAB2 network domain, recipient identity, bounded original formats | Unified reviewed protocol, upgrade/unknown-version execution and interruption drill |
| P2 | Segmented journal, full replay/archives, incremental transport, wallet compaction | Verified state-snapshot/incremental restore path, capacity/fault closure including Windows latency evidence |
| P3 | Fixed-four loopback operations and authenticated full reference replay | Real multi-machine operations, explicit peer identity, remote/dynamic validator trust, four-machine fault acceptance |
| P4 | Encrypted wallet/outbox, local console, numerous diagnostic UIs | Integrated creation/recovery/sync/payment/receipt/history product without manual transaction-file management |
| P5 | Explicit metadata/threat boundaries | Private broadcast/query/sync implementation, no fallback, reproducible traffic acceptance |
| P6 | Valueless fixed public genesis and fee conservation checks | Reviewed economic rules, validator transitions/exit/evidence handling and permissionless validation |
| P7 | Genuine growth/payment workloads and test-only stage instrumentation | End-to-end private-path distributions, stable load, at least30 days, issue23 risk resolution |
| P8 | Pinned source tools and per-stage code-agent review | Actual dependency/license inventory, trusted distributable binaries, integrated drills, external security audit |

P1/P6 rules and P5 threat review precede their state/transport implementations. P2/P3 then allow P4 online integration. P7 actual measurements feed performance changes, not the reverse. C acceptance requires the entire original scope, integration, review, records and a reviewed source merge; a module file or document alone is never marked done.

## Executable closure ledger

`../PROJECT_COMPLETION.json` is a compact maintenance index of24 closure categories, not a replacement for the detailed original acceptance clauses. `implemented` does not mean `accepted`. Existing accepted submodules remain credited in their original reports even when a larger closure category lacks its final evidence. Current empty evidence slots are not a claim that the repository has no successful tests.

```text
python scripts/check_project_completion.py --report
python scripts/check_project_completion.py --require-complete
```

`--report` exits0 for a valid incomplete ledger; `--require-complete` exits2 while any C-category acceptance record is missing. Invalid data exits1. Evidence hashes/commit identities and mandatory experiment counters are checked for consistency, not authenticated as factual experiments. Code/test/CI/reviewer bytes for every accepted category must belong to the explicit candidate_commit in the ledger. That identifies the assessed runtime source, not this bookkeeping file or an automatically inferred latest branch head. The checker never grants release, deployment or real-funds permission, even when all records are populated. Do not make CIgreen by deleting criteria, lowering the4-machine/30-day floors or converting incomplete flags to accepted.

## Provenance and current closure

PR36/C32 was merged as `ae04190a57bff9ccfbeb056e749f30a9a62c2e02` with the exact reviewed C32 tree. All27 PR workflows and an explicit full-PR nonauthor review were read; historical findings remain visible. Issue37's already implemented C9 fix is now accepted and closed. Issue23 is intentionally open. This is the close of a tools/recovery-regression stage, not the whole project.

Six previously absent document paths are now being supplied as newly reconstructed current specifications. The unpublished historical originals have not been recovered. Their historical absence, prior contradictory claims and original version records remain separate from present file availability.

No completion date, project percentage, continuous background development or thirty-day evidence is implied by this roadmap. Work not implemented or tested stays explicit; actual infrastructure and external review must exist before their acceptance claims can be made.

## 2026-10-19 current-candidate addendum

The original roadmap and its reconstructed C32 provenance above remain historical context. For the current handoff, read [the complete 2026-10-19 record](../reports/project-handoff-2026-10-19.md), [CI evidence](../reports/project-ci-2026-10-19.md), and [document index](INDEX.md).

PR38 supplied the six reconstructed documents; PR39's onion-only/auth-only SOCKS client is merged into main at `0e5fd16abfebec3cc5a3db6bb99d1e4e7335c2f6`. Actual Tor service/traffic acceptance and full P5 privacy are still missing. PR40 is an unmerged gateway candidate.

The assessed runtime is PR48 head `5540cd494ad8a3655e8aa2dd77ed7fc91817de46`, tree `0a287892cfa97347e496b25a334f919847daecca`, still open and draft. It contains PR41 and PR47 heads, but not current PR40 or PR42–46 heads. Their online-wallet preparation/recovery/submission work is separately preserved in the handoff; do not combine different source candidates into one passing product.

All 49 head-associated Actions runs were read: 47 success and two Windows retained lifecycle failures, including duplicate push/PR events. Linux/race jobs passed; Windows WAL/replay, signing-state rename and Unix-socket bind failures remain explicit. See the CI report for actual checkout commit/tree identities and skipped downstream steps. This is not full qualification.

The ledger now names the assessed runtime head rather than stale C32. All 24 statuses and evidence lists remain unchanged: 3 implemented, 9 in_progress, 6 not_implemented, 6 evidence_missing, zero accepted. The six specifications' original reconstruction baseline and unrecovered historical-original flags are preserved; PROJECT_STATUS.json is unchanged.

First close the Windows lifecycle blocker and get exact-candidate independent nonauthor review; then reconcile draft dependency branches and integrate P4/P5 without changing the frozen scope. Four real machines, actual privacy-path measurements, 30 continuous days, economic/validator implementation, license/distribution work and specialist security review remain required. Issue23 is open; Issue37 remains closed. No runtime edit, merge, deployment or real-funds authorization is made here.
