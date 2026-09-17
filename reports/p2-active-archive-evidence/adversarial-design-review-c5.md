Zevune C5 固定公共验证密钥复用：独立设计审核原文

结论：**DESIGN PASS**。准确设计 `docs/FIXED_VERIFYING_KEY.zh-CN.md` 保持每次新验证器的独立空授权缓存，只将同一固定上游电路的不可变公共验证材料复用到进程寿命。该边界与现有活动归档的完整真实重放、独立 pin 和状态检查兼容；未发现需要阻断此方案进入实现的设计问题。本结论不批准尚未冻结的 C5 实现，不证明其原生 CI 或性能收益，也不改变 C4 尚未接受的状态。

审核任务 `/root/p2_archive_adversarial_review`，日期 2026-09-17 UTC。本人未编写本设计、未参与拟议实现，也未修改设计、源码、测试、工作流或既有审核原件。本轮只读核查现有代码、准确设计文本和官方资料，仅新建本审核及 JSON。

| 审核身份 | 精确值 |
|---|---|
| 仓库 / PR | [youq616/Zevune PR #13](https://github.com/youq616/Zevune/pull/13) |
| 阶段 base | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| 已冻结 C4 source | `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736` |
| C4 tree | `3c44977028b58ddd387f52946632af594208edfb` |
| 本次设计文件 | `docs/FIXED_VERIFYING_KEY.zh-CN.md` |
| 设计字节 / SHA-256 | `4682` / `363e6a9576b12e5f2eb39487b00486cef92e9a49bc5728d47bf266b23a14f5a5` |
| 活动归档冻结设计 SHA-256 | `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee` |
| 现有授权缓存文档 SHA-256 | `345b481c979cac0ed4b59602e4d20b1cabd4e993162c5efb74b8750b4b6da3bf` |

本轮读取时 HEAD/tree 仍为 C4，唯一未跟踪文件是新设计；尚无供本人审核的 C5 source/tree。父任务给出的设计身份与实际文件摘要相等。

**所依据的开销事实及其限度。** 已完整读取 `c4-ci-overhead-diagnostic.md`，11451 字节，SHA-256 `d85901f61ea58ff5e068ae666af9fa4f4bf371efdc34687a0b839f04623260d8`。它记录新增空块归档/名称测试耗时、重复 key build 的静态调用计数及取消时未完成步骤，支持研究复用初始化；它不是 profiler，也没有把预算关联推断写成确认的取消根因。本次没有重新认证 C4 全部 CI；新设计不得继承 C4 的成功记录，也不能将取消或未执行项升格为通过。

**固定版本和构建来源。** 当前 Cargo.toml 固定 `orchard = "=0.15.5"`，Cargo.lock 同版本、registry checksum 为 `a3cb2b35534bba3c63fbf640dc6cd9dfd1ece2fae886cdab4ab1f1e380dd6ca1`；toolchain 固定 1.98.1。`lib.rs:27` 的 CIRCUIT 是 `OrchardCircuitVersion::FixedPostNu6_2`，与 bundle VERSION 和受信任状态策略分开。新设计只准私有单元从这个编译期常量调用固定 `VerifyingKey::build`，没有从归档、交易、pin、磁盘、网络或调用方选择 key 的路径。

本人读取的 Orchard API `/latest/` 页面明确标为 0.15.5，列出 VerifyingKey 的 Send、Sync 和 circuit_version；其 Source 链接的 build 代码创建固定参数及空电路后执行 keygen_vk，返回带该版本的 key，没有调用本项目的 verifier。准确 `/0.15.5/` 文档 URL 本次未能读取，故不声称已用该 URL 或下载后的 crate 独立验真依赖；实际锁定构建仍必需。[Orchard VerifyingKey API](https://docs.rs/orchard/latest/orchard/circuit/struct.VerifyingKey.html)、[所读上游构建源码](https://docs.rs/orchard/latest/src/orchard/circuit.rs.html)

当前只有这一固定版本，所以一个单元足够。未来改变电路时，仅创建另一个 AuthorizationVerifier 不足以更换已初始化单元；必须重新审核版本和静态存储绑定，不得由运行输入复用旧单元或旧授权缓存。设计第 7 条已经明确这一点。

**Send/Sync 和生命周期。** 官方类型事实支持 `OnceLock<VerifyingKey>` 的只读跨线程共享：OnceLock 的 Sync 实现要求元素 Send+Sync，返回借用不会授予修改权。每个 verifier 持有 `&'static VerifyingKey`，而 VerifiedCache 仍按值持有自己新建的 Mutex/VecDeque。实现必须由锁定版本的 Ubuntu/Windows 原生编译确认，不能增加 unsafe、自制 Sync/Send、可变静态或绕过类型约束。[Rust OnceLock](https://doc.rust-lang.org/std/sync/struct.OnceLock.html)

静态对象在整个进程生存期间保留，进程结束时 Rust 不调用其 Drop；因此最后一个 verifier 释放后，这份公共材料仍驻留，是明确的内存生命周期变化。各 verifier 的交易成功缓存仍随各自对象独立释放。新进程重新初始化，不是磁盘 key/cache 持久化；本变更没有证明峰值内存减少或量化常驻成本。[Rust 静态对象生命周期](https://doc.rust-lang.org/reference/items/static-items.html)

**失败和重入。** get_or_init 在初始化不 panic 的情况下保证竞争调用只执行一个初始化函数；panic 传播且单元保持未初始化，之后可以再次尝试同一固定构建。它不是“初始化失败即永久 poison”，也不是“包括失败在内绝对只尝试一次”。设计第 5 条表述正确，没有允许返回空 key、备用电路或成功 fallback。上游 build 内部的失败 panic 不会产生一个可供 verify 使用的半初始化引用。

初始化重入是错误；Rust 官方当前实现可死锁，未来也可能改为 panic。闭包必须只直接构建固定上游 key，不回调 AuthorizationVerifier::new 或同一个获取函数；不能借本次优化增加会触发这些回调的日志钩子、插件或导入流程。新设计已明确禁止重入。以上属于标准库合同和源码路径审核，本轮没有故意制造真实构建 panic、进程 OOM 或冷启动竞争，也不要求以会永久影响共享单元的故障注入测试来替代合同核查。[OnceLock 初始化合同](https://doc.rust-lang.org/std/sync/struct.OnceLock.html#method.get_or_init)

**授权缓存与重放不会因此放宽。** 当前 `wire.rs` 先 decode、再查实例的 digest+完整字节、验证花费签名与绑定签名、真实 verify_proof，最后 remember；缓存 Mutex 损坏返回 Authorization，未缓存失败。新设计逐项保留该顺序。只共享 key 不共享可变验证结果；一个新实例对达到密码学检查的首次有效输入仍须真正验证，不能凭其他实例的成功接受。

已读取 PoolStore 创建和活动/legacy 重放、State::apply_transaction、Replay::next_block、归档导出/verify/copy，以及 worker::serve、WalletProver、vault outbox 验证的调用方。它们仍得到新 verifier 和空缓存；当前 worker 会话不能导入成功标记，vault 的新 verifier 不能继承别的会话授权。活动 copy 的源、目标和末次源三次完整真实 replay、每次新 verifier，以及重算 pin 后坏签名的 Authorization 拒绝继续保留。`lib.rs::Verifier` 和 WalletProver 的证明生成 key 不在本次复用范围内。

key 本身不包含任何当前账本许可。域、过期、受信任 anchor、已花费 nullifier、重复输出、费用和原子提交仍由状态路径检查；LAB1/LAB2、旧/新 profile 不能因共享公共材料而互相变为可信。`VerifiedCache::default()` 必须留在每次 new 的构造中，不能放进静态单元或改成克隆一个全局已热缓存。

**新增验收测试要求合理且有区分力。** 已确认旧 `tests/authorization_cache.rs` 的新 verifier 再次 `verify(raw)==Ok` 本身不能观察“冷缓存”；耗时也不是可靠替代。当前新设计提出真正检查私有缓存，再执行真实验证，能够识别错误地共享整个 verifier 或成功缓存：

1. 只生成一份真实固定电路 fixture；A 实际验证有效字节后，检查 A 的 contains 为真。不能直接 remember 伪造成功条目。
2. 并发创建新的 B 等实例，核对同一只读 key 身份和准确 `FixedPostNu6_2` 版本；在各自首次验证前，其 contains 必须为假。随后每个实例实际 verify，同一有效字节才分别入各自缓存。测试观察接口应限制在私有 cfg(test) 子模块，不增加生产调用方可导入或标记成功的 API。
3. 签名、证明分别变更仍须拒绝且各自 contains 为假；应选保持规范解码成功的变更，并明确要求 Authorization，确保触达对应密码学拒绝层。保留同一原字节之后仍有效的正对照，避免把 fixture 损坏误认为实现安全。
4. 保留全部原始 cache 碰撞/FIFO/并发、真实 proof 正负样本、热缓存账本拒绝、真实归档/恢复/再次花费、重算 layout 坏签名和 CLI stdout 回归。不得降低预算、减少完整 replay、删除测试或改变 cohort。仅修正“每个 verifier 新 key”的过时注释，不删现有断言。

并发创建加共享 key 身份并不证明首次初始化发生了竞争，因为测试进程可能已被其他测试预热。准确设计已接受这一边界：不要求新进程冷竞争测试时，就不宣称覆盖它；基本互斥/发布行为来自标准 OnceLock 合同，实际并发使用由新回归和双平台运行验证。没有必要增加固定微秒阈值或另造验证器，来将性能改善充当正确性。

实现阶段还应同步核对旧 AUTHORIZATION_CACHE 文档关于“仍自行构建固定 key”和未来更换参数的用语，使读者理解固定构建来源与每个实例空缓存分别保留；这属于当前补充设计的说明一致性，不是本设计阻断。无需修改冻结活动归档格式、容量或三次 replay 合同。

本轮没有 C5 实现、编译、Clippy、Rust/Go 测试或原生结果，亦未认证节省秒数。本地无 Rust/Cargo/Go。旧引用 `docs/PROOF_CONTRACT.md`、`docs/ARCHITECTURE.zh-CN.md` 本地不存在，本人没有声称读取它们；本结论针对准确现存设计、调用路径和既定 NO-FUNDS 边界。实现完成后必须冻结新的 source/tree、完整非作者代码复审并在原有预算内重新跑完整双平台矩阵。

C4 静态原件继续保持：`adversarial-review-c4.md` 15431 字节 / SHA-256 `5d736cf901527a97cf27725212088432f6a1b943a9caccd02e1b94521e34b844`；其 JSON 28068 字节 / SHA-256 `c39f3f128b121b6903fe9fd8603c699084f8361814fb3c49e5b528cb05fc584c`。它们没有被本轮改写，也不自动覆盖将来的 C5。
