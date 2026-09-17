# PR #11 independent code review — exact 8f0de0d candidate

- Reviewer/task: `/root/p2_resource_review`, independent of all candidate authors; this task wrote no candidate code.
- Review date: 2026-09-17.
- Repository/PR: `youq616/Zevune`, https://github.com/youq616/Zevune/pull/11 .
- Exact base: `8324ec8bd153d9502e3e6761d25bfe281a5f3b44`.
- Exact head: `8f0de0df649a0bae719b7ced789d8fc0857ca475`.
- Exact tree: `e861d8af54cc33735b82e796a20e301e10bea137`.
- Observed parent of head: the stated base; local checkout was clean.
- Verdict: **CHANGES_REQUESTED. One medium-severity blocker in cross-component success-evidence validation.**

## Identity, independence and actual checks

Verified local HEAD/tree/parent, clean status, all seven changed paths, and GitHub PR metadata reporting the same base and head. Verified the frozen design SHA-256 `f8fb0f009423f26afbfb84ad2293b13dbe9581032c31ba0bfc379d224a91789f`. The exact Rust and Go files are byte-identical to the previously independently read component candidates:

- `integration/orchard/src/bin/zevune-funded-scenario.rs`: Git blob `5c666fa21d7a8023c52e9e1d5d4f18ab9890de70`, SHA-256 `2b568ca93dc29d6ecc1edcac17973fc00d840e76fc38c5900a4e15db09dfceaa`.
- `internal/poolbridge/payment_resource_e2e_test.go`: Git blob `ec7b3c322560edf62169506eb0d6a2779af33ec9`, SHA-256 `502688e6c43df3521f0d364391b1cfd0bddf35d4bffaa152db73352c76826da7`.

Read the genuine Rust scenario changes, real wallet/pool/history/receipt/authorization callers, the complete Go test, production client and worker pending-slot handling, and the final Python event/progress/result contract and relevant semantic tests. Read the new workflow for cross-component invocation and toolchain/tag alignment. Detailed OS probe, supervisor cleanup and workflow review is independently assigned to `/root/p2_resource_ci_review`; this report does not replace that review. `git diff --check` passed for the exact base/head. Executed the two small Python evidence-validator reproductions below against this exact checkout. Both were accepted unexpectedly. No repository file was modified.

The author reported 121 passing local Python tests. This reviewer did not rerun that entire suite or count it as independent native payment evidence. Go/Rust toolchains are unavailable locally. No native compilation, gofmt/rustfmt, Clippy, real payment execution, Windows execution, memory observation or completed CI job result was consumed as a pass in this review. The PR's native workflows had been triggered and remain a separate acceptance gate.

## Blocker R1 — medium: recovery operation order can contradict the accepted evidence

Location: `scripts/check_payment_resources.py`, `checked_progress` and `checked_result`, with coverage gaps in the two resource semantic-test files.

The frozen test's central claim is that the 32-payment state is recovered before payment 33 is newly constructed, and that its pending outbox is then separately restored before submission. The actual Go source enforces this order correctly. However, the Python acceptance contract only verifies relative order of CORE_OPERATIONS and the multiset/Counter of EXTRA_OPERATIONS. Its per-record progress checks enforce individual operation/payment/height fields and matched started/completed pairs, but not the full global sequence or an already-completed prefix. Consequently, a successful result can contain all 362 records and correctly matching final timings while reporting an impossible or contract-violating recovery chronology.

Two independent runtime reproductions using only synthetic evidence fixtures (not payments/proof fixtures) both reached checked_result without an exception:

1. Move the complete `wallet_recover` started/completed pair after `prepare(33)` and `outbox_restore(33)`, immediately before `candidate(33)`. Resequence all records and make final timings match them. The validator accepts this as complete recovery, despite the claimed new payment having been constructed before wallet restoration.
2. Move the `worker_reopen` pair at committed height 32 to the very beginning, before `scenario_start` at height 0. Resequence and match final timings. The validator again accepts the chronologically impossible history.

Exact local reproduction command (no repository mutations):

```python
import copy, sys
sys.path.insert(0, 'scripts/tests')
import test_payment_resources as fixtures
import test_payment_resources_evidence as checks
resource = fixtures.resource

records = copy.deepcopy(fixtures.progress_sequence())
restore = [r for r in records if r['operation'] == 'wallet_recover']
records = [r for r in records if r['operation'] != 'wallet_recover']
insert = next(i for i, r in enumerate(records)
              if r['operation'] == 'candidate' and r['payment_index'] == 33)
records[insert:insert] = restore
records = checks.resequence(records)
checks.validate_progress(records)
resource.checked_result(checks.result_for(records),
                        [fixtures.event(i) for i in range(1, 10)], records)
print('ACCEPTED: wallet recovery after prepare33 and outbox restore')

records = copy.deepcopy(fixtures.progress_sequence())
reopen = [r for r in records if r['operation'] == 'worker_reopen']
records = [r for r in records if r['operation'] != 'worker_reopen']
records[0:0] = reopen
records = checks.resequence(records)
checks.validate_progress(records)
resource.checked_result(checks.result_for(records),
                        [fixtures.event(i) for i in range(1, 10)], records)
print('ACCEPTED: worker reopen at height32 before scenario start at height0')
```

