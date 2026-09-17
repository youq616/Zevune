# P2 活动归档追加关系与增量计划：独立设计审核

结论：**PASS_DESIGN（设计通过；无阻断发现）**。

本结论仅允许按本设计推进实现，不是代码通过、原生测试通过、阶段验收或合入批准。
本轮交付为双独立可信 pin 下的只读追加关系核验和字节计划；没有增量包写入或恢复能力。

## 身份与冻结对象

- 审核任务：`/root/p2_incremental_design_review`。
- 作者关系：独立非作者任务，未编写或修改该设计、既有实现或后续候选。
- 工作目录：`/workspace/scratch/1753b04c9dbb/Zevune`。
- 本地基线 HEAD：`0927af157a3cc35abde14b036bc50a99a793a32b`。
- 本地基线 tree：`e04479cf7723588885573be2112635efa30e27cc`。
- 被审核设计：`docs/ACTIVE_INCREMENTAL_PLAN.zh-CN.md`。
- 设计原件：**8,604 字节**。
- 设计 SHA-256：`0234062797e5436cbccb307db50655b2b7a50f48046ccb91824e9dabc2e93193`。
- 身份及基线字节机械核对时间：`2026-09-17T13:39:12.674765+00:00`。
- 最终设计全文重读和窄差异核对时间：`2026-09-17T13:42:21.733544+00:00`。

审核期间作者将 JSON 首字段明确为 `format:"zevune-active-incremental-plan-1"`。
已独立验证旧原件为 8,589 字节、SHA-256
`596ca0fdfdefbdbdfc1f242ecec2bed08e745bc362669b021bd31f2a5c0d84aa`，与最终原件只有
这一行替换，其他全部字节保持；新原件全文已重新阅读。本正式结论只绑定上述最终
8,604 字节设计。作者保存的旧原件位于同级证据目录的
`design-v1-before-format-clarification.md`，不是当前批准的设计版本。

审核开始时 `git status --short` 仅列上述未跟踪设计文件；`git diff --exit-code` 成功。
本审核将 15 个所读基线文件逐一与 `git show HEAD:<path>` 比较，全部逐字节一致。
设计是未提交原件，不能为它填写不存在的候选 commit/tree；未来代码候选必须单独冻结和审核。
本任务仅核对本地 Git 身份，没有查询 GitHub API，也不将远端身份核对归为本审核完成项。

## 实际阅读范围

完整阅读 `AGENTS.md`、`docs/STAGE_REVIEW.zh-CN.md`、新设计、
`docs/ACTIVE_ARCHIVE_V1.zh-CN.md`、`pool/recovery/active.rs`、`pool/active.rs`、
`pool/recovery/segments/namespace.rs`、`bin/zevune-pool-recovery.rs`、
`recovery_index_output.rs` 和 `Cargo.toml`。

另外阅读了 `pool.rs` 的活动 open 及 `replay_active_handles` 完整调用路径，
`pool/replay.rs` 的真实头解析、EOF 和有界记录读取，`wire.rs` 的固定公共验证密钥、
新实例缓存及真实授权验证路径。测试阅读重点为已有活动归档 fixture 与独立 repin 辅助，
真实付款强制 1 MiB 轮换、10001 高度归档及恢复后继续提交、重算摘要的坏签名拒绝，
CLI 真付款归档/恢复/再花费，以及真实只读 stdout 句柄探针和可写正对照。
同时检索了已有 namespace/锁/替换测试入口。没有把只检索到的测试名字记为已执行证据，
也没有宣称读完全部既有测试文件或整个仓库。

