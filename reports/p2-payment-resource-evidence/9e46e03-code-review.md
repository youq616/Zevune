# PR #11 independent code re-review — exact C3 / 9e46e03

- Reviewer/task: `/root/p2_resource_review`; independent of candidate authorship and implementation. This task wrote no candidate code.
- Review date: 2026-09-17.
- Repository/PR: `youq616/Zevune`, https://github.com/youq616/Zevune/pull/11 .
- Exact base: `8324ec8bd153d9502e3e6761d25bfe281a5f3b44`.
- Exact candidate head: `9e46e03165250c6c51fa7031526d8de1bbdf27d6`.
- Exact candidate tree: `072da4de0b426e619c80b504dedf019a0808201b`.
- Candidate parent: `b6df89561eb6f2a75ed6fdc630e38d366d299f44` (the evidence-order correction following C1).
- Verdict: **PASS for the independently reviewed code/design/cross-component scope. C1 blocker R1 is closed; no remaining code-review blocker identified. Native CI and stage acceptance are separate and still required.**

## Identity, scope and retained history

Verified local checkout clean at this exact head/tree before execution and again after review checks. GitHub PR metadata independently reported the same base/head and an open, unmerged PR. Reviewed the complete C1-to-C3 diff and ran git diff --check against the stated base/head; it passed. No repository or candidate file was modified.

C1 was `8f0de0df649a0bae719b7ced789d8fc0857ca475`, tree `e861d8af54cc33735b82e796a20e301e10bea137`. Its original CHANGES_REQUESTED report remains unchanged at `8f0de0d-code-review.md`, SHA-256 `348a1f8523b4f6eadfddad00802c350da67eb000ee188fb931d172397fe7be71`. This review does not rewrite that earlier finding or retrospectively accept C1.

Only three files differ from C1: `scripts/check_payment_resources.py`, `scripts/tests/test_payment_resources.py`, and `scripts/tests/test_payment_resources_evidence.py`. Their exact C3 SHA-256 values are:

- Supervisor: `0eb6d68612bc4ba2fc9b5d396dc2663494450703b8fa56361e3c2985f03768ca`.
- Resource tests: `fdc03d1ea09e782e90aea3a86511dd6cc0eb049515217acb5bf6b1fb775cff15`.
- Evidence tests: `6da831e50633d4e4782efc5c1c7d41168c2d0825045abfbff6d107b4220da23e`.

Explicit git comparison proved no C1-to-C3 difference in the previously read Rust scenario, Go real end-to-end test, workflow or frozen design. Their scope is therefore carried from the independent source reading after checking the unchanged bytes, not merely from an author claim:

- Rust scenario blob `5c666fa21d7a8023c52e9e1d5d4f18ab9890de70`, SHA-256 `2b568ca93dc29d6ecc1edcac17973fc00d840e76fc38c5900a4e15db09dfceaa`.
- Go end-to-end test blob `ec7b3c322560edf62169506eb0d6a2779af33ec9`, SHA-256 `502688e6c43df3521f0d364391b1cfd0bddf35d4bffaa152db73352c76826da7`.
- Frozen design SHA-256 `f8fb0f009423f26afbfb84ad2293b13dbe9581032c31ba0bfc379d224a91789f`.

The reviewed scope includes genuine Rust payment/state/history/receipt paths, unchanged production interfaces and limits, complete Go execution and recovery order, and the final Python progress/result contract. Detailed OS probe, cleanup and workflow review is independently assigned to `/root/p2_resource_ci_review`; actual CI observations are assigned separately. This report does not fabricate or replace those agents' original conclusions.

## R1 disposition — closed, previously medium and blocking

C1 incorrectly validated recovery operations by a multiset/Counter, allowing complete evidence whose wallet recovery came after payment33 preparation or whose height32 worker reopen appeared before height0 scenario startup.

The correction removes the multiset acceptance model and derives the complete ordered 181-operation schedule, including initial setup, all 33 five-operation payment cycles, fixed duplicate-check points, the first worker close/physical inspection/reopen/wallet recovery before preparing33, its later outbox restore before candidate33, and final close/physical inspection/finish. Every schedule item includes its exact payment index and committed counts before and after the operation. This matches the manually traced unchanged Go control flow.

checked_progress now binds each sequence number to the corresponding started/completed status, operation, payment and committed count. It rejects record363 and later, wrong order, changed counts and wrong pairing. A completed record also independently revalidates the immediately preceding start record against that exact position. checked_result requires all 362 records and revalidates their complete sequence, then still requires exact final-state/check fields and equality of final timings with completed progress. It does not merely trust that a caller previously validated the list.

Valid incomplete prefixes remain valid observations and never become completed results. started records do not acquire an invented duration. Collector validation still occurs before copying a record into saved evidence, so the first bad reordered record cannot overwrite or falsely extend the last valid prefix. Incomplete worker_commit remains explicitly uncertain; its started count alone cannot prove no later durable commit.

The original two reviewer counterexamples now fail both incremental-prefix and direct final validation with `unexpected_progress_step`. Broader independent permutation and prefix checks described below also pass. No relaxation of load, budget, real authorization, operation order or evidence requirements was used to close R1.

## C3 Windows fixture correction

The C3-only change after the order fix is scoped to the synthetic cleanup-deadline test. Its context-managed mocks now create absent os.killpg and signal.SIGKILL attributes when the test runs on Windows, use the fixed synthetic signal value9 within that context and keep all prior deadline, wait-call and kill-call assertions. No runtime cleanup code, platform skip, response deadline, memory gate or actual process-signaling behavior changed.

