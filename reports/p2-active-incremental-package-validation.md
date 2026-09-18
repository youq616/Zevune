# P2 活动归档持久增量包与新目录恢复验收

日期：2026-09-18。本文件是作者整理的交付说明和证据索引；独立结论以保留的非作者审核原件为准。

**本运行阶段已通过准确 C3 的两份独立代码审核、完整原生审核及非 Rust 分项审核，并经 [PR #17](https://github.com/youq616/Zevune/pull/17) 实际合入。** 新能力是将两份独立可信检查点之间的公开活动账本增量写成一个持久包，结合较早完整归档验证，并恢复成全新活动目录。恢复后仍走真实授权及全历史重放。P2 整体保持 `in_progress`。

## 准确源码和合入身份

| 对象 | commit | tree |
|---|---|---|
| 阶段基线 | `2cc87a2207d502ac5cfe00ea52e525c1516917e5` | `b5841120084a72c5948b0a2754f712e5f67ad602` |
| C1，格式失败 | `61c691270b91aece076177cb757e51e0e63fe310` | `56dad7fdaad64b2b29ddac6b9585b8695aa465d7` |
| C2，strict Clippy 失败 | `f51c8db240933256870ff03c07bc68915b4ac4a1` | `7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400` |
| C3，已验收源码 | `cb0804e7c921a456cbbafab313b3a4a4501b8f5e` | `21de343c12bc27cb1022ffd7ebd451abe0e61f29` |
| C3 PR 实际测试 checkout | `3dfa8d77921693b9e99af5b94af198498b9422e9` | 与 C3 相同 |
| 实际运行 merge | `bf88c6551ff7fa3e4c87e47897c60f6009a5cfc4` | 与 C3 相同 |

实际运行合入时间为 `2026-09-18T16:28:39Z`。测试 checkout 与实际 merge 分开记录；两者有序 parents 均为 `[阶段基线,C3]`。C3 自身 parent 是 C2，C2 自身 parent 是 C1。准确 source/tree、实际 merge、closed PR 和当时 main 的原始响应交叉一致，见[合入索引](p2-active-incremental-package-merge.json)及[作者合入观察收据](p2-active-incremental-package-evidence/source-identities/runtime-merge-receipt.json)。观察收据不算独立审核。

相对基线共 12 个路径：5 修改、7 新增，最终文件 262,465 B；其他 881 个既有 path/mode/type/blob 相同。包含冻结设计、两层 package 实现、既有活动归档/增量公共辅助、CLI 和渲染、对应物理/API/子进程测试及真实付款 flow。工作流、依赖、授权规则、既有时间及容量预算没有改变。最终全部文件身份见[C3 代码范围原件](p2-active-incremental-package-evidence/c3-code-review-scope.json)。

[冻结设计](../docs/ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md)为 13,361 B，SHA-256 `b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41`。实现前取得两路非作者 PASS_DESIGN 后冻结；其历史设计状态和后续审核原件中的 pending 均保留，不倒写成新的结论。

## 实际调用与约束

新增命令为 `pack-active-incremental`、`verify-active-incremental`、`restore-active-incremental`，完整可执行示例见 [README](../README.md)。全部显式要求 `--no-real-funds`、绝对路径和两枚外部独立可信 ZVARCP01 pin。pack 的 source 是较后归档目录；verify/restore 的 source 是包文件，执行时无需保留较后目录。restore 的 output 必须是既存可信父目录下的新目录。

包格式 `ZVAIPK01` 使用固定 268 B 前缀：magic、两枚 128 B pin 和范围数；每个范围 12 B，再接新增原始公开账本字节。无压缩、路径描述符或导入状态。最多 2,048 个范围，元数据最多 24,844 B；包文件保守上限 1,073,766,668 B。重建归档仍受原 1 GiB、1,000,000 条记录、2,048 段和 1 MiB 单段约束。相同 pin 的空包也是 268 B，并照常完成验证和恢复。

内嵌 pin 只与外部可信 pin 比较，不能自行建立信任。必须同 genesis/header、非回退、精确旧尾 offset、严格递增范围及连续新段；最终文件长和 EOF 精确匹配。拼接后的流继续经过原物理帧与规范轮换检查、真正 State Replay 和 Orchard 授权，重新计算的普通摘要或伪造 layout pin 不能绕过签名与状态规则。每次完整验证都新建独立空授权缓存，只共享不可变的固定公共验证密钥。

读入包保持原始只读句柄和共享锁，创建包保留原创建句柄与独占锁。父目录身份、文件名称、链接/重解析点、精确长度和完整字节按操作前后检查。组合 reader 借用原有句柄、显式偏移，使用 64 KiB 有界缓冲，不复制整组文件句柄。restore 保留所有原创建目标句柄，逐文件同步，并在支持路径同步目录后完整验证目标及输入；不会先解锁再重新打开目标来宣称原对象已验证。

成功 CLI 共执行完整重放 **pack 6 次、verify 3 次、restore 8 次**；对已经打开的对象分别由 pack 方法新增 4 次、verify 新增 2 次、restore 新增 5 次。增量包减少重复备份字节，本轮没有证明重放更快或整个进程占用更少。JSON 回执格式为 `zevune-active-incremental-package-1`，声明验证结果与限定的写包/恢复行为；`snapshot_imported`、`finality_verified`、`validator_ready`、`real_funds_allowed` 保持 false。

创建后失败可能留下部分或完整新文件/目录，不自动删除、覆盖、截断、重试或悄悄重建。完整输出也可能因最终检查或 stdout 写入失败而返回错误；只有后续显式验证可以判断该输出是否可用。CLI 回执预算为 `2048 + 96 × 范围数`，最大预留 198,656 B；stdout 写入错误会传播，部分 JSON 不构成成功回执。

## 准确 C3 的实际验证

10 个必需 `pull_request` 工作流、23 个不同 jobs 全部 attempt 1 成功，**274 个成功步骤、9 个原有 Windows 条件跳过**。23 份完整日志共 1,417,655 B，全部绑定 C3 的实际 checkout。没有借用 push run、早期候选或旧阶段结果。逐项 run/job 链接、终态和原始日志大小/SHA 见 [CI 索引](p2-active-incremental-package-ci.json)。

| Rust 实际范围 | Ubuntu | Windows |
|---|---:|---:|
| 每次 default suite：20 个 harness | 库 171，总 185 | 库 163，总 177 |
| funded-library：1 个完整 library harness | 190 | 182 |
| funded interfaces：22 个完整 harness | 71 | 70 |
| 新 package CLI，在 funded interfaces 实际执行 | 8 | 7 |
| 本阶段新增定义中该平台实际适用的唯一测试 | 25 | 24 |

本阶段源码共 27 个新增测试定义：19 个库定义中各平台适用 17 个，加 8 个 CLI 定义中 Ubuntu 8 / Windows 7。八个 default jobs 和四个 funded jobs 共 **206 个完整 Rust harness、1,961 次重复具名通过执行**；重复工作流不是新增唯一测试。默认 feature 下 package CLI target 为 0 项，不计 CLI 执行信用。funded 动态计划逐一覆盖实际 binary/integration targets 和 doc-tests，并有 cohort 完成标记；library 本身没有单独 Clippy，严格 lint 在原 interfaces 等任务实际执行。

原生审核完整核对了 target、`running N`、具名结果、result 和 feature gate。某个 C3 日志的 Cargo stderr announcement 晚于对应 stdout 零测试结果；审核解析器新增 v2，按两个流各自顺序严格配对，逐项检查名称及计数。v1 原件保留，全部 C1/C2 的两版结果相同。此为证据解析修正，未改产品代码或验收条件，也没有把零测试赋予执行信用，见[解析观察](p2-active-incremental-package-evidence/rust-parser-v2-observation.json)。

新增用例包含独立编码的包和完整 JSON、去掉较后归档后的验证/恢复及继续提交、空包、旧尾增长和多个新段、短读写/Interrupted/EOF、锁及父目录身份、Unix 链接替换和 Windows 共享名称保护、错误格式/pin/网络/分叉/范围/包字节，以及失败残留和显式重开验证。非法早轮换与帧拆分即使重算 pin 且通过未验证物理字节组合，也在真实完整 replay 拒绝。物理合成大段只证明 transport 范围，不能充当真实 State 或付款证明。

既有四个真实 active_flow 测试在 funded-library 双平台均通过。主要 flow 保留原先全部余额、费用、双花拒绝和旧复制/恢复断言，原有两笔真实付款证明没有增加或替换成 stub。第一笔在高度 6,964 触发正常 1 MiB 轮换；第二笔在高度 10,001 从本轮增量恢复目录继续实际花费，随后再次打包/恢复并提交 10,002 空块。坏 binding signature 用例重算帧摘要和 later layout pin，直接通过公共包接口与有效 base 组合，得到真实 Authorization 拒绝。

既有 Go test/vet、支持平台 race、8 次实际有界 fuzz engine、Python 全套/资源/scheduler 及真实 Go↔Rust/Python↔Rust 调用通过。fuzz 保持 5 个 3 秒、3 个 10 秒的原命令预算，全部 parallel=2；非 Rust 原文前言中的泛指歧义由[独立追加澄清](p2-active-incremental-package-evidence/c3-native-fuzz-budget-clarification.md)明确，原报告和原生结果均未改写。四进程共识、活动四节点付款/全部节点重启后继续付款、wallet 恢复均按各自实际顺序核对。双平台增长真实完成 100,000 个本地 worker blocks，其中 99,998 空块、2 付款，15,018,544 B / 15 段，完整重放后继续 100,001；这不是 100,000 笔付款或四节点 100,000 共识高度。

双平台既有 32+1 付款资源回归保留原固定预算，完整核对每平台 9 事件、181 操作/362 progress、18 个 OS 内存样本、14 checks 和三个已登记进程身份（两代 worker、一代场景）的清理，最终高度 33、68 commitments、66 nullifiers、费用 33,000。它验证原资源工作负载，本轮没有新增 package CLI 专项峰值、吞吐或全容量测试。操作工具 ZIP 的全部五个 payload 已独立核对长度、SHA 和 CRC、精确 source/tree；没有执行下载的二进制，也不声称可复现构建或代码签名。详见[完整非 Rust 审核](p2-active-incremental-package-evidence/c3-native-nonrust-review.md)。本地没有 Rust/Go 工具链；上述运行来自真实 CI。

## 修正历史与非作者审核

C1 的 7 文件、30 个 rustfmt hunks 被原生检查拒绝：10 runs 为 2 成功/8 失败，22 个 job 为 4 成功/17 格式失败/1 零步骤依赖跳过；没有执行 Rust 测试。C2 按原始 formatter 输出逐字节修正；两路代码审核和原生审核独立重建并核对全部格式变化。

C2 格式通过，默认 Rust 和 funded-library 的实际成功保留，但 10 个 jobs 因测试中的 `drop(reader)` 触发 strict Clippy `drop_non_drop` 而失败。C2 最终 5/5 runs、13/10 jobs，228 成功/10 失败/45 跳过步骤；162 Rust harness / 1,820 次重复具名通过，funded interfaces 在运行测试前已被阻断，因此 package CLI 为 0 次实际执行。资源、增长和 operator 的分项成功不能抵消整个候选拒绝。

C3 只删除一个不持有资源的借用 reader 的显式 `drop`，减少 22 B；其余 892 个 C2 entries 完全相同。真正拥有文件/目录和锁的对象仍按原顺序释放，所有 EOF、字节、锁冲突和释放后重开断言保留。两位独立审核者重新检查准确 C3 后给出 PASS_CODE，C3 自身的全矩阵与独立原生结论才关闭最终验收阻断。

| 非作者任务 | 实际审核 | 原件 |
|---|---|---|
| `/root/p2_package_design_review` | 冻结设计 PASS_DESIGN；C1/C2 全部源码/调用/测试及准确修正链；C3 PASS_CODE | [设计](p2-active-incremental-package-evidence/design-review.md)、[C3](p2-active-incremental-package-evidence/c3-code-review.md) |
| `/root/p2_package_storage_review` | 冻结设计 PASS_DESIGN；独立存储/对抗测试及准确修正链；C3 PASS_CODE | [设计](p2-active-incremental-package-evidence/design-storage-review.md)、[C3](p2-active-incremental-package-evidence/c3-storage-review.md) |
| `/root/p2_package_native_audit` | C1/C2 明确拒绝；准确 C3 全部原件、Rust 具名结果并整合非 Rust，PASS_NATIVE_C3 | [C1](p2-active-incremental-package-evidence/c1-native-review.md)、[C2](p2-active-incremental-package-evidence/c2-native-review.md)、[C3](p2-active-incremental-package-evidence/c3-native-review.md) |
| `/root/p2_package_native_audit/nonrust_logs` | 全部非 Rust 日志/API、真实工作负载、资源 ZIP 与 operator payload，PASS_NONRUST_NATIVE_C3 | [C3](p2-active-incremental-package-evidence/c3-native-nonrust-review.md) |

root 已完整读取上述正式 Markdown，复核文件大小/SHA，并修复和重新审核所有阻断；作者自查与 CI 不替代独立任务结论。每个原件仍保持当时准确 head/tree、已读/未读范围与历史 pending，不被重新标记。设计 PASS、静态代码 PASS、实际 CI 和最终合入分别记录。

## 归档与剩余范围

[原件清单](p2-active-incremental-package-original-manifest.json)列出 292 个归档材料、11,043,577 B，分类保留 reviewer 原件、connector 解码 API/log、精确 resource ZIP/成员及派生校验。所有逐文件大小/SHA 与原始内容核对；清单和保持字节的 `.gitattributes` 本身单列，不计为原件。C1/C2 的失败记录完整保留，旧阶段报告逐字节不变。

operator 完整 ZIP 及二进制已在临时工作区独立逐成员验证；仓库只归档原 manifest、API digest、下载观察和完整校验记录，不能称仓库含有这些完整 ZIP。github_fetch 返回的 API decoded-content 与 job 日志按 connector 解码的原始 UTF-8 内容保存，保留 BOM/CRLF；部分 reviewer remote 包装 JSON 则明确标记其保存表示，不混称 HTTP 传输原字节。原报告内历史绝对路径不改写，清单提供原路径到仓库材料的映射。

当前总清单已按[来源表示类别纠正记录](p2-active-incremental-package-provenance-correction.json)修正 merge-tool result 的分类：该文件是完整 `structuredContent` 对象经格式化 JSON 序列化保存。归档中的 v1 spec 和 builder 保留 D1 的历史生成规则，其中这一处被明确纠正的分类以当前总清单为准；292 份来源材料的原始字节和身份保持不变。`freeze_source` 继续绑定原始收集输入，不表示未经修改的 v1 builder 生成了修订后的元数据；publication-check 中的旧清单 hash 仍是其 D1 历史观察的准确身份。D1 的独立文档拒绝原文与后续准确候选的复核及实际 CI 分别保留在文档 PR #18，本纠正记录本身不授予新候选通过。

本次只将 `incremental_backup_implemented` 在 NO-FUNDS 活动归档持久包及新目录全重放恢复范围设为 true。P2 仍在开发，snapshot state import、生产存储、外部专业审计和真实资金状态保持 false。剪枝/迁移、验证者最后签名状态及 wallet/共识数据库协调恢复、真实断电/磁盘满、Windows 目录掉电持久化、1 GiB/百万记录/2,048 段全容量、长期多机与网络隐私均未完成。可信父目录、OS/文件系统及独立 pin 仍是前提；没有任意敌对瞬时修改再还原下的原子快照保证。

运行 merge 与文档候选分开验收。最终文档的准确 head/tree、运行字节继承、非作者文档审核、其实际自动 CI 和实际文档合入记录在 PR #17 所链接的文档 PR 中，避免本文件包含自己的未来提交、审核或合入 hash。没有授予公开部署、真实资金或新增付费基础设施权限。
