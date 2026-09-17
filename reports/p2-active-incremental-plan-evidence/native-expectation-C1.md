# P2 追加关系计划：独立原生验收预期审计（C1）

审核任务：`/root/p2_plan_native_audit`。本任务未编写候选源码、测试、设计或工作流；未修改仓库。日期：2026-09-17。

状态：**EXPECTATION_REVIEWED / NATIVE_PENDING**。这份记录说明从准确候选源码推导的验收范围，不构成测试通过、CI 完成、阶段接受或 `PASS_NATIVE`。截至本记录完成，本任务尚未收到该候选完整原生日志；本地没有 Cargo/Rust 执行结果。

## 精确范围

- 仓库：`youq616/Zevune`，PR #15。
- base：`0927af157a3cc35abde14b036bc50a99a793a32b`。
- C1：`99ec771c57207167f473d23ffd07b54f15a36abc`。
- tree：`510693b0fd8ec085ab06de4140d6f7fd80f48c7e`。
- root 提供的 PR 合成提交：`066f033f2ca441bdd8533c8e1e4bfe2d3faa84a5`，尚需原生 checkout 与父提交/树元数据相互核对；本记录不将提供的合成身份当作执行证据。

独立阅读了 `AGENTS.md`、`docs/STAGE_REVIEW.zh-CN.md`、完整追加计划设计，两个新库测试文件、新 CLI 测试文件、`active_flow_tests.rs` 全部新增断言及完整的付款/轮换/10001/10002 调用流程、对应新生产模块和既有 `ActiveArchive::open/verify/check_bytes`。还阅读全部 12 个工作流、Cargo manifest、`pool.rs` 的 feature/test 模块接线和 `scripts/run_funded_rust.py` 全文。

机器可核对的准确读取身份和工作流字节相等记录在 `native-expectation-C1.json`：9,177 bytes，SHA-256 `11d2eb548da42aab1fe5a89c8d36d4bd8b522118647036930132fd9f5977fd50`。逐个 Git 对象比对证明必需 10 个工作流、funded 调度器、Rust manifest/lock/toolchain 和仓库已有 Go module/lock 文件与 base 逐字节相同。根 Go 模块没有 `go.sum`，未将不存在的文件算作已检查对象。

## 新增测试接线与期望计数

新增库测试共 15 个定义：物理层 5 个、通用公开 API 7 个、Unix 专属 2 个、Windows 专属 1 个。因此在 Ubuntu 预期执行 14 个，在 Windows 预期执行 13 个。这些模块仅由 `#[cfg(test)]` 接入，不依赖 funded feature，故应出现在默认库及 funded-library 两类原生套件中。

物理层的 5 个定义检查不同合法 short-read 大小、Interrupted 重试/偏移、EOF/异常计数/I/O/溢出拒绝，空计划、尾段增加及真实 1 MiB 物理轮换，超过 64 KiB 后的历史差异、封闭旧段末字节及旧尾差异，genesis/捕获长度/EOF，以及 callback 分配失败不得发布部分计划。合成 frame 明确只经过私有物理存储路径，未经过 State/PoolStore；它们不是授权、真实付款或完整状态重放证据。

公开 API 的 7 个通用定义使用普通 prepare/commit 的空块，覆盖零到零/非零、尾段增加、独立字节期望、同路径及不同路径相同内容、持锁期限/多读者、各自完整通过验证的同高及更高分叉和回退、网络/legacy/错误 pin、成功后再次调用重检、原地同长度有效历史替换、晚于重放和前缀核验的字节或 namespace 变化。更高合法分叉具有独立正确 pin，并额外直接断言私有物理比较返回 Stale，不用错误摘要或锁错误充当前缀拒绝。

Unix 的 2 个定义检查 retained-name 替换、新 hard link、缺失及 symlink，不重建或修复外部改变的条目。Windows 的 1 个定义检查两端持有句柄期间 rename 拒绝、drop 后允许。平台特有测试不能跨平台相互计数。