关键基线原件摘要：

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `docs/ACTIVE_ARCHIVE_V1.zh-CN.md` | 13,188 | `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee` |
| `integration/orchard/src/pool/recovery/active.rs` | 10,383 | `77f47005568fad097edd6f563d3e1d0962957fe932dbd8565b0b4126ebe75137` |
| `integration/orchard/src/pool/active.rs` | 29,276 | `62f470f20534a649b04b0f08f538782b927a7e446172c4f5b397f5057f061586` |
| `integration/orchard/src/pool.rs` | 29,054 | `0faf50b4f90f61a3ef48baf0fceed47d8c7f13719378fd03905498faab99af70` |
| `integration/orchard/src/pool/recovery/segments/namespace.rs` | 4,949 | `7927596f061d3d0fc4e05bf0f5cfd63d53cfdab4d382c1f10a2050c4689b3b3b` |
| `integration/orchard/src/bin/zevune-pool-recovery.rs` | 11,860 | `6cc4a79f85a2f909e48eca5adfd9f7c624afdeb1ca747c84d34dbffb858e775e` |
| `integration/orchard/src/pool/active_flow_tests.rs` | 34,453 | `4426a8b978649de8811a92ded3cf5957924b01db0600bb45af12c6d053796fce` |
| `integration/orchard/tests/active_recovery_cli.rs` | 27,543 | `03363db0cc52668e9aa6598fde23a1767827436ea7d553a0182ae740ed086959` |

## 设计核对结果

### 1. 可信来源、真实授权与状态不变量

通过。两个 pin 都必须独立可信，计划不把二者之间的关系当作来源认证，合法旧 pin 不证明
最新高度或共识 finality。两端均使用现有 ActiveSegmentsV1 的物理头和完整记录重放，
再将结果与各自 pin 的创世身份、高度、AppHash、逻辑长度和布局匹配。

当前 `ActiveArchive::verify` 在重放前后执行 `check_bytes`；后者调用真实布局摘要及
namespace/文件身份检查。`PoolStore::replay_active_handles` 先在单独 genesis 文件中
解析真实 03 头并要求物理 EOF，然后重建完整状态，逐条真实执行记录并调用
`ActiveJournal::validate_frame`。每次建立新的 `AuthorizationVerifier`，其缓存是
`VerifiedCache::default()`；复用的只有固定公共验证密钥。设计明确保留这些路径，
未引入摘要替代证明、外来授权缓存、状态导入、mock verifier 或免重放成功捷径。

返回对象只有两个 checkpoint、公开计数和范围，没有可写句柄、状态对象、钱包或签名状态。
失败不发布部分计划或部分认证状态，与当前失败关闭的归档边界一致。

### 2. 精确物理追加关系是否得到证明

通过。设 base 有 m 个段、later 有 n 个段。完整验证先保证两端各自是合法历史。
创世文件全字节相等，且 n 不小于 m；所有旧非尾段同索引、同长度、同字节；当 m 大于 0 时，
later 第 m−1 段的前 base 尾段长度个字节与 base 尾段完全相同。
因此串联的 later 前 base.length 个字节恰为 base 的完整历史，而且旧物理分段边界被保留。
新增字节只能处于旧尾段后缀和后续连续新段，不会把重新切段、历史记录改写或同高分叉
认证为增量追加。这里的“证明”是设计层面的逻辑推导，不是实现测试结果。

两端本身的真实重放和规范轮换检查使尾段截止于完整记录边界，也阻止跨段拆分一条记录。
无需再为计划发明独立交易解码器、记录摘要格式或快照状态算法。后续实现应重用现有的
底层 retained-handle 读取能力；没有必要把内部 File、可变 Segment 或 writer 能力公开。

同高仅完整内容一致可返回空计划，倒退拒绝，错误创世为 Genesis，互相不衔接但各自合法
的历史为 Stale。不同路径内容相同以及同一路径的两个独立只读实例均可全量验证后返回空计划；
字符串路径相等不能短路验证。不存在需要放宽此规则的正常追加情形。

### 3. EOF、短读、句柄游标与检查窗口

通过。现有数据句柄由 `ActiveJournal` 保留，设计禁止为了比较而通过用户路径重新打开。
`check_namespace` 仍绑定文件名、长度、常规文件属性和 retained 目录；Unix 有设备/inode
绑定，Windows 沿用不共享 DELETE 的句柄、重解析点拒绝策略。

