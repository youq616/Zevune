# P2 活动账本归档与完整恢复：C6 非作者独立代码审核原件

审核者：`/root/p2_archive_review`。日期：2026-09-17 UTC。未编写或修改本候选设计、实现、测试、工作流或依赖。

**结论：PASS_CODE_REVIEW。准确 C6 的全阶段实现与测试设计审核通过，未发现未关闭的代码审核阻断。** 本报告不验收 C6 原生矩阵，不表示阶段已接受。C5 审查因实际格式门槛失败中断，没有出具 C5 正式 PASS 原件；C4 或更早候选的静态结论、原生成功片段、取消与重跑均不转作 C6 验收信用。

## 准确对象与覆盖范围

- 阶段 base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`；base tree：`5e039b41e00f7a0a2e78937c796a40fbe68bfb0c`。
- C6 source：`88146d54f2eaac39958ceaaea9e13f71832d536e`；tree：`cbddd8e982eb9013d10010354e477b264e33841b`。
- Parent C5：`99ef9e8217182c9a6f4f1e9349613c1917ddec50`；其 parent C4：`50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`。
- PR：[#13](https://github.com/youq616/Zevune/pull/13)。本报告以本地准确 Git 对象为审核对象，没有声称独立核验 C6 的 GitHub synthetic checkout；该绑定须在原生验收中另行核对。

全阶段 15 文件，2948 insertions / 37 deletions。我核对了每个变更 Git blob 与工作树的准确字节、长度及 SHA-256，核对 candidate-c6、candidate-c5 与既有 C4 清单的组合，全部相符；开始及写出原件前工作树干净。

这是连续的全阶段源码审核：先完整检查 base..C5 的阶段 diff、新模块、新测试及相关调用方；C5 原生失败后停止批准，再对准确 C6 重新核对全部 15 个 blob，证明 14 个与刚读过的 C5 完全相同，完整重读当前改变的测试文件。没有仅凭 C4/C5 旧 PASS 或单条差异替代全范围审核。

独立观察 JSON：`code-review-c6-observation.json`，11322 B，SHA-256 `c19ef9435e847e06917e1289fbeb23e2b63df34d07b4cfac3b4f0a93d6a37cf6`。其清单记录准确文件摘要、命令结果、未执行项目、历史原件摘要和辅助审核范围。

## C5 格式失败及 C6 准确修正

我实际读取 `c5/job-105166096614.log` 的格式诊断；日志为 20672 B，SHA-256 `994c43ca2a98a46957c99dfe1dd755de2762fcd82a6acae006544894b5d64042`。2026-09-17 10:25:48 UTC 的诊断要求把 `fixed_key_tests.rs` 内固定版本 assert_eq 展开，随后命令 exit 1。

C5→C6 的唯一 hunk 与该原生建议相符：一行改四行，+4/-1。当前测试 92 行、3954 B，SHA-256 `f2b66e8aa4caf4f95fdb7cd202087c9c627b113861a0c088e6971b7e9a8e7592`；两版本去除全部空白后相同。所有运行表达式、断言与调用顺序保持。该核对证明修正对准已知诊断，不能代替 C6 原生 rustfmt 成功。

出具记录时 `code-review-c5.md` 和 `code-review-c5-observation.json` 均不存在。C5 只有只读工作观察，没有正式批准原件可继承；其失败原日志保持。

## 固定公共 key 与实例授权隔离

`wire.rs:261` 的 getter 私有，函数内静态 `KEY: OnceLock<VerifyingKey>` 只有 `get_or_init(|| VerifyingKey::build(CIRCUIT))` 这一入口。没有调用方参数、文件加载、网络获取、可变 setter、备用电路或成功返回的 fallback。初始化闭包只调用固定上游构建，没有回调 verifier 构造或 getter 的重入路径。`lib.rs` 的 CIRCUIT 仍为 `FixedPostNu6_2`，Cargo.toml/lock 和所有协议版本未改。

`AuthorizationVerifier` 只把 key 字段改为私有 `&'static VerifyingKey`；verified 仍是它自己拥有的 `VerifiedCache`。new 及 Default 均创建新的 `VerifiedCache::default()`；没有共享整个 verifier，也没有共享 VecDeque、成功条目或状态。key 的生命周期到进程退出已在文档中说明，并未承诺最后一个 verifier drop 时释放它。