新 CLI target `active_incremental_cli` 有 7 个定义，整个文件受 `#![cfg(feature = "local-funding-lab")]` 限制。默认 Cargo 套件即使产生该 target 的 `0 tests` 完成结果，也没有执行这 7 个测试。`run_funded_rust.py` 基于准确 Cargo metadata 穷尽枚举 bin/test target；新 target 应自动列入 funded **interfaces**，而不是 funded **library**。

7 个 CLI 定义覆盖：真实 A→B，归档/恢复，再由恢复历史扫描后的 B→C 和二次花费拒绝；零高度/同内容完整空计划 schema；参数、NO-FUNDS、旧 pin/profile；独立可验证的分叉/回退/网络；两端错误 pin、损坏、截断、追加、缺失及多余项；writer 锁及共享 reader；只读 stdout 失败以及追加和空计划的可写正对照。JSON 由测试独立依据真实文件、pin 和预期 tuple 构造。普通调用在前后比较整个 fixture 树的条目集合和文件字节，可写 stdout 正对照仅允许预先创建的 receipt 文件获得准确 JSON。

基于旧阶段的已记录计数与上述定义差量，待日志验证的预期是：

| 套件 | Ubuntu 预期 | Windows 预期 | 计数口径 |
|---|---:|---:|---|
| 默认 Rust 库 | 154 | 146 | 旧 140/133 + 新 14/13 |
| 默认完整 Rust 套件 | 168 | 160 | 每个完整套件 19 个 harness result；新 CLI target 为 0 tests |
| funded-library | 173 | 165 | 一次完整 lib harness；新旧所有 funded 库测试均执行 |
| funded interfaces | 63 | 63 | 21 个 harness result，含新 CLI 7 tests；库由另一 job 完整覆盖 |

以上都是预期，不能提前写成“已通过”。四个双平台默认 Rust 工作流、两个 funded-library、两个 funded interfaces，合计预期 12 个执行 Rust 测试的 job、196 个完整 Rust harness result。跨工作流重复运行不能计作不同的独立测试用例。

## 既有真实付款与增长证据的正确归属

`active_flow_tests.rs` 原 4 个测试定义均保留；C1 仅新增 138 行，未删除旧断言。它由 `#[cfg(all(test, feature = "local-funding-lab"))]` 接入，所以新计划断言的原生证据必须来自 **funded-library** job。

`real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` 保留普通逐块 prepare/commit/fsync 的 padding、实际付款强制 1 MiB 轮换、原有双重花费拒绝、真实 archive/restore、余额/手续费和状态摘要断言。新增三次计划核验分别是：

1. 付款前完整旧尾段不变，第一笔真实付款轮换出新段，仅列 `(1, 0, first_frame_bytes)`。
2. 轮换后的源归档到实际恢复后继续增长并在 10001 支付 B→C 的后来归档，计划准确列旧尾后缀。
3. 10001 的恢复流程后继续提交 10002 空块，计划恰好为同尾追加 150 bytes。

辅助断言先独立比较预期 tuple、逻辑总量、真实完整不变段数，然后仅在测试副本中按 range 拼接；重建副本必须逐文件等于 later，再正常打开并完整 verify。这个测试副本拼接不是新增生产增量恢复 API。

重算记录 checksum 和整个布局 pin 的坏 binding signature 在公开 `ActiveArchive::open` 已返回 Authorization。库两端角色测试通过 `open(...).and_then(incremental_plan)`，由于 open 失败，不能宣称坏 archive 进入了方法体。新 CLI 真付款坏签名控制准确修改**新增第二条记录**，旧 base 前缀保持有效，并独立断言 Authorization。

