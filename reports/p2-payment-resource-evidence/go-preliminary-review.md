# P2 payment-resource preliminary independent Go review

- Reviewer/task: `/root/p2_resource_review`; separate task, not a candidate author.
- Review date: 2026-09-17.
- Repository/base: `youq616/Zevune`, `8324ec8bd153d9502e3e6761d25bfe281a5f3b44`.
- Base tree: `38c3caff84bcd6ca626bd5b6d53212d9e4f8e2b2`.
- Exact scope: uncommitted `internal/poolbridge/payment_resource_e2e_test.go`.
- Reviewed Git blob: `ec7b3c322560edf62169506eb0d6a2779af33ec9`.
- Reviewed SHA-256: `502688e6c43df3521f0d364391b1cfd0bddf35d4bffaa152db73352c76826da7`.
- Associated Rust blob/SHA-256 verified: `5c666fa21d7a8023c52e9e1d5d4f18ab9890de70` / `2b568ca93dc29d6ecc1edcac17973fc00d840e76fc38c5900a4e15db09dfceaa`.
- Frozen design SHA-256: `f8fb0f009423f26afbfb84ad2293b13dbe9581032c31ba0bfc379d224a91789f`.
- Result: **NO_BLOCKER_IDENTIFIED within this preliminary Go test/caller source scope. Not final-stage PASS.**

## Work actually performed

Verified the exact Go source identity before and after review and read the complete file. Compared it with the previously reviewed Rust scenario and frozen design. Read unchanged poolbridge framing, executable/genesis pinning, Summary decoding, active-capacity accounting, proposal selection, request deadlines, Finalize/Commit and process-close handling; checked the real Rust worker pending-slot behavior and transaction wire offsets. Manually traced all 33 payments, both worker generations, both wallet recovery phases, physical inspections and the fixed progress/event sequence. No repository/candidate file was changed by this reviewer.

No Go build, gofmt, go vet, native Go/Rust tests, Clippy or CI job was run by this reviewer; native toolchains are unavailable locally. The new Python supervisor and its semantic tests are outside this preliminary source scope and still require final review. The actual complete-candidate base/head/tree is not yet frozen.

## Reviewed behavior

1. **Real paths and isolation.** The file is restricted to the payment_resource_e2e build tag and the existing poolbridge package. It reads test-visible process PIDs without adding a production API. Scenario/worker binaries must be real files; the worker is SHA-256 pinned and the explicit ZVTGEN03 manifest is length/magic/digest/decoder checked. Start still performs the existing production checks. The resource scenario is invoked only with its explicit fixed mode.
2. **Single genuine payment per height.** Every iteration obtains a fresh scenario payment, validates its LAB2 domain, expiry, fee/value balance and action count, performs genuine Check/selection/Preview/Finalize/Commit, then sends the same single-payment block to the independent scenario store. Complete Summary equality is checked for initial state, preview/finalized/committed state, independent scenario apply and each recovery. The real proof verifier and all unchanged state rules remain in the runtime path.
3. **Wallet observations.** The Go parser requires the resource-specific 162-byte response, canonical pending flag, whole Summary equality and expected balances/records, and compares actual regular-file size with storage_status. Rust independently checks the exact pending available balance; Go also checks availability direction and equality when no reservation remains. The expected backup paths follow the Rust backup counter and update only around the prescribed recovery calls.
4. **Replay then new payment then outbox restore.** At 32 commits, the last generation-1 memory checkpoint occurs before Close. A full physical inspection follows Close. Generation 2 is opened with Create=false and must reproduce exact Summary/capacity. The separate scenario ledger and both receipt-bound wallets are then restored and checked before requesting the new thirty-third payment. Its encrypted outbox is separately backed up/reopened and byte-compared, with 51/50 records and stable pending state, before submission. Final state is 33/68/66/33000 and wallet records 52/51 with no pending payment.
5. **Rejections and pending slot.** Broken binding-signature candidates reject Check/Preview/Finalize; selection from broken/valid/duplicate preserves the valid bytes exactly once. Committed Summary/capacity and disk digest remain unchanged before commit. Every duplicate-check batch checks expiry against the next height before asking Check/Preview/Finalize/selection to reject. At height 33 an incorrect tag is rejected while the real finalization remains pending; intervening duplicate and selection checks must leave it intact, and the original valid tag then commits. A Finalize against a different candidate while this slot exists can reject as stale before transaction verification; independent Check/Preview already establish spent-payment rejection, so the test does not need to misattribute that particular error to a second proof check.
6. **Physical records and capacity.** Go accumulates the real header plus 150-byte empty-record framing plus four bytes and actual transaction length for each paid frame. It independently compares committed capacity after each commit. After each worker Close it validates the complete immutable header shape/domain, exact segment names/count, regular-file sizes, complete record boundaries, canonical rotation, checksums, heights, block IDs, predecessor and each saved result AppHash, exactly one transaction and the exact submitted bytes, complete final height and aggregate logical/tail sizes. This supplements genuine replay rather than pretending to be a replacement authorization verifier. The first and final full header digest must agree.
7. **Windows lock handling.** While a worker holds its exclusive genesis lock, non-mutation inspection uses genesis metadata and segment bytes. It reads full genesis/header/frames only after Close returns. Wallet file observations use metadata, and actual decrypt/read/backup happens in the Rust owner through unchanged WalletStore calls.
8. **Durable progress.** measure publishes a bounded started record before invoking the operation, and a matching completed record with measured duration after successful return. A t.Fatal/timeout does not publish a false completed record. Files are synced/closed and atomically published as new numbered targets in the private, initially empty handshake directory. The progress timing excludes evidence-write and later checkpoint-ack overhead; total_ms includes the wider test duration. Final result includes the exact completed operation list for supervisor cross-checking.
9. **Strict acknowledgments.** Event waits are bounded by 15 seconds and the stage context. The code checks the ack file kind/size and opened-file identity, then explicitly rejects duplicate, unknown, case-variant, wrong-type or extra JSON keys/content. A successful ack has exactly schema_version=1, the matching seq, and ok=true. Failed acknowledgments deliberately stop the test.
10. **Time and cleanup.** Scenario write-plus-response is bounded by 90 seconds or the stage context. Worker startup handshake/request options are 60 seconds. The Go stage context is fixed at 20 minutes. Normal cleanup retains ownership of spawned scenario/client handles and uses existing Close behavior. Runtime/enforced global timeout and supervisor cleanup still require cross-component/native validation; this file alone cannot prove cleanup of every abnormal crash before the supervisor's first PID registration.