The issue does not bypass Orchard authorization or corrupt the real runtime state; Rust and Go payment execution order is correct at this head. It is nevertheless a blocker for this stage's explicit strict success-evidence contract: matching counts cannot attest the required post-recovery order, and the current malformed-sequence tests do not catch the gap.

Required fix: validate the complete fixed 181-operation order (including recovery, duplicate checks, disk checks, closes and finish), with its payment/committed-height scopes. Prefer rejecting each progress record at the earliest deviation from the expected 362-record started/completed prefix, and independently require that the final operation list equals the complete sequence. Preserve incomplete-operation/no-invented-duration semantics. Add meaningful negative semantic cases for both reorderings above and for recovery/outbox/close placement errors. Do not fix this by changing the Rust/Go workload, reducing the target, relabeling the malformed order as valid or relaxing a budget. Re-run relevant Python tests and request review of the new exact candidate identity.

The other independent reviewer `/root/p2_resource_ci_review` separately reproduced both accepted reorderings and agreed that this is a medium-severity blocker. Its original report will carry its own scope and conclusions; this note does not substitute for that report.

## Correct implementation paths observed at this head

- The seven-path change set adds a design, resource test, supervisor, two semantic-test files and one workflow, and modifies only the explicit laboratory scenario bin in existing Rust runtime code. Production Client/PoolStore/Wallet APIs, cryptographic verification, transaction/journal codecs, limits and dependency locks are unchanged.
- The resource mode creates two encrypted wallets with the fixed test supply split 50000/50000, derives each sender from the committed height, uses genuine prepare_payment_to and checks the actual two-action LAB2 envelope. No accepting double, prebuilt journal, direct state mutation or capacity override was introduced.
- The Rust apply path compares the incoming single transaction with the genuine saved pending bytes, requires sequential height and the correct recovery flags, and calls unchanged PoolStore prepare/commit. Full history uses the original authenticated replay/scanning APIs. New PoolStore open constructs a fresh verifier; subsequent history calls may use its existing 64-item authorization cache.
- Rust wallet records, balances and pending availability are checked against the fixed schedule. Go separately checks complete Summary, decoded status shape, expected balances/records, actual file sizes, and stable observations around rejected/candidate operations. At 32 commits: 66 commitments, 64 nullifiers, fees 32000, wallets 50/50 records and balances 34000/34000. Pending33: records 51/50. Final33: 68/66, fees 33000, records 52/51, balances 32000/35000 and no pending payment. Padding action counts are not called real input counts.
- Go closes and physically checks the first worker ledger at 32; a new worker fully replays and reproduces exact Summary/capacity; the scenario opens its independent ledger and restores both receipt-bound wallets before the new payment33 request. It then separately restores the same pending bytes and submits that exact transaction. This source order must be enforced by the corrected evidence contract.
- Broken signatures and pre-expiry duplicates reject, selection retains a genuine payment exactly once, and committed state/capacity/disk remain unchanged before Commit. While the valid finalization33 is pending, a wrong tag and other requests cannot replace it; the original tag must still commit. A differing Finalize can reject as stale before proof checking while the slot exists; independent Check/Preview already establish the spent-payment rejection condition.
- Complete physical inspections occur only after worker Close, avoiding the Windows-exclusive genesis read conflict. Inspections check the actual header, segment count/names, whole frames, canonical rotation, all submitted transaction bytes, checksums, contiguous heights and both predecessor/result AppHashes, logical bytes and final tail. The real worker and scenario replay remain the authorization verifiers.
- The intended complete Go path has 181 measured operations, 362 started/completed progress records and nine events; the source event heights and generation mapping are coherent. Exactly two worker process generations and one combined scenario process are sampled; these are source/code observations, not actual benchmark results.
- New progress publication preserves incomplete operations rather than inventing successful duration. Go ack validation is canonical and rejects duplicate/unknown/wrong-case/wrong-type keys and extra data. Single scenario response and worker request/startup budgets remain distinct from composite measure durations.
- The final supervisor contains explicit `unfinished_operation`, last recorded confirmed count and `commit_outcome_uncertain` handling. This resolves the earlier warning that an interrupted worker_commit can have reached disk or received an ACK before a later observation fails; the old count alone is not proof of non-commit. Full ordering validation under R1 is still needed before such records can be called a valid fixed sequence.

## Limits and disposition

No additional blocker was identified in the reviewed Rust/Go runtime-and-test paths. This is not a specialist external security audit and does not prove Windows/Linux execution, memory budget attainability, production durability, cold-disk behavior, activity-segment rotation, cache/anchor/capacity limits, network finality/TPS, privacy performance or whole-P2 completion. Initial-checkpoint hard-crash cleanup of unregistered children remains the explicitly stated limited failure-path boundary; registered-process cleanup and actual resource metrics require the parallel review and native evidence.

Do not mark this exact head accepted or merge it on the basis of component pre-reviews or passing Python tests. R1 must be corrected, the changed exact candidate independently re-reviewed, and the required genuine native CI and evidence gates completed. Original source/review identities and failed observations should remain preserved.
