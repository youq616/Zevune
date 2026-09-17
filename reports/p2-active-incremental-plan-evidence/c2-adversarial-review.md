# P2 活动归档追加计划：C2 非作者独立对抗代码审核

审核任务：`/root/p2_plan_adversarial_review`。审核时间：2026-09-17 14:08 UTC。
审核者没有编写本候选的设计、生产实现或测试，没有修改仓库、推送或合入分支。
本报告由该独立任务直接撰写，根任务的实现摘要、另一审核者的结论及 CI 绿灯均未代替源码阅读。

**结论：PASS_CODE，准确适用 C2。** 未发现需要修改的实质正确性、授权、存储只读边界或兼容性阻断问题。此结论是源码审核结论；本任务没有本地 Rust/Go 工具链，没有运行原生测试。C2 的全部必需原生检查尚须由实际 CI 记录满足，不能将本报告单独作为阶段验收或合入许可。C1 的原生格式失败没有被认定为通过。

## 准确对象与覆盖

| 对象 | 身份 |
|---|---|
| 仓库及 PR | `youq616/Zevune`；[PR #15](https://github.com/youq616/Zevune/pull/15) |
| 本阶段真实基线 | `0927af157a3cc35abde14b036bc50a99a793a32b` |
| 基线树 | `e04479cf7723588885573be2112635efa30e27cc` |
| 初始 C1 | `99ec771c57207167f473d23ffd07b54f15a36abc` |
| C1 树 | `510693b0fd8ec085ab06de4140d6f7fd80f48c7e` |
| 当前审核 C2 | `2020c7314a996769b33706754405c0976ce7c50a` |
| C2 树 | `a25d4752d49f366f9aff047116eeffd9b1f6ae1d` |
| C2 相对 C1 | 4 文件的格式修正；未改变运行语义、测试断言、设计、依赖、工作流或预算 |

已全量阅读基线到 C1 的 11 个变更文件、相应 diff 和下面的继承调用链；随后逐个阅读 C1→C2 的全部 diff，并将 C2 的每个文件与 Git 对象及当前工作树逐字节核对。C2 相对真实基线仍然恰为这 11 个路径，共 173,722 字节；审核结束时本地 HEAD/树准确且 index/worktree 干净。C1 的原始文件内容与交付的 `c1-payload.json` 中全部内容、长度、SHA-256、Git blob 身份逐项相等。

以下是 C2 文件的完整 SHA-256，而非摘要匹配：

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| `docs/ACTIVE_INCREMENTAL_PLAN.zh-CN.md` | 8604 | `0234062797e5436cbccb307db50655b2b7a50f48046ccb91824e9dabc2e93193` |
| `integration/orchard/src/bin/zevune-pool-recovery.rs` | 13309 | `634cf7b3f1617ac02e51b710478a858549145efca25edef4fe12f0a3d19c789d` |
| `integration/orchard/src/pool/active.rs` | 29294 | `6aa482a77f2749c4175384def067743fac5d1f0d862553d9ee05c7d5190c4e6f` |
| `integration/orchard/src/pool/active/incremental.rs` | 6689 | `3ab1d8ccd20005cb2d537a71dc3e8cc83dcb503e98979d333ca93daf68c44274` |
| `integration/orchard/src/pool/active/incremental/tests.rs` | 8480 | `747600d6d14f3e4c758549c58516bcde07c1a403e4783202e3cf26ec34b0ecf3` |
| `integration/orchard/src/pool/active_flow_tests.rs` | 39770 | `a10e38aadf8bd44b2daa6aedb6287159f460929b67682a7aa498e2f29939b86a` |
| `integration/orchard/src/pool/recovery/active.rs` | 10481 | `51d23e0bd0127528e0ed4f0a2877cf164d9e3b3767f780dfcafd914bf7d2c04f` |
| `integration/orchard/src/pool/recovery/active/incremental.rs` | 7162 | `052e6df1227f06cddff8f32e49daf0ed21e4fcabeafcd28d4f084f735a6b8870` |
| `integration/orchard/src/pool/recovery/active/incremental/tests.rs` | 21240 | `4933c10a8b25c506ed9fed17ddf41e222f0a5e68d6f0b80a2390c83208f8acc1` |
| `integration/orchard/src/recovery_incremental_output.rs` | 2540 | `4cdc15626a5062ea757be2813214b4f6f4eabdf221c2697942261b24cd3d2808` |
| `integration/orchard/tests/active_incremental_cli.rs` | 26153 | `26725f2716eb7a53b65581b12117de25f649fc8b6fc3f05f633ad9dd90741ac0` |

除完整新增实现与测试外，实际读取了 `AGENTS.md`、`docs/STAGE_REVIEW.zh-CN.md`、冻结设计全文，以及 `pool/active.rs`、`pool/recovery/active.rs`、`pool/recovery/segments/namespace.rs`、`pool/replay.rs` 全文，`pool.rs` 中状态执行/普通打开/完整 active replay/容量入口，`wire.rs` 中真实授权和缓存生命周期，CLI 完整解析、旧模式和 stdout 路径，funded target 调度脚本、Cargo 配置、固定工具链及 funded workflow。使用 Git 比较确认继承的 `pool.rs`、replay、wire/cache、namespace、Cargo.toml/Cargo.lock、工具链、funded 调度脚本和工作流相对基线字节未变；全阶段路径差集也排除了其他仓库文件改动。

AGENTS 提到的历史 `PROOF_CONTRACT.md` 与 `ARCHITECTURE.zh-CN.md` 在当前 Git 树中确实不存在，已经用文件搜索和 Git tracked inventory 核对。另读了 `docs/PUBLICATION_STATUS.zh-CN.md` 和 README 对六份历史缺失文档的现有记录。本次没有重建或冒充读取这些缺失原件，也没有新增密码学后端设计；审核真实授权行为依据当前可读实现和本阶段冻结设计。

## Findings 与 C1 修正记录

| 编号 | 严重性与状态 | 事实、影响及处理 |
|---|---|---|
| AR-C1-01 | Low；C1 验收阻断，C2 源码修正已复核，原生重跑另验 | C1 的真实 Ubuntu job `105234456854` 在 `cargo fmt --all -- --check` 退出 1。完整原始日志是 `c1-first-format-job-105234456854.log`，21,827 字节，SHA-256 `eb63703046d7a4c8acb37bf584a2e355145159650d3bc917f573bcf720e2d05b`。日志实际 checkout `066f033f2ca441bdd8533c8e1e4bfe2d3faa84a5`，标明把 C1 合成到真实基线。本任务读完原始日志与 10 个格式 hunks，并与 C1→C2 的 4 文件 diff 一一核对，变动仅换行及允许的尾逗号。该问题由原生 CI 发现，不冒充本审核独立发现的逻辑漏洞。C1 保留失败身份；本报告不证明 C2 的 fmt 或其他原生任务已完成。 |

没有未关闭的 C2 实质代码 finding。没有发现需要禁用测试、放宽上限、共享授权缓存、绕过真正证明或缩减 CI 才能成立的实现路径。

## 认证与追加关系

`ActiveRecoveryCheckpoint` 的外部解码保持精确 128 字节 ZVARCP01、非零身份、受限高度/长度/头长度/段数。CLI 先解析两个 pin 再打开任一归档；不是从候选目录自取可信 pin。只读打开继续约束 ActiveSegmentsV1 的真实头格式、固定网络与签名域；不同网络/创世不是两个不可信 pin 能互相背书的条件。

`incremental_plan` 在创建计划前检查 pin 结构、创世与高度关系；回退、同高不同 pin、升高却不增长的长度、减少段数均关闭。元数据兼容后，先 `self.verify()` 再 `later.verify()`。每次调用均经 `PoolStore::replay_active_handles` 创建新的 `AuthorizationVerifier`，仅固定公开验证密钥跨实例共享，各 verifier 的 `VerifiedCache` 独立且起始为空。普通结构解码、域、过期、可信根、重复花费、重复输出、费用及状态摘要验证仍在真实 replay 中，不把旧成功、缓存或 pin 的普通摘要当作免验证凭证。

物理层先检查两端 namespace，再完整比较 genesis。所有旧非尾段要求相同索引、相同全长和全部字节；旧尾段要求 later 同索引文件至少一样长，比较整个旧长度，不能只看最后记录、首块或哈希。旧尾段不增长但新增段时只生成新段；旧尾段增长后再轮转时同时生成一个非零 offset 后缀和之后的整段；空 base 只复用 genesis；相同完整内容生成空计划。合法更高分叉即使拥有自己的正确 pin、完整 replay 成功，也因旧物理前缀不同返回 Stale。

原有 `validate_frame` 仍逐条验证真实 replay 的物理帧边界和实际轮换条件。算法使用捕获的各物理段长度，没有把逻辑偏移除以 1 MiB 来猜段号，也没有把同一逻辑流任意重新切段视为追加。关系验证与两个独立可信 pin 共同成立才有结果；任一 pin 均不证明最新高度或共识 finality。

## 保留句柄、全部字节与错误原子性

比较只读取归档持有的 genesis 和 segment File，没有按用户路径重新打开数据文件。`fill_at` 分别填满左右缓冲，正确处理两端不同 short-read 长度、Interrupted、提前 EOF、I/O 错误、偏移溢出；不假设一次 read 填满，也不依赖克隆句柄的共享游标。两个缓冲各为 64 KiB。每个比较涉及的 base 文件验证捕获全长的 EOF，later 文件也验证其实际捕获全长 EOF，而不是误把较短 base 长度当作 later EOF。

归档完整 verify 的前后均检查布局哈希与 namespace。物理比较完成后，公开方法再次调用两端 `check_bytes`，覆盖 genesis、所有保留段、旧尾段增长部分以及新段的完整字节和 namespace；不是只复核计划中的后缀。Unix 的 inode/device、链接数与原名称检查、Windows 的 no-delete-sharing 与 reparse 拒绝沿用。两端 genesis 的共享锁在 archive 生命周期中保持，合作 writer 不能进入；同一路径的两个独立 reader 没有绕过验证的快捷分支。

生产路径未创建/删除/改写归档、未返回 State/PoolStore、未移交写句柄或导入能力。callback 的部分 Vec 只存在于方法内部；出错整体丢弃，只有最终全部检查及 `ActiveIncrementalPlan::checked` 成功才返回公开值。新 fault 7–10 只在 `cfg(test)` 中模拟最后阶段的外部 namespace/同长内容修改，失败保留这些外部变化；这不能被说成生产方法曾改动源，或说注入用例的整个目录与注入前相等。既有 copy faults 1–6 与完整复制的验证顺序未变。

这些检查仍依赖可信父目录、OS、文件系统与合作锁模型，不构成任意敌对并发修改又复原的原子文件系统快照保证。计划是历史观察；归档随后 drop、路径随后变化，保留的计划不会认证新路径内容。

## 上限、不可变接口与 CLI 输出

`ActiveAppendRange` 和 `ActiveIncrementalPlan` 的字段私有，外部只能读 getter，没有公开反序列化、任意构造或写入入口。pin 检查限制最多 2048 段，Vec 按已验证 later 段数使用 `try_reserve_exact`；callback 在 push 前检查长度，最大 range 数不会超过 later 段数。逐段范围非零且严格递增，旧段只允许旧尾段非零 offset，新段从 base 段数连续出现且 offset 为零；offset+length≤1 MiB。`checked` 再验证新段连续性、`unchanged + ranges.len == later.segment_count`、精确字节和及 checked 加减/转换，因此返回的 reused/appended/new/unchanged 计数与物理含义一致。

CLI 的准确 mode 与四个 key 明确，重复/缺失/未知参数、重复或缺失 NO-FUNDS、相对 base/source、非小写规范 pin、旧 pin、`--output` 均拒绝；现有总参数数及单参数长度边界继续生效。旧命令解析与输出路径除必要分派外未改。新 JSON 首字段 format、所有字段顺序、range schema 与七个布尔标识符合冻结合同，只有固定字符串、受限数值和两个固定大小 pin，没有输出用户路径或私密数据。

renderer 先完整验证并完整构造 ASCII 单行 JSON，再调用已有 File stdout 复制句柄写入路径；只读 stdout 的底层错误会传递为非零退出，不会因 Rust 标准输出适配器吞 EBADF 而报告成功。输出 I/O 失败可能已经写入部分 JSON，这不是验证失败时的成功输出，也不能承诺所有错误都产生零字节。

独立静态十进制长度计算：使用全部 u64/u32 最大值和两个 256 字符 pin，即使这些字段的组合不是合法计划，空 ranges 的完整 JSON 加换行最多 1104 字节；每个三 u32 range 最多 68 字节，额外逗号 1 字节。2048 个范围总计最多 142,415 字节，低于实现预留的 198,656 字节（`2048 + 96 * 2048`）。这是对固定输出上限的 Python 字符计数和源码推导，不是 Rust renderer 执行或 2048 段真实账本测试。

## 测试源是否验证了正确边界

- 物理层 5 个测试定义只使用物理合成帧，明确未执行 State/PoolStore，不充当真实授权。它们覆盖独立 short reads/Interrupted/EOF/I/O/溢出、旧尾后缀和轮转组合、64 KiB 之后及旧封闭段最后字节的前缀修改、物理 genesis/EOF/捕获长度、callback 失败无成功结果。
- 公开库层 10 个测试定义通过普通提交构造空区块历史；其中 7 个通用、2 个 Unix 条件、1 个 Windows 条件。更高合法分叉在两端单独 verify 成功并满足增长元数据后，还直接断言物理层 Stale，再断言公开方法 Stale，确实不是错 hash 或锁冒充前缀拒绝。另覆盖同高分叉、回退、其他网络、旧格式、错 pin、同路径/复制空计划、成功之后每次重新验证、两端被外部改动、最终摘要/namespace 故障，以及系统各自的保留名称/链接/锁行为。
- 完整读取 `active_flow_tests.rs` 的 4 个既有测试及新增调用。静态逐行序列核对确认基线 825 行全部按原顺序保留，C2 共 966 行，新增 141 行；没有删旧证明、付款、恢复、双花、容量或失败不变断言。真实第一笔付款仍使默认 1 MiB 段发生轮转，新增检查断言旧尾不变、只追加 segment 1。原有实际 archive→restore→恢复后第二次花费仍存在；再检查旧尾后缀至 10001 及恢复后 10002 的 150 字节追加。测试按 range 独立重建完整副本，与 later 全目录字节相等后重新完整打开验证；这只是测试重建，不是产品已经实现增量 restore。
- `active_incremental_cli.rs` 的 7 个测试定义真实启动生产 CLI 子进程。正例用物理文件和普通提交摘要独立编码 pin、用预期范围独立构造完整 JSON；没有调用生产 renderer 来自证。覆盖首笔真实付款、正常复制/恢复、Bob 首次扫描实际恢复历史后再签给 Carol、两笔双花拒绝、最终余额/费用守恒、重复计划、空计划、参数与两端错误、实际 writer 锁与多 reader。
- 坏签名用例修改真实绑定签名并重新计算普通帧 checksum 与完整布局 pin；新 CLI 测试特意修改 NEW record，保持正确 base 前缀，断言公开 `ActiveArchive::open` 到达 Authorization。flow 测试的两端坏签名链同样必须先通过 open，实际在 open 被 Authorization 拒绝。不能把这些测试说成坏 archive 已经成功打开并进入 `incremental_plan`，也不能用它们单独证明二次 replay 的缓存独立性；后者由实际 fresh verifier 调用链和另外的修改后重验测试共同支持。
- CLI 普通调用保存整个 fixture 树的目录集合与每个文件字节，调用后相等。stdout 测试先证明只读句柄确实不能写，再执行真实命令并断言 exit 1；另有非空/空计划可写 File 正对照和常规 stdout 对照。可写收据正例只允许预创建的收据文件变为准确 JSON，其他整个 fixture 树不变。

以上是源级覆盖事实，尚非本任务实际执行的通过数。新增库定义在 Ubuntu 会选择 14 项、Windows 13 项；7 项新 CLI 仅在 `local-funding-lab` 选择，默认构建中该 target 的零测试结果不能计作执行。已读 funded 调度器：真实 Cargo metadata 穷尽 bin/integration targets，新 target 会自然进入 interfaces cohort；library 是另一独立完整 cohort。没有降低现有 30 分钟预算、关闭平台或按测试名称省略密码学。

## 本任务实际完成与未完成

实际完成：只读源码/diff/调用链审核；准确 C1 与 C2 Git 对象、文件字节、SHA-256、路径差集和工作树身份核对；C1 完整原生格式失败日志及 C2 格式修正核对；基线旧 flow 行序保留检查；C2 `git diff --check`；固定 JSON 长度上限独立计算。仅在仓库外写本报告。

未执行：本地 `cargo test`、`cargo fmt`、Clippy、Go test/vet/race/fuzz；环境查找 `cargo`、`rustc`、`rustfmt`、`go` 均不可用。没有独立收集或验收 C2 的 10 个 PR 工作流/23 个 native jobs，不把根任务传来的排队信息当作通过；必须另行核对实际 job attempts、checkout source/tree、所有结果和条件 skip。若 C2 后再改变运行代码或测试，本结论不能自动转移到新候选。

CLI 完整调用有四次完整 replay：两次 open，各一次；`incremental_plan` 对两端再各一次。对两个已经打开的 archive 单独调用方法才是新增两次；这未减少历史状态重建、原文件和临时 reader 句柄成本。没有测量本阶段全容量、最大段数、1 GiB/一百万记录或持续付款增长下的资源峰值，也没有真实磁盘满/断电、Windows 目录持久化、长期多机或外部专业安全审计证据。

交付文档必须保持 P2 整体 in_progress，`incremental_backup_implemented=false`、`snapshot_state_import_implemented=false` 及 NO-FUNDS/finality/validator 限制；本阶段仅交付追加关系核验与只读计划，没有持久增量包、快照导入或生产恢复能力。源码审核 PASS_CODE 加上之后真实满足的原生验收和准确文档审核，才可按仓库流程完成本阶段。