## Independently checked sequence counts

There are exactly 181 successful measured operations in the intended complete path, yielding 362 progress files:

- Initial scenario_start, worker_create, wallet_sync: 3.
- prepare, candidate, worker_commit, scenario_apply, wallet_sync for each of 33 payments: 165.
- duplicate_rejection at 8/16/24/32/33: 5.
- First worker_close, first disk_check, worker_reopen, wallet_recover: 4.
- outbox_restore for payment 33: 1.
- Final worker_close, disk_check, finish: 3.

The nine memory events are genesis; payment_8/16/24/32; worker_reopened_32; wallet_recovered_32; pending_restored_33; complete_33. Their heights and worker generations match the frozen design. These source counts must be enforced against actual supervisor evidence, not reported as an executed result at this stage.

## Non-blocking reporting/validation cautions

- A started progress record's committed_blocks is the actual recorded count at operation start. If Commit succeeds but a subsequent Status/capacity check fails inside worker_commit, that started record cannot prove the ledger remained at its old height. Incomplete failure artifacts must say last-recorded/start-of-operation count and unknown/incomplete subsequent outcome, not assert definitely uncommitted. The immutable started/completed protocol supports this interpretation without expanding it.
- prepare includes a payment response plus walletStatus; candidate includes several worker requests and a wallet response; worker_create/reopen include Start plus Status/Capacity. The 90/60-second constraints are single-response/handshake/request budgets. A supervisor must not silently treat every composite measure duration as one request's duration, and the report must describe these combined timings accurately.
- Sampling at the first genesis event means a hard Go crash before that event has no registered worker/scenario identity at the supervisor. For this fixed no-funds CI test, this can remain an explicit unconfirmed-cleanup failure boundary instead of extending the protocol with a Windows Job/start gate. Such a run must fail and preserve the limitation; it cannot report successful cleanup or kill unrelated same-name processes. This is a scope judgment, not a review of unprovided cleanup code.

## Remaining acceptance gates

Require the final exact base/head/tree and review any changes to these source identities. Review the Python supervisor's PID creation/parent identity checks, OS counter semantics, event/progress/final-result validators, failure artifacts and cleanup. Run genuine native Linux/Windows resource tests, the relevant default/funded regressions and prescribed format/static checks. Preserve failures and source/run linkage. Only then can an independent final implementation review and complete-stage acceptance occur. No production capacity, TPS, network finality, funds or overall-P2 completion follows from this preliminary source result.
