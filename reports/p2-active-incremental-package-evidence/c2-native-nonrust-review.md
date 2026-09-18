# P2 持久增量包 C2：非 Rust 原生证据独立分项审核

审核任务：`/root/p2_package_native_audit/nonrust_logs`；父任务：
`/root/p2_package_native_audit`。日期：2026-09-18 UTC。
本审核者未编写本候选源码、tests、workflow 或设计；只创建分项审核材料和 scratch 分析脚本。

**结论：C2_REJECTED_STRICT_CLIPPY_FAILURE_NONRUST_EXECUTION_SCOPE_RETAINED。**

C2 的全部 10 个 PR workflows、23 个 jobs 已有准确候选的完整终态及原件。13 个 jobs
成功，10 个 jobs 因 strict Clippy `drop_non_drop` 失败，完整阶段仍须拒绝。真实资源、
100000 块增长和 operator 两平台执行成功属于 C2 的有效分项证据；这些成功不能填补
Clippy 失败、后续接口测试未执行或缺少其他必要验收的条件。本报告永久固定为 C2，
不得将其改写成 C3 或阶段 PASS，不继承 C1 的执行信用。

## 准确来源和完整原件

- PR：[Zevune #17](https://github.com/youq616/Zevune/pull/17)。
- base：`2cc87a2207d502ac5cfe00ea52e525c1516917e5`。
- C2 head：`f51c8db240933256870ff03c07bc68915b4ac4a1`。
- C2 tree：`7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400`。
- synthetic checkout：`aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f`；parents 正好为
  `[base, C2]`，tree 与 C2 相同。
- C2 自身的唯一 parent 为 C1 `61c691270b91aece076177cb757e51e0e63fe310`，并非直接以
  base 为 parent；审核基线仍为 PR 的实际 base。

已完整读取 AGENTS、STAGE_REVIEW、原生期望、全部 12 个 workflows，以及资源采集验证脚本、
资源 Go 测试、增长 Go 测试、bundle builder/verifier。直接比较 C2/base Git 对象，确认
workflows、scripts、integration/cometbft、internal/poolbridge、两个 root Go 依赖文件无变更，
没有放宽固定付款数、超时、resource 门槛、features、tags 或平台条件。

最终 `c2-native` 目录的 **62 个原件、1,937,332 字节**已逐个重新散列，与清单路径集合、
长度、SHA-256 完全一致；没有清单外文件或清单内缺件。清单为 10,722 字节，SHA-256
`338072a650def9133dcfbca3c2e234cc395aef0dd44f1093add329f53a271cd8`。
其中 **23 份完整 job logs、1,337,508 字节**全部读取、散列及扫描，保留 decoded UTF-8
原件的 BOM/CRLF；逐项检查全部非 Rust 实际命令、具名结果、错误、完整 step 终态和 cleanup。
原始 Go/Python 名称及所在 log 行号保存在配套 JSON，未用 CI badge、作者概述或末尾片段
取代原件。另对两份 operator 原 ZIP 的所有 payload 完整流式读取、散列，不执行二进制。

run list 与 10 个完整 run、10 份 jobs 响应、10 份 artifact 响应相互核对，全部为
`pull_request`、准确 C2 head、attempt 1、completed。所有已执行 job 实际 checkout 都为
上述 synthetic commit。使用不可变顶层 run/job head、head_commit tree、初始 PR 与 Git
parents 绑定 C2；响应中嵌套当前 PR head 可能随 PR 推进而变化，未把它当作历史 run 的
源码身份。API JSON 是 connector 返回数据保存的原件，不声称为底层 HTTP 线缆字节。

## 终态、阻断和未执行项

终态合计 **5 个 workflow success / 5 个 failure；13 个 job success / 10 个 failure**。
23 个 jobs 全部实际执行且都有日志，无零 step 占位、cancelled 或非终态项。Steps 为
**228 success / 10 failure / 45 skipped**。5 个 skipped 位于成功 Windows jobs，分别为
scaffold 三项、consensus adapter race 一项、operator race/fuzz 一项；另 40 个 skipped
位于失败 jobs，不能表述为全部矩阵只有正常平台跳过。

| Workflow / run | 结果与实际范围 |
|---|---|
| [scaffold-tests / 35362925524](https://github.com/youq616/Zevune/actions/runs/35362925524) | 两平台成功：root Go test/vet；Linux root race、两个 3 秒 fuzz |
| [consensus-laboratory / 35362925499](https://github.com/youq616/Zevune/actions/runs/35362925499) | 两平台成功：完整基础集成 test/vet、四进程共识实验、launcher build；Linux adapter race |
| [active-ledger-growth / 35362925526](https://github.com/youq616/Zevune/actions/runs/35362925526) | source 与两平台 growth 全部成功；真实 100000 块及完整重放后继续提交 |
| [payment-resource-baseline / 35362925495](https://github.com/youq616/Zevune/actions/runs/35362925495) | 两平台成功；32+1 真实付款、完整资源原件与清理核验 |
| [local-network-operator / 35362925534](https://github.com/youq616/Zevune/actions/runs/35362925534) | 两平台成功；独立 Git source build、实际 operator 付款、完整 bundle；Linux race/fuzz |
| [orchard-cryptography-laboratory / 35362925520](https://github.com/youq616/Zevune/actions/runs/35362925520) | 两平台默认 Rust suite 先完成，strict Clippy 失败；job 不能接受 |
| [wallet-laboratory / 35362925589](https://github.com/youq616/Zevune/actions/runs/35362925589) | 两平台默认 Rust suite 先完成，strict Clippy 失败 |
| [orchard-bridge / 35362925573](https://github.com/youq616/Zevune/actions/runs/35362925573) | 两平台默认 Rust suite 先完成，Clippy 失败；后续真实 Go→Rust proof、Go regression/race/fuzz 未执行 |
| [orchard-consensus-integration / 35362925543](https://github.com/youq616/Zevune/actions/runs/35362925543) | 两平台默认 Rust suite 先完成，Clippy 失败；后续 Orchard 四进程集成、Go regression/race/fuzz 未执行 |
| funded-wallet-consensus | library 两平台成功；interfaces 两平台 strict Clippy 失败，后续 interfaces cohort、实际 Python→Rust wallet 互通、该 workflow 的 funded 四节点付款未执行 |

10 份失败日志均明确报告：`integration/orchard/src/pool/active/package/tests.rs:354` 中
`drop(reader)` 对没有 Drop 实现的 `JoinedReader` 触发 `drop_non_drop`，`-D warnings`
令命令以 exit 101 终止。没有发现额外 Go 或 Python FAIL；这项观察不消除 strict Clippy
阻断。修复须产生新的准确 head/tree，并对新候选重新检查，不修改 lint 门槛获得通过。

最后补读的 funded-library Ubuntu job 105658336250、Windows job 105658336169 有真实
`FUNDED_COHORT_COMPLETE library` 标记。此分项记录其执行存在，不替代父审核者对完整
Rust harness、genuine replay 和用例含义的专项核验。funded interfaces jobs
105658335868/105658336130 中，Go 编译和 Python 单测之后进入 Clippy 即失败，没有
Rust interface harness 或 `FUNDED_COHORT_COMPLETE interfaces`；默认配置中的空 harness
不能填补该 funded CLI 覆盖缺口。

## Go、Python 与实际 operator 流程

所有实际 Go setup 日志均报告 Go 1.27.1，Linux/Windows 架构与 runner 一致；scaffold
的 stable 本次也解析到该版本。source、funded interfaces 的 `go test ... -run '^$'`
只授予对应模块编译信用，不把 `[no tests to run]` 包结果算成执行测试。

scaffold 两平台 `go test ./... -count=1`、vet 均通过，7 个有测试的 root 包和 2 个无测试
命令包区分记录。Ubuntu root race 通过。基础 consensus 两平台 readonly test/vet、
依赖验证、gofmt、launcher build 和最终 git diff 完成；每平台 63 个顶层 named PASS，
含子项为 106，其中普通调用的 Fuzz 函数只是 seed 执行。其实际四进程恢复、quorum、
签名状态与重启日志均读取，不将基础共识实验等同于未执行的 Orchard 集成步骤。

operator 两平台 `go test -mod=readonly -tags=operator_e2e ./labnet ./cmd/zevune-network
-count=1 -timeout=15m -v` 和对应 vet 实际完成；每平台 55 个顶层、含子项 102 个 named PASS。
记录包括 `TestActiveFundedFourNodePaymentRestart`、`TestRealOperatorNonzeroPaymentsAndRestart`、
`TestQuorumSignedWrongPostStateNeverPersists`、真实 reference checkpoint/payment、journal
copy/restore 及离线锁检查。完整日志明确保留 low-height NO-FUNDS 边界。Ubuntu 普通
labnet/launcher race 和带 tag 的错误 post-state race 均执行成功；Windows 条件跳过。
这是真实 operator workload，不意味着本阶段新增 package CLI 已经在 interfaces cohort
运行过。

本候选实际进入并完成的 fuzz engine 共 **5 次**，均为原参数 `-fuzztime=3s -parallel=2`：

| Linux workflow | Fuzz target | executions | 新 interesting / 总 corpus |
|---|---|---:|---:|
| scaffold | FuzzDecodeBinary | 4,507 | 1 / 4 |
| scaffold | FuzzJournalBlockDecode | 97,406 | 8 / 11 |
| operator | FuzzCanonicalPublicConfiguration | 9,477 | 40 / 42 |
| operator | FuzzNumericLoopbackEndpoint | 13,032 | 50 / 52 |
| operator | FuzzTestGenesisFrame | 66,888 | 2 / 6 |

Python 共有 8 次 suites：funded-library 两次各 13/13/0；funded interfaces 和 operator
各两次完整 scripts suite，Ubuntu 135/132/3、Windows 135/134/1；resources 专项 Ubuntu
53/50/3、Windows 53/52/1（顺序为发现/通过/跳过）。合计 672 次发现、660 次通过、12 次
平台跳过；跨 suite 为 135 个已有 test 身份，不是新增 660 个用例。3 个 Windows 文件共享
测试在 Linux 跳过，1 个 Linux proc descriptor 测试在 Windows 跳过，另一侧实际执行。
每项具名输出与 suite 总数、OK 和 skipped 原文逐项相符。

## 100000 块增长

两平台实际命令保留 `-tags=pool_e2e,funded_e2e`、准确测试名、`-count=1 -timeout=25m`；
测试内部 20 分钟 context、workflow 40 分钟预算未变。正常段上限 1,048,576 字节。

| 平台 / job | growth ms | 完整 replay ms | named PASS 总秒数 |
|---|---:|---:|---:|
| Ubuntu / 105659982100 | 72,160 | 2,082 | 80.99 |
| Windows / 105659982062 | 617,840 | 2,757 | 630.26 |

两平台四个实际进度点均为 25000、50000、75000、100000 块；对应字节数
3,768,544 / 7,518,544 / 11,268,544 / 15,018,544，段数 4/8/11/15。
最终为 100000 块，其中 99998 空块、2 笔真实付款；完整重放后继续到 100001。
读取了 9999/10000/10001/10002 边界、真实 A→B 和恢复后 B→C、余额/费用、outbox 恢复、
有效期内重花拒绝的实际日志，以及 named PASS 和最终源码不变检查。

这些是本地真实 worker 提交，约 15 MB 的历史；不构成 100000 个四节点共识高度，
不证明超过 64 MiB、全 1 GiB、1000000 条记录或 2048 段的压力能力，也不是付款吞吐测量。

## 32+1 真实付款与完整资源证据

两平台 run 35362925495、jobs 105658335664（Ubuntu）/105658335377（Windows）全部步骤
成功。两份 ZIP 均完整核对 metadata 长度和摘要，成员恰好 setup/result 两个 JSON，与
保存的原始成员逐字节一致。setup 的 `not_started` 只是初始观察，最终执行结论独立来自
完整 result、job/step 终态和实际 named PASS；没有把初始观察冒充最终结果。

逐项验证每平台 9 个 events、362 条 progress、181 个严格有序操作、18 个内存 samples，
以及 14 个精确结果 checks。恢复操作必须在第 33 笔 prepare 前完成，新 outbox 必须先
恢复再进入 candidate；所有 started/completed 严格配对，没有 unfinished operation，
commit_outcome_uncertain=false，go_exit_code=0，failures 为空。

两平台最终均为 height33、commitments68、nullifiers66、fees33000；逻辑字节308756、
1 段、tail308616；钱包 records52/51、bytes1713368/1680420。对最后事件、结果容量、
钱包字段、timings 完整操作表进行交叉核对，并按原 Go map/struct JSON 编码重建并匹配
result_sha256。每个进程样本的角色、代次、PID、父进程、创建身份、OS 采样方法、当前与
生命周期峰值关系、代内峰值不降和全部固定 1 GiB 门槛均检查；3 个已登记子进程退出确认。

| 平台 | worker 1 峰值 B | worker 2 峰值 B | scenario 峰值 B | workload total ms / supervisor ms |
|---|---:|---:|---:|---:|
| Ubuntu | 11,325,440 | 11,612,160 | 180,039,680 | 121,975 / 122,133 |
| Windows | 13,119,488 | 12,644,352 | 117,415,936 | 223,916 / 225,188 |

原来的 Go 1200 秒、supervisor1230 秒、handshake15 秒、worker start/request60 秒、scenario
response90 秒上限保持。采样反映单个进程一代生命周期的 OS resident/working-set 峰值，
不是每阶段独立峰值、私有堆、整机内存或跨平台性能比；不包括 Python supervisor/Go
coordinator。这是既有真实付款 workload，未专门测量新增 incremental package CLI 的
全进程资源峰值。完整资源分项见 `c2-resource-independent-review.json`（60,940 字节，
SHA-256 `637327a11702819222ea6205d77d13fd5aa5ef6fba6b6c028a62d6e3316393b5`）。

## Operator bundle 全 payload 完整性

两平台 workflow 的孤立 Git object build、source drift 检查、实际 operator 流程及上传
步骤成功。两份原始 ZIP 共 45,240,450 字节，均独立重算 archive SHA-256，与 GitHub
artifact 元数据及实际上传日志一致；每份恰好 manifest 与 5 个 payload，所有成员完整读完
并核验 ZIP CRC、长度和 SHA-256。Linux payload 共47,866,947字节，Windows共44,563,437字节。

| 平台 | ZIP bytes | manifest SHA-256 |
|---|---:|---|
| Linux | 22,851,983 | `21f9d4b6592b90edc5aca7beb1041f8a527db1e26d8303af4c1bfe81ff4e346d` |
| Windows | 22,388,467 | `df73d5d724b5e69dcda6eaeed60492d76b1f59cea5e7dcba1573c64f0f05e0fb` |

manifest 的 source_commit 精确等于本候选 synthetic checkout，source_tree 等于 C2 tree；
固定 Go1.27.1/Rust1.98.1、isolated_exact_git_blobs、NO-FUNDS 和单机固定验证者 scope 均匹配。
3 个二进制仅检查全部字节及 ELF/PE 容器标记，未执行；Python frontend 和说明文档与准确
C2 Git blobs 逐字节一致。本分项没有独立重建程序，完整性校验不构成代码签名、可重现
构建证明或外部审计。原 ZIP 留在 scratch，不把二进制复制入 repo。

独立 bundle 分项 `c2-operator-independent-review.json` 为12,045字节，SHA-256
`421c54256c66f7e4487717d75c2978919af2e2fd40089dc7723a86b4f6563c80`，保留所有 payload 摘要。

## 固定交付与边界

正式明细 `c2-native-nonrust-review.json`：462,627 字节，SHA-256
`8994d6105169c1eca5375fcd715dec1dd036eeea2a3b82c724610f65d2e29d41`。
其包含完整原件清单验证、10 runs/23 jobs 全部 step、所有非 Rust 具名结果与原始行号、
精确 Git 来源、10 个 Clippy 阻断、独立增长解析、已冻结资源和 bundle 分项的身份。

审核没有在本地运行 Go/Rust workload，没有执行下载二进制或重新采集 OS 数据，没有
修改源码/测试/CI/设计，也没有删除或事后改写 C1 失败记录。C2 的非 Rust 已执行范围未发现
新失败，完整阶段仍因10个strict Clippy阻断拒绝；后续C3必须使用其自己的完整原件、原生
通过与独立代码审核。本文不授予生产就绪、网络最终性、真钱能力或专业外部安全审计结论。
