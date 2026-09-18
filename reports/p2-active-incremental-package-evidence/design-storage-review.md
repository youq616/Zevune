# P2 持久增量包设计：独立存储与对抗审核原件

审核任务：`/root/p2_package_storage_review`。审核日期：2026-09-18 UTC。
本任务未编写被审核设计、生产代码或测试，也没有修改仓库文件。此文件是审核者直接撰写的完整原始结果。

**结论：PASS_DESIGN。** 在下列已读范围内，没有发现阻止进入实现的设计级问题。此结论只针对精确设计字节；不是尚未产生的代码候选批准，不是原生测试通过、阶段验收、外部安全审计或生产可用性证明。运行代码完成后仍须针对准确 base/head/tree 独立复审。

## 1. 身份与冻结范围

- 仓库：`youq616/Zevune`。
- 实际读取目录：`/workspace/scratch/1753b04c9dbb/Zevune`。
- 本地实际核对的基线 HEAD：`2cc87a2207d502ac5cfe00ea52e525c1516917e5`。
- 本地实际核对的基线 tree：`b5841120084a72c5948b0a2754f712e5f67ad602`。
- 设计候选：`docs/ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md`，13361 字节。
- 设计 SHA-256：`b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41`。
- 核对时 `git status --short` 只有该设计文件未跟踪；尚无本阶段代码 candidate commit。不能把基线 HEAD 当成本轮新功能的接受提交。
- 本任务未独立调用 GitHub 读取远程 ref；以上 Git 身份是本地已检出的实际值。正式代码候选的远程身份及 CI 必须另行核对。

## 2. 实际阅读范围

完整读取了 `AGENTS.md`、`docs/STAGE_REVIEW.zh-CN.md`、本轮完整设计和前轮 `docs/ACTIVE_INCREMENTAL_PLAN.zh-CN.md`。审核采用其中 NO-FUNDS、真实授权、拒绝不更改已提交状态、私有故障注入和精确候选独立审核规则。

完整读取了以下生产文件，分段输出均覆盖到文件末尾，没有把被截断的输出认作完整阅读：

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `integration/orchard/src/pool/active.rs` | 29294 | `6aa482a77f2749c4175384def067743fac5d1f0d862553d9ee05c7d5190c4e6f` |
| `integration/orchard/src/pool/recovery/segments/namespace.rs` | 4949 | `7927596f061d3d0fc4e05bf0f5cfd63d53cfdab4d382c1f10a2050c4689b3b3b` |
| `integration/orchard/src/pool/recovery/active.rs` | 10481 | `51d23e0bd0127528e0ed4f0a2877cf164d9e3b3767f780dfcafd914bf7d2c04f` |
| `integration/orchard/src/pool/recovery/active/incremental.rs` | 7162 | `052e6df1227f06cddff8f32e49daf0ed21e4fcabeafcd28d4f084f735a6b8870` |
| `integration/orchard/src/pool/active/incremental.rs` | 6689 | `3ab1d8ccd20005cb2d537a71dc3e8cc83dcb503e98979d333ca93daf68c44274` |
| `integration/orchard/src/pool/replay.rs` | 9818 | `4c25dcd5d92cf5e0ab592b11ae790dba8f3ab7761d3d7cbf7f5e94b13b9b3d64` |

另按调用关系实际读取：

- `pool.rs` 的活动配置打开路径、完整 `PoolStore::replay_active_handles` 及旧恢复入口相邻代码；用搜索核对原有字节、记录、承诺数上限和模块可见性。没有声称完整重审 `pool.rs` 所有状态执行实现。
- `pool/recovery.rs` 的 `regular`、旧父目录同步和旧文件摘要路径；`pool/recovery/segments.rs` 的导入、旧包编码/解码、目录与只读打开、完整 `replay_checked`。
- `wire.rs` 的固定验证密钥共享说明及完整 `AuthorizationVerifier` 构造和 `verify`：每实例新 `VerifiedCache`，真实 action signature、binding signature、proof 校验均在正常成功路径中。
- `pool/recovery/active/tests.rs` 中重算布局后的物理头借用、早轮转、拆帧、错误最终状态等测试，以及部分复制、同步前/后确认丢失、末次源/目标变化测试。
- `pool/active/tests.rs` 中合成帧的早轮转/拆帧、各物理 EOF 与失败 reader、Unix symlink/hardlink/命名替换、Windows 保留句柄拒绝 rename 测试。
- 搜索定位现有 `active_flow_tests.rs`、`active_incremental_cli.rs`、两层 incremental 测试的函数、平台条件及真实付款/恢复再花费入口；本次没有完整读取这些测试文件，所以不据此宣称新功能或整个旧测试组已被代码审核。

## 3. 格式与信任合同检查

两个独立可信 ZVARCP01 pin 是必要前提。包内两份 pin 必须与调用者值逐字节相同，仅作为被校验的输入；两份不可信数据互相相等不会建立来源或最终性。创建时原 `incremental_plan` 对两份归档分别完整重放并比较全部复用字节。验证包时，从已独立完整验证的 base 构造组合历史，并由 independently trusted later pin 的完整物理布局摘要与最终真实重放结果共同约束。这样不需要增加一个容易被误用为授权的普通包 checksum。

