# C7 原生 CI 独立总审核

**结论：PASS_NATIVE_CI。准确 C7 的全部 10 个 required PR 工作流、23 个逻辑必需 job 均完成 success，完整执行与原件审核通过，无本范围未解决阻断。** 本结论只接受下列准确候选的原生验证；代码设计与独立源码审核、整阶段接受及合并决定由根代理综合。本人未写候选源码、测试或工作流，未发起 CI/重跑，也未在本地冒称执行 Rust/Go。

| 身份 | 准确值 |
|---|---|
| PR | [youq616/Zevune #13](https://github.com/youq616/Zevune/pull/13) |
| Base | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| Source | `de474720431daf33afd4a7ebc32de2d230344a5a` |
| Tree | `e4dd17dfb1efd0e3ca20441168b62b72b6fc3108` |
| Parent | `88146d54f2eaac39958ceaaea9e13f71832d536e` |
| 原生 PR checkout | `00d4442b12cb72344ffa5bea101eb7142ab03270` |

GitHub 原生 source 与 synthetic Git 对象、PR 信息及每份 checkout 相互一致。synthetic 的两父提交为准确 base/source，tree 与 source tree 完全相同。全部原生 run 的 event 为 pull_request、head 为 C7、attempt 为 1，全部 check-run、direct steps 与最终 jobs API 逐项对应。十个工作流与 base 的文件字节/摘要相同；本轮未削减测试、放宽预算、修改依赖或把旧运行结果移入接受范围。

## 完整矩阵与证据

| 工作流 | 原生 run | 全部 job | 结果 |
|---|---|---|---|
| scaffold-tests | [35211515211](https://github.com/youq616/Zevune/actions/runs/35211515211) | tests (ubuntu-latest)：105169884469；tests (windows-latest)：105169884871 | 2 / 2 success |
| consensus-laboratory | [35211514974](https://github.com/youq616/Zevune/actions/runs/35211514974) | integration (windows-latest)：105169883452；integration (ubuntu-latest)：105169883820 | 2 / 2 success |
| orchard-consensus-integration | [35211515036](https://github.com/youq616/Zevune/actions/runs/35211515036) | integrated (ubuntu-latest)：105169884577；integrated (windows-latest)：105169884951 | 2 / 2 success |
| orchard-bridge | [35211514980](https://github.com/youq616/Zevune/actions/runs/35211514980) | boundary (ubuntu-latest)：105169884058；boundary (windows-latest)：105169884404 | 2 / 2 success |
| orchard-cryptography-laboratory | [35211515020](https://github.com/youq616/Zevune/actions/runs/35211515020) | tests (ubuntu-latest)：105169883708；tests (windows-latest)：105169884041 | 2 / 2 success |
| wallet-laboratory | [35211514997](https://github.com/youq616/Zevune/actions/runs/35211514997) | wallet (ubuntu-latest)：105169883281；wallet (windows-latest)：105169883394 | 2 / 2 success |
| funded-wallet-consensus | [35211515055](https://github.com/youq616/Zevune/actions/runs/35211515055) | funded-library (ubuntu-latest)：105169883800；funded (ubuntu-latest)：105169883929；funded (windows-latest)：105169883969；funded-library (windows-latest)：105169883974 | 4 / 4 success |
| local-network-operator | [35211515104](https://github.com/youq616/Zevune/actions/runs/35211515104) | operator (windows-latest)：105169884063；operator (ubuntu-latest)：105169884503 | 2 / 2 success |
| active-ledger-growth | [35211514958](https://github.com/youq616/Zevune/actions/runs/35211514958) | source：105169883377；growth (windows-latest)：105173493547；growth (ubuntu-latest)：105173493571 | 3 / 3 success |
| payment-resource-baseline | [35211515004](https://github.com/youq616/Zevune/actions/runs/35211515004) | resources (windows-latest)：105169883365；resources (ubuntu-latest)：105169883621 | 2 / 2 success |

23 份完整原生日志共 **1,360,077 B**，另各有原始 check-run/direct-steps metadata；十个工作流各保留最终 run 与 jobs 原件。实际步骤共 **274 success、9 skipped**，无 failed/cancelled；没有重跑、别名重复或跨候选借用。每份日志先写临时文件、核对完整字节和 SHA，再原子发布，正式日志与 metadata 发布后未改写。最终再次逐份核对大小、摘要、准确 checkout、原生完成步骤及子审核输入，全部一致。

[机械身份/矩阵交叉核对](matrix-crosscheck.json)保留每个 job 的完整步骤、原生起止、日志摘要和 Rust 结果数量；该文件形成时的“semantic reports pending”是当时状态，最终语义接受由本报告及两份已固定子审补齐，未改写早期原件。[最终状态观察](final-run-status-observation.json)时间为 2026-09-17 11:05:45.204 UTC，10 个 PR run 全部 success。单独观察的 11 个 push 工作流亦 success，但没有收集重复 push 日志或计入 PR 门槛。

早期 API 返回 queued/in_progress 只作为工具当时返回状态，不能推断真实任务尚未开始。实际执行时间以完整日志和最终原生 metadata 核对；本次不推测状态延迟机制。

## 独立语义审核与 Rust 实际结果

主审核已全文阅读并复核 [Rust 正式报告](native-rust-evidence-review.md)和[非 Rust 正式报告](native-nonrust-evidence-review.md)，配套 JSON 固定详细行号、时间、测试名、原件摘要及限制。前者独立核对 **12 个 Rust job**，后者独立核对 **17 个非 Rust 范围**；其中 6 个混合 job 重叠，集合并集恰为 **23 个独立 job**，不是 29 个任务。两位子审核均未编写候选代码；主审核独立维护原生收集、身份、矩阵、步骤、原件和核心场景交叉核对。

| Rust 范围 | 平台 | job | 完整结果 / passed | lib 或 CLI |
|---|---|---|---|---|
| crypto / default | ubuntu | 105169883708 | 18 / 154 | 140 |
| crypto / default | windows | 105169884041 | 18 / 147 | 133 |
| wallet / default | ubuntu | 105169883281 | 18 / 154 | 140 |
| wallet / default | windows | 105169883394 | 18 / 147 | 133 |
| bridge / default | ubuntu | 105169884058 | 18 / 154 | 140 |
| bridge / default | windows | 105169884404 | 18 / 147 | 133 |
| integrated / default | ubuntu | 105169884577 | 18 / 154 | 140 |
| integrated / default | windows | 105169884951 | 18 / 147 | 133 |
| funded / library | ubuntu | 105169883800 | 1 / 159 | 159 |
| funded / library | windows | 105169883974 | 1 / 152 | 152 |
| funded / interfaces | ubuntu | 105169883929 | 20 / 56 | CLI 7 |
| funded / interfaces | windows | 105169883969 | 20 / 56 | CLI 7 |

八个 default 均有 17 harness 加 doc 的 **18 个完整结果**；Ubuntu 各 154 passed（lib 140），Windows 各 147 passed（lib 133）。平台库净差 7 来自 11 个 Unix-only 与 4 个 Windows-only 的准确 cfg；不是 ignored。默认 active_recovery_cli 为 **0**，没有计作 funded 的 7。相同平台四次库名称集合一致；日志中 stdout/stderr 的两处先后交错由 FIFO 按完整目标匹配，不把下个 announcement 错算为前一个结果。

双 funded-library 各执行无名称过滤的完整 `--lib` cohort：Ubuntu **159 passed / 206.84 s**，Windows **152 passed / 413.20 s**；均出现完整结果及 `FUNDED_COHORT_COMPLETE library`。这两个 job 本身不设 Clippy，其余十个 Rust job 的严格 Clippy 实际完成。双接口按 cargo metadata 自动枚举 5 bin + 14 integration，再独立 doc，均 **20 结果 / 56 passed**，末尾有完整 interfaces 标记。合计 **186 个完整 Rust 结果**的 failed、ignored、measured、filtered 均为 0；重复运行次数不增加唯一功能覆盖。

新增 archive 用例在相关库各实际执行 Ubuntu **18** / Windows **17**，另每份库有 **1** 个新 fixed-key 用例。全部库新增定义跨平台共 20 个，CLI 新增定义 7 个，共 27 个；每个平台配置后的实际数量另计。两平台 CLI 各完整 **7**，Ubuntu 68.27 秒、Windows 124.60 秒。源码预期、自动目标枚举、全部原生精确 `ok` 名称和完成标记逐一对应，未用筛选后的局部结果替代默认或 feature 完整套件。

关键验收实际执行路径如下。

- `wire::fixed_key_tests::concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold` 在十份相关库均实际 ok：一次 genuine fixture、固定公共验证 key、各实例独立空 VerifiedCache、四并发 verifier、可解码 proof/binding-signature 改动 Authorization 拒绝且不缓存。线程使用已初始化的 key，不宣称冷 OnceLock 初始化竞争覆盖。三次完整 replay 及每个 verifier 的新授权缓存仍保留。
- 双 funded-library 的全部四个 active_flow 均完成。真实 10001/10002 增长用例包含真实付款、默认段轮转、完整备份/恢复和续付；原样保留的 44 行交换两个已存在段回归在原 pin 与重算 pin 下都拒绝 Corrupt，并检查字节/命名空间不变。另一个真实坏 binding signature 用例在重算 checksum/pin 后明确 Authorization 拒绝；不把两种拒绝混为一种证据。
- 双平台 CLI 真实备份/恢复/接收方续付用例保持两次 genuine payment-proof 构建。第七项 stdout 回归完整执行 checkpoint、verify、backup、restore 四个 mode，包含 readonly File 真写失败探针、精确 exit 1、可写 File 的成功 JSON 对照、源/sink 不变、完整目标副本及后验 verify。Ubuntu raw 802、Windows raw 788 是该完整测试的成功行；四个 mode 不额外计作四个测试。

## 非 Rust、增长、付款与平台条件

Go scaffold/root 回归、CometBFT adapter、Go↔Rust bridge、Python↔Rust 钱包、operator、活动增长及资源工作流均由完整命令输出和源码语义对应。compile-only 的 `-run '^$'`、无测试命令包、helper 的直接返回、普通 fuzz seed harness、嵌套子案例分别记账，没有虚构为独立真实网络场景。

双 consensus 各 59 个顶层 Test、4 个 seed harness、43 个子案例；双 operator 各 51 个顶层 Test、4 个 seed harness、47 个子案例。Ubuntu 的 race 与八次实际 bounded fuzz campaign 都有完整执行输出：scaffold 两次 3 秒（7690 / 151359 exec）、bridge 两次 10 秒（497102 / 388902）、integrated 一次 10 秒（385029）、operator 三次 3 秒（9394 / 11094 / 49666）。这些是本次观察，不是安全覆盖率或性能承诺。

| Windows job | 原工作流条件跳过的步骤 |
|---|---|
| operator (windows-latest) / 105169884063 | Race and bounded fuzz checks |
| boundary (windows-latest) / 105169884404 | Boundary race checks；Bounded decoder fuzz checks |
| integrated (windows-latest) / 105169884951 | Real adapter race checks；Local IPC race and bounded fuzz |
| integration (windows-latest) / 105169883452 | Adapter race checks |
| tests (windows-latest) / 105169884871 | Race detector；Bounded decoder fuzz smoke test；Bounded journal decoder fuzz smoke test |

以上恰为九个原生 step，均由原 workflow 的 Linux 条件解释，没有计作 Windows 实际通过。Python 完整 135 项在 Linux 为 132 ok + 3 Windows 文件共享 skip，在 Windows 为 134 ok + 1 Linux proc skip；资源 Python 完整 53 项分别 50+3 / 52+1。Windows 的三个文件共享/替换测试实际 ok。Rust 没有忽略项；没有其他未解释的跳过。

必须区分付款顺序：funded interfaces 的 `TestFundedWalletFourNodesAndRecovery` 以及 operator 的 `TestRealOperatorNonzeroPaymentsAndRestart` 都在全网重启前完成 A→B→C。operator 套件中**重启后新付款**的证据来自独立的 `TestActiveFundedFourNodePaymentRestart`：A→B、全四节点停止/重启、B→C，两平台实际 74.50 / 77.93 秒 PASS，不能把该信用归给前一项。

双增长各真实提交 **100000 个本地 worker 块 = 99998 空块 + 2 付款块**，第二笔在 10001；完整磁盘布局为 15 段、15,018,544 logical bytes、每段上限 1,048,576。恢复后的 **100001 是空块**。Ubuntu growth/replay 为 64090 / 2428 ms，Windows 464635 / 3257 ms，测试本身分别 74.62 / 478.15 秒。这里不是四节点 100000 共识高度、100000 笔付款、超过 64 MiB 或全容量证明，也不换算付款吞吐。

## 原生 artifact 完整性与归档边界

两份小 resource ZIP 原字节及其原 API metadata、两成员解包原文完整保留。Ubuntu artifact **10493495324：9297 B / `f5022d99ae137c45cfa31ca4c769eb642304706f4a46fc4370d708fd65b22d9d`**；Windows **10494490178：9470 B / `8e298238be965a850136001b11926fd84296420cd4148a5ecf5452defa0b1865`**。整体 digest 与 API、upload log 一致，ZIP 成员与解包 JSON 逐字节一致。

每平台 9 个有序 events/checkpoints、18 个 OS samples、362 个连续 progress、181 个完成 operations、14 个 true checks；33 次 prepare/candidate/worker_commit/scenario_apply 各索引 1..33 完整。最终两平台相同：33 付款块、68 commitments、66 nullifiers、33000 fees、308756 logical bytes、1 段、308616 tail bytes；钱包记录 [52,51]、文件 [1713368,1680420] B。恢复第 32 笔、精确恢复 pending 第 33 笔并真实提交的步骤在完整结果之前执行，Go exit 0、无 failures/unfinished/uncertain。

| 本次 OS 资源观察 | Ubuntu | Windows |
|---|---:|---:|
| Worker lifetime peak，B | 11,509,760 | 13,135,872 |
| Scenario lifetime peak，B | 176,611,328 | 117,686,272 |
| Go result total，ms | 155659 | 223185 |
| Go test harness，s | 155.66 | 223.44 |
| Supervised process，ms | 155727 | 225250 |
| Supervisor，ms | 155819 | 226031 |

各测量层不同，不混为一个耗时或跨平台加速比。每进程 1 GiB 为观察预算；Linux RSS/HWM 与 Windows working set/lifetime peak 不等于 private heap 或整机内存。保留三个完整身份（两代 worker、一代 scenario），registered children exit=true，precheckpoint child-tree cleanup=false；这是身份保留和普通清理证据，不是进程隔离。`result_sha256` 只保留原报告的 reported 值，单独原始 result.json 不在 ZIP 内，未伪称独立重算。

两个大 operator ZIP 均在本地完整读取并逐成员校验，API/upload log/manifest/五个 payload 的 bytes 与 SHA 一致，两个文本又与准确 C7 git blob 一致。Linux **22,851,758 B / `6f36e3dd04c364eb502fb1882ce11c61262f73b15f514ec5cf23026fae4ff841`**；Windows **22,388,948 B / `36e519c629f07ae46c911d8e686c9189092599a711c9117ca1b317790e707855`**。三个可执行文件没有由审核者执行；manifest 指向准确 synthetic/tree，三个 real_funds/public_network/anonymity 标志均 false。

按归档范围，证据 Git 只保留 operator 原 API metadata、原 manifest、完整成员核验表和整体 ZIP 摘要，**不嵌入两个大二进制 ZIP**；它们仍是[原生 Linux artifact](https://github.com/youq616/Zevune/actions/runs/35211515104/artifacts/10493857439)与[原生 Windows artifact](https://github.com/youq616/Zevune/actions/runs/35211515104/artifacts/10494057037)，工作流保留期 7 天。这与已完整归档的两个 resource ZIP 不同。ZIP 未含 NOTICE/license inventory，本审核不是发行许可证审计，也未发布 bundle。

## 历史、限制与固定交付

C1/C2/C3 的实际格式、Clippy 和 stdout 测试失败继续保留；C4 首轮 18 success + 5 cancelled 以及四次晚重跑的 2 success + 2 cancelled 单独保留，未接受完整阶段。C5 的选定 source fmt 失败不表示所有测试未运行；C6 的选定 default 完整 154 passed 后 Clippy duplicate_mod exit 101，完整默认测试信用也没有转给 C7。C7 的 attempt1 全通过只描述本候选，不能写成整个开发阶段第一次即全部通过。

本结论限于准确源码的单机固定验证者 NO-FUNDS 实验范围及已执行用例。`File.flush` 不等于 fsync，Windows NULL-handle 分支没有专用 fixture；未测真实掉电/磁盘满、所有 OS/文件系统、全容量或生产资金安全，亦非外部密码学或安全认证。冻结设计文档保留已知 EOF 空行 whitespace 诊断，不能表述全部阶段文件绝无 whitespace 提示。

最终 [native-audit.json](native-audit.json)保存接受判断、23 个选定 job、原生完整步骤、各运行的精确来源与摘要、两个子审固定摘要、场景/资源/限制；[stable-archive-manifest.json](stable-archive-manifest.json)列出全部稳定归档文件的 bytes/SHA。可重建的 working、derived 摘要、临时 `.part` 和本地大 bundle ZIP 排除于证据 Git 清单；正式 23 日志、46 件日志/metadata、20 件 run/jobs API、身份/预期/观察原件、三份成对正式审核及适用 artifact 全部保留。主审核完成时间为 **2026-09-17 11:21:11 UTC**，后续合并动作不属于本审核代理。
