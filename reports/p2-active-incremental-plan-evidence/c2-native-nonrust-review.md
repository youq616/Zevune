**PASS_NONRUST_NATIVE — 准确 C2 的非 Rust 原生证据独立复核通过。**

2026-09-17，独立审核任务 `/root/p2_plan_adversarial_review`。本任务未编写候选实现，未修改仓库，也未执行合并。此次结论覆盖实际 Go/Python 执行、付款与恢复场景、增长测试、资源原件和 operator 包完整性；没有发现本范围阻断项。全部原件到齐后才给出此结论。Rust harness、新增 append-plan 测试逐名核对、funded 动态分区完整性及最终全矩阵结论由 `/root/p2_plan_native_audit` 单独审核。

| 身份 | 冻结值 |
|---|---|
| 仓库 / PR | `youq616/Zevune` / [#15](https://github.com/youq616/Zevune/pull/15) |
| base | `0927af157a3cc35abde14b036bc50a99a793a32b` |
| C2 source | `2020c7314a996769b33706754405c0976ce7c50a` |
| C2 tree | `a25d4752d49f366f9aff047116eeffd9b1f6ae1d` |
| 原生实际 checkout | `2d208360ab665fbe82b57d205cf07e789f06164b` |
| 合成提交关系 | parents 为上述 base、C2；tree 与 C2 完全相同 |

已对 Git API 原件核对身份、树和合成提交父列表；23 份完整日志的实际 `git log -1 --format=%H` 均为上述合成提交。每份日志均与采集 carrier 中的 UTF-8 原文逐字节一致，包含正常作业结尾。10 个 PR workflow、23 个 job 均为此 C2、attempt 1、completed/success；274 个步骤 success，9 个 Windows 条件步骤 skipped。run-list、10 份 run、10 份 jobs 和 23 份日志合计 44 原件、1,698,441 B，其中日志 1,385,937 B。审核者独立重算了全部 44 项，均匹配冻结 manifest：7,136 B，SHA256 `c4887a55df538021d840ea048f5ebbe7977e0987d0055ea52abf9afd17500295`。这项身份核对用于绑定本范围证据，不代替另一审核者的完整 Rust 判定。

此前源码审核 `c2-adversarial-review.md` 保持原文冻结：16,960 B，SHA256 `94d07ad75732ccf8e8894d37d609883766e2d29d8b0c1babf7942e65c61b1252`。其 PASS_CODE 与本报告分开。C1 曾原生 rustfmt 失败，不能从 C2 结论获得验收；C1→C2 的纯格式修复已由此前源码报告核对。

本地仅运行 Python 对保留数据的离线校验、哈希和来源比较，没有本地 Go/Rust 工具链，也没有重新执行付款、原生内存探针或下载的二进制。原生执行结论来自准确候选的完整 GitHub 日志及终态元数据，并结合对应测试源码核对其实际断言。相关 8 份 workflow 和 9 份场景/校验/构建脚本共 17 份行为来源均与 C2 Git blob 逐字节一致，且均未在 base→C2 改动。

**Go 与 Python 的实际执行范围。**

本范围涉及 19 个 job：17 个包含 Go 编译或执行，其中 source job 仅编译，另 16 个执行 Go 测试；还有 2 个 funded-library job 的 Python 分区调度器测试。其余 4 个纯 Rust job 的行为不在本报告授信范围。实际 Go 版本为两平台 `1.27.1`。

| 场景 / workflow | Ubuntu job / Windows job | 已核对的执行 |
|---|---|---|
| scaffold | `105235852600` / `105235852236` | 根模块 `go test ./... -count=1`、`go vet ./...`；Ubuntu 根模块 race 和两个真 fuzz engine |
| consensus | `105235853178` / `105235852703` | CometBFT 模块全量 test/vet、launcher build；Ubuntu app race；每平台 63 顶层 PASS、106 个含子测试的命名 PASS |
| Orchard bridge | `105235853864` / `105235854234` | 根模块 test/vet、实际 `TestGenuineRustWorkerAuthorization`；Ubuntu bridge race 和两个真 fuzz engine |
| Orchard integrated | `105235852428` / `105235852619` | 根模块与集成模块回归、vet；6 个 tagged 顶层 PASS；Ubuntu tagged adapter race、IPC race/fuzz |
| operator | `105235852383` / `105235852011` | tagged test/vet；每平台 55 顶层 PASS、102 个含子测试的命名 PASS；Ubuntu 普通 race、错误 post-state 的 tagged race、3 个真 fuzz engine |
| funded interfaces | `105235853237` / `105235852975` | 编译之后实际 Python/Rust 互操作、真实 funded 四节点测试与 vet；每平台 3 顶层 PASS，包含 1 个长时四节点主场景 |
| resources | `105235853110` / `105235852466` | `go test -c`/vet 后由 Python supervisor 实际运行编译出的 `TestActivePaymentResources32AndRecovery`；两份最终资源原件通过 |
| growth | `105237131101` / `105237130510` | 两平台真实 100000 块 worker/disk 测试及完整重开后第 100001 块 |
| source | `105235853053` | 源码格式检查、根模块及 tagged 集成模块 `-run '^$'` 编译；没有运行 Go 测试 |
| funded scheduler | `105235853245` / `105235853314` | 每平台 Python 分区调度器 13 项实际通过；Rust 库分区由另一审核者判定 |

funded interfaces 早期两个模块的 `go test ... -run '^$'` 同样只计编译。resources 的 `go test -c` 本身也只计编译，其后的独立测试执行和最终 JSON 才是资源工作量证据。没有 `-v` 的 Go 回归仍有实际 package 测试成功输出，不能因为未逐名打印而当成零测试。反之，helper 自身的 0 秒 PASS、普通测试过程中的 fuzz seed PASS、重复平台/工作流中的同名测试，都没有被当成额外独立场景或真 fuzz engine。

9 个 Windows workflow skip 均与源码中的 OS 条件一致：scaffold 3、consensus 1、integrated 2、bridge 2、operator 1，分别为 race/fuzz 步骤。相应 Ubuntu 步骤实际完成。本范围已打印的 Go 命名结果没有 SKIP/FAIL。Python 统计按实际执行拆分如下，不能把 discovered 数写成 passed 数：

| Python suite | Ubuntu | Windows |
|---|---|---|
| operator 的全 scripts suite | 135 discovered = 132 passed + 3 skipped | 135 = 134 + 1 |
| funded interfaces 的全 scripts suite | 135 = 132 + 3 | 135 = 134 + 1 |
| resource suite | 53 = 50 + 3 | 53 = 52 + 1 |
| funded-library scheduler | 13 = 13 + 0 | 13 = 13 + 0 |

Windows skip 为 Linux `/proc` identity 双侧重验语义；Ubuntu 的 3 项 skip 为必须依赖 Windows 原生文件共享/删除语义的测试。对应平台均实际执行各自适用测试。上述重复 suite 合计 672 discovered、660 passed、12 skipped，仅为运行次数统计，不宣称 660 个不同测试。

Linux 的 8 次 bounded fuzz 均进入 `now fuzzing`、产生非零 execs 并以 PASS 结束；所核对的是引擎输出，不仅是声明命令：

| fuzz target | 请求预算 | 最后 execs |
|---|---:|---:|
| `FuzzDecodeBinary` | 3 s | 21,701 |
| `FuzzJournalBlockDecode` | 3 s | 98,045 |
| `FuzzDecodeEnvelope` | 10 s | 493,509 |
| `FuzzReadFrame` | 10 s | 393,987 |
| `FuzzPoolFrame` | 10 s | 653,501 |
| `FuzzCanonicalPublicConfiguration` | 3 s | 10,838 |
| `FuzzNumericLoopbackEndpoint` | 3 s | 12,820 |
| `FuzzTestGenesisFrame` | 3 s | 148,521 |

这些是有限时长探索，不是穷尽验证或安全证明。

**真实付款与四节点恢复的先后关系。**

已结合实际主测试源码核对，不从测试名称推断顺序：

- `TestActiveFundedFourNodePaymentRestart` 使用交付 operator 的 init/run/sync/submit/storage、真实 Rust worker、独立 scenario、4 个共识进程和 active ledger。先完成 A→B 与独立回放，再停止全部 4 节点并逐个检查关闭后的账本，然后重启全部节点、超过持久化高度，**之后才构造并完成 B→C**；再核对钱包重开、余额守恒、签名后的下一高度状态一致和两笔重复拒绝。Ubuntu 60.75 s、Windows 72.20 s 均 PASS。这是全重启后继续新付款的直接证据。
- `TestRealOperatorNonzeroPaymentsAndRestart` 与 `TestFundedWalletFourNodesAndRecovery` 均先 A→B，停 1 个验证者期间完成 B→C，再让其追上；**全 4 节点重启发生在两笔付款之后**。之后的 wallet reopen、签名状态一致、重复拒绝也实际通过。不能把这两项改述成第二笔付款发生在全重启之后。
- funded interfaces 的长时主场景 Ubuntu 64.95 s、Windows 83.51 s，随后 vet 和最终源码无漂移步骤成功。`FUNDED_LOCAL` 两个样本分别为 Ubuntu `[6109,7811]` ms、Windows `[8482,9557]` ms，包含备份/重扫、签名检查和独立回放，不能推出 p95、TPS、WAN 或生产付款速度。
- operator 两平台均执行并通过 `TestQuorumSignedWrongPostStateNeverPersists`，Ubuntu 还执行其 tagged race。源码使用测试 RPC 给出具有真实 quorum 签名但错误 post-state 的响应，并断言不得持久化；这项证据没有把签名表面通过或 AppHash 直接等同于可信钱包状态。

consensus scaffold 的四进程恢复回归会拒绝付款；integrated 的真实 Orchard 四进程回归使用公开零值 fixture。它们支持各自适配器/共识边界，非零 funded 付款证据来自上述明确的 funded 场景。健康检查、preflight、AppHash、单机 ApplyBlock 不能单独称为 finality。

两份 funded interfaces 日志还确认真实 `scripts/check_wallet_backend.py` 完成：临时加密钱包创建/检查/备份/恢复、后端直接拒绝错误网络与无效数值且不改变文件、实际域绑定付款准备、精确 outbox 恢复、实际 pending 钱包压缩后相同交易与新 receipt、拒绝旧 ancestry pin 和坏密码/frame。源码断言覆盖这些行为；不是仅打印成功字样。每平台只保留 1 个 prepare 样本，Ubuntu 8,908,158 μs、Windows 10,368,539 μs，无广播，也不是端到端 finality 计时。

**100000 块增长与真实磁盘范围。**

两平台均执行真实固定 profile Rust worker 的每高度 Finalize/Commit 与磁盘写入，段上限维持 1,048,576 B。付款高度恰为 9,999、10,001；100,000 块中 99,998 空块、2 paid。测试在付款边界重开 worker/钱包并核对精确交易；独立 scenario 逐块回放到 10,002，不能宣称它独立回放了 100,000。worker 自身完成全部增长及 100,000 高度全量恢复。关闭后的完整物理帧扫描核对高度、block ID、状态链、checksum、规范轮转、付款字节和空块，恢复后继续普通空提交至 100,001，再扫描物理文件与不可变 header。

| 结果 | Ubuntu | Windows |
|---|---:|---:|
| 100000 时逻辑字节 / 段数 | 15,018,544 / 15 | 15,018,544 / 15 |
| growth_elapsed_ms | 53,658 | 593,575 |
| replay_elapsed_ms | 2,692 | 1,909 |
| continued_height | 100001 | 100001 |
| 主测试 PASS 用时 | 64.85 s | 601.59 s |

两平台四个进度点均为 25k/50k/75k/100k，逻辑字节分别 3,768,544 / 7,518,544 / 11,268,544 / 15,018,544，段数 4/8/11/15。完整日志和终态步骤一致。这是本机 worker/磁盘及全量恢复证据，不是 100000 高度的四节点共识测试，也没有覆盖 64 MiB 边界、全部容量、最大 commitment 数或物理掉电。

**fixed 32+1 资源原件的独立离线重验。**

资源 workflow `35231320296` 的 Windows artifact `10501028029`、Linux artifact `10501693314` 均已完整收到。原始 ZIP 分别 9,412 B / 9,278 B，SHA256 为 `fedafe1c05d0698e456c54564b5032dddecb7524a1244757d6452eae27109d01` / `ae7c5d7b8978d68a1ce5f465c2127725f52e703b61ee7fec670fb2ae926d4148`，都匹配 GitHub artifact API digest；每包恰好 setup 与最终 resource 两成员，解出的原文逐字节等于 ZIP 内容。实际 upload 日志中的 artifact ID/大小与 API 关联到同一完成 job。

Windows 完整 resource 原文 131,244 B，SHA256 `9765b1edb30abf234de649f75a4e97b4230b26038543effeb33521a85d4a2de5`；Linux 130,206 B，SHA256 `e030d300f387500e94c5e8f7ce3795993b5b2f2cf2718a9ffe4ae8b04a94e334`。setup 仍明确 `not_started`，只说明初始化，实际完成信用来自最终 resource JSON、对应完整测试日志和成功终态。

离线使用准确 C2 的原严格 `decode_json`、`checked_progress`、`checked_event`、`checked_result`、`checked_memory`、`check_budget` 对原文重验，没有调用执行/OS 探针入口。额外独立核对全部事件顺序、进程身份、钱包/账本计数和 Go result 原始序列化 SHA256：包含 map 排序及 progress struct 字段顺序，重建值匹配保留的 `result_sha256`。这既检查格式，也检查保留数据的内部一致性；不能代替重新采集原始 OS 值。

两平台均有 9 个 checkpoint、362 条有序 started/completed progress，即 181 个完整操作；最终 passed、Go exit 0、没有失败检查、没有未结束操作或 outcome uncertainty。33 块全部 genuine paid，每笔 2 actions，最终 height 33、68 commitments、66 nullifiers、33,000 fees、308,756 逻辑字节、1 段、tail 308,616 B；两个钱包 records `[52,51]`、bytes `[1713368,1680420]`。源码实际执行 IPC check/preview/select/finalize/commit、坏 tag、重复拒绝与非变异、独立回放和磁盘帧断言，最终 14 checks 全 true 有对应执行依据。

第 32 笔后先关闭并扫描 worker，再真实全量重开 worker，之后恢复钱包/独立 scenario 全量回放，再准备第 33 笔并从加密 outbox 精确恢复，最后才提交第 33 笔。`pending_restored_33` 仍在 height 32，账本仍 299,404 B；只有 pending 钱包记录先增加。`complete_33` 才达最终 height 33。这个顺序和全部公共计数在两平台一致。

18 个内存样本均绑定事件中宣布的 role/generation/PID；同代创建身份稳定、共有父进程，新 worker 创建身份严格晚于旧 worker。Windows 使用创建 FILETIME 与 GetProcessMemoryInfo；Linux 使用 `/proc` starttime ticks 与 VmRSS/VmHWM。全部样本 current > 0 且 current ≤ 生命周期 peak ≤ 1 GiB，同代 peak 不倒退。

| 原生观测的进程生命周期 peak（B） | Ubuntu | Windows |
|---|---:|---:|
| worker generation 1 | 11,522,048 | 13,197,312 |
| worker generation 2 | 11,653,120 | 12,668,928 |
| scenario generation 1 | 176,222,208 | 117,653,504 |
| 最终 result 总时长（ms） | 161,816 | 212,866 |

这些值是 OS 报告的 resident/working set 生命周期观测，不是各阶段 peak、私有 heap、整机/全部子进程之和、严格分配限制或跨平台性能比。Python supervisor 和 Go coordinator 不在观测角色内；scenario 包含 prover、authorization cache、history、两个钱包与 Argon2。该固定 33 笔负载仍只有 1 段，不覆盖 1 MiB 轮转、64 项 cache 边界、全部容量，也没有测量新增 archive/append-plan 的资源成本。cleanup 记录为已登记 3 进程、已确认其退出；`precheckpoint_child_tree_cleanup_confirmed=false` 按原值保留，不能宣称初始化 checkpoint 之前的全子树清理或进程沙箱。

离线复核原文已冻结：Windows `c2-resource-offline-10501028029.json`，10,729 B，SHA256 `29b103c714facd4b3af322a615d3b828398f8be6bb4244a5f2ea95842f99aeca`；Linux `c2-resource-offline-10501693314.json`，10,688 B，SHA256 `c2fd3d96dd5f9189fd9191ad15c01c7a766e29c88fabdbad6898044601f0ecae`。其 PASS_RETAINED_RESOURCE_DATA 只针对保留数据；本报告将它们与准确 native 执行关联后才给出本范围 PASS。

**operator 包的全部成员完整性。**

workflow `35231320198` 的 Linux artifact `10502192163`：ZIP 22,850,002 B，SHA256 `5aee49045120adff565416ac9a60831f41cb796b8de2780e6a1eb28826adcbce`；Windows artifact `10501053828`：22,388,417 B，SHA256 `4d52f7f0e2bddd70df090b1856d7c14965808b24951311bd7b7732a446ac6276`。均匹配 API digest、日志 upload ID/大小。每包恰好 6 成员，原 manifest 与 ZIP 内字节一致；3 个实际二进制及 2 个文本 payload 全部逐成员重算长度/哈希并匹配 manifest。两个文本另与准确 C2 的文档/Python Git blob 逐字节相等；没有执行下载的二进制。

Linux manifest 1,288 B，SHA256 `7fa94608e90d6fe523a27a69203cc92fcd2ea2514956f33e2a93560b4a6beb0f`；Windows 1,302 B，SHA256 `7866d5d741be3e54b5e777c2dc0afbac012420857452b199ad1ce27371bb8798`。两者均精确声明合成 source_commit、C2 tree、`isolated_exact_git_blobs` 和固定本地 NO-FUNDS 范围；原生 builder 的 receipt 哈希与这里一致。已阅读 exact Git blob 导出、构建与包校验源码，实际 operator/worker 路径来自该构建包，独立 scenario 来自同 checkout。字节/manifest 校验支持保留包完整性及原生构建来源关联，不是独立可复现构建证明或发布者签名审计。

全成员小报告：Linux `c2-operator-members-10502192163.json`，1,974 B，SHA256 `44b1451fbf5c0215a2f874f93787c701020a599b8af70a38b927eb55f169ef29`；Windows `c2-operator-members-10501053828.json`，1,986 B，SHA256 `9f37da1c615d561d088721ce40cf12fbc7b80d9702948ba5be50c273676d9853`。大 ZIP 仅为审核原件，无需把二进制大包作为文本证据提交仓库。

本报告伴随 `c2-native-nonrust-review.json`，83,765 B，SHA256 `c29bb57bf50f43aeaee32c3a6b757733d04d4302a4aa51f84d358286da142987`；其中保留全部 44 原件身份、精确 run/job 关联、命令与 skip 分解、原生成长/付款结果、资源/包派生证据身份与行为来源绑定。阻断 findings 为空。报告没有授予合并许可或替代全矩阵最终 native 审核。

C2 仍是只读的双检查点 append plan；持久化增量备份和 snapshot state import 未实现，P2 仍在进行。此处所有实际付款均为临时 NO-FUNDS 本地实验，不涉及真实价值、公开部署或生产承诺。原生 CI 和独立代理审核也不等同于外部密码学/安全专家审计。
