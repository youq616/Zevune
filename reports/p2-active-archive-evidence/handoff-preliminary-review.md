# P2 活动归档交付文档：非作者预检原文

审核任务：`/root/p2_archive_handoff_review`。观察时间：2026-09-17 08:42:08 UTC。

结论：**PRELIMINARY — 当前交接草稿未发现必须先修复的事实、证据映射或边界表述问题。此结论不是最终文档候选 PASS，也不是 C3 CI、阶段验收或合入批准。** 原生结果、runtime 实际合入和最终准确文档 head/tree 尚未提供完整闭环，必须另行复审。

本任务未编写、修改或格式化候选设计、源码、测试、工作流、状态文件及交接草稿，只创建仓库外的本审核原件。我已阅读 `AGENTS.md`、`docs/STAGE_REVIEW.zh-CN.md` 和准确冻结设计，按非作者任务审核要求进行预检。

## 精确对象

- 仓库：`youq616/Zevune`；运行候选 [PR #13](https://github.com/youq616/Zevune/pull/13)。
- 阶段 base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`；base tree：`5e039b41e00f7a0a2e78937c796a40fbe68bfb0c`。
- C3 source：`7045af4ae254f0a5a5e4810f17004c91e649e474`；tree：`4017bee976c18767ed568d7ec8a33f6d668b8c22`。
- C3 唯一 parent：`7477d9e0656ed751f525a4b6fe9f6649b995ede6`。
- 冻结设计：`docs/ACTIVE_ARCHIVE_V1.zh-CN.md`，13188 B，SHA-256 `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee`。

独立 Git 核对确认上述 C3 身份与父提交；`candidate-c3.json` 的全部 10 份准确 Git blob 的长度、SHA-256 和工作树字节相符。观察时工作树干净。相对阶段 base，`.github`、`scripts`、`internal`、`integration/cometbft`、Cargo/Go 依赖文件、AGENTS/STAGE_REVIEW、原报告、README、DELIVERY_PLAN 和 PROJECT_STATUS 均未由 C3 改动。

此次审核对象仅位于仓库外 `zevune-p2-active-archive/handoff-draft/`，不是已经冻结或提交的文档源码树：

| 草稿文件 | 字节 | SHA-256 |
|---|---:|---|
| `README.md` | 19513 | `9e318d32fcf7fb90f84f65cc1955754d9716d06a6ee91e3b358c144b749dd08b` |
| `docs/DELIVERY_PLAN.zh-CN.md` | 20617 | `9dc8fbe368ac9c51e8d005979f27a5ea1ea041aef9097b1e76650b76d2cd715e` |
| `reports/p2-active-archive-validation.md` | 29198 | `8136acc59dfc7a6f255ca7780897fadd897b1c6269901ce09960eb5f9ff5eba4` |
| `proposed-status-updates.json` | 8581 | `25921aaaf97e21f5abc55ec749442f1fed1fec0784ac7b88dec3b4ecfc02410d` |

## 已完成的核对

1. **独审结论与原生执行明确分开。** 全文读取两份准确 C3 非作者代码复审原文，并检查报告引用的长度和 SHA-256。主审核原文为 14909 B / `7c864c3e9288c4dbae9149fc9bddec3de9113926a014ff6c092c2d5db12b05cf`；对抗复审为 12629 B / `127d9ef1b798aeb008542e58af6241a8efe24799cba59ef2014bc4ec7c7f0f2b`。草稿准确限定两路 PASS 为 C3 代码和测试设计，没有转写成 CI 或阶段接受。报告实际保留 5 个命名 PENDING。

2. **历史失败保留原含义。** 对照 C1 主审核、对抗审核、补充原文、C1 原生拒绝记录及 C2 原生 Clippy 拒绝 JSON。报告保留 C1 格式失败、AR-C1-01 测试合同缺口、C2 Clippy 失败与三组不同 source/tree；初始静态 PASS 没有覆盖其后 CHANGES REQUESTED。报告没有把缺少交换测试说成已证实的生产接受漏洞，没有把 C1/C2 部分执行或未知终态当成 C3 成功。

3. **交换与坏签名的拒绝层准确。** 直接读取 C3 `active_flow_tests.rs` 中两个已有真实段的交换代码。原 pin 因布局变化返回 Corrupt；重算 pin 经实际生产 layout_hash 校验相符后，交换首记录的 base_hash 不等于独立 genesis AppHash，仍要求 Corrupt。报告没有声称该分支返回 Authorization。另一个真实 binding signature 损坏、重算 record checksum 和 layout pin 的用例明确要求 Authorization，且具有正常复制对照。

4. **恢复流程和状态比较范围准确。** 直接读取新 pin、检查点导出、ActiveArchive、共享保留句柄 replay、物理文件复制和 CLI 分支。完整 committed Summary 只在 checkpoint export 与已拥有 store 比较；archive verify 通过真实重放所得 genesis、高度和 AppHash 对照独立 pin，同时核对容量、物理布局和前后字节/namespace。草稿区分了这两类比较。source 共享根锁、target 原创建句柄独占根锁、target 完整验证后再次完整验证 source、最后检查 target 字节/namespace 的描述与源码相符。

5. **故障注入没有扩大为真实故障保证。** fault 1/2 留部分头/段，3 在最后文件完成写入但同步前返回错误，4 在同步后丢失成功确认；完整过程可见副本允许显式后验验证。fault 5/6 故意增加未知源或目标目录项，报告明确只保证原账本文件字节不变，被注入目录项集合已变，未宣称整个目录不变。stdout 失败、残留目标不自动删除和后验验证边界与 CLI 源码相符。

6. **测试名称和平台映射准确。** 自动核对报告 31 个带模块缩写的函数引用均存在于准确源文件；再阅读增长、签名、frame/header、create-new、fault 和 namespace 相关断言。12 个新核心库测试、namespace 的 4 项双平台 / 2 项 Unix / 1 项 Windows 和 7 项新 funded CLI 的源码预期与 cfg 一致。报告将 Ubuntu 18 / Windows 17 明确写为新库测试的执行预期，并未当成已运行数；既有 4 个 active-flow 用例、新增 44 行交换断言、子进程重复单项结果和 default feature 下零测试未被重复计数。6963 个空块、6964 首次付款跨段、10001 第二跳和随后 10002 空提交的映射与实际增长源码相符。

7. **原件、相对链接和状态补丁。** 草稿新证据目录当时共有 36 份文件、764387 B，逐一与 scratch 原件比较字节完全相同。三份 Markdown 的 67 个相对链接以“草稿覆盖当前准确仓库”的最终路径规则检查，均可解析；不能把这项预检当成已经发布到 GitHub 的链接可用性。所列设计、布局向量、C1/C3 审核及历史失败原件大小/hash 全部相符。PROJECT_STATUS 原件 SHA-256 为 `3ab68713693a471fdb39bb9a6f464b2e14fc2aee310db7012ea0ae66f49265e1`，与补丁声明一致。28 项补丁仅在内存模拟，没有写状态文件；add/replace 目标有效，声明保留的 legacy、payment_resource_*、active_ledger_*、旧报告身份及其他工作包状态全部保持。

8. **未完成边界保持。** P2 仍为 in_progress；incremental_backup、snapshot_state_import、production_storage_ready、audited、节点账本整理和已有用户数据迁移仍为 false。新归档 scope 使用独立键，旧 pool_recovery_scope 继续准确描述 legacy API。前阶段 32+1 指标没有被改成归档操作测量；2048 段、reader 额外克隆句柄、完整历史内存、Windows 目录持久化、可信父目录/OS、真实断电/磁盘满和完整验证者签名状态恢复限制都保留。

## 最终复审仍需的对象

报告尚有 `PENDING_CHECKOUT_IDENTITY`、`PENDING_STAGE_ACCEPTANCE`、`PENDING_RUNTIME_MERGE`、`PENDING_HANDOFF_REVIEW_AND_MERGE_RECORD` 和 `PENDING_NATIVE_CI_EVIDENCE`。状态提案也有对应待解析值，并有明确应用门槛；这些内容在本次只读草稿中合理，不能原样作为最终阶段接受证明。

收到完整准确 C3 原生 CI、非作者原生验收、runtime 实际 merge、最终文档 source/tree 和全部最终原件清单后，需重新核对实际结果/跳过项、准确 checkout/source/tree/parent、原日志字节/hash、状态应用、最终相对链接，以及文档候选相对被验收 runtime 的全部运行源码/测试/依赖/工作流字节不变。最终独审及文档实际合入身份必须使用非自指记录方式保留。

本任务没有执行 Rust/Go 编译、测试、fmt、Clippy 或原生 Windows 操作；没有触发或轮询 C3 CI，也没有取得尚未完成的运行结果。这里只执行 Git、字节/hash、链接、源码引用和内存补丁检查。未写候选文件，未发布、合入或批准尚未冻结的最终文档提交。

**最终预检状态：PRELIMINARY，当前草稿事实表述阻断 0；阶段 CI 与最终准确文档审核仍待后续独立闭环。**