新增比较必须让两侧独立完成一个固定长度块的读取；一次 `read_at` 成功返回较少字节是
合法 short read，不能拿两次 read 的返回长度不同当作内容分叉。Interrupted 应重试当前
偏移的读取，0 字节在声明长度前到达则失败。比较偏移必须显式指定，不依赖 clone 后的
共享游标，也不能给 later 较长尾段错误地施加 base 尾段处 EOF 的要求。

设计已正确要求 base 每个文件在捕获长度处达到真实 EOF。later 的完整 EOF、全部新增
字节和捕获长度由它自己的完整验证及末次全布局摘要覆盖。比较后对两端再次调用完整
字节/namespace 检查，可以发现检查期内留下来的内容或名称变化；仅重算计划新范围摘要
将不足以满足此合同。

共享 genesis 锁排除合作 writer，同路径两个读者不会要求互斥写锁；两端验证可以顺序执行。
这些步骤不形成任意恶意外部写者下的原子快照，也无法消灭最后一次检查到返回之间的一切
外部修改窗口。设计已经明确可信父目录、OS/文件系统前提及恶意瞬时修改再还原不在承诺内，
因此不存在未说明的通用快照能力声明。后续测试应报告实际持续变化拒绝或 Windows OS
阻止修改的结果，不能把未发生的修改写成“修改后被内容比较拒绝”。

### 4. 范围、计数和 JSON 数字边界

通过。总逻辑长度最大 1,073,741,824，段长最大 1,048,576，段数最大 2,048。
因此 index、offset、单范围 length 均可用 u32；总长度和差值保持现有 u64 表达最直观。
所有数字都低于 JSON 常见二进制 64 位浮点的精确整数范围，不存在把现有大整数不经处理
输出到 JSON 所导致的精度损失。实现仍必须用 checked 算术和显式转换，不能以这些
设计上界为理由在输入检查之前执行截断或无检查减法。

若旧尾段增长，产生最多一个旧尾后缀范围，其余范围与新段一一对应；当 m 大于 0 时范围数
不超过 1+(n−m)，当 m 为 0 时为 n，所以不超过 2,048。索引严格递增、排除零长度，且
非零 offset 仅在旧尾段，足以防止重复计量和遗漏。

令 G 为相同 genesis 长度，b_i/l_i 为两端段长。由于旧非尾段精确复用，范围长度和为
`(l_(m−1)−b_(m−1)) + sum(l_i, i=m..n−1)`（m=0 时只有后一项），正好等于
later.length−base.length。`reused_bytes=base.length` 正确包含 genesis 和尾段旧前缀。
`unchanged_segment_count` 仅统计完整不变的旧 journal 段，`new_segment_count=n−m`；
它们不应与复用字节数或 ranges.len() 混淆。

独立推导的示例（仅为规则算术检查，没有伪称真实执行）：genesis 为 76 字节，base 段为
[300]，later 为 [450] 时，复用 376、追加 150、范围 `(0,300,150)`，不变段 0、新段 0。
base 为 [1,048,500]、later 为 [1,048,500,150] 时，旧尾段不变，只列 `(1,0,150)`，
不变段 1、新段 1。base 为 [1,048,350]、later 为 [1,048,500,150] 时，尾后缀与新段
各 150 字节，总追加 300，不变段 0、新段 1。空计划所有原段均不变。

### 5. CLI 边界与资源成本

通过。新命令只读两个绝对归档路径和两个独立 pin，拒绝 output、隐式 base、自动最新
pin、旧格式与未知参数。现有参数解析器按命令核对完整键集合，实施时应将 `--base`
纳入绝对路径检查，在文件读取前解码并核对两枚 pin，沿用大小/数量约束及通用错误输出。

