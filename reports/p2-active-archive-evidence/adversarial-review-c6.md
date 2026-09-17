Zevune P2 活动账本归档：C6 完整阶段独立对抗复审原文

结论：**PASS_STATIC（准确 C6 的完整代码与测试设计审核）**。本次覆盖 base..C6 全部 15 文件及相关调用方，未发现已知未关闭的源码阻断项。固定公共验证密钥复用符合已审核设计，每个新验证器仍拥有独立空授权缓存，归档三次完整真实重放不变；AR-C1-01 段交换覆盖和 AR-C3-02 stdout 错误传播修复保持成立。C5 已知原生格式差异在 C6 准确落实，但本人未执行或认证 C6 原生 CI。阶段接受仍需准确 C6 的完整原生门槛，不能继承 C3/C4/C5 的运行结果。

审核任务 `/root/p2_archive_adversarial_review`，2026-09-17 UTC。本人没有编写或修改候选源码、测试、设计、格式或工作流，没有以另一审核者的结论替代判断。本次仅只读检查准确 git 对象、调用方、测试、官方合同和历史原生日志，并执行 Python 摘要/字节比较；仅新建本审核及 JSON。

| 身份 | 精确值 |
|---|---|
| 仓库 / PR | [youq616/Zevune PR #13](https://github.com/youq616/Zevune/pull/13) |
| 阶段 base | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| C6 source | `88146d54f2eaac39958ceaaea9e13f71832d536e` |
| C6 tree | `cbddd8e982eb9013d10010354e477b264e33841b` |
| 第一父提交 C5 | `99ef9e8217182c9a6f4f1e9349613c1917ddec50` |
| 原归档与 CLI 已审 C4 | `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736` |
| 活动归档冻结设计 SHA-256 | `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee` |
| 固定公共 key 设计 SHA-256 | `363e6a9576b12e5f2eb39487b00486cef92e9a49bc5728d47bf266b23a14f5a5` |

上述 source/tree/parent 来自本人 git 核对，审核起止工作区干净。本报告不认证 C6 PR synthetic checkout；源码结论绑定上表 source 的准确树。两个设计分别为 13188、4682 字节，均保持冻结原字节。

**候选差异与历史保留。** base..C6 共 15 文件、2948 行新增/37 行删除。C4..C5 仅五文件、175 行新增/9 行删除：固定 key 设计、授权缓存说明、wire 实现、新真实隔离测试及旧测试注释。C5..C6 仅一个格式 hunk、4 行新增/1 行删除；新测试为 92 行、3954 字节，SHA-256 `f2b66e8aa4caf4f95fdb7cd202087c9c627b113861a0c088e6971b7e9a8e7592`。去除所有空白后与 C5 完全相同，没有删断言或改变表达式。

本人读取的 C5 原生 job `105166096614` 日志为 20672 字节，SHA-256 `994c43ca2a98a46957c99dfe1dd755de2762fcd82a6acae006544894b5d64042`；实际 checkout `44d9b13d1a1eed74158899717304aa42c1b5e30d`，说明为 C5 合入上述 base。格式 gate 因新测试第 32 行附近一个 assert_eq 排版差异退出 1。C6 与该唯一诊断逐字对应；这说明修订落实，不能代替 C6 cargo fmt 运行成功。

C5 没有得到本人的正式代码批准，保留的 `adversarial-review-c5-work-record.md` 为 REVIEW INTERRUPTED / C5 未接受，2305 字节，SHA-256 `a6d6c9a9ecb22f9f28cf9abf958a5e8bf0827a99c223105baaa7251de3d243fa`。C4 静态 PASS 不等于已接受；C3 初始静态结论被 stdout 运行反例纠正为 REQUEST_CHANGES；C1 初始请求修改及全部补充原件也保持原样。配套 JSON 保存旧原件与已读历史失败日志的精确长度/摘要，不倒写历史。

**固定 key 实现符合设计。** `wire.rs:260` 的私有 fixed_verifying_key 内只有一个非可变 static OnceLock；唯一初始化闭包为 `VerifyingKey::build(CIRCUIT)`。CIRCUIT 仍是 `FixedPostNu6_2`，Orchard 仍精确锁定 0.15.5，Rust 仍锁定 1.98.1。没有外部 key、版本输入、读取文件、网络、备用 verifier、unsafe 或手工 Send/Sync。AuthorizationVerifier 的 key 变为静态只读引用，verified 仍是实例按值拥有的 VerifiedCache；每次 new 和 Default 都会新建该空缓存。

已对 verify 方法做准确文本比较：除把 `.verify_proof(&self.key)` 改为 `.verify_proof(self.key)` 以匹配字段类型外，方法内容完全相同。仍完整 decode、比较 digest 和完整字节、逐一验花费签名、验绑定签名、真实验 proof、最后才 remember。VerifiedCache 本身与 C4 逐字节相同，容量/FIFO、失败不入缓存和锁损坏返回错误不变。公开 API 没有增加注入缓存或标记成功的入口。

官方 Orchard API 当次读取页面明确标 0.15.5，列出 VerifyingKey Send+Sync；OnceLock 的共享要求由 Rust 类型系统执行。成功初始化后只有不可变公共 key 常驻，最后一个 verifier drop 不释放它；各实例缓存仍单独拥有。初始化 panic 传播并保持未初始化，后续可重试同一固定构建，不能声称失败后永久 poison。初始化闭包没有回调自身或新 verifier，符合禁止重入的设计。准确版本依赖编译仍由 C6 原生门槛确认；这里没有执行 panic、OOM 或冷初始化竞争测试。[Orchard VerifyingKey API](https://docs.rs/orchard/latest/orchard/circuit/struct.VerifyingKey.html)、[Rust OnceLock](https://doc.rust-lang.org/std/sync/struct.OnceLock.html)、[Rust 静态对象生命周期](https://doc.rust-lang.org/reference/items/static-items.html)

**新测试检查真实授权与实例隔离。** 私有 `wire/fixed_key_tests.rs` 确实由 wire 的 cfg(test) 子模块挂载，复用的 fixtures 路径指向现存 tests/support/fixtures.rs；crate 的测试自引用 alias 已存在。该测试不依赖 local-funding-lab 特性，也没有 ignored 或平台条件，进入正常库测试和 funded 全库目标。

- 只生成一份真实 Orchard proof：100000 测试价值 note 支出，输出 60000 和 39000，fee 1000，使用现有真正 Builder/ProvingKey/create_proof/apply_signatures，无伪接受器。
- A 和提前创建的 B 都先检查缓存为空、key 指针相同，A 的版本必须是明确 FixedPostNu6_2；A 真正 verify 成功后只有 A 的缓存为真，B 仍为空。
- 四线程各新建 verifier，Barrier 后核对共享 key/版本、自己的缓存未命中，然后分别真实 verify，自己的缓存才出现成功条目。提前 B 在全部线程结束后仍为空，再经它自己的真实 verify 入缓存；另一个最后新建实例仍为空。
- proof 首字节和 binding signature 末字节分别翻转，先明确 decode 成功，线程中对每份变更要求准确 WireError::Authorization，前后均确认没有缓存条目，并再以有效原字节作正对照。不是借旧 hash、结构解码失败或直接 remember 来证明隔离。

Barrier 位于线程内可失败断言之前；key 已在主线程初始化，线程只借用有效 fixture。thread::scope 在退出前自动 join，未处理的子线程 panic 会传播，不能出现后台断言失败却把主测试记为成功。该测试明确验证已初始化 key 的并发使用及冷授权缓存，**不宣称覆盖空 OnceLock 的首次初始化竞争**，也没有机器时间阈值。[Rust scoped threads 合同](https://doc.rust-lang.org/std/thread/fn.scope.html)

原 authorization_cache 集成测试只改两行注释；本人比较后确认所有非注释、非空白行完全相同。原 genuine proof fixture、32 次复用及所有 mutation/restart 断言未删。新设计和 AUTHORIZATION_CACHE 说明准确区分共享固定公共材料、独立缓存与未来版本重新绑定，未宣称只重建 verifier 就能替换静态 key。

**调用方完整性。** PoolStore 创建、legacy/active replay、worker 会话、WalletProver、vault outbox 验证仍各自调用新 verifier。State 在每次执行先核对可信签名域、过期、已提交 anchor、输出容量、double spend 和重复输出；授权成功之后仍有费用/状态检查。缓存命中不变成账本花费许可，拒绝候选仍不能发布部分状态。lib.rs::Verifier 和证明生成 ProvingKey 的生命周期没有改变。

活动导出和每次 archive verify 仍通过 replay_active_handles 构造新 verifier 及隔离 State；copy_new 仍源全验、原目标句柄全验、末次源全验，共三次完整真实 replay，随后检查目标最终 bytes/namespace。新全局对象只有 key，没有任何历史 State、交易成功缓存或 pin。因此旧一次归档成功不能让新归档跳过授权；重新计算 layout pin 的真实坏签名仍进入 Authorization 拒绝路径。

**完整阶段归档不变量复核。** C4 原阶段的 10 个设计/存储/重放/归档/CLI/测试文件与 C6 逐字节相同，且本人重新核对共享 verifier 变化对其调用路径的影响。以下结论适用于准确 C6：

1. **有界独立 pin。** 新 ZVARCP01 准确 128 字节，私有字段、非零摘要、1000000 高度、1 GiB 逻辑字节、2048 段、03 头长/32 对齐及零高度关系完整，checked 记录字节上下界防回绕。旧 120 字节 pin 和 ZVPSEG01 不被重解释；不支持 legacy 的导出先拒且不 poison。

2. **物理头、独立 genesis、完整 replay。** genesis 单文件按实际捕获长度解析并要求真实 EOF，不能借段字节伪造头。逻辑头与物理头一致，真实 State 的 genesis 与调用方独立预期绑定。每条真实记录完整授权/执行后还检查帧边界与规范轮换，finish/EOF/namespace 前不对外发布可写状态。归档不暴露 State/PoolStore。

3. **已提交状态和重复核验。** 导出比较全部 committed Summary、genesis、容量及前后 bytes/namespace；PreparedBlock 不被消费或认证。真实历史错误使活动 store 不可用。archive 每次核对全部 pin 字段、真实重放 tip 和末次 bytes/namespace。独立 Python 再次重算 76 字节头摘要 `07782393f4021cabba3a8a09f0d2747e6ae4404457475c6e9df85100f734bc1e` 与 92 字节布局摘要 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`；这仅验证编码。

4. **只读源、共享读锁与名称身份。** 源 readonly + genesis shared lock，普通 writer exclusive；克隆不重复加锁。Unix dev/inode/nlink、链接拒绝和 Windows 无 DELETE 分享/reparse 保护保持。跨进程 exact 测试检查确有 `1 passed`，多个读者和最后 drop 后有正对照；Windows writable 文件 rename/delete 在读者保留时拒绝，全部 drop 后成功，不靠只读权限假装锁保护。平台行为仍须 C6 实际 runner。[Rust Windows OpenOptionsExt](https://doc.rust-lang.org/std/os/windows/fs/trait.OpenOptionsExt.html)、[Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)

5. **创建前完整验证、源不可覆盖。** 先检查保留源绑定、绝对目标、canonical 父路径、源内及父别名/已有目标，再全验源。新目录非递归创建、每文件 create_new，Unix 0700/0600，没有覆盖、truncate、修补、自动删除或重试。非法源不能在创建前验证阶段留下目标；创建后错误可能留下部分或完整新目标。

6. **原目标句柄持续认证。** 写头前目标 genesis 独占锁，64 KiB 有界复制、每文件 sync_all、Unix 目录及父目录同步。第一次目标验证直接使用原创建/持锁句柄，没有 drop/unlock/reopen 窗口。源再全验和目标末次 bytes/namespace 成功后才返回 pin。

7. **偏移、真实 EOF 与故障边界。** 显式偏移、头 clone rewind 和 reader 私有逻辑位置避免 Windows 共享游标依赖。短读与 Interrupted 正确处理，捕获长度后仍查真实 EOF，失败 reader 不可续读认证。私有故障 1/2 留部分目标，3 仅证明过程可见全字节，4 模拟同步后丢确认；5/6 故意新增目录项触发末次检查，保留的是原文件字节，不声称目录未变。没有生产故障捷径或真实断电证明。

8. **真实增长/恢复与兼容。** 原真实付款触发第二段后的归档/恢复、恢复后第二跳至 10001、再次恢复后继续 10002 均保留；新 CLI 两笔真实非零付款及接收者扫描恢复历史再花费、重复花费/余额检查仍在。旧命令/JSON、旧 Go 活动 profile 拒绝、签名域、协议/存储容量和锁定依赖未变。checkpoint-active 仍经独立 03 manifest 和可信高度/AppHash，其他三命令经 readonly archive；所有路径及规范参数、NO-FUNDS 标志继续要求。

**历史阻断在当前源码的关闭依据。** AR-C1-01 的 10001 两段交换测试保留原段字节、原 pin Corrupt、重新编码且生产 layout 真正匹配的新 pin、明确首记录 base_hash 与 genesis 初态不符、新 pin 再 Corrupt，以及源/交换目录不变和正常恢复正对照。它没有新增另一组 proof 或改变段容量。此项源码覆盖关闭；本报告不将其 C6 native 执行记为通过。

AR-C3-02 的 CLI 修复与测试同 C4 原字节：四个 active 命令均持 StdoutLock，通过安全 owned 副本转 File 直写，绕过 stdio 的 EBADF 成功转换，Windows NULL 拒绝；复制/写错误回到非零 CLI 失败。原 stdout 不被关闭、已完成目标不被删或自动重试。第七 CLI 测试保留真实 readonly File 探针、四命令精确 exit 1、可写文件准确 JSON 正对照，以及 backup/restore 的完整目标 bytes 与后验独立 verify。File.flush 不是 fsync 或下游消费确认，交互 Windows 控制台未由本人实测。[Rust 标准 I/O 实现](https://doc.rust-lang.org/src/std/io/stdio.rs.html)、[Rust File 实现](https://doc.rust-lang.org/src/std/fs.rs.html)

**测试挂载和门槛未削弱。** 新 active core 12 个、namespace 源码 7 个（平台 cfg 不同）、funded CLI 7 个、原 active_flow 4 个全部保留；新增固定 key 真实单元测试 1 个。这里是源码名称计数，不是 native pass 数。全部 12 个 workflow 文件、Cargo.toml/lock、toolchain、funded runner 与 C4 原字节相同；本阶段不提高超时、调并行度、删旧 cohort、删真实 fixture 或取消同步/重放换取通过。准确 C6 完整原生矩阵由 native auditor 另行认证。

**验证限制。** 本地 rustc/cargo/go 仍缺失；本人没有执行编译、Rust/Go 测试、cargo fmt/Clippy、原生 Windows 或 C6 CI。已运行 C5..C6 的只读 git diff --check，退出 0；base..C6 的同项检查退出 2，仅报告冻结活动设计第 185 行结尾空白行，原字节保留。此空白提示不是 runtime 缺陷，也不能写成所有工具门槛通过。已有被引用但实际缺失的 PROOF_CONTRACT.md/ARCHITECTURE.zh-CN.md 未被虚称已读取。

仍须保持独立 pin 的来源/最新性/finality 限制，NO-FUNDS、P2 开发中和非验证者完整恢复边界；归档不含钱包、签名状态或共识数据库/WAL。可信父目录、OS 和文件系统仍是前提，未证明任意瞬时恶意替换、真实断电/磁盘满、Windows 目录持久化或全容量资源预算。源/目标各最多 2048 段句柄及 reader 克隆成本仍存在；固定公共 key 常驻成本与本次节约时间没有由本人测量，不能沿用旧 32+1 指标或宣称生产吞吐。本独立编码代理审查不等于外部机构安全审计；后续修改源码/测试须重新审核准确候选。
