# P2 活动归档交付文档：C4 非作者增量预检原文

审核任务：`/root/p2_archive_handoff_review`。观察时间：2026-09-17 09:28:07 UTC。

**结论：PRELIMINARY。所审 C4 草稿未发现事实、测试映射、链接或状态范围的阻断问题；这不是准确最终文档提交的 PASS，不认证 C4 原生 CI，也不批准阶段接受或合入。** C3 的 stdout 原生反例及两份补充已被正确纳入历史；C4 的完整原生门槛和最终文档身份仍须后续独立审核。

本任务保持非作者身份，未修改设计、运行源码、测试、工作流、项目状态、草稿或既有审核原件。先前 C3 文档预检只判断当时草稿是否忠于当时证据，未批准 C3 阶段；不能以该 PRELIMINARY 覆盖后来发现的 AR-C3-02。

## 准确对象与身份

- 仓库：[youq616/Zevune PR #13](https://github.com/youq616/Zevune/pull/13)。
- 阶段 base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`。
- C4 source：`50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`。
- C4 tree：`3c44977028b58ddd387f52946632af594208edfb`。
- 唯一 parent / C3：`7045af4ae254f0a5a5e4810f17004c91e649e474`。
- 冻结设计仍为 13188 B，SHA-256 `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee`。

独立本地 Git 核对确认 C4 head/tree/parent，工作树观察为干净。以 C3 十文件清单覆盖 C4 两文件清单形成完整准确清单，全部十份 Git blob 的长度、SHA-256 和工作树字节相符。C3→C4 确实只改变活动 recovery CLI 和同名集成测试两文件，+90/-22；其余八份阶段文件字节不变。没有变动工作流、调度器、预算、依赖、真实证明数量或旧 CLI 执行分支。

PR synthetic `fb5ec39a59cb87aec0662c7706dce1f9e85e1962` 的 tree/parents 在草稿中明确归因于 root/API 记录，并区分 runner 实际检出。此次没有重新调用 GitHub API，不将这项报告引用检查说成本任务独立取得 synthetic 对象或核对了各 runner。

审核草稿位于仓库外 `zevune-p2-active-archive/handoff-draft/`：

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `README.md` | 19513 | `9e318d32fcf7fb90f84f65cc1955754d9716d06a6ee91e3b358c144b749dd08b` |
| `docs/DELIVERY_PLAN.zh-CN.md` | 20617 | `9dc8fbe368ac9c51e8d005979f27a5ea1ea041aef9097b1e76650b76d2cd715e` |
| `reports/p2-active-archive-validation.md` | 36116 | `f58041f2e60e15954e49601954f04a216802d8a336c0caee861d241c8f4e1f7a` |
| `proposed-status-updates.json` | 8973 | `1aca3836786b1765f8aa03a70033b39d6f96676a203c7498c556f53d5d4a592a` |

## C3 反证与 C4 修订的事实核对

1. **C3 原初 PASS 没有被保留为合入资格。** 草稿保留两份准确 C3 初始静态审核及其原 hash，同时明确说明原生 stdout 反例纠正了初审对错误传播的肯定。全文读取主审核与对抗审核的 C3 addenda，并对照 native 拒绝记录。AR-C3-02 正确归为回执错误传播缺陷，C3 不接受；没有将其表述为密码学失效、账本损坏或目标被删除。AR-C1-01 的历史源码关闭记录仍保持。

2. **失败断言之后的代码没有获得执行信用。** 直接读取准确 C3 失败日志 `c3/job-105131817273.log` 并计算 76073 B / SHA-256 `64c3e286d1f0ba3ed339d3047793b2e6190ea056a0c2b1f9bc037b06d6ff53bb`。实际六个 harness 结果为 0、0、0、3、11、6 passed，最后一个另有 1 failed；合计 20 pass / 1 fail。新增 CLI 的结果确为 6 passed / 1 failed、137.53 s，失败日志为 09:07:51 UTC、`tests/active_recovery_cli.rs:106:5` 的 `!output.status.success()`，随后 `FUNDED_COHORT_NOT_COMPLETED`。结合 C3 准确 helper 及调用方，panic 之后的 stdout/stderr、sink、源/目标字节、显式 verify 和已有目标拒绝断言均未执行。草稿准确保留此边界，未从测试名称推断目标完整或不存在。

3. **直接观察与根因解释分开。** 日志没有打印 OS errno 或 stdlib 底层写入错误；草稿把 EBADF/StdoutRaw 机制明确标注为独立审核结合官方源码和实际控制流得出的因果分析，并链接其依据。没有声称从日志直接读到 EBADF，也没有声称逐字节鉴定 runner 的 libstd 二进制。本次核对该表述与两份补充原文一致，不另做新的标准库二进制鉴定。

4. **C4 生产路径描述忠于实际 diff。** `write_active_receipt` 保留具名 StdoutLock，以安全借用 fd/handle API 建立 owned 副本，再转 File 直接 write_all/flush；Windows 在复制前拒绝 NULL，失败回到原 CLI 错误分支。函数不重新按路径打开输出、不接管或关闭原 stdout，没有 unsafe、权限提升、重复复制或删除目标。仅 active 成功回执调用该函数，旧输出分支不变。草稿没有把 File flush 称为磁盘持久化或接收者已经消费回执的保证。

5. **同一第七项测试被加强，非零要求没有放宽。** 直接核对 C4 同名测试：先将 verify-active 成功输出重定向到真实可写文件，读回并校验准确 JSON；然后四个命令各自先对真实只读 File 做非空写探针、确认失败，再将同一句柄交给实际子进程，要求精确 `Some(1)`。逐项检查原 sink 和原源字节，backup/restore 的新目标还需逐字节相同并由随后正常 stdout 的 verify-active 验证；保留最终已有目标拒绝。顶层测试仍七项，前六项和两笔真实付款 fixture 不变；没有增加证明、放宽预算或将扩展断言当成更多独立测试。

6. **C3 已得部分结果不替代 C4。** 草稿对 C3 七份日志、六成功一失败、412261 B 及 21 个实例化 jobs 的时间快照保留不同范围，不声称 C3 全部 23 个任务已完成。默认 cfg 排除的新 CLI 零测试没有计为 funded 七项通过。重复 push 的 cancelled 与必需 PR 结果分开，未推断取消原因。后续 C4 必须取得自己的原生日志，草稿没有据 C3 部分通过登记 C4 通过。

## 函数、链接、证据与状态范围

报告仍有 31 个带模块缩写的测试函数引用，全部存在于准确 C4 源码。C4 输出 helper 和第七项的映射与上述真实调用一致。保留的 12 个核心库、4 项双平台加 2 Unix/1 Windows namespace、7 项 funded CLI 的源码预期未改变；Ubuntu 18 / Windows 17 仍明确为新增库的源码预期，未伪装成当前已验收的执行数。

当前证据目录共有 **52 份原件副本、1541678 B**，逐一与 scratch 对应原件完全相同；另有仅限本证据目录的 8 B `.gitattributes`，内容为 `* -text\n`，没有拿该规则文件冒充上游原件。三份 Markdown 共 **75 个相对链接**，按草稿覆盖准确仓库的最终路径规则检查均存在；这不表示尚未发布的 GitHub 页面已可访问。C3 新增失败日志、native 拒绝 Markdown/JSON 和两份 addenda 的大小/hash 均与报告相符。

28 项 proposed status patch 只在内存应用；add/replace 目标合法，base status hash 仍匹配 `3ab68713693a471fdb39bb9a6f464b2e14fc2aee310db7012ea0ae66f49265e1`。所有声明保留的旧 `pool_recovery_scope`、`payment_resource_*`、`active_ledger_*`、历史验收标识和其他 P1/P3–P8 状态保持，P2 仍以 in_progress 开头。incremental_backup、snapshot_state_import、production_storage_ready、audited、node_ledger_compaction 和 existing_user_data_migrated 均保持 false。没有把旧 32+1 观测改写为新归档资源测量。

Summary 仅 export 全量比较、交换历史 Corrupt 与坏签名 Authorization 的区别、fault 5/6 注入目录项改变以及 NO-FUNDS、公开账本与完整验证者恢复的边界保持原来准确表述。README、DELIVERY_PLAN 相对上次草稿原字节不变，没有提前声称 P2 完成。

## 待最终更新与审核

本快照报告仍有 5 项 PENDING：阶段接受、runtime 合入、C4 独立审核、最终文档审核/合入和完整原生 CI。现已另行读取 `code-review-c4.md`（16663 B，SHA-256 `a4bab8b1ae3fe05c185a82b4256bda8420ba5cbcf37c5c7304cbfceb708512e2`），它给出准确 C4 的 PASS_CODE_REVIEW，限定代码与测试设计，并明确原生验收待完成；尚未纳入本草稿是后续更新待办。草稿“C4 只完成冻结/独审待执行”的临时文字应在最终纳入真实原件时更新，不能作为最终报告的当前状态。此次不替作者补写，也不据主审核或即将产生的另一份复审推定完整验收。

最终准确文档提交还须逐项核对 C4 全部必需 23 份原生日志及 steps/skip、两路准确复审、独立 native 验收、runtime 实际 merge、完整原件清单和文档 head/tree，并确认运行源码、测试、依赖、工作流相对被验收 runtime 逐字节不变。不得以本 PRELIMINARY 代替最终非作者 PASS。

本次只执行 Git/diff、源码及既有证据读取、SHA-256、相对链接、函数引用和内存补丁检查，没有执行 Rust/Go 编译、测试、fmt、Clippy、原生 Windows 操作，没有触发或轮询 C4 CI，也没有修改候选文件或审批合入。**当前预检范围事实阻断 0；最终阶段和文档验收仍待独立闭环。**