成功 JSON 不拼接用户路径和外来字符串；固定 operation/format、两个 256 字符 pin、
有界数字及布尔范围声明，适合一次完整构建后通过既有 `write_active_receipt` 写出。
它保留 `StdoutLock` 并复制安全拥有的 FD/handle 交给 File 写入，能够传播操作系统错误；
不能退回可能吞掉 EBADF 的 stdout 缓冲适配器。设计准确说明写出失败可能残留部分 JSON，
并没有声称所有失败都绝无输出。

最多两块 64 KiB 比较缓冲与有界范围数组是合理增量成本。两份归档各自的完整段句柄、
重放临时 reader 克隆和完整历史状态仍存在；本轮不宣称资源峰值、读盘次数或当前存储量
获得降低。只读字节核验不会要求 fsync 或目录持久化的新能力。

### 6. 验收方案与范围控制

通过。验收已列出零高度、空计划、尾追加、真实 1 MiB 轮换、各自合法的同高/更高分叉、
倒退、不同创世、链接/替换/额外项、打开后变化、重复调用重新验证及 stdout 实际错误。
特别是“各自验证成功的更高分叉”能检验真正前缀拒绝，不会只落在旧 pin/hash 或锁错误。

现有真实付款的跨段归档恢复和接收者继续花费流程可直接插入只读计划断言，保留原始
proof、签名、容量、状态及双花断言。对新增计划范围必须独立读取实际后缀并核对精确
长度/内容；只断言 ranges.len() 或 appended_bytes 大于 0 不足以完成设计验收。

原生 Ubuntu/Windows 的默认及 funded Rust、CLI、Go test/vet、受支持的 race/fuzz、
增长、资源和四节点回归仍须绑定最终准确候选。设计审核和基线已有成功均不能冒充这些
新候选运行证据。本轮范围窄且可复用现有边界，没有为只读计划新增增量包容器、状态导入、
后台任务或另一套证明/重放逻辑，未见过度设计。

## 非阻断实现提示

**DI-DESIGN-01（Low，接口明确性，已关闭）**：旧设计仅列格式值，未逐字列出承载该值的
键名。作者在最终 8,604 字节设计中明确首字段
`format:"zevune-active-incremental-plan-1"`，随后按原列表输出 operation 和其他字段，
与既有 `recovery_index_output.rs` 约定一致，歧义已消除。
请在代码/完整 JSON 断言中固定这个键及全体字段顺序。建议对整个输出使用 checked
容量估计、try_reserve 和完整渲染后再写，避免把已有 ranges 上限与 JSON 构建是否有界
当成两个互不相干的保证。此提示不要求更改可信来源、存储或协议设计。

**DI-DESIGN-02（Info，实际重放成本）**：现有 `ActiveArchive::open` 本身执行一次
verify。正常 CLI 打开两份归档后，再调用设计要求的 incremental_plan 内两次新 verify，
首个命令调用实际会有四次完整重放，而非两次。对已经打开的两个实例执行一次方法则
本次新增两次重放。设计没有承诺少于此成本，故不构成阻断；实现和验收报告应准确计数。
不能为了减少运行时间省去本次重新验证，或把上次成功的授权缓存移入本次调用。

## 未执行项与最终结论

本任务未运行 Rust/Go 编译、格式/Clippy、单元或集成测试、原生 CI、子进程实验、模糊测试，
也没有触发 workflow、提交、推送或合入。没有候选实现可供本任务认证；以上测试检查均为
阅读既有源码与评估新验收方案。未声称完成外部密码学/安全审计、1 GiB 全容量资源验证、
磁盘满、真实断电、Windows 目录持久化、长期多机或验证者签名状态恢复。

**最终结论保持 PASS_DESIGN，无开放阻断。** 允许按上述确切 8,604 字节设计推进实现；
实现候选的独立代码审核、实际原生回归和阶段验收仍待执行。
`incremental_backup_implemented`、`snapshot_state_import_implemented`、生产就绪和
真实资金相关标志不能因本次设计通过改为 true，P2 继续开发中。

本审核原文冻结后不修改；若确切设计合同或实现范围改变，应保留此原件并另行补充审核。
