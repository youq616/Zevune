# C1 持久增量包：非作者独立存储与对抗代码审核

审核任务：`/root/p2_package_storage_review`。日期：2026-09-18 UTC。
本任务未编写本轮设计、生产源码、测试、CLI 或 workflow，也未替作者修复本候选。此前同任务的设计审核不代替这次准确代码候选审核。本文件是审核者直接撰写并保存的完整原始结果。

**静态代码结论：PASS_CODE（仅静态语义审核）。原生验收结论：BLOCKED_NATIVE_FMT，剩余原生范围 NATIVE_PENDING；C1 不可接受或合入。** 在下列实际阅读范围内没有发现生产语义、安全或测试逻辑阻断，但我独立读取的准确 C1 原生日志明确显示格式检查失败。格式修复后的 C2 必须重新绑定 head/tree、复审全部变化并取得新候选原生结果，本报告不能直接转用为 C2 通过。

## 1. 独立核对的候选身份

- 仓库及 PR：[youq616/Zevune #17](https://github.com/youq616/Zevune/pull/17)。本次读取 PR 时为 open、merged=false、commits=1、changed_files=12。
- 实际 base：`2cc87a2207d502ac5cfe00ea52e525c1516917e5`。
- base tree：`b5841120084a72c5948b0a2754f712e5f67ad602`。
- [准确 C1](https://github.com/youq616/Zevune/commit/61c691270b91aece076177cb757e51e0e63fe310)：`61c691270b91aece076177cb757e51e0e63fe310`。
- C1 tree：`56dad7fdaad64b2b29ddac6b9585b8695aa465d7`。
- C1 Git commit 的唯一 parent：上述 base。
- PR synthetic checkout：`bd710cf4c985012ca23e86c333567ce116de72bb`。
- synthetic parents 按序为 `[2cc87a2207d502ac5cfe00ea52e525c1516917e5, 61c691270b91aece076177cb757e51e0e63fe310]`，tree 与 C1 精确相同。

我自行调用 GitHub connector 读取 PR 和上述三个 Git commit 对象，并与本地 Git 对象核对，未只采用作者口头身份。本地初次精确核对时 HEAD=C1、tree=C1 tree，工作区 clean。随后 root 开始修改 C2 格式；本报告继续使用 C1 固定 Git 对象与之前已完整读取且核对相同的 C1 字节，不将变化中的工作区归入 C1。

`git diff --name-status base C1` 精确为 12 路径：7 新增、5 修改，改动后这些完整文件共 262548 字节。逐文件核对工作区初次冻结字节、`git show C1:path`、SHA-256 和按实际字节重算的 Git blob SHA，全部相等。基线共 886 个 tree entries；C1 共 893 个；其余 881 entries 的 mode/type/blob 与 base 精确相同。工作流、依赖、原预算、其余测试及先前证据文件不在差异中。这是树身份继承核对，不是重新阅读 881 个未改文件的声明。

## 2. 完整阅读与字节范围

`AGENTS.md`、`docs/STAGE_REVIEW.zh-CN.md`、已冻结设计、前阶段追加计划设计及相关基线 ActiveJournal/ActiveArchive/incremental/Replay/namespace 在本任务设计审核时完整阅读。本次又读取全部新文件、完整 CLI 和完整实际 funded flow；旧生产文件以已完整阅读的基线源码加全部精确 C1 hunks 覆盖。高层测试仍由作者增补时的预读没有作为最终依据；作者最后冻结后，我从头到尾重新读取其最终 853 行，并再次核对 C1 blob。

| C1 路径 | 字节数 | SHA-256 |
|---|---:|---|
| `docs/ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md` | 13361 | `b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41` |
| `integration/orchard/src/bin/zevune-pool-recovery.rs` | 16512 | `a7f251856937ae0096e4f777181fed91c7ab2daa5da181bed84957247603f31c` |
| `integration/orchard/src/pool/active.rs` | 29857 | `621257f7690ec6d467a19616dde11553fcd6dec150e13d9bc7bc4f12c5016151` |
| `integration/orchard/src/pool/active/package.rs` | 27158 | `3bd76e74f276d895c13d7c50d7398ceb2afbb7c8b4d7fe5b24baf9565b41d361` |
| `integration/orchard/src/pool/active/package/tests.rs` | 22487 | `b81fb39e0be2e4f021b68ff3bf40135007cc528b69f64cc2d6cd414c075190fa` |
| `integration/orchard/src/pool/active_flow_tests.rs` | 46198 | `4030794c09a066ac7cce9970af81883810240cc11423f6c844bc5c5884eeab4d` |
| `integration/orchard/src/pool/recovery/active.rs` | 10574 | `aeba87d0648cf043bcb22554a71b30509f4fa19ac99863738ed729b870c280eb` |
| `integration/orchard/src/pool/recovery/active/incremental.rs` | 7548 | `50d291f6613450faec4441d769758728423ae12aa7912d6f2d04cfbe010beedc` |
| `integration/orchard/src/pool/recovery/active/package.rs` | 14687 | `87869f9261a8043f2e4ae33f7158bed328c1c63c2238f8c97d4f6d2faed40b9c` |
| `integration/orchard/src/pool/recovery/active/package/tests.rs` | 34919 | `936c8092f1d798e4c9be87315475808a1051b957da608ca6fbab1439ac57e5e8` |
| `integration/orchard/src/recovery_package_output.rs` | 2720 | `7c2a82ac2238ccce46d4656ef884aee75e6ae9104943496336aa78c2bce52aab` |
| `integration/orchard/tests/active_incremental_package_cli.rs` | 36527 | `914165fb58851df2da8435742848e0be6a865a8b5d67bed99768d267ff9143ce` |

相关未修改调用关系也已亲读：完整 `PoolStore::replay_active_handles`、`Replay`、`AuthorizationVerifier::new/verify`，active 与旧 recovery 各自 `regular` 的差异、namespace 保留目录/文件 helper，以及现有头借用、帧切分、EOF、保留句柄、失败复制和平台命名测试。没有把任一作者自查或另一 reviewer 的摘要当成本报告的代码阅读。

## 3. 非可信二进制与范围边界

`open_unverified` 是私有构造边界，唯一公开 `open` 立即完整 `verify` 后才返回。它先检查外部两 pin 的 bounds 与相互关系，再通过 `RetainedPackage::open` 保留同一个文件、共享锁和父目录。固定 268 字节、magic、两份外部 pin、N 上界、metadata 大小和文件精确 `metadata + delta` 均在 payload 处理和相应分配前核对；try_reserve 与 checked 加减乘法失败关闭。无忽略尾部、压缩、用户路径表或整个 payload 分配。

`checked_plan` 使用保留 base 的实际 `capacity()`，将旧尾索引、实际 tail 长度及 offset 精确绑定；之后调用原计划的 bounded ascending/count/sum 检查。`JoinedJournal::new` 再次绑定每个旧尾 offset 与真实 base segment length，并要求新段从 base 数量连续到 later 数量、offset=0、nonzero length、range end 不超过 1 MiB。它根据实际旧长度加 payload 长度构造每个物理段，不按“总长除以容量”猜测切分。

同内容空包只允许相同两 pin；零 range 精确 268 字节，仍完整验证与恢复。base 无段、旧尾增长、旧尾不变而新增段以及多个连续新段都由同一逻辑处理。包创建会再次要求每个被拷贝 range 的末端等于 retained later 对应段长度，避免截取任意中间片段再冒充追加。

`RangeSpec` 和物理层仅在 `crate::pool` 内可见；公开计划/范围字段仍不可由外部构造或修改。提升到 `pub(super)` 的 plan helper 和 range constructor 仅供受限恢复兄弟模块组合，不新增外部的未验证状态入口。

## 4. 显式偏移、EOF、完整布局与 frame gate

所有新 payload/span 读取使用原始保留文件加显式偏移。`fill_at` 会独立补齐短读，重试 Interrupted，拒绝零进度、异常返回数量和偏移溢出；`write_all_checked` 对短写、Interrupted、零进度和异常返回数量同样失败关闭。生产使用固定 64 KiB 缓冲；测试 fake reader/writer 只进入这些私有物理 helper。

`visit_span` 明确不在包中间 range 验证 EOF；`RetainedPackage::check` 在整个包捕获长度处检查真实 EOF 和当前严格 metadata。`JoinedReader` 对每一个完整 base 物理文件单独检查 EOF，包 payload 部分只按准确 span 读取，所有 piece 消耗完后再次检查 source namespace、包 metadata 与整体 EOF。reader 发生错误即 sticky failed，即使以后补回文件长度也无法继续使用该 reader。它借用原始所有者，不额外克隆成可独立存活的授权对象。

`JoinedJournal::layout_hash` 逐字节采用既有 ZVARLY01 域、物理 genesis 长度及全部 bytes、准确段数、各段 index/length 和完整合成段 bytes。读取前后都核对 base namespace、包 parent/原始句柄/metadata/EOF。高层 `check_bytes` 另外独立核对完整 base layout hash 和外部 later layout hash，因此同长度 payload 改写不能只靠 length/metadata check 通过。

C1 将既有 `ActiveJournal::validate_frame` 提取为私有 `validate_physical_frame`，并让 ActiveJournal 与 JoinedJournal 共同调用。对实际 Replay start/end 的最小/最大 frame、逻辑边界、物理段边界和“前段剩余空间足以容纳新段第一帧”的拒绝规则均保留；唯一额外算术防护为段累加 checked_add，未扩大旧接受条件。helper 的 `previous + frame_length` 两项均已受 1 MiB 范围约束，不能由公开未验证整数直接进入。

高层测试明确证明重算 pin 后的 early rotation 与 split frame 能通过私有 metadata/完整 layout 检查，再由组合 verify 返回 Corrupt，restore 在写前失败且不创建目标，公开 open 也拒绝。反序范围用例同时反序 payload，两个索引都合法，具体排除“只是索引越界导致拒绝”的伪覆盖。它们是正常真实空块的公开存储字节，未使用接受型密码学替身。

## 5. 完整真实重放与创建句柄恢复

每个包 verify 先执行新的 base.verify，再核对 base 与组合全部字节；从 base genesis 单独解析完整物理头，随后解析组合 reader 逻辑头，比较 length/initial/domain，创建隔离 State 并核对 genesis。之后创建新的 `AuthorizationVerifier`，通过原 Replay 执行所有记录，每帧检查共享物理 gate，完整 finish 后检查 final genesis/height/app_hash，末次重新核对 base 全部 bytes、组合全部 bytes 与 metadata/namespace。没有导入 state snapshot、已有授权缓存、部分 replay state 或“之前通过”的权限。

pack 先保留新目标 parent 并禁止已有/源内输出，执行原双归档完整 incremental_plan，按 retained later 原句柄写精确 metadata+payload，持有原新建文件及排他锁并同步；之后完整 package.verify，最后再次检查两个完整源及包。成功对象一直持有原创建句柄，直到 drop 才释放。

restore 先完整 verify，再通过 JoinedJournal 流式 create_new 新目录及每个真实文件，保持原 genesis 排他锁和所有创建句柄，逐文件同步、目录同步与 Unix parent 同步。返回的 `(File, ActiveJournal)` 被直接用于私有 ActiveArchive 实体目标 verify，没有释放后 reopen 的空窗。再完整 verify 输入包/base，最后核对目标全部 bytes/names 与 retained parent。成功只返回 later pin；没有可写 PoolStore 或早期认证状态外泄。

成功调用路径对应设计重放数：pack 方法 4 次、verify/open 各 2 次、restore 方法 5 次；CLI 三种模式分别 6/3/8。此为代码调用关系，不是由耗时推导的执行次数测量，也不是资源峰值或加速结论。

## 6. 路径、锁与失败现场

设计时指出的 Unix 硬链接风险已经在 C1 实际实现中关闭：包调用 active 的 `regular`、`check_file`、`open_file_access`、`create_file`，包含 `nlink == 1`，没有只依赖缺少此条件的旧 namespace regular。打开、创建、末检都使用这些严格规则。

`NewTarget` 从输出前验证开始保持同一个 parent Directory；后续 create/sync/末检都重新核对该 parent 的命名身份。canonical parent 限制禁止在 base/later 内写包和在 base 内恢复。包 parent 无 inventory 白名单，允许合法无关 sibling 及旁边的新恢复目录。所有目标仍是 create_new，不覆盖已有空/非空文件、目录或链接。

Unix 保留 inode/device 检查及 symlink/hardlink 拒绝；Windows helper 保留无 DELETE sharing 与 reparse-point 检查。源码测试覆盖包名/父目录替换、增加硬链接、两个共享 reader、创建对象排他锁、最后 reader drop 及 Windows rename/remove 正反对照。CLI 还有跨进程 writer/shared-reader 调用。测试正确在普通 Windows 外部字节读取前释放相关创建者排他锁，不把读写锁错误误记为内容拒绝。

故障注入严格受 cfg(test) 限制。pack 的 20..23 对应部分 metadata、部分 payload、完整 bytes 同步前、同步后确认丢失；restore 的 11..14 对应部分 genesis、部分段、最后同步前及全部同步后。失败保留新输出；重新指定同一路径拒绝；完整留下的输出必须显式 full verify，原始创建锁应已释放。末次 base/later namespace、包 metadata/payload、目标 namespace/tail 变化均有对应失败断言。

包字节故障 helper 使用 `^ 1`，base/目标 tail 测试 helper 使用 `^ 0x80`；最终冻结测试的三处包故障预期已经分别正确对应，未将不同 helper 的位翻转混淆。这些用例是受控进程观察，不能称真实磁盘满、掉电或 Windows 目录掉电持久化验证。

## 7. 真实付款调用方、CLI 与覆盖边界

`active_flow_tests.rs` 相对 base 为 161 行纯新增，原旧归档复制、只读计划、10000 边界、实际段容量、余额/手续费、双花和错误后不变断言未删。正常 prepare/commit 先产生 6963 个空块，真实第一笔付款在 6964 强制 1 MiB 规范轮转；原归档恢复后再执行真正增量包创建、打开和恢复，返回的增量恢复路径遮蔽旧 path 并被 ordinary `genesis.open_pool` 使用。随后第二笔真实付款在高度 10001 从该路径的真实钱包历史继续，第二次增量恢复后还正常提交 10002。

新增坏授权用例只改第二笔新增付款 binding signature，重算 frame 普通摘要及 later 全物理 pin，保留有效 base 前缀。它没有先打开无效 later 归档；直接以有效 base 加独立编码包调用新 public open，并要求 `Err(PoolError::Authorization)`。该源码具体检验组合重放授权路径，不是旧 pin mismatch 或 checksum 拒绝。绑定签名可先于 proof 失败，因此不宣称该无效实例执行完 proof。

物理层三个连续新段场景使用私有合成 header/frame，明确从不进入 State/PoolStore；我没有将这些通过预期算作真实付款或真实状态恢复。真实 funded fixture 仍复用已有两笔付款生成，未增加接受型 verifier、skip-proof 或新密码学。

CLI 对三模式逐一白名单参数，显式 NO-FUNDS、绝对路径，两个 pin 都在打开任一输入前严格解码；旧命令路由和既有安全 stdout helper 保留。renderer 使用固定 operation、两 pin hex、数字与布尔值，不包含用户路径；先按 2048+96N 上界完整生成单行 ASCII JSON，再通过实际 File-backed stdout 传播错误。新 CLI 测试逐字节核对独立格式与所有字段顺序，包含删除 later 后 verify/restore、恢复后 ordinary commit、选项/错误 pin/缺失与源内目标、整个目录树不变、真实只读 stdout 写探针及可写正对照、失败回执后的完整输出另行明确验证。

静态定义计数为 physical 8（6 通用+Unix1+Windows1）、高层 API 11（9 通用+Unix1+Windows1）、新 CLI 8（7 通用+Unix1，funded gate）。因此新增源定义共 27；按平台预期 Unix 25、Windows 24。默认 CLI target 受 feature gate 可为 0-test harness，不能计新 CLI 通过。这些均为源码计数；本报告没有将它们报告为已经执行的测试结果。

## 8. 已亲读的原生阻断与结论范围

发现 C1-FMT-1：**验收阻断，格式 gate 失败；不是已发现的状态安全漏洞。** 我独立通过 GitHub job-log 工具获取并完整读取 `wallet (ubuntu-latest)` job `105656510131` 的日志。它实际 checkout 上述 C1 synthetic `bd710cf4...`，该 commit 的 tree 已独立绑定 C1；Ubuntu 24.04.5、Rust 1.98.1 (`48a229cea 2026-09-01`) 执行 `cargo fmt --all -- --check`，输出 7 文件 / 30 个格式 diff，最终 exit code 1。

| 文件 | 原生格式 diff 数 |
|---|---:|
| `pool/active/package/tests.rs` | 7 |
| `pool/active/package.rs` | 3 |
| `pool/active.rs` | 1 |
| `pool/active_flow_tests.rs` | 1 |
| `pool/recovery/active/package/tests.rs` | 11 |
| `pool/recovery/active/package.rs` | 4 |
| `tests/active_incremental_package_cli.rs` | 3 |

所读完整日志没有 cargo test、running N tests 或 test result。该格式失败不能当成测试通过，也不能因为 shell step 同时打印了后续 metadata/diff 命令便认定它们已执行。本任务没有审完 C1 所有 runs/jobs，不能据这一个 job 声称其余全部 job 的终态或完整 native 覆盖。完整原生审核由对应独立任务另行完成并保留失败历史。

该 job 原件：`c1-storage-fmt-job-105656510131.log`，40556 字节，SHA-256 `247217a4771742d0e14f66222cc6e9657d1969e290c3052272a44c9e5a927080`，保留 connector decoded content 的 UTF-8 BOM 与原换行。不是抓包原始 HTTP bytes。修复应严格按该输出对冻结 C1 应用格式变化，再用新候选完整回归；我未修改这些文件。

本地 `git diff --check base C1` 成功仅表示 diff whitespace，没有本地 cargo/rustc/rustfmt/go，未执行编译、Clippy、真实 CLI、付款、Windows、磁盘满或掉电实验。前阶段测试和作者自查不提供 C1 新通过信用。源码逻辑审核未见额外阻断，但准确 C1 因已知 fmt 失败不可验收。后续 C2 需新的候选审核原件，并以其真实默认/funded Rust、fmt/Clippy、Go test/vet/race/fuzz、增长、资源和四节点 CI 结果关闭 native gate。

本报告不批准部署、状态快照导入、pruning/migration、钱包/验证者签名状态恢复、真实资金或任意敌对 OS/FS 原子快照；不等于外部专业安全审计。P2 整体仍在开发。本轮设计 PASS、静态代码 PASS 和失败中的 native gate 各自独立记录，不可相互替代。

## 9. 可复核原件

所有下列文件位于 `/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package/`：

- `c1-storage-review-scope.json`：9047 字节；SHA-256 `88d691f2d92b91da7f20884c6144355f8ffc9396ec15d8405dd068e4fa747001`，记录独立 Git/API 身份、12 文件 blob/bytes/hash、881 未改 entries、源码计数及准确已读单 job 原生边界。
- `c1-storage-pr-api.json`：3656 字节；SHA-256 `442fb421056a4e369be265dc01b2a9cad3f44092b29426aa99b79566c679feae`，connector structured PR 对象的明确格式化 JSON，不称原始 HTTP bytes。
- `c1-storage-head-api.json`：1121 字节；SHA-256 `af7d6a6a279f3fbf88bf5e6b5e34da72570529c1eea2953498f6266b44b33599`。
- `c1-storage-base-api.json`：3105 字节；SHA-256 `4fa3cdb1568a9888f122ca131a0a438a73a9e72238ac95b384a2579d658cd4a9`。
- `c1-storage-synthetic-api.json`：2569 字节；SHA-256 `6c2af59ee7af5b30baf7d5e2ff776c1fcf1ae84fb9001b17d77578aa52c49f9d`。
- 上述三个 Git API JSON 保留 connector 的 decoded content 精确 UTF-8 字节，不进行 newline 改写；其身份与本地固定 Git 对象交叉核对。
- 原设计审核 `design-storage-review.md` 保持不变：14683 字节；SHA-256 `acb078f95d2d73dcac85060b382b698443d5690af5073f0f0005a5b7dbe00f26`。其 PASS_DESIGN 不包含本次代码/native 范围。
