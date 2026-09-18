# P2 持久增量包：非作者独立设计审核原件

结论：**PASS_DESIGN**。该结论仅允许以本文件确认的设计继续实现，不是运行代码审核、原生测试通过、合入许可、阶段完成或外部安全审计。未发现需要更改此设计文本后才可开始实现的阻断问题。

审核日期：2026-09-18 UTC。独立审核任务：`/root/p2_package_design_review`。审核者未编写本设计、实现或测试；本任务仅读取仓库与原始代码，写入仓库外审核记录。未修改仓库生产代码、测试、设计、状态、工作流或预算。

## 准确身份与审核材料

- 基线 commit：`2cc87a2207d502ac5cfe00ea52e525c1516917e5`。
- 基线 tree：`b5841120084a72c5948b0a2754f712e5f67ad602`。
- 设计文件：`docs/ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md`。
- 设计原件：13,361 字节；SHA-256 `b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41`。
- 当前候选类型：在该基线上新增、尚未提交的设计文件。本审核不指向一个已经冻结或发布的运行候选 head/tree。
- 本任务独立运行 `git rev-parse HEAD HEAD^{tree}`，结果与上述基线一致；开始审核时 `git status --short` 只有这一设计文件为 untracked。对下列源文件又按 `git show <base>:<path>` 逐字节比较，全部等于基线。
- 辅助读取范围清单：`design-review-scope.json`，4,612 字节；SHA-256 `ca79e53087baaa2526c4c65a3dffe25eb3385c971742e064ebb864ee52bb65ff`。该清单记录实际文件字节数、SHA-256、完整读取或准确的部分范围。它是审核者生成的材料目录，不是测试日志或远端 CI 证据。

完整亲读以下 18 个原文件。合并读取出现工具输出截断时，已单独重读 `active_flow_tests.rs` 全文及 `active_incremental_cli.rs` 的尾部缺失区，没有把缺失输出算作已读。

1. `AGENTS.md`。
2. `docs/STAGE_REVIEW.zh-CN.md`。
3. `docs/ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md`。
4. `integration/orchard/src/pool.rs`。
5. `integration/orchard/src/pool/active.rs`。
6. `integration/orchard/src/pool/active/incremental.rs`。
7. `integration/orchard/src/pool/recovery/active.rs`。
8. `integration/orchard/src/pool/recovery/active/incremental.rs`。
9. `integration/orchard/src/pool/recovery/segments/namespace.rs`。
10. `integration/orchard/src/pool/replay.rs`。
11. `integration/orchard/src/wire.rs`。
12. `integration/orchard/src/wire/cache.rs`。
13. `integration/orchard/src/bin/zevune-pool-recovery.rs`。
14. `integration/orchard/src/recovery_incremental_output.rs`。
15. `integration/orchard/src/pool/active_flow_tests.rs`。
16. `integration/orchard/tests/active_incremental_cli.rs`。
17. `integration/orchard/src/pool/recovery/active/incremental/tests.rs`。
18. `integration/orchard/src/pool/testnet.rs`。

另亲读 `integration/orchard/src/pool/recovery.rs` 第 1 至 230 行及 `integration/orchard/src/pool/recovery/segments.rs` 第 1 至 230 行，用于追踪 namespace 的 `regular` 真实来源、旧文件句柄打开/创建和 checkpoint 行为。没有声称完整审阅这两个文件的其余内容，也没有声称完整审核整个仓库、全部历史报告、GitHub 分支规则或所有工作流。

## 审核结果及依据

### 独立信任来源和授权

设计将两枚外部可信 ZVARCP01 pin 与包内字段区分清楚。包内的 base/later 字节仅供精确比对，不是获取真实性的来源。既有 `ActiveRecoveryCheckpoint::from_bytes` 只解析、限制物理容量并拒绝零关键哈希；既有 `ActiveArchive::open` 随后验证全部物理字节及完整真实重放。新 `open(package, &mut base, trusted_later_pin)` 必须在完整 package.verify 后才发布对象，符合这些既有职责。

没有公开可构造的计划、可变范围、File、State、PoolStore、导入缓存或跳过验证能力。`plan()` 与 `package_bytes()` 是历史描述；后续 verify/restore 必须从保留句柄重新核验，不能把此前成功视为可复用授权。调用者可以提供字节完全相同的另一个已验证 base 归档对象；身份约束应是准确 checkpoint 与持续检查的源句柄，不应要求某个内存地址或路径字符串相同。

我亲读了真实 `AuthorizationVerifier::new/verify` 及其缓存：新实例共享固定公开 circuit verifying key，但是每个实例新建空 `VerifiedCache`。真实 verify 在 canonical decode 后验证各 action 签名、binding signature 和 Orchard proof，再允许缓存记忆精确已验证字节。缓存命中仍不跳过状态层签名域、expiry、anchor、nullifier、output 与容量检查。设计要求 base 重放与组合重放各用新 verifier，符合这一权威边界。

