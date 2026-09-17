Zevune P2 活动归档：C7 全阶段独立对抗审核原文

结论：**PASS_STATIC，适用于下列准确 C7 源码树的完整阶段代码与测试设计。** 未发现本次范围内尚未关闭的源码阻断项。C7 用单一测试 fixture 模块及受 cfg(test) 限定的重导出，修复 C6 已被原生 Clippy 证实的重复模块问题；真实测试函数没有删改。固定公共验证密钥复用仍与授权成功缓存分离，归档仍执行三次完整真实重放，原段交换和 stdout 错误传播修复保持成立。**本报告不认证 C7 原生矩阵，也不表示阶段已接受。** C6 的部分测试成功与 Clippy 失败、C5 的格式失败以及更早候选结果均不得转作 C7 通过。

审核任务 `/root/p2_archive_adversarial_review`，2026-09-17 UTC。本人为未编写候选的独立审核者，没有修改源码、测试、设计、格式、工作流或分支；没有借另一审核者结论替代代码判断。只读检查准确 git 对象、完整阶段差异、相关调用方、全部新增测试及已知失败证据，执行 Python 字节比较和独立摘要向量。新建的审核原件及检查记录位于仓库外证据目录。

| 身份 | 精确值 |
|---|---|
| 仓库 / PR | [youq616/Zevune PR #13](https://github.com/youq616/Zevune/pull/13) |
| 阶段 base | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| C7 source | `de474720431daf33afd4a7ebc32de2d230344a5a` |
| C7 tree | `e4dd17dfb1efd0e3ca20441168b62b72b6fc3108` |
| 第一父提交 C6 | `88146d54f2eaac39958ceaaea9e13f71832d536e` |
| 归档 / CLI 先前已审 C4 | `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736` |
| 冻结活动设计 bytes / SHA-256 | `13188` / `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee` |
| 冻结固定 key 设计 bytes / SHA-256 | `4682` / `363e6a9576b12e5f2eb39487b00486cef92e9a49bc5728d47bf266b23a14f5a5` |

本人在开始、机械检查结束及正式交付前核对 source/tree/parent 与工作区状态；源码结论绑定准确 git tree，不认证 PR 的 synthetic merge checkout。配套 JSON 保存当前 33 个审查输入的长度、SHA-256、测试名称、16 个阶段变更文件、实际机械检查和旧原件索引。两个冻结设计保持原字节。

**范围与候选差异。** base..C7 为 16 文件、2949 行新增/38 行删除。覆盖活动 pin 和 archive、活动物理文件/共享 replay、CLI、真实增长/恢复、core/namespace/CLI 测试、wire 固定 key 和新隔离测试、原授权缓存测试注释及两份设计/缓存说明。另核对 State 执行、legacy replay、worker、wallet/prover/vault 调用方、精确字节 cache、真实 proof helpers、namespace/segments、依赖与执行入口。

C6..C7 仅三文件 +5/-5：`pool_tests.rs:8` 的 fixtures 为 pub(crate)，`pool.rs:785` 新增 cfg(test) 下同级重导出，`wire/fixed_key_tests.rs:3` 使用该模块且去掉第二个 path/mod。当前测试文件 3911 字节，SHA-256 `84f91eeef6b2c9b694cc2109bbd55896b3d64e75f7e7b7ba41c2d73738ea3eeb`；从 `#[test]` 起的完整函数与 C6 原字节相同。fixture 实现文件与 C4 原字节相同。生产 wire 与 C5/C6 相同，原 cache 实现未变。C4 最初十个阶段文件中九个与 C7 完全相同；pool.rs 只有新增测试别名，移除该精确三行块后即与 C4 相同。这些字节比较用于重新确认先前逐行审查覆盖，不把先前候选运行结果移交当前候选。

**AR-C6-03（P2）源码修复关闭，原生关闭尚待准确 C7。** 原 C6 同一个 helpers 文件分别经 pool_tests.rs 与 wire/fixed_key_tests.rs 的 path/mod 进入 library test，Clippy duplicate_mod 被 -D warnings 提升为错误。现在 src 树仅剩 pool_tests.rs 的那一处文件模块声明，wire 测试导入已有定义，没有 lint allow，没有删除测试或新增生产测试入口。

pool 的私有 tests 模块不阻止它向父模块提供足够可见的子项；fixtures 的 pub(crate) 与重导出的 pub(crate) 相匹配，wire 在同一 crate 内使用该别名。原 pub(super) 若不提升会不足，本次已配套更改。pool 的 tests、重导出和 wire 的固定 key 测试都受 cfg(test) 限定，正常库/可执行文件不包含此入口。消费端实际使用该 import；原 pool 测试的显式 fixtures 定义不因父模块 glob import 成为第二份文件加载。没有观察到新的可见性、未使用 import 或重复定义源码问题；是否通过锁定工具链的全部 lint 仍须实际编译。[Rust 可见性与重导出规则](https://doc.rust-lang.org/reference/visibility-and-privacy.html)

**共享固定公共 key，不共享授权缓存。** `wire.rs:260` 私有函数内部仅一个 OnceLock<VerifyingKey>，初始化闭包唯一调用 `VerifyingKey::build(CIRCUIT)`。lib.rs 的 CIRCUIT 仍是 FixedPostNu6_2，依赖仍锁定 Orchard 0.15.5，工具链仍为 Rust 1.98.1。没有外部 key/版本输入、文件/网络加载、备用电路、可变 static、unsafe 或手写 Send/Sync。

AuthorizationVerifier 持只读静态 key 引用，同时按值拥有自己的 VerifiedCache；new/Default 每次新建空缓存。本人准确比较 verify 方法：除匹配字段类型而把 `.verify_proof(&self.key)` 调整为 `.verify_proof(self.key)` 外，与 C4 方法原字节一致。仍先完整规范 decode，后检查该实例完整字节与 digest；未命中时验证全部花费签名、binding signature、真正 proof，全部成功后才 remember。cache 的容量 64、FIFO、完整字节匹配、失败不插入、poison 返回错误均未变。没有成功标记、外来 cache 或状态导入 API。

公共 key 在进程内存活到退出，不随最后 verifier drop 释放；新进程独立构建。OnceLock 初始化 panic 向外传播，未完成 cell 仍可重试相同固定构建，不产生备用成功，也不能描述成永久 poison。初始化没有回调 getter/新 verifier；现有 helper 的依赖方向不会进入初始化闭包。未来电路版本须重新绑定并审查，不允许同一 cell 接受运行时切换。官方 Orchard API 当次读取页标 0.15.5 并列出 Send/Sync；固定版本 URL未成功读取，引用范围如实限定为该页面。实际锁定类型能否编译、多线程行为仍须当前 native 验证。[Orchard VerifyingKey API](https://docs.rs/orchard/latest/orchard/circuit/struct.VerifyingKey.html)、[Rust OnceLock](https://doc.rust-lang.org/std/sync/struct.OnceLock.html)、[static 生命周期](https://doc.rust-lang.org/reference/items/static-items.html)

**真实隔离测试有实质断言。** 新测试默认进入库测试，不需要 funded 特性，没有 ignore 或平台跳过。沿用真正 Builder/ProvingKey/create_proof/apply_signatures，生成一笔 100000 测试价值输入、60000 与 39000 输出、1000 fee 的有效交易；没有合成成功 cache。A 和提前创建的 B 先确认同一 key 指针、明确固定版本和各自空 cache。A 真正 verify 后仅 A 命中，B 仍空；四线程各 new verifier，在 Barrier 后检查同一 key/版本与本实例空缓存，再分别真正 verify 并各自记入。线程结束后 B 仍空，经 B 自己的 verify 才记入；最后新建实例仍空。

proof 首字节和 binding signature 尾字节两个变更先证明 decode 成功，再要求准确 WireError::Authorization，变更字节在失败前后均未缓存，有效字节仍作正对照。这里不是以结构错误、旧 layout pin 或假 remember 代替密码学拒绝。Barrier 在可失败断言之前；key 已初始化，scope 自动等待所有线程，未处理子线程 panic 传播到主测试。该测试涵盖已初始化 key 的并发使用及冷授权缓存，**不声称首次空 OnceLock 竞争**，没有 panic/OOM 注入或耗时阈值。[Rust thread::scope](https://doc.rust-lang.org/std/thread/fn.scope.html)

原 authorization_cache 集成文件只改两行说明，机械比较确认所有非注释非空行与 C4 相同。旧 genuine fixture、32 次复用、mutation/restart 及 state guards 没有删减。生产验证器之外的 lib::Verifier 与 ProvingKey 生命周期未改。worker 会话、WalletProver、vault outbox、PoolStore 创建及每次 replay 仍各自持有/构建需要的实例。State 仍在每次执行重新检查可信域、期限、已提交 anchor、容量、double spend、重复输出及费用；授权缓存从不替代这些状态规则。失败候选持有可丢弃状态，不发布部分更新。

**完整归档与恢复安全路径。** 已复核共享 key 对原所有调用路径的影响，以下结论适用于 C7：

1. ZVARCP01 只接受准确 128 字节和独立 pin；三个摘要非零，1000000 高度、1 GiB 逻辑容量、2048 段、76 起始头长及 32 对齐、零高度/零段等关系有界，checked 运算覆盖总长减法与记录字节上下界。旧 120 字节 checkpoint、ZVPSEG01 及 legacy 含义不变，不支持 profile 的请求先拒且不 poison。
2. 先在真实 genesis 物理文件内解析 03 头，按捕获长度核对真实 EOF；不能从 journal 借字节补伪造头。逻辑解析与物理头一致，State::from_storage_policy 生成的 genesis 与独立调用方期望绑定。shared replay 每次 new AuthorizationVerifier，逐条 Replay::next_block、真实授权/状态执行、validate_frame、finish/EOF 与 namespace 全部成功才返回未发布状态。
3. 活动导出比对全部 committed Summary、genesis、容量和前后原字节/namespace。PreparedBlock 不被消费或认证，真实历史错误使 store 不可用。archive verify 比对全部 pin 字段、真实 replay tip，并以 bytes/namespace 前后包围。没有以 app hash/layout hash 单独替代完整授权。
4. copy_new 在创建前核对保留源身份、绝对目标、canonical 父路径，拒绝同路径、已有目标、源内和父别名目标，然后完整 verify 源。目标非递归新建，文件 create_new，Unix 0700/0600。不会覆盖、truncate、删除、自动修补或重试；错误源在创建前拒绝，创建后失败可能保留部分或完整新目标。
5. 目标 genesis 在写入前持独占锁，64 KiB 缓冲复制每个准确原文件；各文件 sync_all，Unix 同步目标目录及父目录。目标第一次真实 verify 直接使用原创建且持续持锁句柄，没有解锁/重开。然后末次源真实 verify、目标末次 bytes/namespace，全部成功才返回 pin。**源、目标、末次源三次完整 genuine replay 均保留，每次独立空 cache。** 共享 key 不保存交易成功结论或 State。
6. 只读归档源持 genesis shared lock，正常 writer exclusive，克隆不会重复加锁。源/目标目录及文件持续保留；Unix dev/inode/nlink 拒绝替换/软链接/多硬链接，Windows 无 DELETE 分享及 reparse 检查保持。多读者/跨进程测试有 exact 测试名及确实运行一项的控制；Windows rename/delete 拒绝使用可写原文件，并在全部 drop 后验证操作成功，避免只读权限伪装锁。
7. 摘要与复制显式偏移，物理头 clone rewind，reader 保留自身逻辑位置。短读与 Interrupted 正确处理，捕获长度后仍检查真实 EOF；reader I/O 失败保持失败关闭。跨段拆帧、空段、非规范提前轮换、尾字节、缺号/未知项均在状态发布前拒绝。源/目标长期身份绑定需要可信父目录、OS 和文件系统；不声称抵抗任意瞬时替换后复原。
8. 私有故障 1/2 留部分 genesis/段，3 只模拟最后文件写完未同步返回，4 模拟全部同步后丢回复；完整副本允许随后显式验证。5/6 故意增加末次源/目标目录项以验证最终检查，保持的是原文件字节，不能称目录未变。没有真实断电、磁盘满或 Windows 目录耐久性保证。

独立布局向量在本次 C7 机械检查中实际运行：`ZVOPOL03`、SHA-256(network)、32 个 7 字节及 BE 零 commitment count 组成 76 字节头，摘要 `07782393f4021cabba3a8a09f0d2747e6ae4404457475c6e9df85100f734bc1e`；加 `ZVARLY01`、长度和零段数构成 92 字节布局，摘要 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`。该检查验证外部编码，不是 proof 或 CI 成功。

**AR-C1-01（P2）覆盖修复仍在。** active_flow_tests 的真实 10001 高度双段原字节交换：先由原 pin 明确 Corrupt；源与变更目录字节不变。重新构造的 pin 经过 codec 且生产 layout 实际匹配，解码第一条完整原 record，明确其 height 和 base_hash 与 genesis 初态关系，然后新 pin 仍 Corrupt。第二次失败后两个目录字节继续不变；正常源后续 archive/restore、10002 提交作正对照。这证明测试拒绝不只依赖旧摘要不匹配。真实付款触发第二段后的第一次归档/恢复、收款方第二跳及钱包状态原断言全部保留。源码缺口已关闭；当前 native 执行由另行准确矩阵证明。

**AR-C3-02（P2）产品修复仍在。** 四个 active CLI 命令仍持 StdoutLock，经安全 owned duplicate 转 File write_all/flush；Unix 直接传播 EBADF 等 OS 错误，避免缓冲 stdout 将其转换为成功，Windows 明确拒绝 NULL handle。原 stdout 不被关闭，错误统一非零退出，已完成目标不被删除或自动重试。第七 CLI 测试保持 readonly File 实际写失败探针、四模式精确 exit 1、sink/source 原字节、writable File 精确 JSON 正对照，以及 backup/restore 完整目标的后验 verify。File.flush 不等于 fsync 或下游收到回执；本人未实测交互 Windows 控制台。[Rust 标准 I/O 实现](https://doc.rust-lang.org/src/std/io/stdio.rs.html)、[Rust File 实现](https://doc.rust-lang.org/src/std/fs.rs.html)

active CLI 的独立 03 manifest、可信高度/AppHash、准确小写 hex/绝对路径、NO-FUNDS 标志、未知/重复参数拒绝保持。source 与 archive 不自动选择最新 pin；输出明确 replay_verified 而 finality/validator_ready/real_funds_allowed 均 false。旧命令/JSON 与 Go CopyStorageAtCheckpoint 对 active 的拒绝保持。本阶段不包含钱包、共识数据库/WAL 或验证者签名状态，不能把完整账本副本当作完整验证者恢复。

**测试范围和历史证据。** 源码保留 core 12、namespace 7（Unix/Windows cfg 不同）、active_flow 4、funded CLI 7，新增固定 key 单元测试 1；这些是函数名称计数，绝非运行通过计数。全部 12 个 workflows、Cargo.toml/lock、toolchain 和 funded runner 与 C4 原字节相同，没有提高超时、删 cohort、减证明、改并行或取消同步/重放来换通过。C7 需要自己的全部 23 逻辑原生 gates 与项目既有 Rust 默认/funded、Go test/vet/race/fuzz、增长、资源及四节点证据，本审核不代为签发。

C6 原生 job 105167396538 日志为 68156 字节，SHA-256 `a0368cb426a63c9ed4763cd88429f5744b0d0404b30c50e419f0e86903b40e40`，checkout `4bfe426af700303719bbc58344408e070af90467` 明确为 C6 合入阶段 base。真实 key test 和 140 个库测试在其中通过，但随后 duplicate_mod 导致 Clippy exit 101，C6 未接受。原 C6 Markdown 的静态判断与尚未完成的 JSON/收尾身份描述已在独立 `adversarial-review-c6-addendum.md` 更正；从未生成 C6 JSON，不补造。C5 格式失败、C3 stdout 运行反例及 C1 缺失段交换原件均保留。当前结论建立在 C7 源码修复审查之上，没有将旧失败写成成功。

**实际检查与未测限制。** 本地 rustc/cargo/go 均不存在；本人未编译、跑 Rust/Go 测试、cargo fmt、Clippy 或 C7 CI，未认证 Windows 原生通过。实际运行的是 git identity/status/diff、SHA-256/字节比较、源码挂载与测试名枚举及独立 Python 编码向量。C6..C7 git diff --check 为 0；base..C7 同项为 2，只指出冻结活动设计第 185 行结尾空白行。原设计字节保留，该非运行提示不能写成全部检查通过。PROOF_CONTRACT.md 和 ARCHITECTURE.zh-CN.md 仍实际缺失，没有虚称读过。

未测边界还包括冷 OnceLock 初始化竞争、初始化 panic/OOM、全容量/全句柄预算、真实断电/磁盘满、Windows 目录持久化和任意恶意 OS/文件系统。源与目标各可持 2048 段及 genesis/目录，reader 再克隆整套句柄；key 常驻也有进程内存成本，本人没有给出吞吐、节省时间或峰值资源测量。独立 pin 不证明来源真实性、最新高度或 finality。NO-FUNDS 与 P2 开发中边界继续成立；本编码代理审核不等于外部机构安全审计。后续源码/测试改变须重新审核准确提交，本 PASS_STATIC 不适用于未知后续树。
