# P2 活动账本归档与完整恢复：C7 非作者独立代码审核原件

审核者：`/root/p2_archive_review`。日期：2026-09-17 UTC。本代理未编写或修改候选设计、源码、测试、工作流或依赖。

**结论：PASS_CODE_REVIEW。准确 C7 的全阶段代码与测试设计审核通过，未发现未关闭的代码审核阻断。** 已从源码层面确认 C6 的 fixture 重复模块加载原因被移除；这不表示 C7 原生 Clippy 或完整矩阵已经通过。当前 native acceptance 待独立验收，stage_accepted 为 false。

## 准确对象、历史与审查范围

- 阶段 base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`；base tree：`5e039b41e00f7a0a2e78937c796a40fbe68bfb0c`。
- C7 source：`de474720431daf33afd4a7ebc32de2d230344a5a`；tree：`e4dd17dfb1efd0e3ca20441168b62b72b6fc3108`。
- Parent C6：`88146d54f2eaac39958ceaaea9e13f71832d536e`。
- PR：[#13](https://github.com/youq616/Zevune/pull/13)。本报告以本地准确 Git source/tree 为对象，未声称本轮独立核验 C7 synthetic checkout；原生审核须核对实际 checkout 绑定。

全阶段 16 文件、2949 insertions / 38 deletions；C6→C7 为 3 文件、+5/-5。逐文件核对当前 Git blob、工作树字节、长度及 SHA-256，与 C7 清单和保留文件的 C6 清单全部相符；工作树干净。

本轮覆盖完整 base..C7 及相关调用方，重新审视 pin、物理/逻辑重放、状态、复制/namespace/锁、CLI、真实付款/错误样本和 key/cache 生命周期。直接重读当前模块上下文、完整 pool_tests、wire/cache/新真实证明测试及 helper；核对保留阶段文件与此前完整读过的源码字节相同，并重新检查核心调用和历史问题的当前断言。没有从 C6 PASS 自动继承批准或原生信用。

观察原件 `code-review-c7-observation.json` 为 12460 B，SHA-256 `1d51bc65bbbc838794c6374b84e964a0f6aaeac070907bcd66bbfcdf2fa1c968`，保存 16 文件摘要、实际检查、未测范围和历史原件摘要。

C6 失败历史保持：`c6/job-105167396538.log` 68156 B，SHA-256 `a0368cb426a63c9ed4763cd88429f5744b0d0404b30c50e419f0e86903b40e40`。其 18 组结果合计 154 passed、library 140 passed/66.85s、新 key 用例 ok，随后 Clippy duplicate_mod 受 -D warnings 提升为错误，exit 101，C6 不接受。我对重复模块的静态漏检已在 C6 addendum 承认；部分测试成功没有转为 C7 证据。

## 重复模块修复、可见性与生产排除

准确改动只有三处：pool_tests.rs 的 fixtures 从 pub(super) 调整为 pub(crate)，原 path/mod 保留；pool.rs 在 cfg(test) 下仅 `pub(crate) use tests::fixtures`；wire 私有测试通过 `use crate::{pool::fixtures, CIRCUIT, NETWORK}` 导入，删除第二个 path/mod。

搜索 src 内全部 fixtures 引用和相关 path 后，只剩 `pool_tests.rs:7` 一个 fixture 文件加载点。use/re-export 引用已有模块，不创建第二个模块。原 tests 仍私有，没有公开整个 tests，也没有移动旧模块；wallet_flow_tests 和 root_cache_tests 的原 tests::fixtures 路径保持。helper 内无全局共享状态，复用代码模块不复用随机生成的密钥、见证、交易或授权成功。

pub(crate) 限制在当前 crate；pool 可访问自己的私有 tests，fixture item 本身的可见性允许同范围重导出，wire 通过 crate-private alias 合法使用。pool_tests 的 `use super::*` 不引入新 mod 声明，局部显式 fixtures 声明仍指向唯一模块，未见名称解析、循环模块定义或类型身份改变。[Rust Reference：可见性与重导出](https://doc.rust-lang.org/reference/visibility-and-privacy.html)

三个 cfg 边界均实际核对：pool 的 tests 模块、pool 的 re-export、wire 的 fixed_key_tests 模块各自受 cfg(test) 控制。非测试 library 构建不包含这些项；仅启用 local-funding-lab 不会启用 cfg(test)。没有生产 helper、外部 API、unsafe、allow(duplicate_mod) 或其他 lint 抑制。独立 integration test crate 各自导入原 fixture 的行为未改，不是同一 library test 编译单元中的重复加载。

机械字节检查也确认：从当前 pool.rs 删除新增的精确 cfg-test re-export 后与 C6 相同；pool_tests 还原唯一 visibility 字样后与 C6 相同；wire 新测试从 #[test] 起的完整 3537 B 函数体与 C6 相同。helper 实现自阶段 base 起保持 3371 B，SHA-256 `b064d2e9086943d0e19564e4872027e3b2c3132a0f510e187079b17722ae0473`。

因此已知 duplicate_mod 的源码原因已排除，未发现新的可见性或语义阻断。**未运行 C7 Clippy，不能把静态判断写成“已确认没有任何新 lint”；实际 fmt、Clippy、编译仍须准确 C7 原生结果。**

## 固定公共 key 与独立授权

生产 wire 与 C6 完全相同，符合冻结 FIXED_VERIFYING_KEY 合同。私有 getter 内 OnceLock 唯一初始化为 `VerifyingKey::build(CIRCUIT)`；CIRCUIT 仍为 FixedPostNu6_2。没有外来 key/版本、文件加载、网络获取、备用 verifier、catch 后成功或 getter 重入。每个 AuthorizationVerifier 保存只读静态 key 引用，但各自创建 VerifiedCache::default()，Default 走 new，没有共享整 verifier 或授权成功条目。

verify 顺序仍为完整规范解码、本实例 digest+完整 raw 精确查找、全部花费签名、绑定签名、上游真实 verify_proof、最后 remember。cache 的容量、FIFO、完整字节比较和锁错误拒绝未改。账本每次执行仍重查签名域、过期、可信历史根、双花、重复输出、容量、费用及区块/提交条件；cache hit 不是可复用花费许可。

相关构造调用方仍各自 new：活动/旧单日志重放、旧 SegmentedArchive 每次 replay、worker 每会话、WalletProver 每对象、vault outbox 恢复。只共享公开 key，不跨调用方继承成功记录；其他原 Verifier 和证明生成密钥生命周期未扩大到本优化。

直接固定构建与 OnceLock 的并发初始化、panic 后仍未初始化的标准语义相符，没有增加接受路径。VerifyingKey API 的显式版本和 Send/Sync 支持共享只读 key；文档不替代实际锁定依赖编译。查阅的是页面标为 Orchard 0.15.5 的 latest URL，不声称读过不可用的版本专属源码。[Rust OnceLock](https://doc.rust-lang.org/std/sync/struct.OnceLock.html)、[Orchard VerifyingKey API](https://docs.rs/orchard/latest/orchard/circuit/struct.VerifyingKey.html)

新增回归仍生成一个真实 proof：100000 输入、60000 收款、39000 找零、1000 费用，经原 helper create_proof/apply_signatures，不 fake remember。first 与 existing 起初均无条目；first 真正验证后 existing 仍无；四个后建 worker 实例分别断言空 cache、共享正确固定 key、真 verify 后 own cache 有条目。线程返回后 existing 再证明冷缓存，然后独立验证；最后新建实例继续为空。这个组合能识别误共享成功缓存，而不仅仅检查“新实例也能验证成功”。

两个 mutant 分别改变 proof 首字节和绑定签名末字节，先要求规范 decode 成功，再 exact Authorization 拒绝，坏字节前后不入 cache，有效原字节继续成功。proof mutation 不改变效果、上下文和签名，结合现有 V5 效果 commitment 与生产顺序，静态支持它进入实际 proof 验证；C7 运行结果仍需本候选证据。[Orchard Bundle API](https://docs.rs/orchard/latest/orchard/bundle/struct.Bundle.html)

四个 worker 各只 wait 一次，全部断言位于 Barrier 之后；key 已提前成功初始化。scope 自动 join 并传播正常线程 panic，不会忽略验证断言失败。仍未测冷首次初始化竞争和上游构建 panic；OS 若中途拒绝创建后续线程，已启动 worker 可能等不到完整 Barrier 人数，此测试资源失败局限作为非阻断观察保留，不据此改生产同步或预算。[Rust thread::scope](https://doc.rust-lang.org/std/thread/fn.scope.html)

所有真实检查次数与旧断言保留。旧 authorization_cache 集成测试相对 C4 只有说明文字更新。公共 key 常驻至进程退出的生命周期已记录，不承诺最后一个 verifier drop 即归还内存或一定满足任何性能阈值。

## 全阶段活动归档、复制与失败边界

**独立 pin。** ZVARCP01 精确 128 B，三个 hash 非零，高度≤1000000、逻辑长度≤1 GiB、段数≤2048、头长 76+32n、零高度与零段/零记录关系及 checked 算术均先验证。旧 120 B ZVPRCP01 与新格式互斥。布局绑定仍为 ZVARLY01、u32 头长、原头、u32 段数、逐段 index/length/raw，不把字节指纹当来源、最新高度或 finality 证明。

**物理/逻辑完整重放。** 原 genesis 单文件先解析，头长等于捕获物理长度且到真实 EOF，伪 commitment count 不能借 journal 补齐。物理与逻辑头一致后 State 重建实际状态并绑定独立 expected_genesis：普通 open 来自可信期望头，导出来自 committed store，归档来自外部 pin。每次 replay 新建空缓存 verifier；每记录验证 checksum、前状态、真实授权/状态执行、后状态，并 validate_frame 拒绝跨段和过早轮换。finish 要求实际 EOF；错误重建不发布。

**导出。** active_recovery_checkpoint 前后 layout/namespace 检查夹住 fresh replay，比对完整 committed Summary、genesis 和长度，PreparedBlock 不消费或变动。unsupported legacy 请求先拒绝且不 poison 健康 store；真实字节/身份/历史错误使 store unavailable，不把替换历史发布成新状态。

**名称与持锁句柄。** 严格连续八位 journal 清单拒绝未知项、缺段、空段、非普通文件、Unix 链接及 Windows reparse。Unix device/inode 和单硬链接、Windows 目录及文件 no-DELETE-sharing 规则保持。归档源只读且 genesis 共享锁，writer 独占锁，目录/文件/reader clones 持续保留。每物理文件读完捕获长度还检真实 EOF/metadata，并前后核对 namespace。

**仅新建复制。** 先核原源身份、绝对目标、已存在 canonical parent，拒绝源内和父别名回到源内、同路径及已有目标。完整源验证发生在创建前；新目录/文件排他创建，Unix 0700/0600，以 64 KiB 缓冲从持有的原句柄复制；各文件 sync_all，Unix 同步目录及父目录。目标原创建且独占持锁的句柄直接完整验证，不 drop/unlock 后重开；然后末次完整源验证，最后目标字节/namespace 检查。源前验、目标验、末次源验三次重放及每次独立空 cache 保留。

创建后失败仍可能留下部分或完整目标，未新增删除、截断、覆盖、自动重试、修复或启用节点。明确偏移读取与串行重放不依赖 Windows 克隆共享游标的偶然位置，append 明确 seek tail；key 的线程安全未扩张成归档并发快照承诺。完整副本在回执失败后可后验验证，错误不证明目标不存在，同步不等于已做真实断电证明。

## 测试覆盖与历史问题

AR-C1-01 在当前代码/测试设计层面重新核对关闭：真实 10001 历史的两个已存在活动段交换完整字节，旧 pin 拒绝；repin 与生产 layout hash 明确匹配后，解码首记录确认 base_hash 不等于 genesis，再要求 Corrupt；源和坏候选字节不变。没有用旧 ZVPSEG01 样本代替。另有真实 binding signature 损坏并重算 record checksum/layout pin 的 Authorization 拒绝，不是旧哈希或锁失败。

真实增长流程仍在第一笔付款导致生产 1 MiB 轮换后 backup→restore，经普通 open 恢复钱包历史、余额、双花检查，再继续真实提交到 10001 并执行原第二跳；之后再次 backup→restore 并继续 10002。没有将空块数量冒称付款数量；全部旧选择、容量、状态不变性和失败断言保留。

其他完整覆盖保持：codec 截断/尾字节/边界、独立固定布局向量、genesis 无段/正常副本、prepared work、同长历史替换、持锁原头变化的独立 genesis 绑定、头借段/错 profile-network-domain-curve、repin 后 frame/轮换/后状态/EOF、只读源、实际双进程锁、多 reader 与 drop、Unix 名称持久替换/链接、Windows rename/delete 至最后 reader drop、已有/相对/缺父/源内/别名目标拒绝、失败 open 句柄释放及末次未知项检查。六个私有故障点覆盖部分文件、完整未同步、同步后丢确认和最终源/目标 namespace 变化，仍仅 cfg(test)。

AR-C3-02 也重新核对代码/测试闭环：active receipt 持 stdout lock，以安全 owned fd/handle 复制转 File 写入/flush，Windows NULL 拒绝，避开 StdoutRaw 将 EBADF 视为成功的路径，原 stdout 所有权不被夺取。真实只读 File probe、可写文件 JSON 正控制、四 active mode exit 1、完整 backup/restore 后验 verify、已有目标不可覆盖全保留。执行闭环仍须准确 C7 原生证据。

## CLI、旧接口与不变范围

checkpoint-active 通过独立 pinned 03 TestGenesis、active profile、可信准确 height/AppHash 后导出；其他模式使用独立新 pin，backup/restore 共用 copy_new。缺失/重复/未知参数、非规范 hex/height、相对路径和错误 profile 拒绝。成功 JSON 保留 replay_verified true，finality_verified/validator_ready/real_funds_allowed false；错误不泄漏路径或声称失败后目标不存在。

旧 CLI/成功 JSON、ZVPRCP01/ZVPSEG01、索引语义未重解释；Go CopyStorageAtCheckpoint 仍拒绝 active profile，没有网络恢复入口、自动迁移、钱包/签名状态或完整验证者恢复。

实际比较确认工作流、scripts、Go/internal/cometbft、Cargo/go 依赖、lib 固定电路/协议参数、cache 容器、Replay、TestGenesis、segments/namespace 与阶段 base 无 diff。相对 C6，生产 wire、两份冻结设计、归档核心/CLI/真实付款和既有测试不变；pool 新文本只在 cfg(test)。没有 allow、删测试、减少 proof/replay、改并行参数或放宽预算。

ACTIVE_ARCHIVE_V1 仍为 13188 B / `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee`；FIXED_VERIFYING_KEY 仍为 4682 B / `363e6a9576b12e5f2eb39487b00486cef92e9a49bc5728d47bf266b23a14f5a5`。设计限制与当前实现一致。

## 实际检查、未执行与接受边界

实际执行 Git 身份/16 blobs/工作树/清单核对、完整阶段与 C6 delta 检查、源码和调用方复核、唯一 fixture 加载点/三个 cfg guard、完整测试函数体与 helper 原字节比较、protected paths 比较和 diff --check。本报告未冒认新的 C7 辅助子审核结果；此前 C6 辅助结论仅属历史，本代理独立作出当前判断。

full base..C7 diff --check exit 2，唯一诊断仍为冻结 ACTIVE_ARCHIVE_V1 第 185 行 EOF 额外空行；source/test 和 C6→C7 范围 exit 0。没有修改冻结设计或把它说成全范围无诊断。

未本地执行 Rust 编译、fmt、Clippy、测试或 Go test/vet/race/fuzz，未重触发 CI，也未验收 C7 原生矩阵。必需逻辑 gate 须按准确 checkout source/tree、完整命令/测试结果和后续步骤独立核查，不能以 C6 的 154 passed 抵扣 C7；静态 PASS 不保证尚未执行的 lint 没有问题。

此前 C1/C3/C4/C6 原件、C6 addendum、C4 诊断与 race 勘误全部保留且摘要记录于 observation。C6 主报告仍为 17003 B / `055968cb720dc117c6e4f451d2910973d3d92b6af596aee88cda6a8184a05aa2`；addendum 为 3244 B / `155dd3ed2284e0cc2a1abb1d5b72ff770bb63938eecd7b8679e198673d9752fb`。失败历史未删改或改写成通过。

未测范围仍包括冷首次初始化竞争、key 构建 panic、线程资源耗尽、2048 段全容量、真实磁盘满/断电及 Windows 目录持久化；公开 key 常驻、完整历史/状态内存、源/目标/reader 整套句柄成本保持。可信父目录、OS、文件系统是前提，不防任意瞬时恶意替换再还原。NO-FUNDS、P2 开发中和外部安全审计未完成的边界未变。

本报告只批准准确 source `de474720431daf33afd4a7ebc32de2d230344a5a` / tree `e4dd17dfb1efd0e3ca20441168b62b72b6fc3108` 的代码审核范围。运行代码或测试再次变化须重新冻结复审；当前阶段接受仍等待准确 C7 的完整原生验收。