组合验证从全量 base genesis 开始构建隔离 State，使用原 `Replay::next_block` 执行完整历史，最终比对 genesis/height/app_hash/length。既有 Replay 在失败时丢弃未发布 State，达到准确 EOF 后才允许 finish。设计没有通过 bytes/layout hash 代替真实授权，也没有让部分恢复状态向公共 API 逃逸。

### 物理格式与范围约束

独立重算固定长度：`8 + 128 + 128 + 4 = 268`；范围表上限 `268 + 12 × 2048 = 24844`。元数据有界、payload 流式读取，最外层物理长度先受限，所有差值、范围和偏移使用 checked 算术，合理约束了外来文件的分配和遍历成本。

旧 `ActiveIncrementalPlan::checked` 只检查旧尾 range.offset 非零，因为它的唯一生产调用来自 `visit_append_ranges` 对真实保留文件的全字节比较。外来包描述没有这一先验。新设计明确要求旧尾 offset 精确等于实际 base 尾长，并要求旧非尾整段复用、新段连续、range 顺序严格、全长/段数/sum 与 later pin 一致。这补足了接受外来范围所必需的条件。扩大 `checked` 的可见性不能代替这一步；它仍应只对池内受限模块开放。

真实 ActiveJournal 的布局哈希覆盖域标签 `ZVARLY01`、实际 genesis 长度与字节、段数以及各段 index/length/字节。设计将完整组合布局与独立 later pin 对比，因此在 base 已验证、组合布局严格唯一且前后覆盖全 payload 的条件下，无需额外添加可被误当作授权的 package checksum 或每范围 hash。

实际旧尾长度绑定和完整 base 复用令公开 `byte_prefix_verified:true` 有明确含义：重建历史包含精确的独立 base 前缀，later pin 约束完整重建布局。验证不需要已删除或离线的 later 目录。该字段不应被扩展解释为确认包的来源、最新 tip 或共识最终性。

N=0 的 268 字节同内容包也受两个 pin 完全相等、准确 EOF、完整 base 与完整组合重放约束。允许旧尾不增长而直接开新段是必要情形；是否规范轮转仍必须由真实首帧尺寸检查决定，不能仅根据 range 数量、段长或固定 chunk 猜测。

### 原解析器与物理边界保持

既有 `PoolStore::replay_active_handles` 先独立解析物理 genesis 文件，再从逻辑 reader 读取头，并比较 length/initial/signing_domain。若仅在组合 reader 上解析，外来创世 commitment count 可能试图从第一 journal 借字节。新设计明确保留双读和一致性检查，满足这一实际调用约束。

我亲读 `ActiveJournal::validate_frame`：每个真实 frame 的起止位置必须处于同一实际 segment；在非首段第一帧处，前段长度加该帧大小必须大于 1 MiB。设计要求共享或等价复用此私有物理判定，而非按 range 边界接受。包 reader 的子片段只限制读出的区间，整个包 EOF 检查不能错误地施加到每个中间 range。设计对此已有清楚约束。

组合 reader 只负责编排保留文件和 payload 片段；它不持有认证后的 State，也不能作为免重放成功 API。显式偏移、short read 与 Interrupted 循环，以及中途 EOF/错误的严格返回，与现有 ActiveReader 和物理比较的行为相容。复制目标后仍要用目标自己的普通 ActiveArchive 完整重放，提供第二种具体物理布局的验证入口。

### 创建、恢复、持锁与失败语义

pack 前置路径/新建检查与现有双源全重放计划先完成，再以 create_new 创建输出。包文件按所列原始 later 句柄区间复制，写满、sync 文件及 Unix 父目录后，通过原创建句柄完整验证包。最后检查两原源和包全部字节及保留名称，符合只读取已提交归档的目标。

restore 在创建任何目标目录前重新验证包；复制所有基础文件及增量，逐文件同步，保留原创建 genesis 排他锁及其他文件句柄，构造私有目标 ActiveArchive 并完整 verify。再重放验证 base+package，最终核验目标全部字节/名称。设计没有释放锁后按路径重开目标，也没有向现有 PoolStore 追加，更没有恢复钱包保留项、validator signer 或共识数据库。

目标父目录须存在、真实且持续绑定；源内输出拒绝与 create_new 都在设计中明确。对包父目录只检查身份、允许合法兄弟项，避免在旁边恢复新目录时使包自身无效。Unix inode 绑定和 Windows no-DELETE sharing 与现有 namespace 实现一致。

失败保留现场包括部分头、部分 payload、完整但未同步/同步后确认丢失、末次校验失败及 stdout 失败。再次指定同一路径必须拒绝。完整但被操作返回错误的目标可以由后续显式独立验证处理；不能由此次失败自动删除或“修复”。设计正确地将这个行为与可信父目录/OS/文件系统、Windows 可移植目录持久化及物理掉电未验证界限同时写明。

### CLI、成本与真实测试计划

我亲读 CLI 的参数解码、选项白名单、绝对路径约束、lowercase hex、两 pin 先解析再开源、NO-FUNDS 强制参数与 File-backed stdout。新三命令参数数仍在现有 rest ≤ 13 上限内：pack/restore 为五对选项加一次 ack，即 11 项。设计保留旧模式和旧 renderer，不需要放宽原参数或输出权限。