`verify` 的实际顺序保持为：完整规范 decode；完整字节摘要；本实例 digest+完整 raw 的精确查找；逐花费签名；绑定签名；上游 `verify_proof(self.key)`；最后 remember。与 C4 相比，proof 调用的唯一变化是传递已经为引用的 key，未减少检查。缓存失败/poison 仍返回 Authorization；新实例首次授权不能命中另一实例成功记录。已有容量、FIFO、完整字节比较、成功后写入规则逐字节未变。

标准 OnceLock 的并发初始化、panic 保持未初始化和重入错误语义符合设计；上游 VerifyingKey 的显式版本 build/circuit_version 与 Send/Sync 支持这个只读复用方案。独立读取的 Orchard API 是 latest URL，页面标为 0.15.5；不声称成功取过不可用的版本专属源码链接，也不把文档替代锁定依赖的双平台编译。[Rust OnceLock](https://doc.rust-lang.org/std/sync/struct.OnceLock.html)、[Orchard VerifyingKey API](https://docs.rs/orchard/latest/orchard/circuit/struct.VerifyingKey.html)

我核对了所有相关实际构造调用方：活动/旧单日志重放、旧 SegmentedArchive 的每次 replay、worker 每会话、WalletProver 每对象以及 vault 恢复 outbox 的临时 verifier。它们仍各自 new，因而只共享公开 key，不跨调用方继承授权成功。其他原始 Verifier 和证明生成密钥生命周期保持原样。

账本每次执行仍在可信状态上重查 signing_domain、过期、历史根、双花、重复输出、容量、费用及区块/提交规则。授权缓存命中没有变成花费许可；LAB1/LAB2 的签名域和编码没有变化。

## 新增真实证明与并发回归

`wire/fixed_key_tests.rs` 在 cfg(test) 下导入原 fixtures；lib.rs 的既有 test crate alias 使其引用真实项目模块。测试生成一个真实 Orchard proof，输入 100000，60000 收款、39000 找零、1000 费用，通过真实 create_proof/apply_signatures 得到规范 raw，不调用 remember 注入条目，不使用伪接受器或耗时阈值。

隔离断言不只是“新实例也能返回成功”。first 与 existing 均在 first 成功前构造，双方起初 contains=false；first 调生产 verify 成功后只有它 contains=true，existing 仍 false。四个 worker 在 first 已成功后分别构造新实例，各自要求相同只读 key 与固定版本、contains=false，再调用真实 verify 并要求 own contains=true。scope 返回后 existing 仍 false，再独立 verify 成功；最后又新建实例要求 false。该组合能够识别误共享全局成功缓存和同线程实例共享缓存。

两个 mutant 分别改变 proof 首字节与绑定签名末字节；先要求 canonical decode 成功，随后在每个 worker 明确断言 `Err(WireError::Authorization)`，并检查坏字节在拒绝前后均没有入缓存，有效原字节仍成功。proof 改动保留签名、效果字段和上下文；结合现有 V5 效果 commitment 与生产验证顺序，静态分析支持它进入真实 proof 验证路径。这里描述的是代码路径及测试断言，不宣称 C6 已执行通过。[Orchard Bundle commitment/verify_proof API](https://docs.rs/orchard/latest/orchard/bundle/struct.Bundle.html)

Barrier 人数为 4，仅四个 worker 各 wait 一次。所有测试断言与缓存锁操作位于 wait 之后；key 已在主线程成功初始化。没有第二道 Barrier 让正常验证断言 panic 留下等待者。未保存 join handle 并不忽略线程失败：thread::scope 在返回前自动 join，自动 join 的线程 panic 会使 scope panic，测试因此失败。[Rust thread::scope](https://doc.rust-lang.org/std/thread/fn.scope.html)

非阻断限制 AR-C6-N01：若 OS 在四个线程尚未全部创建时拒绝后续 spawn，先启动的 worker 可能停在人数不足的 Barrier，最终依赖外层作业预算结束。这是测试在线程资源耗尽条件下的退出局限，不涉及生产密钥安全或正常断言传播。没有宣称覆盖该故障；不因此要求改生产同步原语或放宽预算。

测试注释明确未测冷首次初始化竞争；也没有初始化 panic 注入或实际 key-build 运行时计数。固定 key 常驻及性能改进是设计/源码事实，不是吞吐承诺。旧 authorization_cache 集成测试只改两行说明；我逐行去除注释比对，全部旧运行语句和断言与 C4 相同。AUTHORIZATION_CACHE 文档同步说明新实例仍空缓存、未来更换版本需重新绑定，冻结固定 key 设计的 4682 B 摘要保持不变。

## 全阶段活动归档复核

**独立 pin 与 bounds。** ZVARCP01 精确 128 B，与旧 120 B ZVPRCP01 互斥；私有字段的外部入口先检 exact length/magic，再检非零 hashes、高度≤1000000、总字节≤1 GiB、段数≤2048、头长 76+32n、零高度与零段关系、记录字节范围和 checked 算术。头长/段长/index 转换受已验证界限保护。pin 不由候选目录自行决定信任，也不证明最新高度或 finality。

**物理与逻辑双重验证。** 原持有的 genesis 单文件先按真实头长与实际 EOF 解析；伪造 commitment count 不能借第一段补齐。逻辑头与物理头一致后 State::from_storage_policy 重建真实状态，并将实际 genesis hash 与调用者独立期望值比较。普通 open 的期望来自可信构造头，导出来自 committed store，归档来自外部 pin。新 verifier 建在每次重放内部；Replay 每记录校验 checksum、前状态、执行授权、后状态，再逐帧 validate_frame 拒绝跨段与非规范提前轮换。finish 需要实际 EOF，完整失败状态不发布。

**导出与健康状态。** active_recovery_checkpoint 先取 committed Summary，完整 layout hash/namespace 与 fresh replay 前后夹验，比对完整 Summary、genesis 和 length，成功才返回 pin。PreparedBlock 不消费不更改；unsupported legacy profile 先拒绝而不 poison。真实存储/身份/历史错误使 store unavailable，不发布替换历史。

**精确 layout。** 哈希仍为 ZVARLY01、u32 header length、原 header、u32 segment count、顺序 index/length/raw bytes。访问每个物理文件都按捕获长度明确定位，并检实际 EOF 和 metadata，不用逐段摘要替代原字节；前后 namespace 检查保留。固定向量断言未被优化改动。

**名字与锁。** 严格 genesis/连续八位 journal 清单拒绝未知项、缺号、空段及非法对象。Unix 保持 device/inode 和单硬链接；Windows 保持目录/各文件 no-DELETE-sharing 与 reparse 拒绝。归档源只读+genesis 共享锁，普通 writer 独占锁；保留原文件/目录及克隆句柄，不为验证 drop 锁再重开。

**创建与三次重放。** copy_new 先检原源身份、绝对目标、真实父目录及 canonical source/parent，拒绝源内目标、父别名回到源内、同路径和已有目标。创建前完整源 verify；新目录/文件逐一排他创建，Unix 0700/0600，64 KiB 缓冲从原句柄复制；各文件 sync_all、Unix 目录和父目录 sync。目标原创建句柄保持独占锁并完整验证，随后完整源末验，最后目标字节/namespace 检查。三次生产重放没有删减，也没有共享其授权缓存。失败后不自动删除、截断、覆盖、重试或启用节点。

**Windows 游标与错误边界。** read_at/seek_read 使用明确偏移；物理头 clone rewind 和逻辑 reader 串行，写 append 明确 seek tail。未在同一个归档对象承诺并发读写快照；没有把共享 key 的线程安全扩大成文件/状态并发安全。创建后失败仍可能留下完整副本，后续显式 verify 可认证完整字节；错误不意味着目标不存在或已持久到断电。

## 历史缺口与测试闭环

AR-C1-01（Medium，历史 C1 交换覆盖缺口）在准确 C6 的代码/测试设计层面重新核对关闭：10001 高度使用实际已存在两段交换完整字节，旧 pin 拒绝；repin 与生产 layout hash 先明确匹配，解码交换后首记录验证其 base_hash 不是 genesis，再断言 Corrupt。源与坏候选目录字节不变。不是用旧 ZVPSEG01 样本代替活动归档测试。另一个真实付款样本损坏 binding signature 并重算 record checksum 与 layout pin，明确要求 Authorization；没有将旧哈希/锁失败冒称授权拒绝。

保留的真实增长流程在第一笔真实付款引发 1 MiB 轮换后执行完整 backup→restore，经正常 open 回到钱包历史和双花检查，再继续到 10001 并做原第二跳；之后再次 backup→restore 并继续 10002。10001 是真实提交历史高度，不宣称有 10001 笔付款。全部旧状态、容量和 rejected-candidate 不变性断言保留。

归档测试完整复核了 codec 截断/尾字节/边界、genesis 无段副本、prepared work 保留、同长真实历史替换、原持锁头变化绑定、物理头借段、错 profile/network/domain/curve、重算 pin 后分帧/提前轮换/错后状态/尾字节、只读源、实际跨进程锁、Unix 名字替换/链接、Windows rename/delete 拒绝至最后 drop、失败 open 句柄释放及未知项。六个私有故障点覆盖部分文件、完整未同步、同步后失去确认和末次源/目标 namespace 变化，仍在 cfg(test) 内。

AR-C3-02（Medium，历史 C3 stdout EBADF 漏检）在 C6 代码/测试设计层面重新核对关闭：active receipt 持有原 stdout lock，通过安全复制的 owned fd/handle 转 File 写入/flush，Windows NULL 明确拒绝，不再依赖 StdoutRaw 将 EBADF 映射成功的行为；原句柄所有权不被强取或关闭，没有 unsafe。七项 CLI 测试中的输出失败项先探测真实只读 File 写入失败，另有可写文件成功 JSON 控制；四种 active 模式明确 exit 1。backup/restore 在失败回执后分别比对完整目标字节并用正常 stdout 显式 verify，随后已有目标仍不能覆盖。该代码闭环须由准确 C6 原生执行最终验收。

## 旧接口与不变范围

新 CLI checkpoint-active 经独立 pinned TestGenesis 03 profile、准确 trusted height/AppHash 再导出；其余使用独立 ZVARCP01。backup-active/restore-active 共用 copy_new。缺失/重复/未知参数、非规范 hex/height、相对路径与错误 profile 拒绝；活动成功 JSON 的 replay_verified 为 true，而 finality_verified/validator_ready/real_funds_allowed 保持 false，错误文本不泄漏路径。

旧 CLI 分支、旧成功 JSON、ZVPRCP01/ZVPSEG01 和索引语义未改。recovery.rs 仅导出新的独立模块。Go CopyStorageAtCheckpoint 仍先拒绝非 LegacyJournal；没有新增网络恢复入口或钱包/签名状态恢复能力。

与阶段 base 比较，工作流、scripts、Go/internal/cometbft、Cargo/go 依赖、lib 固定参数、cache 容器、Replay、TestGenesis、旧 segments/namespace 均无 diff。与 C4 比较，归档核心、全部既有归档/CLI/增长测试逐字节相同；没有减少三次 replay、删测试、改并行参数或放宽预算来获得成功。

## 实际检查、未执行及限制

实际执行了 Git 身份/15 blobs/工作树/manifest 摘要核对、全阶段源码与调用方读取、C5 原生诊断及 C6 hunk 比较、旧授权测试非注释行比对、protected paths 比对、官方 API 合同核对、diff --check。辅助独立任务 `/root/p2_archive_review/ci_cancel_timing` 对准确 C6 的 wire/cache/新真实隔离测试与文档重新只读审查，反馈无 blocker；已完整读取反馈，未替代本代理全阶段审核。

full base..C6 的 diff --check exit 2，唯一诊断仍为冻结 `ACTIVE_ARCHIVE_V1.zh-CN.md:185` 的 EOF 额外空行；source/test 范围和 C5→C6 范围均 exit 0。没有将此说成全范围无诊断，也没有修改冻结设计。

我未在本地执行 cargo fmt、Clippy、编译、Rust/Go test/vet/race/fuzz、CI rerun 或 C6 完整 native 验收。新候选全部必需 23 个逻辑 gate 应由原生验收独立逐项核查 source/tree、命令完成、测试结果及后续步骤，不接受旧候选或取消 job 的部分成功替代。

C4 开销诊断保持原 11451 B / `d85901f61ea58ff5e068ae666af9fa4f4bf371efdc34687a0b839f04623260d8`；勘误单列 race raw 已成功 1.326s、步骤随后取消、后续未完，不改原文，也不对 C6 授信。C1/C3/C4 审核与 addendum、两份已冻结设计审核原件均保留，摘要列于 observation。

边界仍是可信父目录/OS/文件系统，不防任意瞬时恶意替换再还原。2048 段加 genesis/目录及重放 clone 的句柄成本、完整历史/状态内存、公共 key 常驻、冷初始化/构建 panic 未测、全容量/真实磁盘满/断电/Windows 目录持久化未测均明确。P2 不据此称完整验证者恢复或生产可用；NO-FUNDS 和外部安全审计未完成的状态保持。

本报告只批准上述准确 C6 的代码审核范围。后续任何运行代码或测试变化都需新提交复审。阶段是否可接受还取决于准确 C6 原生矩阵的独立完整验收；当前本报告的 stage_accepted 为 false。
