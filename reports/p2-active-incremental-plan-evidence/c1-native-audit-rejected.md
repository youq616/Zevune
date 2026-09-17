# C1 原生验收独立审核：拒绝接受

审核任务：`/root/p2_plan_native_audit`，2026-09-17。此任务未编写候选，不修改仓库。结论：**REJECTED_NATIVE_C1**。C1 的 Rust 格式门槛失败，新增实现没有原生 Rust 编译、测试或 Clippy 验收信用；不能接受或合入 C1。

审核身份是 base `0927af157a3cc35abde14b036bc50a99a793a32b`，C1 `99ec771c57207167f473d23ffd07b54f15a36abc`，tree `510693b0fd8ec085ab06de4140d6f7fd80f48c7e`，PR #15 合成提交 `066f033f2ca441bdd8533c8e1e4bfe2d3faa84a5`。独立核对创建响应中的 source SHA、合成 Git API 元数据的 tree 与有序父提交 `[base, C1]`，以及全部原生日志中的真实 checkout 输出，均一致。

## 原件完整性和读取方法

`c1-native/manifest.json` 的 41 个原件全部逐一验证实际 bytes 和 SHA-256：10 份原始 run API JSON、10 份原始 jobs API JSON、21 份完整 job 日志，共 918,751 bytes。21 份日志占 730,967 bytes；独立脚本读取全部原始 bytes、逐行扫描全部 8,325 行。未以作者派生 `derived-log-summary.json` 作为裁定输入。保留原始 UTF-8 BOM/CRLF，不修改原件。

人工核对了所有终态 step 元数据、所有日志的 checkout/error/执行终点、四个成功 job 的完整检查与测试执行输出、所有失败 job 的实际先行步骤和测试计数，以及格式差异。17 个失败日志的完整格式差异在仅去除时间戳/ANSI 和绝对 Diff-header 根路径后逐字节相同，SHA-256 为 `e22dad3d33ea5d1e56f1f0a104f74e87d229a090ba405dab4d8727ca42045d2c`；该相同内容经完整阅读后与 C1→C2 的补丁逐项比对。

独立派生记录 `c1-native-audit-rejected.json` 为 138,923 bytes，SHA-256 `6f471f733afc13455ec0ff9f864723291211cc10a965cb548d9591370a6d0172`，包含原件 hash、全部 22 个 job、每个 step 的终态、全部错误、格式差异原文、先行 Python/Go 结果、资源 artifact 原件身份和限制。可复核脚本为 `audit_c1_native.py`。脚本读取和元数据核对不是本地运行项目测试。

## 实际终态

| 工作流 | run ID | C1 终态 | 返回的 job 状态 |
|---|---:|---|---|
| scaffold-tests | 35230914482 | success | Ubuntu/Windows 两个 success |
| consensus-laboratory | 35230914464 | success | Ubuntu/Windows 两个 success |
| orchard-consensus-integration | 35230914450 | failure | 两个 fmt failure |
| orchard-cryptography-laboratory | 35230914451 | failure | 两个 fmt failure |
| wallet-laboratory | 35230914460 | failure | 两个 fmt failure |
| local-network-operator | 35230914478 | failure | 两个 fmt failure |
| payment-resource-baseline | 35230914481 | failure | 两个 fmt failure |
| active-ledger-growth | 35230914499 | failure | source fmt failure；一个无步骤 growth skipped 占位 |
| orchard-bridge | 35230914503 | failure | 两个 fmt failure |
| funded-wallet-consensus | 35230914556 | failure | 两个 funded-library 和两个 funded 均 fmt failure |

实际为 10 个 pull_request run，全部 attempt 1，2 success / 8 failure。API 返回 22 个 job：4 success、17 failure、1 skipped。预期完整矩阵为 23 个可执行 job；这里 source 失败后 growth 矩阵未展开，仅返回 ID `105234829708`、name `growth`、0 steps 的依赖跳过占位。它没有日志，不能计作 Ubuntu/Windows growth 已执行或两份缺失的已运行日志。

所有 261 个返回 step 的终态合计为 152 success、17 failure、92 skipped。失败/依赖导致的跳过不能与 Windows 上原本仅限 Linux 的条件跳过混为一种“通过”。没有将 push run、旧阶段或 C2 的任何结果计入本报告。

GitHub run 元数据的顶层 `head_sha/head_commit`、job `head_sha`、日志 checkout 和合成 tree 均属于 C1。原 run JSON 的嵌套 `pull_requests[0].head.sha` 已随当前 PR 更新显示 C2；它是当前 PR 元数据，不重新定义历史 run 的 tested source，也不是 C1 日志属于 C2 的证据。

## 阻断项

**NATIVE-C1-FMT-01：构建验收阻断。** 17 个失败 job 都在含 `cargo fmt --check` 的源检查步骤结束，唯一 action error 为 `Process completed with exit code 1.`。完整输出是相同的 4 文件、10 hunks 格式要求：

- `pool/active/incremental.rs`：链式 checked 操作换行，1 hunk。
- `pool/active_flow_tests.rs`：长 `assert_eq!` 换行，1 hunk。
- `pool/recovery/active/incremental/tests.rs`：条件表达式和长断言换行，2 hunks。
- `tests/active_incremental_cli.rs`：长路径构造、JSON 换行计数断言、付款调用、子进程辅助调用和参数数组格式，6 hunks。

