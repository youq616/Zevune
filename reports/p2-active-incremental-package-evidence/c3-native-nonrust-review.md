# C3 非 Rust 原生证据独立分项审核

结论：**PASS_NONRUST_NATIVE_C3**。本分项已独立核验 C3 的完整原生 CI 原件、实际 Go/Python 执行、两平台增长与资源工作负载、两份 operator bundle 的所有 payload。未发现本分项阻断项。此结论只授予下列固定 C3；完整候选验收还需要父审核者的 Rust 原生审查和独立源码审查。本审核者没有修改仓库源码、测试、工作流或设计，没有在本机运行原生工作负载，也没有执行下载的二进制。

## 固定身份与原件闭包

- PR：<https://github.com/youq616/Zevune/pull/17>。
- base：`2cc87a2207d502ac5cfe00ea52e525c1516917e5`。
- C3 source head：`cb0804e7c921a456cbbafab313b3a4a4501b8f5e`。
- C3 source tree：`21de343c12bc27cb1022ffd7ebd451abe0e61f29`。
- 实际 PR synthetic checkout：`3dfa8d77921693b9e99af5b94af198498b9422e9`；tree 与 source tree 完全相同，父提交为 `[base, C3 head]`。
- C3 source commit 的直接父提交为 C2 `f51c8db240933256870ff03c07bc68915b4ac4a1`。源身份 Git API、初始 PR API 与全部实际 checkout 日志交叉一致。

已完整读取 `c3-native/` 内 **62 份 / 2,017,223 B** 原件；逐文件重新计算 SHA-256 和字节数，确认清单与实际目录完全闭合。组成是 runs 列表 1 份、run/jobs/artifacts API 各 10 份、完整 job logs 23 份、两平台资源 ZIP/setup/result 共 6 份、operator manifest 2 份。23 份日志合计 **1,417,655 B**，无缺失或仅截断尾部的日志。原始 BOM、CRLF、时间戳均保持；去时间戳和 ANSI 仅用于派生解析。

冻结清单 `c3-native-original-manifest.json`：**10,748 B**，SHA-256 **`ce46da4d693bd973862f7401a753eeccf4af0338c03f4a775c5daf32f54e67bb`**。本审核 JSON `c3-native-nonrust-review.json`：**516,810 B**，SHA-256 **`19d6cdaf3d44a3972883a2261115171b70b21a154fdb9e7c83487c2e8d16b30e`**；其中保留每份原件摘要、完整 job/step、逐名 Go/Python 输出、实际命令、全部 fuzz 进度、增长数值、实际互通诊断和范围限制。

10 个 run、23 个 job 均为 attempt 1、`completed/success`；合计 **274 success steps / 9 skipped steps / 0 failure**。9 个 skip 都是工作流本来仅在 Linux 执行的 race/fuzz：Windows scaffold 3、bridge 2、integrated 2、consensus 1、operator 1。没有失败导致的后续跳过，也没有整 job skip。逐 job 均核到准确 Complete job name、synthetic checkout 和最终 cleanup；无 `##[error]`。

GitHub 历史 run 的嵌套 `pull_requests[].head.sha` 可以随 PR 更新而改变，因此身份授信以不可变的顶层 run/job head、commit tree、初始 PR 原件与实际 checkout 为准；没有改写 API 原件。C1 的 rustfmt 拒绝记录及 C2 的 strict Clippy 拒绝记录均继续有效、独立保存。本报告不把任一旧候选的执行结果移给 C3。

## 全量运行与实际非 Rust 范围