新增回执区分写出包、仅验证包和恢复目录。两 pin、准确范围、checkpoint 高度/长度与明确 false 的 finality/validator/funds 字段没有混入路径或私密内容。独立重算上界 `2048 + 96 × 2048 = 198656`，固定字段和每项三个 u32 数值可在此有界格式中编码；实现仍须完整渲染后检查实际长度及 ASCII，再交给已有能传播 OS 写错误的 stdout。

成功 replay 次数的设计加法一致：pack 方法为计划 2 次加 package.verify 2 次，共 4；CLI 两个 archive.open 再加 2，共 6。verify/open 各 2；verify CLI 加 base.open 1，共 3。restore 方法为写前 2、目标 1、写后 2，共 5；restore CLI 加 base.open 1 和 package.open 2，共 8。这些是设计中的完整重放调用次数，不能等同 proof 调用次数、测得性能、CPU 时间或峰值内存。

现有真实增长测试确实通过普通 prepare/commit 和默认 1 MiB 分段产生第一笔付款轮转，随后从旧完整恢复目录产生第二跳支付并超过 10,000 记录。现有 CLI 测试也确实生成两笔真实支付，独立编码 checkpoint/JSON、测试双花及普通 checksum 重算后的 binding signature 失败。新设计要求保留这些断言，把实际后续花费的来源接到增量恢复结果，并让新的坏签名用例在组合回放而非旧 later.open 中达到 Authorization。这是本阶段必要的新证据，不能借用旧测试的最终错误名替代。

## 发现、严重性与后续实施检查

设计阻断发现：0。必须修改当前设计文本的非阻断缺陷：0。以下是亲读现有源码后确认的实施检查点；它们在当前设计已有相应明确要求，尚不存在待审核的新实现，因此没有把尚未发生的实现错误列成既成缺陷。

| 检查点 | 若遗漏的影响 | 依据及要求 |
|---|---|---|
| 新包 Unix 多链接检查 | 不满足源文件唯一命名合同 | `namespace::check_file` 调用的 `regular` 来自 `recovery.rs`，仅检查普通文件及 Windows reparse；它本身不检查 Unix nlink。现有 ActiveJournal 自己的 `regular/check_file` 另加 `nlink == 1`。新包须复用该严格检查或等价私有检查，并有包文件 hard-link 原生测试。此点已单独及时报给作者。 |
| 外来旧尾 offset | 范围解析可能省略实际 base 绑定 | 旧 `ActiveIncrementalPlan::checked` 的 offset>0 不能单独认证外来表；要在同一保留 base 上精确要求 offset==实际尾长，并构造唯一段布局后才发布不可变 plan。 |
| 真实坏签名落点 | 可能只证明旧归档入口拒绝 | 已有测试坏 later 在 ActiveArchive::open 即被拒绝。新包测试必须用真实已验证 base 与自洽的外来包，重算 frame 摘要与 later layout pin，确认组合完整 Replay 返回 Authorization；不能把早期 pin/hash/锁失败当作新入口授权证据。 |
| 原句柄与验证次数 | 可能出现 unlock/reopen 窗口或错误成本声明 | 创建对象保持创建锁；目标通过这些句柄重放；每次调用新 verifier；独立审阅最终代码实际调用数，CLI 不得添加未记载的额外 verify 或移除设计指定 gate。 |

以上检查点不是批准偏离设计的例外。后续任何一项未落实时，应按准确新候选返回阻断发现、修复并重新独立审核。

## 实际执行与未执行边界

实际执行：本地只读文件检查；基线 commit/tree 查询；设计字节数与 SHA-256；所有审核源文件逐字节与准确 base 比较；`git diff --check`；Python 独立重算固定头、最大元数据和 JSON 预留容量。这些不是运行库测试。`git diff --check` 不包含 untracked 设计，不能把它当作新代码格式测试。

工具链探测 `shutil.which` 对 cargo、rustfmt、rustc、go 均返回 None。未本地编译、执行 Rust/Go、运行 fmt/Clippy、原生 Windows、真实 Orchard package 调用、故障注入或 CLI 子进程。未请求或审计本阶段 GitHub CI，尚无本阶段运行候选。未模拟真实磁盘满、物理掉电、全 1 GiB/1,000,000 记录容量或任意敌对主机并发改写。

设计允许开始实现；最终冻结的运行候选仍须独立读取 diff、完整相关实现及真实调用/测试，确认全部必要 CI 和真实授权/恢复证据，关闭阻断，才可按仓库阶段规则接受及合入。文档和证据后续变更仍需独立审核，并以逐字节不变证据继承准确运行候选的验证范围。

最终结论：**PASS_DESIGN**，仅对应上述 13,361 字节、SHA-256 `b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41` 的设计。此原件不得后改为运行或原生验收通过；后续结论应新增并保留准确候选身份。
