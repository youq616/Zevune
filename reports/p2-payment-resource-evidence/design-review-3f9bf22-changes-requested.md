# P2 payment-resource frozen-design independent review

- Reviewer/task: `/root/p2_resource_review` (separate task; did not author the design or implementation).
- Review date: 2026-09-17.
- Repository: `youq616/Zevune`.
- Base commit observed locally: `8324ec8bd153d9502e3e6761d25bfe281a5f3b44`.
- Base tree observed locally: `38c3caff84bcd6ca626bd5b6d53212d9e4f8e2b2`.
- Candidate: uncommitted design only, `docs/PAYMENT_RESOURCE_BASELINE.zh-CN.md`.
- Exact reviewed design SHA-256: `3f9bf22a77dab4095cb52ed20aaba9a1e072ab78ad435dbe8dfe96d2f0a4fee2`.
- Verdict: **CHANGES_REQUESTED — one design-freeze blocker concerning incomplete-run evidence preservation.**

## Scope and work actually performed

Read the exact design and verified its file hash and repository base/tree. Read AGENTS.md, docs/STAGE_REVIEW.zh-CN.md, the P2 delivery plan, the existing active-ledger design and normal-worker growth test, Go funded-driver/client process handling, the genuine Rust funded-scenario, wallet_history, Wallet::sync/payment_selection/build_payment, and WalletStore sync/backup/restore/record-accounting paths. Independently consulted the official Linux /proc and Microsoft process-memory-counter definitions. No repository file or candidate code was changed. No Go/Rust/native CI test was run; those toolchains are not available locally. This is a design review, not an implementation acceptance or external security audit.

## Blocking finding D1 — medium, evidence integrity

The design requires per-payment timings, completed observations and the failure stage to survive an incomplete run. However, the specified wire/file protocol exposes detailed `timings` only in `result.json`, which is written after all checks and process closure with `complete=true`. The nine event files expose checkpoint `elapsed_ms`, but not the operation currently executing or the accumulated per-payment timing records.

A concrete failure is payment 17 timing out during preparation after event `payment_16` was accepted. A Go test timeout, unexpected process exit, or stalled operation can prevent the normal final-result write. Under the specified protocol, the supervisor has the event-16 sample, but cannot reliably distinguish prepare, worker validation/commit, independent scenario apply, or wallet sync for the next payment. The previous detailed payment timings can also remain only in the Go process and disappear. A final-only cleanup/defer is insufficient for hard termination. This conflicts with the explicit requirement to retain unsuccessful-run evidence.

Required correction before design freeze: define a durable, bounded progress record independent of the nine memory-sampling events. For example, an atomically replaced `progress.json` or a strict structured progress stream consumed and persisted by the supervisor should record, before each potentially blocking phase, a fixed operation identifier, payment index, last committed counts and `started` state; after the operation it should retain duration and completion/failure state plus all completed timing records. The supervisor must copy the latest validated progress and already completed samples into its failure artifact on timeout, process failure, invalid protocol or nonzero exit. Missing, invalid or unsavable required progress must not become a successful result. A `started` record left without completion should be reported as interrupted/incomplete, not assigned an invented duration or success.

This correction does not add a tenth resource handshake, change the fixed 32+1 load, or relax a time/memory budget. The exact field representation may remain an implementation choice if the before/after persistence and failure-artifact contract are explicit. Do not upload wallet files, transaction bytes, passwords, command lines or environment content as fallback diagnostics.

## Other reviewed areas

1. **Load and accounting are coherent.** At even height n, both balances are `50000 - 500*n`; at 32 they are 34000/34000, and an A-to-B payment at 33 yields 32000/35000. Two actions per accepted payment produce `commitments=2+2*n`, `nullifiers=2*n` and `fees=1000*n`. The text correctly avoids equating padded action/nullifier counts with real spend inputs.
2. **Wallet-record table is coherent with the current path.** Creation plus genesis sync accounts for records 2/2. Every committed new height adds one saved sync per wallet; the sender additionally persists its pending payment. At even n, each has `2+3*n/2` records, hence 50/50 at 32. Preparing payment 33 yields 51/50; final new-height sync yields 52/51. Reopening an unchanged checkpoint/outbox must not append an extra record. Implementation and CI must assert this rather than only repeat the expected table.
3. **Recovery order meets both separate requirements.** The design first restores/replays the 32-payment state, then builds payment 33 from the restored wallet, then separately backs up/reopens that pending outbox and requires exact bytes before submission. This proves more than recovering a transaction constructed before the initial wallet restoration. The intended complete-state, capacity, balance, availability and pending-clear checks are appropriate.
4. **Nine memory events are coherent.** Heights 0/8/16/24/32/32/32/32/33 and worker generations 1 for the first five, 2 for the remaining four cover both worker lifetimes. `payment_32` and `complete_33` are appropriate last observations before worker closure. `complete_33` covers the scenario's final observed workload. Sampling after all relevant calls but before process closure avoids losing a terminated process's counters. The explicitly excluded final cleanup window must stay outside reported workload claims.
5. **Memory semantics and budgets are honestly scoped.** The 1073741824-byte threshold is an OS-reported resident/working-set lifecycle-high-water acceptance gate for each observed process, not a hard allocation cap, private-commit budget, phase-local peak, pure heap measurement or system-wide limit. The current design correctly states that attainability is not yet measured. Worker generation, process creation identity and parent verification must be enforced in code. Current RSS snapshots alone cannot replace the high-water counter.
6. **Time boundaries are coherent.** The 60-second startup target is accurately distinguished from the older growth test's 5-minute startup budget; 60-second worker requests, 90-second scenario responses, 20-minute Go total, 15-second handshakes and at most 30 seconds additional cleanup are explicit. Operation durations must include failed/incomplete observations through the D1 correction. No budget may be quietly increased after failure.
7. **Authorization and temperature claims are properly limited.** The text acknowledges the PoolStore authorization cache, distinguishes new verifiers on new worker/open from repeated cached history verification, and does not call a same-process wallet recovery a fresh wallet process or cold-disk measurement. It keeps complete rule replay and genuine proof authorization.
8. **Scope exclusions are appropriate.** The modest baseline does not demonstrate cache eviction, anchor exhaustion, 65536 commitments, 256 wallet saves, active rotation/capacity, TPS, network finality or production readiness. No protocol/format/production API expansion is justified by this measurement-only stage.

## Source references for metric definitions

- Linux kernel /proc documentation: https://docs.kernel.org/filesystems/proc.html . VmHWM is resident high-water; VmRSS counts resident portions and its scalable accounting can be approximate.
- Microsoft PROCESS_MEMORY_COUNTERS: https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters . WorkingSetSize and PeakWorkingSetSize describe current and peak working sets.
- Microsoft PROCESS_MEMORY_COUNTERS_EX: https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex . PrivateUsage/PagefileUsage represent private commit and must not be relabeled RSS.

## Disposition

Design freeze remains pending D1. The remaining reviewed design areas have no identified blocker at this exact file hash. After a corrected design is provided, re-review the new file hash before implementation acceptance. Final runtime acceptance will separately require exact base/head/tree, relevant callers and tests, native cross-platform evidence, and another independent review of the implemented candidate; this design review does not supply those results.
