# C4 非 Rust 原生证据独立部分审核

结论：**本报告明确列出的 4 个 PR jobs 通过证据审核；C4 整体仍为 PENDING。** 没有在这些原件中发现失败、身份错配、缺失尾部或未声明的 workflow skip。此结论不能代替其余必需 jobs 的完整原生验证。

审核人：`/root/p2_archive_native_audit/nonrust_log_review`，未编写或修改候选代码、测试及工作流。逐段全文读取 4 份日志及各自 metadata/direct steps，另以准确 commit 的 `git show` 核对对应 workflow 与 isolated bundle 构建脚本；计数直接从原件独立提取，未依赖上游 derived summary。未自行轮询 GitHub、未触发 CI、未重跑测试。原件保持不变；逐行证据索引和计算结果见同目录 JSON。

- Source：`50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`
- Tree：`3c44977028b58ddd387f52946632af594208edfb`
- Base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`
- 所有原件 `git log -1 --format=%H` 实际 checkout：`fb5ec39a59cb87aec0662c7706dce1f9e85e1962`（PR 13 synthetic）。源 commit/tree 也由本审核本地 Git 对象读取复核；synthetic/base/source 的 Git 对象亲缘验证沿用父审核已保存的独立身份记录，不把 source SHA 与实际 checkout SHA 混写。

| PR job | 实际 job 起止（UTC，metadata） | 原件 bytes | 实际步骤结果 |
|---|---|---:|---|
| Windows consensus `105145581373` | 09:18:17–09:20:40 | 43,146 | 11 success / 1 conditional skip |
| Windows scaffold `105145581297` | 09:27:36–09:28:42 | 19,225 | 9 success / 3 conditional skips |
| Ubuntu scaffold `105145580839` | 09:27:21–09:28:40 | 21,312 | 12 success |
| Ubuntu operator `105145580920` | 09:17:06–09:29:29 | 97,642 | 14 success |

4 份共 **181,325 bytes**，50 个 terminal steps 中 **46 success / 4 skip**。每份原件包含 setup、准确 checkout、实际命令/输出、post cleanup 和 `Cleaning up orphan processes`；Windows 原件的 BOM/CRLF 与 Linux 原件 BOM/LF 原样保留。每份无 `##[error]`。metadata 的抓取时间与上述 job 实际运行时间分别保存。

## Windows consensus

准确 workflow：`.github/workflows/consensus-lab.yml`。原件实际运行 `go test -mod=readonly ./... -count=1 -timeout=8m -v`，5 个有测试 package 返回 `ok`，`cmd/zevune-devnet` 是 `[no test files]`，不计执行测试。日志明确可见 **59 个顶层 Test PASS、4 个 fuzz seed harness PASS、43 个子例 PASS**，没有 `--- SKIP`；这些是本次 invocation 的计数，不与其他 jobs 汇总成唯一覆盖数。普通 `go test` 执行 fuzz seeds，不等于持续 fuzz campaign。

`TestFourProcessConsensusAndRecovery` 实际 PASS（43.00s），原件逐项记录共同高度 4、相同 block/app hashes、验证超过 2/3 签名、真实 RPC/mempool 拒绝付款入口、1 节点离线仍提交、2 节点离线高度在观察窗口保持 7、恢复 quorum 和落后节点追赶、突发进程终止恢复、四进程完整重启。`TestFullRestartAdvancesBeyondDurableHeight` 实际 PASS（7.87s），记录从 recovered 最高高度 3 前进到至少 6。该 suite 的付款入口关闭语义不与 operator 的 enabled local funding profile 混为同一实验。

`go mod download`、`go mod verify`（实际 `all modules verified`）、`go mod tidy -diff`、gofmt、`go vet -mod=readonly ./...`、launcher build 和最终 `git diff --exit-code` 均有准确命令及 terminal successful step 支持。Windows 的 `Adapter race checks` 是 workflow 中 `runner.os == 'Linux'` 的 **1 条预期 skip**，不计 Windows race 覆盖。

## Ubuntu / Windows scaffold

准确 workflow：`.github/workflows/ci.yml`。两平台均实际执行 gofmt、`go test ./... -count=1` 与 `go vet ./...`；各有 **7 个测试 package `ok`**，2 个 command packages 为 `[no test files]`。非 verbose 日志不能推出逐例数或断言不存在内部 runtime skips，因而不作这些主张。

Ubuntu 还实际执行 `go test -race ./... -count=1`，同样 7 个 package `ok`；两个 bounded fuzz campaigns 均有 baseline complete、fuzzing with 2 workers、PASS 和 package `ok`：`FuzzDecodeBinary` 675 execs、`FuzzJournalBlockDecode` 97,840 execs。`-run=^$` 在这里同时配合 `-fuzz`，由实际 fuzz markers 证明进行了 fuzz；不能简单归类为 compile-only。

Windows 的 race 与两个 bounded fuzz steps 共 **3 条预期 Linux-only skips**，不计 Windows race/fuzz 运行。setup-go 的 stable 实际解析为 Go 1.27.1；这只是本次工具链观测，未据此更改 workflow。

## Ubuntu operator

