# P2 活动归档与完整恢复：独立设计审核原文

审核任务：`/root/p2_archive_review`。审核时间：2026-09-17 08:03:18 UTC。
结论：**PASS — 仅通过下述准确文件的实现前设计审核。**

## 候选身份与独立性

- 仓库：`youq616/Zevune`。
- 已核实阶段基线：`6913d4ab2fda6956db37e0ceb49790a4518c2762`。
- 已核实基线 tree：`5e039b41e00f7a0a2e78937c796a40fbe68bfb0c`。
- 设计文件：`docs/ACTIVE_ARCHIVE_V1.zh-CN.md`。
- 文件长度：`13188` 字节。
- SHA-256：`de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee`。
- 本次候选为基线上的未提交设计文件，尚无可审核的实现 head/tree；不能把基线 tree 当作新设计或实现 tree。正式代码审核必须另外固定准确提交。
- 本任务没有编写或修改该设计、任何实现、测试或工作流。先前只读预检提供的是现有架构约束；本次独立读取了完整准确设计，并与实际调用方、存储、重放和现有恢复实现核对。

## 读取范围

完整阅读 `AGENTS.md`、`docs/STAGE_REVIEW.zh-CN.md` 和本次设计。相关现状核对包括：

- `docs/ACTIVE_LEDGER_V1.zh-CN.md`、`docs/POOL_RECOVERY.zh-CN.md`、`docs/SEGMENTED_BACKUP.zh-CN.md`、`docs/JOURNAL_COPY_RECOVERY.zh-CN.md`。
- `integration/orchard/src/pool.rs` 的 profile、State 初始化、普通打开、共用 replay、checkpoint 与状态可用性边界。
- `integration/orchard/src/pool/active.rs` 的目录清单、句柄与锁、创建/打开、物理帧验证、规范轮换、有界读取、真实 EOF 和失败关闭。
- `integration/orchard/src/pool/recovery.rs`、`pool/recovery/segments.rs` 及其 `namespace.rs` 的旧 pin/清单边界、原句柄验证、源内目标拒绝、前后字节与路径检查。
- `integration/orchard/src/pool/replay.rs` 的隔离 State 重建、真实授权、逐块结果比较、完整 EOF 和不可恢复的失败 reader。
- `integration/orchard/src/pool/testnet.rs` 的独立清单 pin、profile 与签名域、正常 open_pool 和钱包历史绑定。
- `integration/orchard/src/bin/zevune-pool-recovery.rs` 的旧命令、参数、输出和 NO-FUNDS 入口。
- 活动真实付款跨段/跨 10000/重开继续提交，以及真实句柄/双进程锁、替换与失败路径的现有测试调用。没有把旧测试内容当成本次候选的执行通过证明。

## 审核结论与理由

本次未发现需要在实现前修改该准确设计的阻断问题。设计规定了可由现有真实调用路径实现、且保持原状态及兼容边界的恢复合同。

1. **独立 pin 与格式隔离成立。** 新 128 字节 `ZVARCP01` 独立于旧 120 字节 `ZVPRCP01`。它绑定活动 genesis 头、准确高度/AppHash、逻辑字节、头长、段数及布局摘要。`ZVARLY01` 的固定字段宽度、顺序、长度和序号使布局编码无歧义；逐段原字节进入摘要，物理分段不同不能仅凭相同逻辑串流得到同一编码。没有把旧 pin 或 `ZVPSEG01` 的容量/语义扩宽，也没有让归档自带材料决定可信身份。

2. **结构检查与真实状态检查没有混淆。** pin 的严格长度、非零摘要、checked 运算、高度/段数关系、头长步长以及字节下界/上界都在不可信分配和文件读取之前执行。它们只证明结构可能成立；真实 03 头、曲线点、签名域、记录、授权和最终状态仍由完整验证负责。旧合法 pin 的新鲜度限制明确。

3. **物理 genesis 边界和逐帧活动约束保留。** 设计先在保留的 genesis 文件内部解析头并要求准确物理长度及真实 EOF，避免从 journal 续读伪造头。随后共用真实 State/Replay，并对每条完整记录执行活动 `validate_frame`。跨段拆帧、提前轮换、空段和物理尾字节不能被一般串流拼接隐藏。状态在完整重放、pin 匹配及末次检查完成前不得发布。