Independently simulated the specific missing-attribute condition on Linux by temporarily removing both module attributes, running only that synthetic fixture, and confirming success and absence of the temporary mock attributes after its context exited. The outer simulation then restored Linux's original attributes. No real signal was sent and no Windows process was executed; this proves that fixture portability case only. Genuine Windows CI remains required.

## Checks actually executed by this reviewer on exact C3

1. Git identity/clean-state checks, complete C1-to-C3 diff reading, unchanged-file comparisons for Rust/Go/workflow/design, and base-to-C3 git diff --check: passed.
2. The original C1 wallet_recover-after-prepare33/outbox counterexample: rejected by both prefix and final validation with `unexpected_progress_step`.
3. The original C1 worker_reopen32-before-scenario_start0 counterexample: rejected by both validation layers with `unexpected_progress_step`.
4. Independently swapped every pair of neighboring whole operations in the 181-operation fixture, preserving both records per operation, all values/durations and a resequenced matching final result: all 180 reordered full sequences were rejected by both prefix and final validation.
5. Independently enumerated every proper prefix length0 through361 of the correct 362-record sequence: all 362 prefixes were accepted as valid partial observations without mutating their records; odd-length prefixes retained their exact started record without duration; even-length prefixes had no pending operation; every prefix was rejected as a complete result. The complete 362-record sequence was accepted, and record363 was rejected.
6. Ran `python -m unittest discover -s scripts/tests -p 'test_payment_resources*.py' -v`: **44 tests passed in 1.857 seconds**, no failures/errors/skips in this Linux execution. These include the meaningful reordered/missing/extra sequence cases, prefix persistence, fixed result/progress agreement, failed evidence saves, uncertain commits, and real small Linux self/child-process memory/identity observations. They do not execute Orchard payments.
7. Ran the additional missing-killpg/SIGKILL fixture simulation described above: passed. This was a synthetic portability check, not native Windows validation.

The reviewer did not rerun the author's broader 126-test Python suite, so that total is not claimed as this reviewer's own execution. No Go/Rust compilation, gofmt/rustfmt, Clippy, native funded tests, real 32+1 payment/resource workload, or Windows CI run was performed locally; those toolchains/platform are unavailable here. No native CI result is counted as a pass by this report. The current-head native audit and all required relevant CI remain separate acceptance conditions.

## Carried source conclusions, confirmed against unchanged identities

- Resource mode uses two new encrypted wallets with fixed 50000/50000 public test allocations, real prepare_payment_to, actual two-action LAB2 decoding and the pinned ZVTGEN03 domain. Each normal worker commit and independent scenario commit receives the same single genuine payment at the next height; no empty blocks, fabricated journal, direct state changes, verifier double or limit override are introduced.
- At32, both stores must agree on complete Summary/capacity: 66 commitments,64 nullifiers, fees32000, wallet records50/50 and balances34000/34000. At pending33, records51/50 and exact outbox/reservation state must survive receipt-bound backup/open. At33, commitments68/nullifiers66/fees33000, records52/51, balances32000/35000 and cleared pending payments are required. Padded action/nullifier totals are not relabeled real-input counts.
- The first worker is sampled then closed; complete physical records are inspected before generation2 starts and fully replays the same ledger. The independent scenario ledger and both encrypted wallets recover before payment33 is freshly built. That pending payment is separately restored byte-for-byte and submitted using those same bytes. New PoolStore opens construct new verifiers; subsequent full state-rule/history replay may use the existing bounded authorization cache.
- Genuine candidate selection/Preview/Finalize/Commit must agree. Bad signatures and still-unexpired historical spends reject. Incorrect Commit tag and intervening selection/duplicate requests cannot destroy the valid pending finalization33; the original tag must commit. State/capacity/segment-byte comparisons surround rejected and uncommitted calls.
- After Close, physical verification compares whole header/frame structure, exact submitted transaction bytes, checksums, continuous height/block/predecessor/result hashes, canonical rotation and complete capacity totals. During worker ownership, header observation uses metadata to respect Windows exclusive locking. These physical checks supplement actual authorization replay.
- The fixed nine memory events cover two worker generations and the combined scenario generation. Their observed OS resident/high-water metrics are not heap-only, private-commit, phase-local or whole-machine memory; the scenario includes both wallets, its independent store, prover/verifier/cache/history and KDF costs. Go/Python supervisors are excluded as explicitly stated.
- Thirty-two-plus-one is a modest fixed-load baseline. It does not verify full active capacity or rotation, cache/anchor exhaustion,65536 commitments,256 wallet saves, production TPS, network/consensus finality, cold disk, real power loss/disk full, multi-machine long-running behavior or specialist external security review. P2 remains in progress.

## Final disposition

C1 R1 is closed at exact head9e46e03165250c6c51fa7031526d8de1bbdf27d6/tree072da4de0b426e619c80b504dedf019a0808201b. No new blocker was found within this independent code and cross-component contract scope. The appropriate code-review verdict is PASS. This verdict must not be described as native benchmark success, zero possible bugs, a specialist security audit or full-stage acceptance before the separate required current-source CI/evidence and parallel-review gates pass. Any changed runtime/test/verification source requires review of the new exact identity; original C1/C3 reports and failed observations should remain preserved.
