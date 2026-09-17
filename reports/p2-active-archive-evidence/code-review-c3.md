# P2 活动归档与完整恢复：C3 独立完整代码审核原文

审核任务：`/root/p2_archive_review`。记录时间：2026-09-17 08:32:06 UTC。

结论：**PASS_CODE_REVIEW — 准确 C3 的独立完整代码审核通过。** 已对本阶段完整变更、现有调用方和测试设计重新核对；此前活动归档“交换两个已有段”的测试覆盖阻断 **AR-C1-01 在 C3 代码与测试设计层面关闭**。本次未发现新的代码审核阻断。

本结论不等于 C3 的原生 CI 或阶段验收通过。审核者没有执行 Rust/Go 编译测试、cargo fmt、Clippy 或原生平台运行；C3 的准确原生结果仍需独立验收。C1/C2 的历史失败和原审核原件保留，不把旧候选或部分检查转为 C3 的执行通过。

## 候选身份与独立性

- 仓库：`youq616/Zevune`；[PR #13](https://github.com/youq616/Zevune/pull/13)。
- 阶段 base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`。
- Base tree：`5e039b41e00f7a0a2e78937c796a40fbe68bfb0c`。
- C3 source：`7045af4ae254f0a5a5e4810f17004c91e649e474`。
- C3 tree：`4017bee976c18767ed568d7ec8a33f6d668b8c22`。
- C3 唯一 parent / C2：`7477d9e0656ed751f525a4b6fe9f6649b995ede6`。
- C2 parent / C1：`c5f60ac440ac39032f8f8efefc2fbfbf6e299a90`；C1 parent 为阶段 base。
- 冻结设计：`docs/ACTIVE_ARCHIVE_V1.zh-CN.md`，13188 字节，SHA-256 `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee`，与先前独立设计审核对象相同。

已独立核实本地 Git 提交／树／父链，逐一读取全部十个变更文件的准确 Git blob，确认工作树原字节、长度、SHA-256 与 C3 清单一致，并记录干净工作树。身份及检查详情见 `code-review-c3-observation.json`：7955 字节，SHA-256 `2a21882b231dbd935b57057e3325fe9fcadf0532d9f3b52946d537b66707d0a1`。

本任务没有编写或修改候选设计、实现、测试、工作流或依赖，只创建仓库外审核原件。C1 的静态审核没有自动继承为 C3 PASS；本次重新审查完整恢复流程、权限、状态边界及全部变更的测试职责，并核对 C1→C2 的格式修订与 C2→C3 的代码／测试变化。

## 历史阻断与 C3 关闭核对

### AR-C1-01：活动归档的两个既有段交换

严重性：Medium / 固定验收覆盖缺口。C1 原初审未指出此项，由另一独立审查提出，本任务在补充记录中确认。它不是已证实的运行接受漏洞，但不能用旧 `ZVPSEG01` 的交换测试替代新的 ActiveArchive 路径。

C3 在 `real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` 中，复用真实正常提交到 10001 的两段原始文件。前一段来自原空块增长，后一段含触发生产 1 MiB 轮换的真实非零付款及后续历史。测试没有制造模拟记录，没有修改实际 source，未增加证明跳过或降低容量。

新增部分按顺序实施以下检查：

1. 把两个实际已存在段的完整原字节互换到另一个新目录，保留各记录原 body/checksum；使用原 pin 打开，明确要求 Corrupt。
2. 检查原 source 与错误候选的实际每个文件字节保持不变。
3. 重新按外部 pin 规范构造匹配新布局的 pin，确认它不同于旧 pin。
4. 用实际 `ActiveJournal::open_readonly` 与生产 `layout_hash` 验证重算摘要确实等于 pin 的 96..128 字节，而非仅用测试辅助函数自行相等；之后显式 drop journal 与根共享锁句柄。
5. 解码交换后首个完整真实记录，确认它的高度为首次付款高度，并明确证明其 base_hash 不等于独立 genesis.initial_summary 的 AppHash。
6. 再以匹配布局的新 pin 调用公共 `ActiveArchive::open`，明确要求 Corrupt，随后再次检查原 source 与错误候选字节不变。

已按实际代码核对拒绝层：原 pin 在布局完整性匹配处拒绝；新 pin 通过生产布局摘要检查后，第一条记录的前状态与 genesis 不匹配，进入真实历史重放拒绝。这不是 Authorization 拒绝，也不能冒称坏签名测试；坏签名的独立测试仍要求 Authorization。显式释放临时锁及使用实际副本避免 Windows 锁失败造成错误的“交换已拒绝”证明。

因此本项缺口在代码与测试设计层面关闭；是否实际执行通过，仍以 C3 原生 funded-library 日志中该完整测试的结果为准。

### C1 格式失败与 C2 Clippy 失败

已读取 C1 30 个 rustfmt 差异及七个文件的实际 C1→C2 修改。它们改变排版、等价 match arm 表达形式及调用换行，没有关闭格式检查、跳过测试或改变冻结设计。已保留 C1 native 失败，不将其静态代码 PASS 当作可合入凭据。

已读取 C2 原生日志 `c2/job-105130677319.log`，SHA-256 `67fa4d451492b8958ee1750e81c6a2fd261dea5cdf326048fc87de5ba916375c`。该日志在 `bash -e` 步骤中完成 cargo fmt 和 metadata 后进入 Clippy，由 `clippy::manual_is_multiple_of`、`-D warnings` 导致 exit 101。对应建议与 C3 修订一致。

C3 将 `(header - MIN_HEADER) % 32 != 0` 改为 `!(header - MIN_HEADER).is_multiple_of(32)`。被减数仍由前一个短路条件限制在合法头长范围，除数固定为非零 32；合法输入的判定及非法头长的提前拒绝不变，没有新增 underflow 或零除数边界。`-D warnings`、工具链、依赖与工作流均保持原样。该源码修正已审查，C3 的实际 Clippy 和格式成功仍不可由 C2 历史结果推定。

## 完整运行流程审核

### 独立身份与真实重放

普通 `PoolStore::open_with_profile` 从独立 initial commitments、签名域和固定活动 profile 构造预期头，并保留实际头字节精确检查，再将预期头 SHA-256 传给共享 `replay_active_handles`。归档传入独立 pin.genesis；pin 导出传入已有 committed State.genesis。调用者身份没有由待恢复目录自行替换。

共享重放先独立解析物理 genesis，只允许在其捕获物理长度内读取，检查真实头长完全相等及实际 EOF，再检查逻辑读取头与物理解析结果一致。实际重建 State.genesis 必须匹配调用者 expected_genesis；不是只相信一次早先文件读取。测试通过原持锁句柄改写同长 genesis，要求 Genesis 拒绝并保持既有 committed state，避开 Windows 第二句柄读锁干扰。

每次共享重放新建 AuthorizationVerifier；其实际构造创建新的空 VerifiedCache。重放仍调用原 State::from_storage_policy 和 Replay，对全部记录执行真实授权／签名域、历史根、防双花、输出、费用及逐块状态摘要规则。没有承载可写能力的 State 或未完成历史被提前发布。

每条实际完整记录都调用 `ActiveJournal::validate_frame`，继续拒绝跨物理段拆帧和非规范提前轮换。每个文件捕获长度后的真实 EOF、整个逻辑 EOF、finish 前的错误 State 丢弃及最后 namespace 核对均保留。新归档没有用一般串流拼接掩盖活动物理格式。

### pin、布局摘要与导出状态

新 `ActiveRecoveryCheckpoint` 保持私有字段、128 字节独立 magic、三个非零 hash，以及准确转换前的长度判断。高度、总长、头长、头长步长、段数、零高度关系、最小记录帧累计及段字节容量均有界；输入相关乘法和减法使用 checked 运算。

布局编码保持固定 `ZVARLY01 || u32头长 || 原头 || u32段数 || 逐段(u32序号 || u32长度 || 原字节)`，没有替换成另一套 hash 列表、路径或时间元数据。逐段 u32 转换受实际私有 inventory 与 1 MiB 约束；每个文件通过 64 KiB 缓冲和明确偏移读取，捕获长度、真实 EOF、元数据及前后 namespace 全部参与检查。

`active_recovery_checkpoint` 在前后布局字节检查之间完整真实重放，核对整个 committed Summary 和逻辑长度，最后构造并检查 pin。它不消费 PreparedBlock、不写原账本、不发布替代 State；真实历史／身份错误使 store 不可用。legacy 不支持请求在存储操作前返回 Bounds，不使健康 legacy store 失效。

先前独立 Python 复算的固定 genesis／布局向量及 C3 输入与实现已再次核对一致：76 字节头摘要 `07782393f4021cabba3a8a09f0d2747e6ae4404457475c6e9df85100f734bc1e`，92 字节布局输入摘要 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`。没有将此静态字节计算当作 Rust 测试执行。

### 只读源、根锁和原创建句柄

普通活动 store 继续使用读写句柄与 genesis 独占锁；归档源使用只读句柄与根共享锁。根目录和所有文件句柄保留到对象销毁，多个读者可共存，合作 writer 的独占根锁被拒绝。没有先打开 writer 再释放／重开成 reader，也不对已经持锁的克隆重复加锁。

目标目录非递归新建，文件使用 create_new；Unix 权限保持目录 0700、文件 0600。目标 genesis 在第一次字节复制前获得独占锁，段按原顺序精确复制并保留原创建句柄。所有文件 sync_all 后，Unix 同步目标目录和父目录；Windows 不伪造等价目录持久化能力。

目标 `checked.verify` 用原创建且持续持锁的句柄完成完整验证，不 unlock/drop 后再次路径 open。私有目标对象可以持有创建写句柄，但公共 copy_new 仅返回 pin，没有返回可写 PoolStore、State 或节点启用能力。成功及错误返回靠所有权释放句柄，测试包含失败后的显式重新打开和锁释放控制。

克隆的共享游标没有成为依赖偶然顺序的输入：物理头解析 rewind，摘要和复制显式偏移，所有流程串行；既有 append 仍显式 seek 到确认尾部。此实现没有声称并发读取／写入快照能力。

### 路径、复制顺序与失败确认

copy_new 先核对源路径和保留句柄绑定，再检查绝对目标与已存在父目录、canonicalize 可信父目录及源，拒绝源内／父别名目标及任何已有目标；完整源 verify 成功后才创建新目录。Unix device/inode、多硬链接拒绝及 Windows 不共享 DELETE 的名称保留语义不变。

复制完先完整验证目标，再完整验证源，最后核对目标的全部精确字节与 namespace，才返回原 pin。没有用长度／时间当成身份或旧缓存 metadata 当成末次确认。源的持续替换在目标检查之前被拒绝，不能认证脱离路径的旧句柄为当前同名源。

失败不删除、截断、覆盖、修复或自动重试新目标。私有 cfg(test) 分别覆盖部分 genesis、部分段、末文件写完未同步、同步后丢失确认以及最终源／目标 namespace 改变。完整可见字节允许后验验证，但未被当成真实断电证明。原源文件和 PreparedBlock 状态的非变更断言仍在。

### CLI 与旧 API 边界

四个新活动命令明确选择新类型；checkpoint-active 先固定 03 TestGenesis/profile 和可信准确 height/AppHash，另外三条通过独立新 pin；备份与恢复共用同一 copy_new。严格选项集合、重复／未知参数、绝对路径、准确小写 hex 和规范高度检查保留。

活动成功回执使用 stdout.write_all + flush，失败返回非零且不删除已经完成的目标。实际 CLI 测试使用继承的只读 OS stdout 句柄，检查完整目标仍可显式验证、原 source 不变及后续不能覆盖。错误文本不回显用户路径。

旧命令分支及成功 JSON 保持，旧 ZVPRCP01、ZVPSEG01、旧派生索引与 legacy 容量没有扩宽或重解释。旧 recovery.rs 的候选变化仅增加独立模块导出；Go 网络恢复、IPC、共识、交易、真实验证器、状态算法、依赖与工作流没有对应变更。错误 profile 不能变成迁移或验证者恢复。

## 测试职责与未执行边界

已复核新核心测试、namespace 测试、真实增长 fixture、真实坏签名重算样本及实际 CLI 测试的调用路径。它们覆盖 pin codec/边界、创世零段、逐文件精确复制、恢复后继续提交、PreparedBlock、同长身份／历史改变、物理头边界、真实帧/规范轮换/交换、错后状态、坏签名、路径和锁、失败确认及旧新 API 隔离。

真实付款增长路径两次完整 backup→restore 后通过普通活动 PoolStore 重放，在恢复目录中继续真实第二跳付款和 10002 提交。CLI 另有低高度真实非零付款恢复后的收款人首次扫描及再花费。原空块增长仍仅用于存储边界，不被称作同数量真实付款或 TPS。

namespace 测试保留实际双进程 writer/reader 冲突、多个共享读者、只读源、失败打开释放句柄、Unix 文件／目录持续替换及父别名，以及 Windows 真实 rename/delete 拒绝与最后读者 drop 后正控制。Linux 静态阅读不替代 Windows 实际运行。

读取 existing funded cohort 调度器确认新 CLI 目标会由 Cargo metadata 纳入 interfaces；没有针对新增测试添加过滤或默认跳过，也未缩减原全套门槛。但本任务没有执行任何 Rust 或 Go 测试、编译、cargo fmt、Clippy、原生 OS 测试或 CI，也没有安装工具链。测试代码存在及静态审查不能记为执行通过。

## 实际检查、非阻断观察与最终范围

实际执行了 Git 身份／父链／blob／工作树核对以及 base..C3 whitespace 检查。十个变更文件与 C3 清单完全一致；被核对的 `.github`、scripts、internal、integration/cometbft、Cargo.toml/Cargo.lock、go.mod/go.sum、AGENTS 和 STAGE_REVIEW 均与阶段 base 无差异。

完整 `git diff --check base..C3` 实际退出 2，唯一诊断仍为冻结设计第 185 行 EOF 空行；排除此冻结设计文件的源码／测试范围退出 0。该设计原件不改动，空行不影响合同与功能。不能把完整范围表述成完全无诊断，亦不要求为此解冻设计。

C3 代码审核的活动覆盖阻断计数为 0，AR-C1-01 已在代码与测试设计层面关闭。C1 格式失败、C2 Clippy 失败保留为历史；C3 的独立原生证据、当前各工作流及实际执行完成状态仍须单独审核。

本结论只适用于 source `7045af4ae254f0a5a5e4810f17004c91e649e474`、tree `4017bee976c18767ed568d7ec8a33f6d668b8c22`。后续代码或测试变动需要新准确提交的独立复核。

可信父目录／OS／文件系统、恶意瞬时替换再还原不在保证内；独立 pin 不证明最新高度或共识 finality；完整历史与句柄成本、真实断电／磁盘满、Windows 目录持久化、全容量、增量／快照、钱包及完整验证者恢复等限制保持。本文不是零缺陷承诺、生产验收或外部机构安全审计。

**最终结论：C3 独立完整代码审核 PASS；阶段验收仍待准确 C3 的必需原生 CI 及其他合入条件完成。**