| 工作流与原生 run | Jobs | 本次实际非 Rust 执行范围 |
|---|---:|---|
| [scaffold-tests / 35363727199](https://github.com/youq616/Zevune/actions/runs/35363727199) | 2 | 两平台根 Go module 七个有测试包的 test、vet；Linux race 与两次真实 fuzz |
| [consensus-laboratory / 35363727392](https://github.com/youq616/Zevune/actions/runs/35363727392) | 2 | 两平台 CometBFT test/vet、真实四进程本地共识及全网络重启；Linux adapter race |
| [orchard-bridge / 35363727125](https://github.com/youq616/Zevune/actions/runs/35363727125) | 2 | 两平台根 Go test/vet、真实 Rust worker 授权；Linux boundary race 和两次真实 fuzz |
| [orchard-consensus-integration / 35363727277](https://github.com/youq616/Zevune/actions/runs/35363727277) | 2 | 两平台实际 proof/Finalize/Commit/replay、四进程共识与重启、根与 CometBFT modules test/vet；Linux 两条 race 和一次真实 fuzz |
| [active-ledger-growth / 35363727172](https://github.com/youq616/Zevune/actions/runs/35363727172) | 3 | source 编译检查 + 两平台真实 100,000 block worker 提交、边界付款、全量重放及继续提交 |
| [payment-resource-baseline / 35363727198](https://github.com/youq616/Zevune/actions/runs/35363727198) | 2 | 两平台 Python 资源验证测试、显式 resource tag 编译/vet、32+1 真实付款/恢复/OS 测量及完整证据 ZIP |
| [local-network-operator / 35363727265](https://github.com/youq616/Zevune/actions/runs/35363727265) | 2 | 两平台完整 Python 发现、实际 bundle 构建、真实 operator 工作负载及 vet；Linux 两条 race、三次真实 fuzz；全部 bundle payload 完整性 |
| [funded-wallet-consensus / 35363727269](https://github.com/youq616/Zevune/actions/runs/35363727269) | 4 | library 两平台各 13 个 Python scheduler 测试；interfaces 两平台完整 Python、实际 Python→Rust 互通、真实非零四节点付款与恢复及 Go vet |
| [wallet-laboratory / 35363727131](https://github.com/youq616/Zevune/actions/runs/35363727131) | 2 | 原件身份、全部 steps 与结果完整核对；Rust harness 语义由父审核负责 |
| [orchard-cryptography-laboratory / 35363727278](https://github.com/youq616/Zevune/actions/runs/35363727278) | 2 | 原件身份、全部 steps 与结果完整核对；Rust harness 语义由父审核负责 |

所有实际 Go 环境均显示 `go1.27.1`；工作流固定 Rust 为 `1.98.1`。已按 exact source 与 base 比较 `.github/workflows`、`scripts`、`integration/cometbft`、`internal/poolbridge`、`go.mod` 和 `go.sum`，无本阶段调小预算、改小工作负载或删减 Go/Python 覆盖。声明的命令必须与实际输出、完成步骤相符才计入覆盖。

scaffold 两平台各七个有测试包实际通过；两个 `[no test files]` command 包不计成测试。consensus 两平台各 **63 个顶层 / 106 个含子测试命名 PASS**，其普通 fuzz seed 位于该数字中，不能再称持续 fuzz。桥接 `TestGenuineRustWorkerAuthorization` 两平台实际通过（Linux 2.35 s、Windows 2.76 s）。integrated 两平台各六个顶层命名 PASS，含真实 Finalize 未持久化→worker 重启→重放→Commit→耐久重启，以及真实零金额 proof 的四进程一致性；该四进程测试 Linux 38.85 s、Windows 48.79 s，不能冒充 funded 非零付款测试。

source growth 及两平台 funded interfaces 开头的两个 Go module `-run '^$'` 只做编译。每次覆盖 12 个 `[no tests to run]` 包与三个 `[no test files]` 包，均不算实际测试运行。正式 JSON 保留逐条 `compile_only` 标记；后续具名真实工作负载另行确认。

## 8 次真正进入 fuzz 引擎及 7 条 race

下表逐项核到完整 baseline 收集、`now fuzzing with 2 workers`、正执行次数、最终 `PASS` 和对应成功 step。全部为 Linux，`-parallel=2`。实际尾部耗时可能因收尾变为 4 s，但命令预算仍是固定 3 s；没有把两者混写。

| Job / 引擎 | 命令预算 | 最终 executions | new interesting / corpus |
|---|---:|---:|---:|
| scaffold 105660992183 / `FuzzDecodeBinary` | 3 s | 131,991 | 2 / 5 |
| scaffold 105660992183 / `FuzzJournalBlockDecode` | 3 s | 193,929 | 9 / 12 |
| bridge 105660991657 / `FuzzDecodeEnvelope` | 10 s | 572,694 | 2 / 5 |
| bridge 105660991657 / `FuzzReadFrame` | 10 s | 474,533 | 3 / 5 |
| integrated 105660992723 / `FuzzPoolFrame` | 10 s | 387,330 | 4 / 5 |
| operator 105660992215 / `FuzzCanonicalPublicConfiguration` | 3 s | 12,113 | 56 / 58 |
| operator 105660992215 / `FuzzNumericLoopbackEndpoint` | 3 s | 14,412 | 45 / 47 |
| operator 105660992215 / `FuzzTestGenesisFrame` | 3 s | 85,882 | 4 / 8 |

7 条实际 race 命令分别是根 module `./...`、bridge `./internal/orchardbridge`、consensus `./app`、integrated 的两个真实 adapter tests 与 `./internal/poolbridge`、operator 的 `./labnet ./cmd/zevune-network` 与具名 `TestQuorumSignedWrongPostStateNeverPersists`。已逐条核对 package 成功输出及步骤结果，零 race 报告。7 是命令调用次数；operator 一条命令测试两个 package，不能把 package 数等同于调用数。

这些是现有短时 fuzz smoke 和指定 race 范围，不是长期 fuzz、安全完备证明或 Windows race 结果。普通 `FuzzStorageCheckpointInputs`、`FuzzStorageAccounting` 的 seed PASS 不列入八次引擎。

## Python 与真实 Python/Rust 互通

本轮 **8 次 unittest suite / 672 次重复计入的发现 / 660 PASS / 12 个按 OS 的 skip**。逐名去重是 **135 个已有测试身份**，每个至少在一个原生平台真正 PASS；不把重复调用增加为新增测试。

| 实际 suite | Linux | Windows |
|---|---|---|
| funded-library scheduler | 13 发现 / 13 PASS / 0 skip | 13 / 13 / 0 |
| funded interfaces 完整 scripts/tests | 135 / 132 / 3 | 135 / 134 / 1 |
| operator build 完整 scripts/tests | 135 / 132 / 3 | 135 / 134 / 1 |
| resource 专用 helper | 53 / 50 / 3 | 53 / 52 / 1 |

Linux 的三类 skip 是必须在 native Windows 上执行的 delete-sharing 场景，分别检验 legacy open 被 holder 阻止而 shared reader 保留准确 JSON、post-read size check、replacement identity check；它们均在 Windows 真实通过。Windows 的唯一 skip 是 Linux proc descriptor 两侧身份重检，已在 Linux 真实通过。8 份输出均按具名测试逐条计数，并与 `Ran ...`、`OK (skipped=...)` 相符，没有 unittest failure/error。

funded interfaces Linux job **105660992545**、Windows job **105660992463** 均有 `FUNDED_COHORT_COMPLETE interfaces`，随后确实执行 `scripts/check_wallet_backend.py`，不是只发现 Python 单元测试。核到真实临时加密钱包的创建/只读容量/备份恢复、genesis-bound 收款地址、后端直接拒绝错误域与非法金额且不修改文件、真实准备付款、准确 outbox 导出、pending 钱包压缩并保持相同交易、旧 receipt/重复目标拒绝、旧 LAB1 读取边界、错误密码和额外输入拒绝；最后输出真实互通成功。

每平台只有 **1 个本地 prepare 样本**。Linux total **8,221,319 µs**；Windows **12,041,777 µs**。完整 stage 值保留在正式 JSON，全部非负、schema/unit/scope 准确，总数与五阶段和的微秒截断余量在 `[0,5)`。其 scope 明确为 `local_prepare_not_finality`、`single_local_prepare_sample_not_end_to_end`。这不包含全网络付款确认，也不能统计成第二笔 outbox 测量、p95、TPS 或用户支付速度。

## 四节点工作负载和时间界限

funded 四节点真实工作负载两平台各三个具名 PASS，其中两个是 helper/genesis 校验，只有 `TestFundedWalletFourNodesAndRecovery` 是完整非零付款场景。它验证 genesis 绑定与降级拒绝、A→B→C、multi-input change、加密钱包准确 outbox、一个 validator 停止时继续付款、全网络重启、签名状态与独立 Orchard replay 一致以及重复支出拒绝。源码中的余额/fee/commitments/nullifiers 断言未删减；实际最后状态为 6 commitments、4 nullifiers、2,000 fees。

| 原生场景 | Linux | Windows | 可接受解释 |
|---|---:|---:|---|
| funded 四节点具名测试总耗时 | 61.32 s | 91.34 s | 整个本地 NO-FUNDS 测试及恢复/重启 |
| funded 两个局部付款样本 | 6,139 / 6,330 ms | 8,824 / 12,055 ms | 包含备份、rescan、签名 header 检查及独立重放的两次本地样本 |
| operator `TestActiveFundedFourNodePaymentRestart` | 66.78 s | 99.77 s | shipped active profile 命令、非零付款、重启及钱包 history reopen |
| operator `TestRealOperatorNonzeroPaymentsAndRestart` | 77.33 s | 117.91 s | shipped init/run/sync/submit、RPC 错误域拒绝、非零付款与恢复 |

两平台 operator 各 **55 个顶层 / 102 个含子测试命名 PASS**。另逐名确认 wrong-post-state 不持久化、严格 reference checkpoint、真实 pinned reference payment、journal copy/restore、离线 storage inspection/lock、取消与不确定发布等现有测试；Linux 还实际执行 wrong-post-state race。operator `labnet` 包总耗时 Linux 319.543 s、Windows 478.631 s，不能当成单笔付款时间。

所有四节点结果均是固定 validator、本机 loopback、NO-FUNDS 实验，不是公网匿名网络或生产终局性承诺。两付款样本没有样本量支持 p95、吞吐、WAN 或跨平台性能比值。基础 consensus 和 integrated 零值场景没有被记作 funded 覆盖。

## 两平台 100,000 block 增长

[run 35363727172](https://github.com/youq616/Zevune/actions/runs/35363727172) 的 source **105660991690**、Linux growth **105663826735**、Windows growth **105663826669** 全部成功。实际命令保持 `-tags=pool_e2e,funded_e2e`、准确具名测试、`-count=1 -timeout=25m -v`。

两平台均核到 9,999 / 10,000 / 10,001 / 10,002 边界的选择、preview、finalize、commit 一致，真实 A→B 后恢复 B→C、完整钱包历史、准确 outbox 与到期前重复拒绝。四次 progress 都是 25,000 / 50,000 / 75,000 / 100,000 committed blocks，对应 logical bytes **3,768,544 / 7,518,544 / 11,268,544 / 15,018,544**，segments **4 / 8 / 11 / 15**，每次 paid blocks 固定 2。

| 数值 | Linux | Windows |
|---|---:|---:|
| growth elapsed | 68,105 ms | 418,674 ms |
| full replay elapsed | 2,436 ms | 2,743 ms |
| 整个具名测试 | 78.50 s | 430.14 s |
| final committed / empty / paid | 100,000 / 99,998 / 2 | 100,000 / 99,998 / 2 |
| final logical bytes / segments | 15,018,544 / 15 | 15,018,544 / 15 |
| segment limit / continued height | 1,048,576 B / 100,001 | 1,048,576 B / 100,001 |

全部 marker 与具名 PASS 一致，源码、依赖锁未变化。这里是本地 worker 的 100,000 次 block 提交和约 15 MB 数据；不宣称 100,000 个真实四节点共识高度，也不推导 full-capacity 或 1 GiB 存储性能。

## 资源 ZIP、全部进度、事件和 OS 测量

两平台独立冻结的详细复核为 `c3-resource-independent-review.json`，**60,951 B**，SHA-256 **`2502f314c3fdf81944bf438b0e7c8925c5fb1af729daf20487e0f0bddd366460`**。本次 formal 再次确认其源身份、每份绑定 API/日志/ZIP/setup/result 原件仍与冻结摘要相同。该早先文件中的“full matrix pending”是当时状态，未追写原文；完整 C3 证据范围在本报告中授信。

Linux 原 ZIP **9,249 B**，SHA-256 `41662467bc9043f6478db51b73aa1045f36829168cfdf9a39209b113da0323a8`；Windows 原 ZIP **9,450 B**，SHA-256 `bb3adae475200be7ea3d266fe78a90fd12b14d4dc8db70a323ba2da3f344bdf2`。两个 ZIP 均恰好只有 setup/result 两个成员；完整读出字节等于保留的原件，并与 artifact API size/digest 一致。result 原件分别 **130,165 / 131,255 B**。初始 setup 的 `not_started` 是首次观测，不能当成最终执行状态；两份最终 result 均 `passed`、Go exit 0、failures 空、无 unfinished operation、无 uncertain commit。

已核每平台全部 **9 events、362 progress records（181 个准确 start/end 操作对）、18 memory samples**。9 checkpoint 精确为 genesis、payment_8、payment_16、payment_24、payment_32、worker_reopened_32、wallet_recovered_32、pending_restored_33、complete_33，后四个高度分别 32/32/32/33。逐操作身份、顺序、对应付款号、commit 状态、耗时和结果摘要都校验，无缺口、重复或越序。pending_33 的未提交状态没有伪称 height 33。

终态 14 个 checks 全 true：真实付款、summary 一致、capacity accounting、worker/scenario 完整 replay、wallet backup、准确 outbox、pending 保留并清除、恢复后新付款、wallet records/bytes、物理帧以及拒绝时不变更。两平台最终都是 **33 paid blocks、每付款 2 actions、68 commitments、66 nullifiers、33,000 fees、308,756 logical bytes、1 segment、308,616 tail bytes**；两个钱包 **52 / 51 records、1,713,368 / 1,680,420 B**。实际 Go result 编码的 SHA-256 重新生成后与原 result 摘要一致。

| OS 原生资源值 | Linux | Windows |
|---|---:|---:|
| workload total | 138,872 ms | 235,796 ms |
| supervised process elapsed | 138,929 ms | 236,188 ms |
| supervisor elapsed | 139,042 ms | 238,282 ms |
| worker 第 1 代 lifetime peak | 11,522,048 B | 13,053,952 B |
| worker 第 2 代 lifetime peak | 11,685,888 B | 12,783,616 B |
| scenario lifetime peak | 176,529,408 B | 117,739,520 B |

每一代 PID/creation identity/共同父进程保持一致，新 worker generation 身份不同且创建更晚；每个 memory sample 的 current > 0、lifetime peak ≥ current，同代 peak 单调，全部在原定每进程 **1,073,741,824 B** 内。原有 Go 1,200 s、supervisor 1,230 s、handshake 15 s、scenario response 90 s、worker start/request 各 60 s 等预算不变。三个注册子进程退出得到确认；原件明确 `precheckpoint_child_tree_cleanup_confirmed=false`，此处不把 retained identities + Go 正常 cleanup 宣称进程树沙箱。

这里测的是现有 **32+1 真实付款资源基线**，不是本阶段新增 incremental package CLI 的资源测量。OS resident/working set 与每代 lifetime peak 不等于私有 heap、阶段峰值或机器总内存；Python supervisor 与 Go coordinator 不在被测角色内。scenario 包含 prover、cache、history、两个钱包及 Argon2。结果没有证明分配强制限额、冷磁盘性能或满容量行为。

## 两份 operator bundle 的全部 payload

详细复核 `c3-operator-independent-review.json`：**12,050 B**，SHA-256 **`19759c64009d7cc2d893210afd17484ba9699a38517e5435f98b284ee18b65c0`**。两原 ZIP 完整哈希、metadata、builder receipt 和 manifest 已核对；各 ZIP 恰好 manifest + 五个扁平成员。对所有五 payload 逐块读完、重新算 size/SHA-256，并由完整 ZIP 读取完成 CRC 校验，非只看成员名或 manifest。

| 原件 | Linux | Windows |
|---|---|---|
| ZIP bytes | 22,851,984 | 22,388,463 |
| ZIP SHA-256 | `3e69680f0523548e7445c39ff0d3c0eaca85ce89169cd54843f1ec7e71f6436b` | `087f26324e3769cc68c5fbea9bbfce65bfb09f08e7634c32508c518a55dd22fc` |
| 五 payload 解压字节合计 | 47,866,947 | 44,563,437 |
| 原 manifest bytes | 1,288 | 1,302 |
| manifest SHA-256 | `6d13f013cf5c20bfb216d77cba3fc93141b003ed27950bba2fc87982cbe56b4f` | `e51793f802589fd4018765b2344902935bdcc4f7d9c40debbc16182a9751bcc1` |

五 payload 为三可执行文件 `zevune-network`、`zevune-pool-worker`、`zevune-wallet-local`（Windows `.exe`）及 `zevune_wallet.py`、`LOCAL_NETWORK_OPERATOR.zh-CN.md`。两个文本成员与 C3 exact Git blobs 逐字节一致，三个二进制只验证 ELF/PE 容器与摘要，未执行。

manifest 的 `source_commit` 正确绑定实际 synthetic `3dfa8d...`，`source_tree` 为 C3 `21de343...`；不是误用 source head 填入 checkout commit。format 为 `zevune-local-bundle-2`，build_source 为 `isolated_exact_git_blobs`，scope 为 `single_machine_fixed_validator_test_lab`，toolchains 为实际固定 Go/Rust。`real_funds_allowed`、`public_network_supported`、`network_anonymity_implemented` 都为 false。

原 ZIP 只留 scratch payloads；仓库只归档公开 metadata、原 manifest 及本派生摘要，不复制二进制。这是完整性与源码身份核验，没有独立重建二进制，不能称 code signing、可复现构建证明或外部审计。

## 审核界限

本分项覆盖固定 C3 的完整原生非 Rust 证据，结论 **PASS_NONRUST_NATIVE_C3**。源码预算、所有实际测试与 artifact 都按本轮重新核验；C1/C2 的拒绝原文和其有限成功范围不变。Rust 测试名称、harness 分类、默认/feature cohort 覆盖由父审核者独立作结；本报告不另行发放完整阶段、合并、生产、真实资金、公网匿名性或密码学外部安全审计的许可。