这些是原生 Rust 1.98.1 formatter 要求。C1→C2 的 4 文件、10 hunks 已完整读取，改变仅为排版和合法尾逗号；未删除测试、改调用、放宽条件或改工作流。但 C2 格式修正本身不是 C2 原生成功证据。

C1 全部 21 日志没有任何 Rust `test result`，没有任何 `FUNDED_COHORT_COMPLETE`。Rust 的测试、接口、真实 proof/signature、恢复后再花费、跨段/10001/10002 计划、新 CLI JSON/stdout、Clippy 等步骤均未执行到，不能从日志中的脚本命令展示或先行 Python 成功推断它们通过。

## 四个成功 job 的有限信用

`scaffold-tests` Ubuntu job `105234456578` 完成根模块 gofmt、`go test ./... -count=1`、`go vet ./...`、`go test -race ./... -count=1`，以及协议/账本 decoder 两个 3 秒有界 fuzz。各 Go 测试包正常完成；fuzz 实际终点分别为 11,057 和 116,693 execs，均 PASS。Windows job `105234456841` 完成 gofmt、同一根模块测试和 vet；race 与两个 fuzz 的 3 个 Linux 条件步骤明确 skipped，不给予 Windows 运行信用。根模块没有 `-v`，日志提供包级完成，不伪造逐名用例计数。

`consensus-laboratory` Ubuntu job `105234457063`、Windows job `105234457332` 均完成固定 Go 1.27.1 的依赖下载/verify/tidy-diff、gofmt、完整无额外 tag 的 CometBFT 模块测试、vet、launcher build 和最终无 source drift 检查。每平台日志可见 63 个顶层 PASS（包含普通调用的 fuzz 种子 harness，子测试不重复加总）。Ubuntu 另完成 app race；Windows app race 明确 skipped。

这两个 consensus job 的 `TestFourProcessConsensusAndRecovery` 与 `TestFullRestartAdvancesBeyondDurableHeight` 都有真实 PASS 和实际四进程恢复观察。它们属于已存在的无 funded tag 的 NO-FUNDS 共识 scaffold：付款 admission 明确拒绝。不能将此扩充为本轮 Orchard 真实支付、active archive 规划或 funded 四节点继续花费的证据。

## 失败 job 中确实完成的先行检查

funded-library 两个平台各实际完成 13 个调度器 Python 测试，随后 fmt 失败；它们没有执行 funded library suite。funded interfaces 与 operator 的 Python 全套各报告 135 discovered tests：Ubuntu 为 `OK (skipped=3)`、Windows 为 `OK (skipped=1)`。其平台 skipped 名称和原因已保留在 JSON 中，不能将 discovered 总数全部写为 passed。

funded interfaces 的前置两 Go 模块 `-run '^$'` 输出明确 `[no tests to run]`，只计编译信用。后续 Rust interfaces、Python→真实 Rust 后端、funded 四节点及 operator processes 都未执行。

resources 两平台分别完成 53 discovered Python tests：Ubuntu `OK (skipped=3)`、Windows `OK (skipped=1)`，随后 fmt 失败；它们检查测量/证据逻辑，并未运行真实 32+1 payment measurement。

## 资源 artifact 核对

完整读取两个 artifact 的 metadata JSON、ZIP 和解出的 setup JSON，独立验证 ZIP bytes/SHA-256 与 GitHub `digest/size_in_bytes`、ZIP 恰好一个成员、解出文件逐字节一致，以及 source/checkout/tree 三元组绑定 C1。

| 平台 | artifact ID | ZIP bytes / SHA-256 | setup bytes / SHA-256 |
|---|---:|---|---|
| Ubuntu | 10501366180 | 460 / `2e708b68417e7ff42018c51af8f0fa6f050322b4cfd1d7517936e76d5cb0ab3a` | 456 / `59a426f4f6321eb49b492fdfe2d7518980893208685ec7caff70cb363560a775` |
| Windows | 10500499765 | 464 / `2221e103aca41e19b796e20af94d57c27bb46ed5dccd13680a390317f4ca06cf` | 466 / `44e90d79378f1b3b9809288cfa88cee2f94550406fe28c6b22efd817bd242510` |

两份 ZIP 都只包含 `payment-resource-setup.json`，没有 `payment-resources.json`，均明确 `observed_execution_status: "not_started"`。失败后 always-upload 成功保存了初始观察，不代表资源门槛执行。root 说明的下载端 urllib 403/1010 后改用 curl 成功属于原件获取过程，本审计不将其记为 CI 运行失败；临时签名 URL 不是交付证据。

## 后续要求和未测范围

C1 拒绝记录永久保留。C2 `2020c7314a996769b33706754405c0976ce7c50a`、tree `a25d4752d49f366f9aff047116eeffd9b1f6ae1d` 需要自己的完整 10 个 PR run / 23 个原生 job、准确源码的非作者代码审核及最终 native 审核；C1 的四个成功 job 不替代 C2。

本报告不给新追加计划任何运行验收，也不给 100000 块 growth、真实资源门槛、funded 四节点或 operator 验收。失败历史本身不证明实现有状态/密码学缺陷，只证明格式门槛尚未通过且后续相关验证未发生。P2 仍在开发中，持久增量包、快照导入、真实断电/磁盘满、完整容量成本、长期多机、外部安全审计和真实资金使用均未完成。