4. **每次验证都重新执行真实授权。** 普通活动打开、归档、复制目标的内部重放路径使用新 AuthorizationVerifier；导出 pin 也要求重放后的整个 Summary 与当前 committed Summary 和容量一致。设计没有允许以 layout hash、一次缓存命中或当前 AppHash 代替重新检查历史。错误签名样本必须重算普通完整性摘要后仍到达 Authorization 拒绝层，能验证这一约束。

5. **源只读与目标持锁验证边界可实现。** 源使用只读文件句柄和 genesis 共享锁，普通 store 保持独占锁；多个读者与合作 writer 的关系明确。目标通过原 create-new 句柄持有独占根锁、写入、同步及完整重放，没有为 Windows 二次打开而释放锁，也不对克隆重复加锁。私有归档对象不向外返回写者能力。

6. **路径绑定与只创建目标的顺序完整。** 创建之前先核对源路径/保留句柄，解析源和可信目标父目录，拒绝源内目标、父别名及已有目标，再完整验证源。复制之后核对目标原句柄、完整字节和 namespace；成功前再完整验证源并复核目标。Unix inode/device 和 Windows 不共享 DELETE 的既有边界保留，未把长度/时间当作 Windows 唯一身份。

7. **失败语义没有过度承诺。** 创建后失败可以留下部分或完整新目录；不自动清除、截断、修复或重试，完整副本可按原 pin 另行验证。清单不再存在，也没有引入另一种可误认成功的提交标记。文件同步、Unix 目录同步、Windows 未实现的目录持久化和真实断电限制明确区分。NO-FUNDS、非完整验证者恢复及不得重复启用同一验证者身份的边界保留。

8. **句柄、资源与 CLI 合同明确。** 设计承认每个目录最多 2048 段加头和目录，reader 还克隆句柄，并要求资源不足失败关闭。串行读取与明确定位解决共享游标的使用约束。新命令显式区分活动 profile，保留旧输出，只增加活动成功字段；错误参数、相对路径、非规范 pin、高度及 stdout 失败均要求失败。没有自动猜 profile、自动信任最新 pin 或增加节点启用能力。

## 实现后必须核对的既定要求

以下是该设计已有合同在代码和证据中的核对点，不是本次新增设计范围，也不是已经完成的测试：

- 私有目标构造必须在复制 genesis 字节之前获得其独占根锁；目标验证确实只使用原创建句柄，克隆仅保留锁和读取能力。
- 共享内部重放不能使归档得到可写 PoolStore，也不能削弱原普通活动打开对可信创世头/域的精确比较。
- 每次摘要、复制及重放的实际游标定位、每文件 EOF、前后 namespace 和最终目标字节检查必须落实到所有成功返回路径。
- layout hash 至少有一组独立生成、固定输入的准确向量；不能仅由同一被测编码函数生成期待值。
- Windows 原生测试必须实际覆盖共享读者、writer 拒绝、保留句柄阻止重命名以及目标原句柄重放。Linux 成功不能替代它们。
- 恢复后的真实收款再花费、重复付款拒绝、真实签名损坏并重算所有普通摘要、源内别名目标拒绝、部分写入与丢失确认等要求需保留实际拒绝层与源/目标字节证据。
- 后续正式代码审核、准确候选的完整相关原生 CI 和阶段合入条件仍待执行。设计文件变化必须重新审核受影响合同。

## 官方合同核对

本任务阅读了当日 Rust 1.98.1 官方 File、Windows OpenOptionsExt 和 Microsoft 文件范围锁说明。`File::try_clone` 共享底层对象和游标；对已经持锁的句柄或克隆重复请求锁具有未指定的平台相关行为。文件锁对普通读写的影响也依赖平台，不能把锁表述成恶意主机防护。仅创建、同步和名称共享约束的设计表述与这些合同一致。

- [Rust std::fs::File](https://doc.rust-lang.org/std/fs/struct.File.html)
- [Rust Windows OpenOptionsExt](https://doc.rust-lang.org/std/os/windows/fs/trait.OpenOptionsExt.html)
- [Microsoft：Locking and Unlocking Byte Ranges in Files](https://learn.microsoft.com/en-us/windows/win32/fileio/locking-and-unlocking-byte-ranges-in-files)

## 实际执行与范围限制

本次执行了只读源码/文档检查、基线 commit/tree 核对和设计 SHA-256/长度复核；没有安装工具链、运行编译、执行测试或重跑旧 CI。没有实现候选可供代码验收，因此本结论不能表示后续代码正确、原生测试成功、已合入 main、P2 全部完成、生产可用或外部安全审计通过。

最终结论仍为：**PASS，允许按该准确设计开始实现；设计范围内未发现未关闭的阻断问题。**
