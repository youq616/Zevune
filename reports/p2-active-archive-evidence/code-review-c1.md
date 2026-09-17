# P2 活动归档与完整恢复：C1 独立代码审核原文

审核任务：`/root/p2_archive_review`。记录时间：2026-09-17 08:23:10 UTC。

结论：**PASS — 准确 C1 的独立代码审核通过。** 本次未发现需要修改该候选运行代码或测试的阻断问题。此为非作者代码／测试设计的静态审核结论，**不表示编译、格式、Clippy、Ubuntu／Windows 原生运行或阶段验收已经通过**；这些 CI 条件仍待单独确认，尚不可仅凭本文合入。

## 准确候选与独立性

- 仓库：`youq616/Zevune`；[PR #13](https://github.com/youq616/Zevune/pull/13)。
- Base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`。
- Base tree：`5e039b41e00f7a0a2e78937c796a40fbe68bfb0c`。
- Source head：`c5f60ac440ac39032f8f8efefc2fbfbf6e299a90`。
- Source tree：`10fb6d729c610aa1c935c96891c99e05f81d7dd1`。
- 本地 HEAD、tree、唯一父提交和干净工作树均已实际核实。逐项读取十个变更文件的 Git blob，确认工作树字节、长度、SHA-256 与 `candidate-c1.json` 一致；它们也全部与预检结束时保存的字节观察一致。
- 冻结设计为 `docs/ACTIVE_ARCHIVE_V1.zh-CN.md`，13188 字节，SHA-256 `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee`，与先前独立设计 PASS 对象相同。
- 本任务未编写或修改候选设计、实现、测试、工作流和依赖；仅创建仓库外审核原件。未把作者预检、测试内容或另一轮测试当作独立审核。
- 精确字节观察保存于 `code-review-c1-observation.json`，5942 字节，SHA-256 `1ccd3f9c3b8f7c785f26e578222d18aec07b84516b0e409af4cf53edf4ee4898`。

## 审核范围

完整复核 base..C1 变更、全部新增文件以及有关的既有调用方和边界，包括：

1. `pool.rs` 普通活动打开与共享 `replay_active_handles`；原 State 初始化、摘要、真实执行及 Replay 失败状态行为。
2. `pool/active.rs` 读写／只读打开、根锁、目录和文件保留、物理头解析、布局摘要、有界原字节复制、真实 EOF、逐帧边界、规范轮换、失败 reader 和原 append 路径。
3. `pool/recovery/active.rs` 新 pin codec/bounds、pin 导出、只读归档、反复验证及 copy_new 全部成功和错误返回路径。
4. `zevune-pool-recovery.rs` 新旧命令参数分派、可信 genesis/profile、CLI 输出及失败处理。
5. 新核心与 namespace 测试、`active_recovery_cli.rs`，以及真实付款增长 fixture 中新增的两次归档／恢复和重算摘要的坏签名测试。
6. 既有 `recovery.rs`、`segments.rs`、`namespace.rs`、`replay.rs`、`testnet.rs`、`wire.rs` 的实际权限、锁、验证器缓存和 legacy 合同。
7. 现有 funded 工作流及 `run_funded_rust.py` 的目标发现机制，确认新增 funded CLI 测试可进入既有 interfaces cohort；未将阅读工作流等同为实际执行。

## 实质核对结果

### 可信身份、profile 与真实重放

普通 `PoolStore::open_with_profile` 仍根据独立的预期 initial commitments、签名域和活动 profile 构造准确预期 genesis 头。活动文件打开保留原准确头字节检查；随后把该预期头的 SHA-256 传入共享重放函数。

`replay_active_handles` 先通过 `ActiveJournal::read_header` 在物理 genesis 文件中解析，明确要求真实头长与捕获物理长度相等、实际 EOF 和前后 namespace 检查。逻辑 reader 再读取的头必须与物理解析结果一致。实际重建的 State.genesis 还必须匹配调用者提供的 `expected_genesis`，因此不会仅相信早先读取过的可变文件头。

普通打开、导出 pin 和归档验证分别传入独立预期头摘要、原 committed State.genesis 和独立 pin.genesis。新 `retained_replay_binds_the_independently_expected_genesis_after_a_same_length_change` 测试通过原持锁句柄改变同长 genesis，要求共享重放明确返回 Genesis，并检查导出失败后 committed state 未被替换、store 不可用。这个测试不会由 Windows 的第二句柄读锁失败代替所需绑定检查。

共享重放每次构造新的 `AuthorizationVerifier::new()`。已核对该构造同时创建空的 `VerifiedCache`，没有继承旧 store 或另一个归档的成功授权缓存。Replay 仍逐块执行真实授权、域、历史根、防双花、输出、费用与状态摘要规则，并在每条记录后调用 `ActiveJournal::validate_frame`。原 Replay 在任何错误后丢弃未发布 State，finish 只在完整 EOF 后返回；没有导入状态或接受模拟验证器。

### pin 边界与精确物理布局

`ActiveRecoveryCheckpoint` 字段私有；准确 128 字节和 `ZVARCP01` 在切片转换之前检查。三个摘要非零、高度／总字节／头长／段数上限、头长步长、零高度关系以及记录字节下界和段容量上界全部落实。来自输入的减法和乘法使用 checked 运算；固定常量的乘积不承载不可信输入。

`layout_hash` 实际编码为 `ZVARLY01`、u32 头长、原头字节、u32 段数，再依次追加 u32 段序号、u32 实际捕获长度和原段字节。段序号与段长转换受既有私有 inventory 和 1 MiB 边界约束；没有让输入路径、文件时间或另一种逐段 hash 编码替代文档合同。每个文件通过 64 KiB 缓冲、明确偏移、捕获长度、实际 EOF 以及末次类型／长度检查读取，摘要前后还核对全部 namespace。

独立 Python hashlib 复算的固定向量与 C1 测试常量相符：76 字节 genesis 摘要 `07782393f4021cabba3a8a09f0d2747e6ae4404457475c6e9df85100f734bc1e`；92 字节布局输入摘要 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`。这项实际执行仅为静态向量复算，不是 Rust 测试执行。

### committed state 与导出错误行为

`active_recovery_checkpoint` 在读取前取得现有 committed Summary，前后执行完整布局字节检查，中间以独立原 genesis 重新执行历史，再比较完整 Summary 以及逻辑长度。导出不消费 PreparedBlock、不发布重建 State，也不改变成功路径中的预留或 committed state。

legacy 请求在操作前明确返回 Bounds，健康 store 保持可用。活动文件身份／历史／字节错误使 store 按既有模式不可用。测试分别覆盖健康 profile 拒绝后的原 PreparedBlock 继续提交，以及同长有效但不同历史被外部写入时拒绝导出和不发布替代状态。

### 锁、源只读和原目标句柄验证

普通活动打开继续使用读写句柄和 genesis 独占锁。`open_readonly` 使用只读文件句柄与 genesis 共享锁，保持根目录与所有原文件句柄；多个归档读取者可共享，合作 writer 的独占根锁与之冲突。没有先打开可写 PoolStore 再解锁重开，也没有在已持锁句柄的克隆上重复加锁。

`copy_new` 的目标目录和每个文件均只创建新对象。目标 genesis 在任何字节复制之前获得独占锁；所有段复制后保留原创建句柄。`checked.verify()` 的完整状态重建、字节和 namespace 检查直接使用这些拥有句柄，未通过另一次路径 open 绕开 Windows 锁。私有 `checked` 可持有创建时的写句柄，但不向公共 API 返回可写 PoolStore 或 State；返回值仅为原 pin。

`read_header` 对克隆句柄 rewind，摘要和复制使用明确偏移；调用串行运行。既有 append 仍显式 seek 到已确认尾部，所以 Windows 克隆共享游标不会成为隐式读写位置前提。此结论不扩大为并发读取写入快照能力。

### 创建顺序、源内目标和最终检查

公共复制首先检查源的保留名称绑定，然后检查绝对目标、canonicalize 已存在父目录与源、拒绝源内父目录及已有目标，接着完整验证源，最后才创建任何目标。父目录别名在创建前解析；持续替换的源会在最初 namespace 检查失败，不能把被移动的旧句柄伪称成同名源。

复制后先完整验证目标，再次完整验证源，最后检查目标全部原字节与 namespace 才返回成功。两处末次检查不是只比较长度或缓存元数据。Unix inode/device、多硬链接拒绝与 Windows 不共享 DELETE 的原语义保留。

### 失败确认、CLI 与兼容

所有目标写入和同步错误都通过 Result 传播，不删除、截断、覆盖或重试新目录。部分写入、最后文件写完但尚未同步、文件／目录同步完成后丢失确认以及末次源／目标 namespace 变化均有私有 cfg(test) 故障路径。完整可见字节的测试没有被描述成真实断电持久性保证。

新 CLI 明确分为 checkpoint-active、backup-active、verify-active、restore-active。checkpoint-active 要求独立固定的 03 TestGenesis 和准确可信 height/AppHash；另外三个操作使用独立新 pin，备份和恢复调用同一个 copy_new。缺失、重复、未知参数，错误长度／magic／hex，非规范高度和相对路径在分派或解析处拒绝。

活动成功 JSON 通过 stdout 的 write_all 和 flush 输出；回执写失败返回非零，保留可能已经完整创建的目标。新实际 CLI 测试把有效继承的只读 OS 文件句柄用作 stdout，验证此失败边界。旧命令分支与旧成功 JSON 没有重解释；旧 pin、旧分段备份、旧索引及 legacy 容量保持独立。Go、共识、IPC、依赖和工作流没有候选变更。

## 测试设计审查与未执行部分

新单元测试同时覆盖准确 pin codec 和结构极值、所有截断／尾字节、独立固定向量、零段创世、字节完全相等复制、PreparedBlock 保存、健康 legacy 拒绝、同长头及历史改变、物理头不能借用段字节、重新 pin 的跨帧／提前轮换／错后状态／尾字节。布局负面样本先通过实际生产 layout hash 比较，再要求明确拒绝，避免把错误摘要提前拒绝冒称更深层验证。

真实坏签名样本在 existing funded flow 中修改付款 binding signature，重算 record checksum 和整个新 pin/layout hash；正常活动打开和 ActiveArchive 都明确要求 Authorization 拒绝，并有未修改原样本成功控制。这是实际真实授权测试代码，没有跳过 verifier。

真实增长 fixture 保留原正常提交、选择、预算、容量、余额、重复拒绝和状态断言，新增第一次付款造成实际 1 MiB 轮换后的完整备份／恢复，以及 10001 高度的再次完整备份／恢复。恢复目录通过正常活动打开，后续第二跳付款及继续 10002 走原代码。空块仍只为增长和分段边界定位，不计为相同数量的真实付款。

独立 CLI 测试另覆盖低高度非零付款经实际可执行文件归档／恢复，收款人首次从恢复目录扫描后再花费；还有准确 pin、新旧命令互斥、已存在／源内目标、损坏源在创建前拒绝及回执失败。namespace 测试有实际双进程锁和 drop 后控制、只读源、Unix 文件／目录持久替换及父别名、Windows 真实 rename/delete 拒绝及最后读者 drop 后正控制。

本审核没有执行 cargo test/build/fmt/clippy、Go test/vet/race/fuzz、原生 Windows 测试或 CI。没有安装工具链或重跑旧测试。上述描述确认的是测试的实际调用和断言设计，不记录任何未执行测试为通过；C1 的准确原生日志、执行计数、退出结果、完整既有 cohort 和最终 CI 接受仍须单独核实。

## 非阻断观察与实际检查

1. **Informational — 冻结设计文末空行。** 对完整 base..C1 执行 `git diff --check`，实际退出码为 2，唯一诊断为 `docs/ACTIVE_ARCHIVE_V1.zh-CN.md:185: new blank line at EOF.`。该空行已经属于通过独立审核的准确设计原件，不影响运行、编码或合同，不要求为此解冻设计。不得把完整范围该项检查描述为无诊断通过。
2. 排除该冻结设计文件后，同一 base..C1 的源码／测试 `git diff --check` 实际退出码为 0。
3. 十个文件的 Git blob、工作树、候选清单逐字节匹配，工作树干净。`.github`、scripts、internal、integration/cometbft、Cargo.toml/Cargo.lock、go.mod/go.sum、AGENTS 和 STAGE_REVIEW 等被检查路径与基线无差异。

未发现新的功能性 blocker；没有用忽略测试、扩大预算、降低真实验证或改变设计来关闭问题。

## 结论的边界

本次 **PASS_CODE_REVIEW** 只适用于 head `c5f60ac440ac39032f8f8efefc2fbfbf6e299a90`、tree `10fb6d729c610aa1c935c96891c99e05f81d7dd1`。若运行代码或测试发生修改，即使是格式修正，也需要在新准确提交上核对差异和当前审核适用性。

独立 pin 不证明最新高度或共识终局。可信父目录、OS、文件系统、句柄／内存资源成本，以及 Windows 目录持久化、真实断电／磁盘满、全容量、增量／快照、钱包和完整验证者恢复等未覆盖范围保持冻结设计说明。本文不是零缺陷承诺、生产验收或外部机构密码学／安全审计。

**本次独立代码审核通过；阶段验收仍等待 C1 的必需原生 CI 与其他合入条件。**
