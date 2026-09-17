**PASS_NATIVE — PR #15 准确 C2 的完整原生矩阵及新增测试执行审计通过，没有未关闭的本范围阻断项。**

审核日期为 2026-09-17，独立任务为 `/root/p2_plan_native_audit`。本审核者没有编写候选实现、测试、设计或 workflow，没有修改仓库或执行合并。结论在全部 10 个 PR workflow、23 个 job 和完整日志终态到齐，并完整阅读另一独立审核者的非 Rust 原文后形成。它只适用于下列准确运行树及只读追加关系计划阶段，不将 CI 成功解释为不存在任何缺陷。

| 身份 | 准确值 |
|---|---|
| 仓库 / PR | `youq616/Zevune` / [#15](https://github.com/youq616/Zevune/pull/15) |
| base | `0927af157a3cc35abde14b036bc50a99a793a32b` |
| C2 source | `2020c7314a996769b33706754405c0976ce7c50a` |
| C2 tree | `a25d4752d49f366f9aff047116eeffd9b1f6ae1d` |
| 实际 PR checkout | `2d208360ab665fbe82b57d205cf07e789f06164b` |
| 合成提交关系 | parents 精确为上述 base、C2；tree 与 C2 一致 |

本任务独立阅读了 `AGENTS.md`、`docs/STAGE_REVIEW.zh-CN.md`、完整新增设计、两个新增库测试文件、整个新 CLI 测试文件、既有 `active_flow_tests.rs` 的新增断言及真实付款/轮转/10001/10002 调用流程、对应物理层与公开 API 实现及旧 archive 验证调用者。还阅读了全部 12 个 workflow、Cargo feature/test 接线和完整 funded 调度脚本。原 C1 预期报告保持原文，其预期计数在这里逐项由准确 C2 的实际运行证实；预期本身没有被当作运行证据。本报告不替代另两份非作者实现审查。

本地没有执行项目 Go/Rust 测试或下载的原生二进制。全部原生执行信用来自 GitHub 的准确候选终态元数据和完整日志；本地仅用 Python 读取、比较、解析和重算保留证据的哈希。审核不依据 root 的 `derived-log-summary.json` 作裁定。

**准确矩阵、原件和失败历史。**

Git API source/tree/parents、10 个 run 的顶层 head、23 个 job 的 head、attempt、状态及各日志真正 checkout 相互一致。10 个 run 均为 `pull_request`、attempt 1、completed/success；23 个不同 job 全部 success。所有 23 份日志唯一实际 checkout 都为上述合成提交，包含作业正常结束与清理，没有 `##[error]` 或未完成的 Rust harness。

| 必需 PR workflow | 实际 run | 完成 job 数 |
|---|---|---:|
| local-network-operator | [35231320198](https://github.com/youq616/Zevune/actions/runs/35231320198) | 2 |
| orchard-consensus-integration | [35231320202](https://github.com/youq616/Zevune/actions/runs/35231320202) | 2 |
| scaffold-tests | [35231320231](https://github.com/youq616/Zevune/actions/runs/35231320231) | 2 |
| orchard-cryptography-laboratory | [35231320272](https://github.com/youq616/Zevune/actions/runs/35231320272) | 2 |
| funded-wallet-consensus | [35231320287](https://github.com/youq616/Zevune/actions/runs/35231320287) | 4 |
| payment-resource-baseline | [35231320296](https://github.com/youq616/Zevune/actions/runs/35231320296) | 2 |
| orchard-bridge | [35231320339](https://github.com/youq616/Zevune/actions/runs/35231320339) | 2 |
| consensus-laboratory | [35231320342](https://github.com/youq616/Zevune/actions/runs/35231320342) | 2 |
| active-ledger-growth | [35231320368](https://github.com/youq616/Zevune/actions/runs/35231320368) | 3 |
| wallet-laboratory | [35231322405](https://github.com/youq616/Zevune/actions/runs/35231322405) | 2 |

逐个 job 的名字、原件身份、checkout、全部步骤和 Rust target/result 记录在伴随 JSON。`workflow-run-list.json` 的 `total_count=10` 与实际列表一致；每个 jobs API 的 total_count 与完整返回列表一致。growth 的 source 及两个原生 growth job 都实际完成，不再是依赖失败的未展开占位。`development-source` 是 push/workflow_dispatch 范围，`crate-notice-inventory` 的特定触发路径未变化，均未混入这 10 个 PR workflow。

全部步骤为 **274 success、9 skipped**。9 个 skip 都是原有 Windows OS 条件：scaffold 3、consensus 1、integrated 2、bridge 2、operator 1，分别对应 race/fuzz；相应 Ubuntu 步骤实际运行。没有把 Windows skip 当成执行成功。10 个必需 workflow、funded 调度器、Rust manifest/lock/toolchain 及存在的 Go module/lock 输入共 17 文件，与 base 逐字节一致，预算、分区和验收命令未降低；根 Go 模块原本没有 `go.sum`。

`c2-native/` 的 23 份完整原生日志共 **1,385,937 B、16,432 解码行**。加上 10 份 run、10 份 jobs 和 1 份完整 run-list，合计 **44 原件、1,698,441 B**。本任务读取全部日志原始字节并独立重算 44 项长度/哈希，与冻结 manifest 全部一致；解析时保留原始 BOM/CRLF 的字节身份。manifest 为 7,136 B，SHA256 `c4887a55df538021d840ea048f5ebbe7977e0987d0055ea52abf9afd17500295`。

C1 的历史结论仍为 `REJECTED_NATIVE_C1`：10 PR run 中 8 failure、2 success，返回 22 job，实际为 17 formatter failure、4 有限范围 success、1 未展开 skipped growth；完整 21 日志中没有 Rust 测试完成结果。17 份失败日志的同一格式差异仅涉及 4 文件、10 hunks。C1 两个平台资源包只有 `not_started` setup，不授予实际资源执行信用。C2 只应用这 4 文件的格式修复，没有改变测试语义或 workflow，然后以新的准确 source/checkout 全量运行成功。此过程关闭 C2 的格式阻断，但没有覆盖或追认 C1。原拒绝 Markdown/JSON 保持冻结。

**Rust 全量执行、分区和新增测试。**

下表数字均来自完整原生日志中的实际 `running N tests`、逐名 `ok` 和对应最终 result，不是测试定义数推算。Cargo 输出可能跨 stdout/stderr 交错，解析按目标启动顺序对应完成结果，并核对每个 harness 的命名结果总数；`--nocapture` 中间插入指标的测试也核对到最终 `ok`。所有 196 个 result 均为 0 failed、0 ignored、0 measured、0 filtered。

| 默认 Rust 套件 | Ubuntu job | Windows job | 每 job 实际结果 |
|---|---:|---:|---|
| integrated | 105235852428 | 105235852619 | Ubuntu lib 154 / 总 168；Windows lib 146 / 总 160 |
| cryptography | 105235853115 | 105235853346 | 同上 |
| bridge | 105235853864 | 105235854234 | 同上 |
| wallet | 105235862028 | 105235862497 | 同上 |

8 个默认 job 每个都有 19 个完整 harness result，同平台四次默认库的测试名称集合完全相同。新 CLI target 在默认 feature 下的结果为 **0 tests**；这 8 个 job 没有执行新 CLI 的 7 个用例。

| funded 分区 | Ubuntu 实际完成 | Windows 实际完成 |
|---|---|---|
| library | job 105235853245；173 passed，193.63 s；1 lib result | job 105235853314；165 passed，374.41 s；1 lib result |
| interfaces | job 105235853237；63 passed，21 results；新 CLI 7 tests 用时 87.21 s | job 105235852975；63 passed，21 results；新 CLI 7 tests 用时 101.85 s |

每个平台 funded-library 的名称集合包含完整默认库，并多出 19 个原有 feature 专属用例；新增 14/13 个库用例也全部逐名执行。library job 的动态计划为完整 `--lib`，最终有 `FUNDED_COHORT_COMPLETE library`。

两个 interfaces 的实际动态计划均基于 Cargo metadata 枚举 **5 个 bin、15 个 integration target**，包含 `active_incremental_cli`，并另跑 doc harness，合计 21 个 result。命令保留 `--locked --release --features local-funding-lab` 和 `--test-threads=1`，没有测试名称筛选；两个 job 均到达 `FUNDED_COHORT_COMPLETE interfaces`，后续实际 Go/Python 与最后清理也完成。两个 cohort 合起来完整覆盖 funded 库和接口，不能单凭接口绿灯替代库。

8 个默认 job 的 strict Clippy，以及两个 interfaces 的带 `local-funding-lab` strict all-target Clippy 均实际结束，保留 `-- -D warnings`；funded-library 按原 workflow 没有独立 Clippy 命令。fmt、编译、测试和最终源码/锁文件无漂移检查均成功。总计 12 个执行 Rust 测试的 job、196 个完整 harness；JSON 中 1,776 passed 是跨平台及 workflow 重复运行的总执行次数，不能表述为 1,776 个不同用例。

新增库源码是 **15 个定义：5 个物理层、7 个通用公开 API、2 个 Unix、1 个 Windows**。因平台 gating，Ubuntu 每个相关库 job 实际 14 个，Windows 13 个；10 个相关默认/带 feature 库 job 都与其平台逐名吻合。它们支持的具体范围如下：

- 物理层验证合法 short-read、Interrupted 重试/偏移、EOF/异常计数/I/O/溢出拒绝、空计划/旧尾增长/真实 1 MiB 物理轮转、超过 64 KiB 后的旧字节差异、封闭旧段末字节、捕获长度，以及分配 callback 失败不得返回部分计划。这些合成 frame 只经过私有物理存储路径，不能当作真实授权或付款证据。
- 通用 API 使用普通 prepare/commit 空块与独立字节期望，检查 genesis/非零、同路径及异路径相同内容、共享锁/多 reader、各自独立完整验证成功的同高和更高分叉/回退、错误网络/legacy/pin、重复调用重新验证、原地同长度有效历史替换，以及最后重检拒绝晚发字节或 namespace 修改。更高合法分叉具有正确独立 pin，并实际到达物理前缀的 Stale 拒绝，不以无效 pin 替代。
- Ubuntu 实际执行 retained-name 替换、hard link、缺失和 symlink 测试；Windows 实际执行保留句柄期间两端 rename 拒绝、drop 后允许。外部故障注入造成的条目变化按原样保留，没有被测试或 API 修复。没有 macOS 原生结论。

新 CLI 的以下 **7 个名字在两个 funded interfaces 日志中均逐名 `ok`**，其中真实付款测试不是仅作编译或 feature 接线：

1. `active_incremental_cli_genesis_and_same_content_have_exact_empty_plan_schema`
2. `active_incremental_cli_individually_valid_forks_rollback_and_networks_fail`
3. `active_incremental_cli_options_profiles_and_legacy_pins_are_rejected_readonly`
4. `active_incremental_cli_readonly_stdout_fails_with_writable_and_empty_controls`
5. `active_incremental_cli_real_payments_restore_spend_and_rehashed_bad_signature`
6. `active_incremental_cli_writer_locks_reject_and_shared_readers_coexist`
7. `active_incremental_cli_wrong_pins_missing_and_damaged_bytes_fail_on_either_side`

这些测试独立构造准确 ASCII 单行 JSON schema/tuple、检查普通调用前后整个 fixture 的成员和字节相同，并对可写 receipt 单独限制允许变化；同时运行追加计划和空计划的可写正对照及只读 stdout 失败，覆盖双方 pin/截断/追加/缺失/多余条目、writer 锁与多 reader。一般输出 I/O 失败仍可能写出部分 JSON，不能由只读 stdout 的零字节控制推出所有失败原子输出。

**既有真实付款流程中的新计划断言。**

原有 4 个 `pool::active_flow_tests` 在两个 funded-library 中全部逐名通过：域/legacy 非变异、写失败毒化、legacy 10000 上限，以及真实付款轮转/10001/10002。默认套件没有被用于授予这四个 feature 专属测试的信用。

`real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` 的真实付款、签名验证、双花拒绝、1 MiB 默认轮转、原 archive/restore 和余额/费用断言保留。新增三段计划断言也实际随主测试执行：第一笔付款把不变旧尾保留并产生新段 range；恢复历史后在 10001 的 B→C 对应精确旧尾后缀；10001 再恢复后提交 10002 空块，计划恰为 150 B 后缀。测试副本仅按 ranges 重建，必须逐文件等于 later，再正常打开并完整 verify；这是测试验证方法，不是生产增量恢复功能。

重算 checksum/布局 pin 的坏 binding signature 在公开 `ActiveArchive::open` 已返回 Authorization。库的 `open(...).and_then(incremental_plan)` 不能说明无效 archive 进入了规划方法体。新 CLI 控制修改新增第二条付款记录而保留有效 base 前缀，也独立核对 Authorization 拒绝。

**非 Rust 独立复核的整合及实际边界。**

`/root/p2_plan_adversarial_review` 的正式非 Rust Markdown 已全文阅读，MD 与伴随 JSON 均独立重算哈希并与冻结值一致；其结论为 `PASS_NONRUST_NATIVE`，findings 空。它复核 19 个范围内 job：17 个 Go 相关，其中 source 仅编译、16 个实际执行 Go 工作量，另外 2 个 Python scheduler job。它没有替代本任务的 Rust/完整矩阵判定。本任务已独立核对全部 23 日志身份及终态，以下场景细节结合该独立原文及其行为来源/原件关联采纳。

- 根模块、CometBFT/真实 Orchard adapter、operator 的适用 test/vet/race 实际完成；Linux 有 8 次进入 `now fuzzing`、产生非零 execs 并 PASS 的真正 bounded fuzz。普通 fuzz seed、`go test -run '^$'` 和 `go test -c` 本身都没有冒充实际场景运行。Python 135 discovered 按 Ubuntu 132 passed + 3 skip、Windows 134 + 1 拆分；53 suite 为 50 + 3 / 52 + 1，scheduler 两端均 13 passed。
- active operator 的 A→B 后全 4 节点关闭/恢复，之后才完成 B→C，Ubuntu 60.75 s、Windows 72.20 s 均通过。旧 funded/operator 流程的两笔付款发生在全 4 节点重启之前，保留这个顺序区别。funded interfaces 的真实四节点主场景两端也完成，Ubuntu 64.95 s、Windows 83.51 s；quorum 签名但错误 post-state 不得持久化的场景及 Linux race 通过。健康/preflight/AppHash/单机 ApplyBlock 不是独立 finality 证明。
- growth 两端实际完成 100000 本地 worker 块（99998 空块、2 paid），15 段、15,018,544 逻辑字节，完整重开后继续到 100001；主测试 Ubuntu 64.85 s、Windows 601.59 s。独立 scenario 逐块回放到 10002，不能宣称独立 scenario 回放全部 100000，也不能把此用例称为 100000 笔付款或四节点 100000 高度。
- 两平台资源原始 ZIP/API digest、setup/最终 JSON、准确 checkout、完整 native 日志与严格离线校验一致：9 checkpoints、362 progress、181 完整操作，32 笔后实际恢复再付款至 33；最终 33 paid、68 commitments、66 nullifiers、308,756 B、1 段。setup 仍只写 `not_started`，执行信用来自最终 JSON 和实际测试。生命周期 resident/working-set 样本绑定进程 generation/PID/创建身份并通过预算；它们不是阶段峰值、私有堆、全部进程总量或严格分配限制，也没有测量新增 archive/planner 的成本。
- 两平台 operator 包的全部 5 个 payload 与 manifest/ZIP/API 来源逐项验证，文本成员另与准确 Git blob 相等；没有本地执行二进制。完整性与构建来源关联不等于独立可复现构建或发布者签名证明。资源记录的 `precheckpoint_child_tree_cleanup_confirmed=false` 保留，不扩大为全子树清理或进程沙箱保证。

上述非 Rust 完整原件、资源进程观测与各包成员细节均保留在其正式报告，未复制成另一份相互漂移的结果表。与本任务的 Rust 执行、原有 1 MiB/10001/10002 和新增 CLI 证据合并，没有发现验收缺口或需重新运行的未关闭失败。

**冻结审核原文及验收限制。**

| 原文 | bytes | SHA256 |
|---|---:|---|
| `c2-native-audit.json` | 220066 | `f42aff22f05e2a2e9061e2c3a10b111bfbd45509d589361e341c2ac4b9061591` |
| `c2-native-audit-structural.json` | 212004 | `4d99b635fed749c75cbf68af0b3555a7c4541058854aab484fde562524c03f54` |
| `c2-native-nonrust-review.md` | 17275 | `472e869ca2d68ea153b7a1468ae63d9292072783a778d4bbbbff93b994e83d74` |
| `c2-native-nonrust-review.json` | 83765 | `c29bb57bf50f43aeaee32c3a6b757733d04d4302a4aa51f84d358286da142987` |
| `c1-native-audit-rejected.md` | 9372 | `f7d438dd151f3d970f91b5f8e9ebab16760ee9fd301e47520081ebb6feeac2a4` |
| `c1-native-audit-rejected.json` | 138923 | `6f471f733afc13455ec0ff9f864723291211cc10a965cb548d9591370a6d0172` |

结构化中间记录刻意保持 `STRUCTURAL_CHECKS_COMPLETE / SEPARATE_REVIEW_REQUIRED` 原值；最终 JSON 的 `PASS_NATIVE` 是本任务完成源码/实际日志审计并阅读全文非 Rust 原文之后给出的明确判断，不是原自动解析状态。新候选树不能沿用此结论；后续纯文档或合入关联仍需按仓库要求单独核对。

本阶段只是双独立可信 `ZVARCP01` checkpoint 的只读追加关系验证和有界计划。CLI 两次 open 加上方法中的双方完整验证，实际共四次完整 replay；对已打开 archive 调用方法增加两次，每个新 verifier 的授权缓存起始为空。CI 通过没有证明 replay 时间、磁盘占用或 planner 资源成本降低。

`incremental_backup_implemented=false`、`snapshot_state_import_implemented=false`，P2 仍为 `in_progress`。本轮不覆盖完整容量/2048 ranges 的原生资源成本、64 项 cache 边界、真实 OOM/磁盘满/物理掉电、Windows 目录持久化、长期多机、pruning/migration、验证者签名状态恢复，或任意敌对瞬时改写下的原子快照。实际付款均为临时 NO-FUNDS 实验；独立代理审查及 CI 不等于外部密码学/安全专家审核，也不授予真实资金或公开部署就绪结论。
