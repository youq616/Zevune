# P2 活动归档交付文档：C7 非作者预检原文

审核任务：`/root/p2_archive_handoff_review`。日期：2026-09-17 UTC；主要身份／字节快照时间为 10:58:11 UTC。

**结论：PRELIMINARY_WITH_FINDING。发现 1 处需在最终文档候选前收窄的测试映射表述（HD-C7-01，Low）；其余本次范围未发现事实、来源身份、历史边界、现有链接或状态补丁错误。** 本结论不是最终 D 的 PASS，不批准运行候选、阶段接受或合入，不认证 C7 原生 CI。

本任务保持非作者身份，未修改草稿、仓库、设计、源码、测试、工作流或既有审核原件。仅新增本预检原文。最终文档必须在准确 D head/tree 发布后另行独立审核。

## 对象与文件身份

- Stage base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`。
- C7 source：`de474720431daf33afd4a7ebc32de2d230344a5a`。
- C7 tree：`e4dd17dfb1efd0e3ca20441168b62b72b6fc3108`。
- C7 唯一 parent / C6：`88146d54f2eaac39958ceaaea9e13f71832d536e`。
- PR：[#13](https://github.com/youq616/Zevune/pull/13)。
- 报告记录的 synthetic：`00d4442b12cb72344ffa5bea101eb7142ab03270`；该身份明确引用 root/API 与 native 身份原件，本任务没有重新访问 GitHub API 或认证各 runner checkout。

独立本地 Git 检查确认 source/tree/parent，观察时工作树干净。C3 十文件清单与 C4、C5、C6、C7 增量叠加后恰好覆盖全阶段 16 个变更文件，全部当前 Git blob 的长度、SHA-256 与工作树字节相同；全阶段准确为 +2949/-38。C6→C7 准确为 3 文件 +5/-5。

本次四份草稿位于仓库外 `zevune-p2-active-archive/handoff-draft/`：

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `README.md` | 20223 | `a246b842c5ee6ce102e598e70ff86b9fbbdb670250b8c7f0ade25ed010c2e058` |
| `docs/DELIVERY_PLAN.zh-CN.md` | 21279 | `a9602b334bbe5f86365f51104bc1011b32167b52837a4adfeec69e195cfdc115` |
| `reports/p2-active-archive-validation.md` | 65498 | `cf88c044e0e6ff491be97debe7d65440e3452cc003ae84e75237c5d1d64d2514` |
| `proposed-status-updates.json` | 11518 | `c38ec58b4a249a7da1a59e8c2b01b84cd3451bc4cf3a51e6f82aa6ba3acbe36f` |

## HD-C7-01：最后一个新验证器的测试断言被合并描述得过宽

严重性：**Low，交付文档的测试证据映射问题**。不是已证实的生产或密码学缺陷，不要求修改运行代码／测试。

位置：上述准确报告第 136 行，“固定公共 key 与独立真实授权缓存”一行。当前描述为：

> A 与提前创建的 B、4 个并发新实例及最后新实例分别检查空缓存／真实成功记入

准确 C7 的 `integration/orchard/src/wire/fixed_key_tests.rs` 中，A、B 和四个并发实例确实各自检查空缓存、执行真实 verify，并检查本实例已记入成功；但是最后临时新实例只有 `AuthorizationVerifier::new().verified.contains(&raw, digest)` 为 false 的断言。没有对这个最后实例调用 verify，也没有检查它成功记入。两份 C7 代码复审原文对这一步均准确写成“最后新建实例仍空”。

建议将该行拆清：“A、提前创建的 B 与四个并发实例分别执行真实验证并独立记入成功；最后新建实例仅核对缓存仍为空。” 保留 1 份真实 proof、固定 key 指针／版本、坏 proof／binding signature 的准确 Authorization 拒绝及原字节正对照描述。无需新增测试或提高用例计数。

本任务已向 root 报告；root 确认该句过宽并保持草稿原字节，计划由作者修订。**本原件记录的是修订前快照，未验证修订已经完成。** 最终 D 复核需确认该处已修正。

## 本次其余核对结果

**固定 key 与测试模块范围。** 直接读取 C4→C7 的全部七文件差异、新冻结 FIXED_VERIFYING_KEY 合同、当前 wire 与完整固定 key 测试。私有 OnceLock 只构建编译期 CIRCUIT，新的 verifier 仍按值新建独立空 VerifiedCache；verify 顺序、缓存容量／规则、真实签名与 proof 路径保持。新共享对象是不可变公共电路材料，没有全局成功缓存、外部 key、备用接受器或状态共享。报告对进程常驻成本、初始化 panic、冷首次初始化竞争和未量化性能的限制明确，没有将历史耗时归因为完整 profiler 结论。

C7 三处变化仅将既有 fixture 可见性限定为 pub(crate)、在 pool 的 cfg(test) 下重导出，再由 wire 私有测试导入单一定义；没有第二次 path/mod 加载、lint allow 或生产 helper。机械比较确认：C6→C7 的生产 wire 原字节相同，完整 `#[test]` 函数体 3537 B 原字节相同，原 fixtures 实现与 stage base 原字节相同。完整归档核心和 CLI 未削减；copy_new 中源前验、目标验、末次源验三次完整 replay 保持，每次 verifier 的授权缓存独立为空。README、DELIVERY_PLAN 和状态新增 scope 对这些范围描述相符。