固定结构无歧义：8 字节 magic、两份 128 字节 pin、4 字节 N，共 268 字节；每范围 12 字节，N 上界 2048，使元数据上界 24844 字节。整个文件只能是元数据加精确 delta，拒绝未知版本、尾随和短文件；没有可以忽略的后缀或扩展。保持原恢复结果 1 GiB、1000000 记录、2048 段及 1 MiB 物理段限制，包格式开销没有被当作提高账本容量。

我用独立 Python 算术核对了：

- `8 + 128 + 128 + 4 = 268`。
- `268 + 12 * 2048 = 24844`。
- 保守包文件上界 `1073741824 + 24844 = 1073766668` 字节。
- 按合同字段顺序及名称构造 2048 个范围，并把每个 u32/u64 输出值保守扩大为该整数类型最大十进制值，完整 ASCII 单行 JSON 为 142510 字节；小于 `2048 + 96 * 2048 = 198656`，余量 56146 字节。该合成数值组合不是合法 pin/包，只用于独立核对回执分配上界，不能代替真实 CLI 测试。

N 和文件实际长度应在分配前检查，所有加减乘法有界，payload 流式读取。设计明确固定头、表、正文来自同一保留句柄，元数据每次与捕获字节重新比对，payload 的完整检查由组合布局覆盖。这避免只认证 metadata 或只认证已读取前缀。

## 4. 精确追加关系与物理边界

设计正确区分受信内部计划和外部范围表。现有 `ActiveIncrementalPlan::checked` 对旧尾只检查 `offset > 0`，这在原先由实际全前缀比较生成 range 的调用下成立，却不足以解析包。新设计明确要求旧尾 range 的 offset 等于实际 retained base tail 长度，最多出现一次，所有其他旧段完整复用；新的段索引连续、offset 为零；范围严格递增、长度非零、总和精确为 delta。

这项实际尾偏移约束不能留到布局 hash 之后才被隐式“通常发现”，也不能只根据 base 总长和段数猜测旧尾长度。它必须绑定保留 ActiveJournal 捕获的实际物理长度，才能保证公开 `plan()` 精确描述本次重建。

保留旧尾且直接新增段也是合法情形，但新的第一帧必须大到无法放入原尾；不能把完整帧恰好落在 descriptor 边界当成规范轮转。现有 `ActiveJournal::validate_frame` 按 Replay 实际 start/end 定位真正物理段，拒绝跨段帧和“前一段长度加本帧长度不超过 1 MiB”的过早轮转。设计要求组合视图复用相同判定，而非修改授权或重新解释记录，适合实现为私有共享纯函数。

组合逻辑 reader 的实际物理切片来自 base 文件与包 payload，二者的 EOF 语义不同：base 每个完整物理文件需维持真实 EOF；包的 range 中途不是整个包 EOF，只能在文件整体末尾要求 EOF。设计已明确后者，并由 base 完整校验继承前者。实现仍需确保 reader/复制辅助函数没有把原 `visit_file` 的整文件 EOF 检查误用于包中间切片。

建议代码验收明确执行两个新包对抗向量：在新增空块中构造过早新段和跨帧切段，重算 later layout pin，并保持范围表、文件长度及逻辑流自洽；要求包组合 Replay 到达 physical frame gate 拒绝。只运行旧归档的同类测试不能证明新组合视图调用了该 gate。此为落实现有设计要求的测试检查点，非新增功能或设计阻断。

## 5. 完整重放与状态隔离

新包 open 仅在完整 verify 后发布对象；之后 verify/restore 每次再次执行完整 gate。没有只解析即返回的“已认证”对象、可变 range、File、State、PoolStore 或外部计划导入接口。`plan()` 仅记录已验证历史观察，不是未来支出权限。

设计的完整重放与现有真实调用路径相符：先单独解析 base genesis 的完整物理文件，再读取组合流头并比对 length、initial 和 domain。现有 `replay_active_handles` 特意执行该双读取，防止伪造承诺 count 从 journal 借 header 字节；新组合视图必须同样执行，不可因 base 已在 earlier verify 通过而删掉。

组合验证创建隔离 State 和新的 `AuthorizationVerifier`，每个 Replay frame 都执行原授权与状态规则以及真实物理边界检查；只有 finish 达到实际 EOF、genesis/height/app_hash/完整长度与 later pin 一致、之后完整字节和名称仍一致才可返回成功。前后 full layout 核验覆盖旧前缀及全部新增 bytes，防止保留旧对象或更改同长度 payload 后复用 earlier success。不得把 layout hash、预检查或缓存命中变成恢复后支出的权限。

设计要求改坏新增真实付款 binding signature，同时重算普通 frame 摘要及 later layout pin，让组合 replay 明确拒绝 Authorization，这是重要的非空支付验收。该错误可能在 proof 调用之前失败，不能把它报告成该无效实例完成了 proof 验证。

