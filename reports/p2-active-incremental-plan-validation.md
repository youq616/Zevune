# P2 活动归档追加关系与只读增量计划验收

日期：2026-09-17。本文件是作者整理的交付说明与证据索引，独立结论以链接的非作者原件为准。

**本运行阶段已验收，并通过 [PR #15](https://github.com/youq616/Zevune/pull/15) 实际合入。** 准确C2的两路非作者完整代码审核均PASS_CODE，完整原生审核PASS_NATIVE、另一路非Rust原生审核PASS_NONRUST_NATIVE；本范围没有开放阻断。已实现的能力是：对两份分别由独立可信检查点固定的活动归档进行完整真实验证，确认其精确物理追加关系，并通过库和实际命令行返回有界的新字节范围。生产接口不创建增量包或导入状态，P2 整体保持开发中。

## 准确源码与交付身份

| 对象 | 身份 |
|---|---|
| 仓库与运行 PR | [youq616/Zevune · PR #15](https://github.com/youq616/Zevune/pull/15) |
| 阶段真实基线 | `0927af157a3cc35abde14b036bc50a99a793a32b`；tree `e04479cf7723588885573be2112635efa30e27cc` |
| C1，原生格式失败 | `99ec771c57207167f473d23ffd07b54f15a36abc`；tree `510693b0fd8ec085ab06de4140d6f7fd80f48c7e` |
| C2，已验收运行源码 | `2020c7314a996769b33706754405c0976ce7c50a`；tree `a25d4752d49f366f9aff047116eeffd9b1f6ae1d` |
| C2 PR 测试 checkout | `2d208360ab665fbe82b57d205cf07e789f06164b`；有序父提交 `[0927af157a3cc35abde14b036bc50a99a793a32b,2020c7314a996769b33706754405c0976ce7c50a]`；tree 与 C2 相同 |
| 实际运行合入 | [`274a2b5b86ca3e33d61b3695995450540a9cd278`](https://github.com/youq616/Zevune/commit/274a2b5b86ca3e33d61b3695995450540a9cd278)；2026-09-17 14:51:39 UTC；有序父提交为 `[base,C2]`，tree 与 C2 相同 |

C2 相对阶段基线恰为 11 份文件，共173,722字节：4个既有文件更新、7个新文件，无删除；其余739个既有条目的 mode/type/blob 保持。运行改动集中在两层增量计划模块、命令分派与JSON渲染、对应库/CLI测试和既有真实付款flow的新增核对点。依赖、固定工具链、工作流、原时间预算、真实授权/状态执行、旧历史报告及既有命令合同保持。

[冻结设计](../docs/ACTIVE_INCREMENTAL_PLAN.zh-CN.md) 保留实现前的历史状态文字，准确原件为8,604字节、SHA-256 `0234062797e5436cbccb307db50655b2b7a50f48046ccb91824e9dabc2e93193`。设计PASS与后续运行接受分开记录。源身份API响应包、各正式审核及native日志均保留冻结身份，不把先前原件中的 pending 历史状态倒写为 PASS。实际merge API、已关闭PR、merge Git对象与当时main分支的响应交叉核对一致；[作者观察收据](p2-active-incremental-plan-evidence/source-identities/runtime-merge-receipt.json)为122,691字节，SHA-256 `58863b542f82a1e28b8a0a226c688b97140bf784cae570aa8832830cfc9922c0`。PR #15已保存下文所链接的六份正式Markdown审核原文，逐块与冻结文件一致；合入收据是作者记录，不充当另一项独立审核。

## 新的调用行为

公开库方法 `ActiveArchive::incremental_plan(&mut self, later: &mut ActiveArchive)` 由较早归档调用，返回字段私有的 `ActiveIncrementalPlan` 与 `ActiveAppendRange`；范围只有只读getter，没有外来反序列化、应用计划或写入能力。

实际入口为 `zevune-pool-recovery plan-active-incremental --no-real-funds --base <较早归档绝对目录> --base-checkpoint <独立可信pin> --source <较后归档绝对目录> --checkpoint <独立可信pin>`。两枚pin各为128字节ZVARCP01、256个小写hex字符，均在打开任何目录前完成解码。可执行示例见[README](../README.md)。

两端只接受 LAB2／ZVTGEN03／ActiveSegmentsV1，并分别进行真实授权、状态、帧边界、规范轮换、物理EOF、布局摘要和目录身份检查。逐字节比较完整genesis、全部旧非尾段的全长内容及旧尾段的完整前缀；追加数据由旧尾段的非空后缀、其后连续的新段，或两者组成；允许旧尾段保持不变而直接新增段。同内容返回空计划；回退、不同网络、同高或更高却改写旧历史的合法分叉拒绝。关系成立后还要重新核对两端的完整字节和目录身份，全部成功才发布计划。

成功JSON格式为 `zevune-active-incremental-plan-1`。范围按段索引递增，`segment_index`、`offset`、`length` 均为u32；只有旧尾段可以有非零offset。`reused_bytes`包含genesis及旧尾段前缀，范围长度和精确等于`appended_bytes`；`unchanged_segment_count`只计整个文件未变的旧journal段，`new_segment_count`为两端段数差。空计划沿用同一schema。回执声明`replay_verified:true`、`byte_prefix_verified:true`，保留`incremental_backup_written:false`、`snapshot_imported:false`、`finality_verified:false`、`validator_ready:false`、`real_funds_allowed:false`。

生产路径只读取原保留文件句柄，并在双方归档生命周期内保持genesis共享锁。多个合作reader可以共存，合作writer被排除。任何验证错误都不返回部分公共计划；stdout写入错误传播为非零退出，但可能已写出部分JSON。普通调用不改写两端归档；测试专用外部修改注入被检测并保留，不能描述为注入前后整个目录未变。

## C2 的实际原生证据

准确C2已取得完整矩阵的PASS_NATIVE及非Rust范围的PASS_NONRUST_NATIVE；两份正式Markdown均全文读回、Markdown/JSON大小与SHA-256均核对，以下数量与完整原件对应。代码审核与native审核各自保持明确范围，实际运行合入另列。

C2的10个必需`pull_request`工作流、23个互不重复的job全部在attempt 1成功。原始元数据包含274个成功步骤和9个原有Windows条件跳过；23份完整日志共1,385,937字节。没有把push、重复run、先前候选或旧阶段结果混作C2通过。原始日志保留UTF-8 BOM/CRLF，并与准确checkout/source/tree绑定。

| 工作流 | 实际成功job |
|---|---|
| [local-network-operator](https://github.com/youq616/Zevune/actions/runs/35231320198) | [operator (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320198/job/105235852011)、[operator (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320198/job/105235852383) |
| [orchard-consensus-integration](https://github.com/youq616/Zevune/actions/runs/35231320202) | [integrated (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320202/job/105235852428)、[integrated (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320202/job/105235852619) |
| [scaffold-tests](https://github.com/youq616/Zevune/actions/runs/35231320231) | [tests (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320231/job/105235852236)、[tests (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320231/job/105235852600) |
| [orchard-cryptography-laboratory](https://github.com/youq616/Zevune/actions/runs/35231320272) | [tests (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320272/job/105235853115)、[tests (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320272/job/105235853346) |
| [funded-wallet-consensus](https://github.com/youq616/Zevune/actions/runs/35231320287) | [funded (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320287/job/105235852975)、[funded (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320287/job/105235853237)、[funded-library (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320287/job/105235853245)、[funded-library (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320287/job/105235853314) |
| [payment-resource-baseline](https://github.com/youq616/Zevune/actions/runs/35231320296) | [resources (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320296/job/105235852466)、[resources (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320296/job/105235853110) |
| [orchard-bridge](https://github.com/youq616/Zevune/actions/runs/35231320339) | [boundary (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320339/job/105235853864)、[boundary (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320339/job/105235854234) |
| [consensus-laboratory](https://github.com/youq616/Zevune/actions/runs/35231320342) | [integration (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320342/job/105235852703)、[integration (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320342/job/105235853178) |
| [active-ledger-growth](https://github.com/youq616/Zevune/actions/runs/35231320368) | [source](https://github.com/youq616/Zevune/actions/runs/35231320368/job/105235853053)、[growth (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231320368/job/105237130510)、[growth (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231320368/job/105237131101) |
| [wallet-laboratory](https://github.com/youq616/Zevune/actions/runs/35231322405) | [wallet (ubuntu-latest)](https://github.com/youq616/Zevune/actions/runs/35231322405/job/105235862028)、[wallet (windows-latest)](https://github.com/youq616/Zevune/actions/runs/35231322405/job/105235862497) |

逐job链接、完整日志大小/SHA-256、run/jobs原件及条件跳过见[CI作者索引](p2-active-incremental-plan-ci.json)。完整步骤、Rust每个target的结果及非Rust执行边界由[独立native JSON](p2-active-incremental-plan-evidence/c2-native-audit.json)和[非Rust JSON](p2-active-incremental-plan-evidence/c2-native-nonrust-review.json)另列；这里不把重复工作流运行当作新增独立测试。

| 实际Rust范围 | Ubuntu | Windows | 计数含义 |
|---|---:|---:|---|
| 默认suite | 168通过，其中lib154 | 160通过，其中lib146 | 各次默认执行19个完整harness结果；默认新CLI target为0测试，不给予其执行信用 |
| funded library | 173通过 | 165通过 | 各为独立完整library cohort，包含原有4项active_flow |
| funded interfaces | 21个harness结果／63通过 | 21个harness结果／63通过 | Cargo metadata穷尽接口目标并有cohort完成标记，新增active_incremental_cli各7项实际通过 |
| 新增定义对应实际执行 | 21项 | 20项 | 跨平台源码共22个新增定义；Unix/Windows专属测试选择不同，不把workflow重复加总 |

所有相关Rust job共有196个完整`test result`记录。格式与Clippy按原工作流运行；funded-library job自身没有Clippy，该检查位于原funded interfaces等实际任务。本地环境没有Rust/Go工具链，本文件不声称作者在本地完成编译或测试；原生执行由上述CI提供。

## 真实调用与拒绝路径

- 新CLI7项测试使用真实二进制子进程。普通调用前后比较整个fixture的目录集合与每个文件字节；正例按独立物理文件/pin/预期范围组装完整JSON字节。追加和空计划各有只读stdout的实际写入失败探针、精确非零退出、可写File正对照及之后的正常stdout控制。
- 真实付款沿正常证明、签名、提交、完整复制/恢复及恢复后再次花费执行，并保留余额/费用守恒、两笔双花拒绝和错误后不变检查。原flow在第6,964块的真实付款触发默认1 MiB轮换，检查旧尾段不变而新增第1段；真实归档恢复后第10,001块继续付款并检查旧尾后缀，第10,002空块再检查150字节追加。空块不计为同等数量付款。
- 测试独立按计划范围拼接副本，与较后归档完整字节比较后再用较后pin完整打开验证。这是测试内的范围正确性证据，生产代码没有增量包或增量恢复入口。
- 同高和更高分叉两端先独立有效重放；更高分叉还通过增长元数据条件，并直接断言物理前缀检查为Stale。错误网络、回退、错误pin、旧格式、两端缺失/截断/追加/替换/链接、多余项、打开后变化、成功后的再次调用与末次检查均有对应用例。
- 真实坏签名用例重算普通checksum和完整布局pin；新CLI例仅改变新增第二条付款记录，保留base前缀。实际拒绝发生在`ActiveArchive::open`的Authorization，不能说坏归档已成功打开并进入`incremental_plan`，也不能说该坏实例完成了证明验证。方法每次新建验证器的性质另由真实调用链及打开后重检用例核对。
- Unix专属用例执行保留名称替换、硬链接、缺失/软链接；Windows专属用例执行两端rename被原OS句柄保护拒绝、drop后成功。两平台均执行双方writer锁与多个共享reader控制。

既有Go test/vet、支持平台race和有界decoder fuzz、Python工具与调度器、真实四节点付款/重启、100000块正常worker增长和固定32+1付款资源回归也按准确C2执行，细目见[非Rust独立审核](p2-active-incremental-plan-evidence/c2-native-nonrust-review.md)。其19个job范围包含16个实际执行Go测试的job、1个Go编译专用source job和2个Python调度器job；source的`-run '^$'`及`go test -c`本身不计测试。Ubuntu8次有界fuzz实际进入引擎并以PASS结束；9个Windows工作流条件skip按原OS分支保留。Python全套135项为Ubuntu132通过/3跳过、Windows134通过/1跳过，资源suite53项为50/3和52/1，scheduler两平台各13项通过；重复suite与平台跳过不记成更多独立测试。增长负载依然是99998空块加2个真实付款块，关闭完整重放后继续100001，既不是四节点100000块也不是100000笔付款。32+1仍是原付款资源工作负载，本轮重跑没有成为追加计划专用资源测量。活动四节点场景先A→B，再全部节点重启，之后B→C；另外两个旧场景的A→B→C在重启前完成，保持各自真实顺序。

## 失败、修正与非作者审核

实现前的设计审核提出JSON首字段键名的Low级明确性提示；作者在最终设计中明确写为`format`，该提示已关闭。最终8,604字节设计已修正并取得PASS_DESIGN，之后才开始运行实现。旧8,589字节设计和正式设计审核均保留。两位最终代码审核者独立读取全部候选、调用方及测试，未发现开放的C2实质代码阻断。

C1因原生Rust 1.98.1格式检查失败而被明确拒绝。10个PR run中2成功、8失败；返回22个job为4成功、17格式失败、1个零步骤growth依赖跳过占位。21份完整日志共730,967字节，没有任何Rust测试结果或funded cohort完成记录；其先行成功不转记给C2。两个C1资源artifact仅有`not_started`的setup记录，没有实际32+1资源结果。

C2严格按原生formatter输出修正4文件10处排版和合法尾逗号；两路代码审核完整核对差异，其中一路独立从原hunk重建四份文件并与C2字节完全相等。没有改变运行语义、测试断言、段容量、依赖、工作流或时间预算。C2自身的完整原生执行才关闭该验收阻断。完整拒绝记录见[C1 native原件](p2-active-incremental-plan-evidence/c1-native-audit-rejected.md)。

| 非作者任务 | 实际范围 | 结论 | 完整原件身份 |
|---|---|---|---|
| `/root/p2_incremental_design_review` | 实现前冻结设计 | PASS_DESIGN | [design-review.md](p2-active-incremental-plan-evidence/design-review.md)；15031 B；`64774b864189730d44529d4e86ff0eb004655cb3235109f3b89ad1f73b945e1f` |
| `/root/p2_incremental_design_review` | C2 全部11文件、继承调用链、测试及C1格式修正 | PASS_CODE | [c2-code-review-design-authority.md](p2-active-incremental-plan-evidence/c2-code-review-design-authority.md)；17742 B；`13b0857052f6da6b3482f4c53e7ac70908040e14b5fa7f2488cc713eb10eac35` |
| `/root/p2_plan_adversarial_review` | C2 全部11文件、认证/只读/错误边界及测试 | PASS_CODE | [c2-adversarial-review.md](p2-active-incremental-plan-evidence/c2-adversarial-review.md)；16960 B；`94d07ad75732ccf8e8894d37d609883766e2d29d8b0c1babf7942e65c61b1252` |
| `/root/p2_incremental_design_review/c1_test_evidence` | 四份测试、真实调用边界及准确C2身份 | 静态范围无新增实质问题 | [c2-test-evidence-subreview.md](p2-active-incremental-plan-evidence/c2-test-evidence-subreview.md)；12313 B；`f30dc7c696ca74d075375caed334081ebcf49cd9800b1f602bd92afbc45e1d3c` |
| `/root/p2_plan_adversarial_review` | C2 Go/Python、真实付款/恢复、增长、资源及操作工具包完整性 | PASS_NONRUST_NATIVE | [c2-native-nonrust-review.md](p2-active-incremental-plan-evidence/c2-native-nonrust-review.md)；17,275 B；`472e869ca2d68ea153b7a1468ae63d9292072783a778d4bbbbff93b994e83d74` |
| `/root/p2_plan_native_audit` | C2完整PR矩阵、全部Rust harness/新增逐名执行，整合非Rust原文 | PASS_NATIVE | [c2-native-audit.md](p2-active-incremental-plan-evidence/c2-native-audit.md)；17,306 B；`29aa86bf6569e62fded5f871dc8a98091d3927b019869b52eea30e5cf5e705bc` |

代码审核原件中的`native_acceptance=false`或阶段pending是当时范围的真实记录，不能修改为新结论；本报告在完整读取后结合后续原生证据另行形成作者交付总结。CI、作者自查、附属静态检查及设计PASS均没有被当作另一项完整非作者代码审核。

## 原件、成本与后续范围

最终归档为131份原件、3,893,034字节，另有8字节`.gitattributes`用于保持原始字节，清单自身不计入原件。清单45,397字节，SHA-256 `d516fcf9eefe98482be6a7bb509db72c49c8a51945dfc67b8022ef864197af6c`，没有待补原件。[原件清单](p2-active-incremental-plan-original-manifest.json)列出本阶段源身份、冻结设计审核、两路完整代码审核、测试附属检查、C1失败、C2完整native、资源artifact和操作工具manifest的精确路径、大小与SHA-256。各artifact的`metadata.json`是GitHub连接器返回值的规范JSON保存；原始日志和已归档ZIP成员保留逐字节内容，各自单独记录hash，不混称同一种原始传输字节。[合入索引](p2-active-incremental-plan-merge.json)只记录实际运行合入；最终文档候选的准确身份、源码逐字节等价、非作者复核与实际文档合入应另记于PR #15所链接的文档PR，避免文件包含自己的未来提交或审核hash。

成功CLI完整路径执行四次完整真实重放：两次open各一次，方法再验证双方各一次。两个已打开归档调用方法新增两次。每次验证器都有独立空授权缓存，只有固定电路的不可变公共密钥按进程共享。只读计划没有降低既有完整复制的三次重放，也没有节省当前两份归档占用的磁盘。

计划最多2048条，比较缓冲为两个各64 KiB，JSON预留预算`2048 + 96 × 范围数`最大198656字节。这些是实现上界和静态预算；未实跑2048段、1 GiB或一百万记录的计划。两份归档仍保留全部段句柄，重放reader复制句柄且完整历史状态占用内存；这些局部预算不等于整个进程的内存或句柄峰值。物理合成帧测试不充当真实授权证据，回调主动返回Storage也不等于实际allocator OOM。

两枚pin各自需要独立可信来源，关系检查不认证未来路径、全网最新状态或共识finality。保留句柄、合作锁、链接/重解析点及全字节检查仍以可信父目录、OS和文件系统为前提，没有任意敌对瞬时修改再还原下的原子快照保证。

P2继续`in_progress`；`incremental_backup_implemented`、`snapshot_state_import_implemented`、`production_storage_ready`、`audited`和`real_funds_allowed`保持false。持久增量包及应用/恢复、状态快照导入、剪枝与迁移、验证者最后签名状态协调、真实断电/磁盘满、Windows目录持久化、全容量及长期多机、网络隐私和外部专业安全审计均未完成。本次合入不构成真实资金或公网部署授权。