**准确 C7 独审原件。** 全文读取两份正式 C7 Markdown，并核对成对 JSON、身份、结论和 hash。主审核为 PASS_CODE_REVIEW，16385 B / `67ce684d10ac4c6cdf26fda1c182a589e589ff3d64cd9842456f1670e130fabb`；对抗审核为 PASS_STATIC，16719 B / `f4f99272f42e0057a9012d9b8f1e7b8ad174e4a576f3acc094e8038f3acc969e`。两份 JSON 都保持 stage_accepted=false，均未认证当前 native 和 synthetic checkout。报告正确把 GitHub synthetic 身份归因于另两份 API 原件，没有扩大代码审核者的取证范围；C7 静态关闭未被当成原生关闭。

**C4–C6 历史没有转为 C7 信用。** 读取 C4 NOT_ACCEPTED 首轮快照、晚到重跑附录、C5/C6 native 拒绝和 C6 两路纠正补充。C4 的 18 success/5 cancelled、23 个首轮完整日志和四次另存重跑的 2 success/2 cancelled 均保持原范围；没有把完整日志归档误写成被取消用例全部完成，没有由接近预算的时长推定取消原因。C4 最终 NOT_ACCEPTED 保持。

直接检查选定原始日志中的关键事实：C5 的唯一格式 hunk 于 10:25:48 UTC exit 1；C6 的新 key 测试实际 ok、库 140 passed/66.85 s、全部 default 18 个结果合计 154 passed，随后 duplicate_mod 于 10:33:51 UTC 被 -D warnings 提升为错误，10:33:52 exit 101。报告既没有抹去真实部分成功，也没有以其覆盖必需 lint 失败或默认 feature 的零 CLI 用例。C6 对抗 Markdown 未成对交付 JSON、末次 HEAD 核查／再次 Python 向量未完成的事实按 addendum 如实列出；本地原件和草稿原件目录都没有 `adversarial-review-c6.json`，未补造它。C7 的实际 Python 检查没有被追记为 C6 完成。

**之前已审边界保持。** 当前报告继续将导出时的完整 committed Summary 比较与 archive 的 pin/重放 tip 比较分开；交换真实段的 Corrupt 与坏签名重算后的 Authorization 分开。fault 5/6 明确改变被注入目录项集合，只保留原文件字节不变；C3 stdout 失败停在 helper 首断言，后面的副本断言未取得执行信用。C4 安全 File 回执修复及同名七项 CLI 计数、Windows NULL 未设专用 fixture、File flush 不等于 fsync 等限制继续准确。

**测试函数与计数口径。** 原 31 个带缩写函数引用全部存在于准确 C7，再加新 wire 固定 key 函数也存在。原活动核心／namespace／CLI／active-flow 的数量和 cfg 范围保持；固定 key 用例单独增加一个库源码预期，含一份真实 proof，未当作新增归档付款、四份线程 proof 或重复运行的新增覆盖。默认与 funded 的 140/133 和 159/152 在报告中仅作为源码预期，未登记为 C7 实际验收通过。唯一需收窄的映射为 HD-C7-01。

**现有证据、链接及摘要。** 本次快照证据目录已有 271 份对应原件副本、6883071 B；逐份与 scratch 原件比较字节全同，另有 8 B 的局部 `* -text\n` 属性文件。该数包括继续装配的部分 C7，不能作为最终 archive manifest 或完整原生验收数量。三份 Markdown 的 135 个相对链接在“草稿覆盖准确仓库”的路径规则下均存在。报告 46 个不同 64 位十六进制摘要中，45 个匹配对应现有文件；另一项为已知规范布局向量 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`，本来不是文件 hash。两份冻结设计、当前固定 key 测试、C7 正式审核／JSON、native/root 身份原件及关键历史记录的大小/hash 均匹配。

**状态补丁。** 提案现在为 32 项操作（较 C4 增加四个固定公共 key 字段），只在内存模拟，没有写状态文件。base 状态 hash 保持 `3ab68713693a471fdb39bb9a6f464b2e14fc2aee310db7012ea0ae66f49265e1`。已有顶层键仅 current_ci、delivery_workstream_status 内的 P2、active_segment_backup_implemented 有建议变化；其余新增键为独立 scope/来源。legacy pool_recovery_scope、全部 payment_resource_*、active_ledger_*、历史元数据及 P1/P3–P8 全部保持。P2 为 in_progress，incremental_backup、snapshot_state_import、production_storage_ready、audited、node_ledger_compaction 和 existing_user_data_migrated 仍为 false。旧 32+1 数据未被改记为归档资源测量。

## 有意待装配部分与最终复核

报告四项 PENDING（native、stage acceptance、runtime merge、文档审核/合入）符合本次任务阶段，**不是内容缺陷，也不要求现在填完**。状态提案指向的最终 `p2-active-archive-ci.json`、`p2-active-archive-merge.json` 和 `p2-active-archive-original-manifest.json` 当前尚未装配，按预期列为待完成；不得据此虚构结果，也不把现有原件副本数当成最终清单。

本次预检未本地运行 Rust/Go、fmt、Clippy、原生平台测试；未触发、轮询或验收 C7 CI。实际执行的是准确 Git/diff/blob 比较、阅读代码与已有审核／历史证据、哈希／链接／函数检查和内存状态补丁模拟。未重新审核全部原生日志，也未生成新的 native 审核结论。

作者修正 HD-C7-01 后，仍须在完整 C7 原生验收和 runtime 实际合入之后，冻结准确 D head/tree，再由非作者检查最终报告、原件清单、真实合入身份与运行源码／测试／依赖／工作流字节等价。**当前仅有界 PRELIMINARY_WITH_FINDING；最终 D 审核必须单独完成。**