另一个 unchanged 的 `active-ledger-growth` 工作流执行 `TestActiveSegmentedLedger100000BlocksBoundaryPaymentsAndRestart`：100000 本地 worker 区块包含 99998 空块和 2 个付款块，再完整 reopen 并继续到 100001。它不是 100000 笔付款，不是四节点 100000 块，也未新增调用 incremental planner。资源工作流仍是 32 笔真实付款、恢复后第 33 笔的既有资源门槛，不能说这轮测量了双归档规划、2048 ranges 或完整 1 GiB 容量峰值。

## 必需 PR 原生矩阵

| 工作流 | job 名称 | 数量 |
|---|---|---:|
| scaffold-tests | tests (ubuntu-latest/windows-latest) | 2 |
| consensus-laboratory | integration (ubuntu-latest/windows-latest) | 2 |
| orchard-consensus-integration | integrated (ubuntu-latest/windows-latest) | 2 |
| orchard-bridge | boundary (ubuntu-latest/windows-latest) | 2 |
| orchard-cryptography-laboratory | tests (ubuntu-latest/windows-latest) | 2 |
| wallet-laboratory | wallet (ubuntu-latest/windows-latest) | 2 |
| funded-wallet-consensus | funded-library 与 funded 各 ubuntu-latest/windows-latest | 4 |
| local-network-operator | operator (ubuntu-latest/windows-latest) | 2 |
| active-ledger-growth | source；growth (ubuntu-latest/windows-latest) | 3 |
| payment-resource-baseline | resources (ubuntu-latest/windows-latest) | 2 |

总计 10 个工作流、23 个 job。源码/路径触发均覆盖本轮 Orchard 改动。crate-notice-inventory 的精确路径没有变化，不应将其当成缺少的本轮 PR job；development-source 是 push/workflow_dispatch 专用，不应把它混入 10 个 PR 工作流或充当 PR 原生成功。

fmt、锁依赖和所有目标 Clippy 按旧命令保留；funded-library 本来就没有 Clippy，funded interfaces 执行 `--features local-funding-lab --all-targets -D warnings`，两个并行 cohort 合在一起取代原完整 funded Rust suite，没有测试名称筛选。两种 OS、每 job 原预算和并行线程均未变。growth 依赖 source，source 失败导致 skipped growth 不算完成。Go `-run '^$'` 的步骤只有编译信用，不能当作真实 Go case 执行。

Ubuntu 要求现有 race 和有界 fuzz；Windows 工作流中的明确 Linux 条件步骤应保留 skipped 身份并单列，不宣称执行。需要逐个实际 job 检查全部 step 元数据和最后结果，不能仅凭一个绿色 run、日志中的 `test result: ok` 或先前候选/重复 push 的结果验收。

## 最终 native 审核待办与限制

准确候选若变化，先检查新 source/tree、完整改动及验收期望是否改变。最终记录必须将 10 个 PR run、23 个 job 的候选 head、attempt、checkout 合成提交、父提交、源码树和 step 终态闭合；读取全部原始日志，核对每次编译/测试实际完结、全部 Rust harness、动态 funded 计划与 `FUNDED_COHORT_COMPLETE`、新测试逐名 `ok`、旧付款/增长/资源/四节点相关正向完成，以及所有错误、skip 或未执行部分。完整失败候选和取消结果应保留，不能用新成功覆盖掉旧失败。

本审计当前没有给出 native PASS，也不代替另一名非作者对完整生产调用链的代码审核。已有静态测试设计未发现阻止进入原生验证的覆盖接线遗漏；实现正确性、编译格式/Clippy、真实加密回归是否在时间预算内全部完成仍需原生日志裁定。

本阶段只是只读追加关系核验与计划。`incremental_backup_implemented`、`snapshot_state_import_implemented` 仍为 false，P2 仍 in_progress。成功也不会证明最新高度/共识 finality、任意瞬时敌对文件改写下的原子快照、磁盘满或真实断电恢复、Windows 目录持久化、完整容量成本、长期多机、验证者签名状态恢复或真实资金可用性。