## 6. 保留句柄、锁和命名安全

单文件包可避免再引入一个最多 2048 子文件的备份目录，但不减少 base 当前 ActiveJournal 全部句柄和完整重放 State 的成本。设计未宣称全容量资源峰值已测或任意高描述符负载一定可用。

创建用 create_new、原创建文件及排他锁；正常 open 用只读文件及共享锁；两者一直保留到对象 drop，不通过解锁重开取得“方便”的新句柄。源 archive 同样在原句柄上读取，Windows 无 DELETE sharing 保持、Unix 比较实际 device/inode。不把字符串路径相同当成身份，也不把相同长度或时间戳当成 Windows 唯一文件 ID。

**具体实现核查点：** `namespace::check_file` 从旧 recovery 导入的 `regular` 不检查 Unix `nlink == 1`。现有 `active.rs::check_file` 在 namespace 检查外又执行自己的严格 `regular`，才真正继承硬链接拒绝。包文件实现不能只调用 namespace helper 后声称符合设计。此事实已发送给 root 和存储作者；存储作者确认计划在 active 子模块复用严格的 `super::{regular, check_file, create_file, read_at, ...}`。这是一项设计已经要求、尚待代码审核验证的实现检查点，不是已关闭的代码缺陷。

目标 parent 预先存在、保留为真实目录，通过 canonical parent 检查禁止包输出在 base/later 内以及恢复目录在 base 内；源/目标最后仍按保留句柄核对名称。包的 parent 只检查目录身份，不要求目录项集合完全不变，才能合法在其旁边恢复新目录。对包 parent 错套 ActiveJournal inventory 将使合法 sibling 输出被当作攻击，设计已明确避免。

这些规则依赖可信 parents、OS、文件系统和合作文件锁。设计没有承诺能发现任意敌对瞬时改写再还原，也没有把 Windows 可移植目录 fsync 或物理掉电当作现有能力。此界定与现有代码限制一致。

## 7. 创建、恢复及失败现场

pack 在写入前验证目标条件，并执行现有全量 incremental_plan；按其原 later 句柄流式复制，仅写元数据及实际追加 payload。sync_all 和 Unix parent sync 之后，继续用原创建句柄完整 package.verify(base)，最后检查两源和包全部 bytes/metadata/名称。单次 earlier plan 不能授权后来一次写入。

restore 在建立任何目标目录前完整 verify；之后逐文件 create_new、原始保留句柄、精确复制/尾段拼接及全部同步；再从创建句柄构成私有 ActiveArchive，真实 verify 目标，完整 verify base+package，再做完整目标 bytes/name check。没有通过 PoolStore append 或早先生成的状态快照改写现有已提交历史的路径。目标 genesis 的排他锁必须保留到目标认证结束，不能 copy 后 drop 再 reopen。

目标产生后遇到部分写、同步前错误、同步后确认丢失、末次源/包/目标变化或 stdout 写失败，均允许留下实际已写新内容。函数错误不是“未产生目标”的证明；下次同路径 create_new 必须拒绝。测试只能显式验证完整留下的目标或使用另一个新路径，不得通过自动清理掩盖错误现场。这不与“拒绝不得改变已提交状态”冲突：新输出不是现有已提交状态，source 及既有目标依旧只读。

完整成功路径重放次数按调用结构自洽：pack 方法 4 次、CLI 含两输入 open 共 6 次；package verify/open 各 2 次，verify CLI 加 base open 共 3 次；restore 方法 5 次，restore CLI 加 base open 1 次和 package open 2 次共 8 次。末次 byte/name check 不额外计作真实 replay。设计没有把新增能力宣传为减少重放时间；执行时仍需实际确认既有工作流预算未超。

## 8. 发现、后续要求与未执行边界

设计级 Critical/High/Medium 阻断：**未发现**。未发现必须先修改该精确设计才能开始实现的内容。上文 strict regular、包中间 range EOF、实际 base tail offset、共享 frame gate、创建句柄保留、parent sibling 容许和 Authorization 对抗向量，均作为后续准确代码候选审核检查点保留，不能据本设计 PASS 推定实现已正确。

本次实际执行的是源文件读取、Git 身份/状态、字节哈希和独立 Python 格式/JSON 上界算术核对。`command -v cargo rustfmt go rustc` 没有发现可调用的本地 Rust/Go 工具链。**未编译、未运行本阶段 Rust/Go/CLI/native CI、未运行真实付款或跨段恢复、未测试 Windows 文件系统，也没有进行实际断电/磁盘满实验。** 没有新的运行源码，因而也不存在可接受的代码 diff 或新功能 test pass。

进入实现后应保留旧全部测试与 CI 预算，对新包读写/恢复运行真实流程及故障测试，取得 Ubuntu/Windows 原生结果及准确代码 commit 的非作者审核。文档跟进还需运行树逐字节继承和独立文档审核。不得把本次 PASS_DESIGN 转写为 PASS_CODE、全阶段完成、P2 完成、生产可用、真实资金许可或外部审计结论。