准确 workflow：`.github/workflows/network-operator.yml`。`python -m unittest discover -s scripts/tests -v` 的逐例输出为 **132 `ok` + 3 `skipped` = 135**，与 `Ran 135 tests in 2.798s / OK (skipped=3)` 一致。3 条 skip 都明确要求 native Windows file-sharing semantics：旧 open 与 delete holder 的兼容、post-read size check、replacement identity check。它们在此 Linux job 不获 native Windows 通过信用；其他 Windows-handle mock/ownership tests 的 Linux `ok` 也不替代这三项。

源码格式检查通过；`cargo build --locked --release --features local-funding-lab --bins` 实际完成（1m03s）。这是 binary build，不计为 Rust test harness 通过。

Isolated bundle 步骤实际调用 `python scripts/build_local_lab.py`，编译路径进入独立 `/tmp/zevune-source-build-.../source/integration/orchard`，第二次 release build 完成（1m01s）。原件 JSON 明确为 `built: true`、`source_commit: fb5ec39...`、`real_funds_allowed: false`，manifest SHA256：`6fcd1207cfd0b003bddd1c76e220e1533a4e12f4ad790b93d0d3f8d6a3dae42a`。准确源码中的成功 marker 位于 `export_source`、隔离构建、source unchanged 检查、create-only 目录/manifest 写入与 `verify(destination, pin, commit)` 之后；因此它支持这一次真实构建/验证完成。Python source snapshot、create-only、bundle adversarial 验证 tests 也实际 `ok`。这不声称 ZIP 在本审核中另行下载验证。

Go 实际使用环境登记的 bundle operator/worker 可执行文件以及本次构建的 funded scenario，运行 `-tags=operator_e2e ./labnet ./cmd/zevune-network -count=1 -timeout=15m -v`。原件可见 **51 个顶层 Test PASS、4 个 fuzz seed harness PASS、47 个子例 PASS**，2 个测试 packages `ok`，无 Go runtime skip。关键行为有实际 PASS/markers：

- `TestActiveFundedFourNodePaymentRestart`（79.59s）：active profile 实际 shipped init/run/sync/submit/storage，InitChain version rejection，真实非零 A→B、所有四节点重启、B→C 再花费、wallet history reopen、签名 next-header 验证与 duplicate rejection。
- `TestRealOperatorNonzeroPaymentsAndRestart`（101.36s）：wrong-domain/downgrade/unknown-profile RPC 拒绝、非零 A→B→C、加密 outbox backup、单节点离线、signed reference-state checks、完整重启、重复提交拒绝。
- `TestQuorumSignedWrongPostStateNeverPersists`（4.15s）：实际 PASS；准确源码测试断言错误 post-state 必须返回 `ErrCertificate`，内存 state 不变、关闭 worker 后 journal 字节与原件一致，覆盖不只由测试名称推断。
- `TestRealReferenceCheckpointBeforeRPC`、`TestRealPinnedReferencePayment`、`TestRealJournalCopyRestoreAndAdversarialReplay`、`TestRealOfflineStorageInspectionAndLock` 均实际 PASS。日志的低高度、本地 NO-FUNDS 范围保持明确；现有 Go storage-copy 测试不冒称新 Rust active archive CLI 的原生覆盖。

随后 `go vet` 完成，Linux race 的 labnet 与 command packages 返回 `ok`，带 `operator_e2e` 且单独指定 false post-state 测试的 race invocation 也返回 `ok`（5.251s）。三项 bounded fuzz 都有真实 fuzz/PASS 输出：canonical public configuration 8,217 execs，numeric loopback endpoint 8,386，test genesis frame 99,125。race 重复的测试不增加唯一案例数。

最后 `git diff --exit-code` 成功；上传实际报告 6 files、22,853,524 bytes、artifact ID `10489996280`，ZIP SHA256 `ba1cf17cd00269bd76f270a4f3b0c4846f5288f488fbe0973d5883cd377fd7c4`，finalized 后完整 cleanup。

## 证据限制与原件哈希

静态命令及组内命令的成功有命令启动、shell fail-fast 设置、后续输出以及终态 successful steps 共同支持；GitHub 日志没有为每一条成功命令逐一打印数字退出码，故不伪造这些数字。日志中 Node 20→24 等 action 弃用警告不是测试失败，但已随原件保留。没有把原件 `Complete job` / cleanup 单独当作通过依据。

只审核以上 4 个 PR jobs；其余 Rust/default/funded/bridge/integrated/resource/growth 必需证据与 C4 全矩阵验收仍由父审核等待并汇总。本报告不作真实资金、生产就绪、完整容量、断电、磁盘满或外部密码学审计承诺。

| 原件 | SHA256 |
|---|---|
| `job-105145581373.log` | `88f846455557f2631f2c27ffaedbfc3475437ce789b5f90bff92b179e8d5444a` |
| `job-105145581297.log` | `9c88121f6864989b66ebb9821e61e5faebd2a6d4f1eb7f2d7ea3680407758cb6` |
| `job-105145580839.log` | `add91febdc052efd243983ab5c1aeff4b813db797d0a2c49877dce5e8b23931e` |
| `job-105145580920.log` | `e911804ccd44737924def63aabcafe3298f94c02aec2fb84f61c7639d08fcb1f` |
