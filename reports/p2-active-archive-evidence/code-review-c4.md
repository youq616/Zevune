# P2 活动账本归档与完整恢复：C4 非作者独立代码审核原文

审核任务：`/root/p2_archive_review`。记录日期：2026-09-17；本地身份／字节观察时间为 09:21:46 UTC，随后独立核对 GitHub synthetic commit。

**结论：PASS_CODE_REVIEW。准确 C4 的完整阶段代码与测试设计审核通过，本次未发现未关闭的代码审核阻断。** 历史 AR-C1-01（两个已有活动段交换的覆盖缺口）及 AR-C3-02（真实 stdout 写入失败却成功退出）已在 C4 代码和测试设计层面复核关闭。**此结论不表示原生执行成功或阶段已接受；仍须取得准确 C4 的完整必需 CI，并独立验收其实际结果。**

我没有编写或修改该候选的设计、源码、测试、工作流或依赖。此次重新检查 stage base..C4 的全范围实现和相关调用方，不以 C3 原初静态 PASS 自动继承。C3 后验失败及我对 StdoutRaw EBADF 的漏检已另存 `code-review-c3-addendum.md`，旧原件保持不变。

## 精确对象与取证范围

- 仓库 `youq616/Zevune`；[PR #13](https://github.com/youq616/Zevune/pull/13)。
- Stage base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`；base tree：`5e039b41e00f7a0a2e78937c796a40fbe68bfb0c`。
- C4 source：`50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`；tree：`3c44977028b58ddd387f52946632af594208edfb`；唯一 parent 为 C3 `7045af4ae254f0a5a5e4810f17004c91e649e474`。
- PR synthetic：`fb5ec39a59cb87aec0662c7706dce1f9e85e1962`。本地没有这个 Git 对象，第一次 `git rev-parse synthetic^{tree}` 实际退出 128。随后使用 GitHub plugin 的只读 Git commit API 独立取得 tree 与两个 parents，确认 tree 等于 C4，parents 顺序为 stage base、C4 source；不声称本地验证过该对象。
- 冻结设计 `docs/ACTIVE_ARCHIVE_V1.zh-CN.md`，13188 字节，SHA256 `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee`，与已独审的设计对象相同。

实际检查十个变更文件的 Git blobs、工作树原字节、长度、SHA256 与 HEAD/tree/parent，工作树干净。全阶段共十文件，2770 insertions / 28 deletions；C3→C4 仅 CLI 及其现有第七项集成测试两文件，90 insertions / 22 deletions。源码核心、布局、旧 API、设计及其余测试未因输出修复改变。

详尽清单与实际／未执行项目保存在 `code-review-c4-observation.json`，8674 字节，SHA256 `9608eadbabc493e66e88090c2a576f0fa8cd69a9b7c11cb8ddec9575f1cbce9a`。GitHub API 原响应保存在 `code-review-c4-synthetic-github.json`，2570 字节，SHA256 `0668331800cdd71258d9c091b4ef8cb94e6992996e7a43505340c7f1681ada36`。

## AR-C3-02：输出失败的真实合同

严重性 Medium，原 C3 的验收阻断。C3 Ubuntu funded interfaces 原生日志显示新 CLI 7 项中 6 passed / 1 failed，失败点在 `failure` 的首个 `!output.status.success()` 断言；这不曾证明后续源／目标字节检查或目标 verify 已执行。原日志与边界详见 C3 addendum；我保留承认原静态审核漏检的记录。

C4 增加仅供 active 命令使用的 `write_active_receipt`：取得具名 `StdoutLock`，从其借用 FD／Windows handle 执行 `try_clone_to_owned`，再将新 OwnedFd／OwnedHandle 转移给 `File`，通过该 File 执行 `write_all` 和 `flush`。失败都返回 `Err(())`，沿原 main 统一错误分支退出 1。所写报告为非空 ASCII JSON；不存在空写掩盖错误的路径。

具名 stdout guard 在函数作用域内保留至 File 写入／刷新完成或错误返回，源码未提前 drop 它。File 只拥有新复制的句柄，析构不会关闭原 stdout；没有 unsafe、从裸句柄强行取得所有权、重新按路径打开输出、提升访问权限或新增依赖。CLI active 分支在此前没有待刷新的 stdout 成功文本，也不混用旧输出分支。

官方合同核对结果支持这一修复路径：Unix `BorrowedFd::try_clone_to_owned` 建立共享同一底层文件描述的新所有者；Windows 相应方法采用 `DUPLICATE_SAME_ACCESS`，File 接管复制句柄。标准 File 的写入直接返回底层写入结果，不经 StdoutRaw 的 `handle_ebadf` 成功替代。相关文档当前显示 Rust 1.98.1。[Rust BorrowedFd](https://doc.rust-lang.org/std/os/fd/struct.BorrowedFd.html#method.try_clone_to_owned)、[Rust Windows handle 源码](https://doc.rust-lang.org/src/std/os/windows/io/handle.rs.html#192-230)、[Rust File 写入实现](https://doc.rust-lang.org/src/std/fs.rs.html#1389-1433)、[Microsoft DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)。这是源码／合同分析，不是本任务对新二进制的实际运行证明。

Windows 借用 stdout 允许 NULL，官方 clone 实现也会把 NULL 转成成功的空 OwnedHandle；C4 在复制前明确拒绝 NULL。其他不能使用的句柄由 clone 或实际 File write 返回错误。没有把 Rust 句柄中的 -1 一概等同于无效文件句柄；该值在 BorrowedHandle 中可能是进程伪句柄，但不能据成功复制就免除真实非空写入。没有把重定向报告的 flush 声称为磁盘持久化或接收端已经读取的确认。[Rust BorrowedHandle 合同](https://doc.rust-lang.org/std/os/windows/io/struct.BorrowedHandle.html)。

新测试仍是同一第七项实际可执行文件测试，修复没有放宽旧失败断言：

1. 用真正可写 OS 文件承接 `verify-active` 回执，要求退出成功、stderr 为空，并从该文件读回准确完整 JSON；其他 CLI 测试继续覆盖真实捕获管道成功。
2. 每次先对 `File::open` 的真实只读句柄执行非空写探针，必须得到错误，再把这个句柄交给实际子进程作为 stdout。fixture 无法写的事实不会仅由注释推定。
3. 顺序执行 checkpoint-active、verify-active、backup-active、restore-active，逐一要求 `status.code() == Some(1)`，再验证统一错误文本、没有捕获成功输出、stdout 文件不变和原源目录字节不变。
4. backup 与 restore 必须留下准确完整副本，并通过随后 stdout 正常的独立 `verify-active`；restore 以刚完成但失去回执的 backup 为源。最后再次检查两个目标原字节，并保留已有目标拒绝覆盖的检查。

代码路径、测试正控制和执行顺序足以关闭此代码／测试设计问题。C4 的这七项新 CLI 测试及整个 interfaces cohort 必须原生实际通过，才能把 AR-C3-02 的执行验收条件关闭。没有专门运行 Windows detached-console NULL fixture 或任意异步句柄组合；当前静态 NULL 检查及标准同步文件／管道 fixture 不等于所有输出环境均实测。

## 全阶段恢复实现复核

**独立 genesis 与 profile。** 普通 active open 由独立 initial commitments、domain 和固定 profile 构造预期头，实际文件与其比较，再把预期头 SHA 传入共享 replay。归档传入独立 pin.genesis，已有 store 导出传入 committed State.genesis。共享方法以本次真正读取头重建 State，并明确比较 expected_genesis。待恢复目录不能自行升级 legacy 或自行声明可信域。

**物理头、EOF 和逐帧。** 先只从持有的 genesis 文件解析，限制真实捕获头长并要求真实 EOF；再建立逻辑 reader 并比较两次头的长度、initial、domain。每条 Replay 完整记录都调用 validate_frame，拒绝跨段拆帧与提前轮换；各物理文件和逻辑流都检查实际 EOF。失败的 unpublished State 不发布，finish 必须已经耗尽，再核对 namespace。原读句柄克隆不重复加锁。

**真实授权和状态。** 每次完整 replay 新建 AuthorizationVerifier，其构造确实创建新的空 VerifiedCache。实际 Replay 调用原 State::from_storage_policy、next_block、execute_unpublished、finish，继续执行签名域、授权／证明、锚点、双花、输出、费用和前后 AppHash 检查。旧 verifier 的缓存成功不会认证新归档；拒绝历史不会修改 live committed State、PreparedBlock 或钱包保留项。

**新 pin 与布局。** 私有字段、准确 128 字节、ZVARCP01 与三个非零 hash 保留。高度 ≤ 1000000、总长 ≤ 1 GiB、段数 ≤ 2048、头长 76 加 32 倍数及 MAX_COMMITMENTS 上限、height0/零段/精确头长关系、最少 150×height 和段数×1 MiB 上界均先于外部文件操作验证。checked 算术与短路头长范围阻止 underflow；C3 的 is_multiple_of 修订仍保持等价边界。

布局严格为 ZVARLY01、u32 原头长、原头、u32 段数，再逐段 u32 序号、u32 长度、原字节。没有路径／时间字段，没有 MANIFEST，没有以 hash 列表替代原字节。摘要和复制都按 64 KiB 缓冲显式偏移读取，检查捕获长度、真实 EOF、metadata 与前后目录清单。新 pin 仍须独立保留，不能证明来源、最新高度或网络 finality。

已独立再算固定 Python hashlib 向量：76 字节头 SHA256 `07782393f4021cabba3a8a09f0d2747e6ae4404457475c6e9df85100f734bc1e`，92 字节布局输入 SHA256 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`，与测试硬编码一致。这是实际字节计算，不记作 Rust 测试通过。

**导出与 verify。** 导出在前后 layout 检查之间做全新真实重放，对照整个 committed Summary 和 length，最后检查 pin bounds。PreparedBlock 保持；不支持 profile 先返回 Bounds，不 poison 健康 legacy；实际历史／身份错误按原规则使 store 不可用。ActiveArchive 的每次 verify 同样先核对完整 bytes、完整 replay、全部 tip 字段、再核对 bytes，不暴露可写 State。

**句柄、名称和复制。** 普通 writer 的读写句柄与 genesis 独占锁继续保留；归档源只读并用共享根锁，保留目录及全部文件。Unix device/inode 与单硬链接规则、Windows no-DELETE-sharing / reparse 拒绝及严格连续八位 journal 清单继续成立。目录的未知项、空段、缺号、链接或非普通文件不能被静默忽略。

copy_new 先检查源持有句柄绑定，验证绝对目标、已存在父目录和 canonical source/parent，拒绝源内／父别名与任何已有目标；完整源 verify 后才非递归创建。Unix 目录 0700，文件 0600，create_new；目标 genesis 在第一次复制前获取独占锁。每个文件复制后 sync_all，Unix 同步目录及父目录。目标完整 replay 使用原创建且持续持锁的句柄，不释放后从路径重开。

复制后先完整验证目标，再完整验证源，最后核对目标完整原字节／namespace 后才返回 pin。失败不删除、截断、覆盖、修补或重试目标。复制返回的只有 pin，不启用运行节点。克隆可能共享游标，但物理头显式 rewind、摘要／复制显式偏移、流程串行，原 append 继续显式 seek 到尾部；不存在假称并发快照的新增 API。

## AR-C1-01 及全部测试职责

再次完整检查 C4 的真实两段交换样本，确认新增覆盖仍在活动归档路径。它复用正常提交到 10001 的两个真实物理段，不降低 1 MiB 阈值，也不增加模拟记录或跳过授权。交换完整原文件后先要求原 pin Corrupt；然后重算布局 pin，直接用生产 ActiveJournal::layout_hash 确认相等，释放临时源句柄／共享锁，解码交换后的首条真实记录，证明其 base_hash 不等于 genesis 初始 AppHash，再要求公共 ActiveArchive::open 对新 pin 仍 Corrupt。两轮均检查原源与坏候选字节不变。

因此交换后的拒绝层明确为原 pin 的布局不符和新 pin 的真实历史链不符；不是 Authorization，也不能用旧 ZVPSEG01 交换样本替代。独立坏签名样本另行翻转真实付款 binding signature、重算 record checksum 与完整 layout pin，明确要求 Authorization；未重算旧 hash 或锁失败不能冒充这一检查。

其余测试职责已复核：codec 全截断、尾字节、hash/边界、零高度；无段及普通目录精确 backup→restore；导出保留 prepared work；同长真实历史替换和原持锁句柄同长 genesis 更改；物理头借段攻击、错 profile/network/domain/curve point；repin 后分帧、提前轮换、错后状态、尾字节；已有／相对／缺父／源内目标拒绝；六个私有复制失败点覆盖部分写入、写完未 sync、同步后失去确认、最终源／目标额外项。

实际双进程锁测试包含 writer→reader 冲突、多个 reader 共存、最后 drop 后 writer 成功；Unix 文件／目录持久替换、软硬链接与父别名；Windows rename/delete 拒绝至最后 reader drop 后的正控制；错误打开释放全部句柄。只读源测试在 Windows 先确认写打开 access-denied，防止把根锁错误当成只读权限证据。Linux 静态阅读不替代 Windows 执行。

真实增长 fixture 先以正常 prepare/commit/write/sync 空块填充，首次真实非零付款触发生产 1 MiB 轮换，随后实际归档并恢复到新目录；在该恢复目录继续至 10001 并做第二跳真实付款，再精确归档／恢复并正常提交 10002。恢复前后 state、capacity、重复付款拒绝、钱包余额／费用均有断言。CLI 另有低高度真实非零 A→B→C 路径，B 首次接收扫描发生在恢复目录。空块数量没有被称为同数量真实付款或吞吐结果。

## 旧调用方和不变范围

四个新命令明确区分 profile 和新 pin；checkpoint-active 使用独立 TestGenesis::read_pinned、03 profile、可信准确 height/AppHash；备份与恢复都调用同一个 copy_new。缺失／重复／未知参数、非规范 hex/height、相对路径继续拒绝。活动 JSON 保留 replay_verified true 与 finality_verified / validator_ready / real_funds_allowed false，错误文本不泄漏用户路径。

旧 CLI 分支、成功 JSON 和旧 ZVPRCP01、ZVPSEG01、派生索引 API 未重解释。recovery.rs 的实际候选修改只有导出新独立模块。新增 File 输出函数只被 active 分支调用。Go CopyStorageAtCheckpoint 对 active 拒绝的路径没有变动；没有网络入口、自动迁移或 signer-state 恢复。

已通过 Git 对比确认 .github、scripts、internal、integration/cometbft、Cargo.toml/Cargo.lock、go.mod/go.sum、AGENTS/STAGE_REVIEW，以及真实 verifier、Replay、TestGenesis 和旧 segments 模块均与 stage base 无差异。读取 funded 调度器，interfaces 从 Cargo metadata 收集全部 bin/test 目标再执行 docs；新增 CLI 没有被配置过滤，原 cohort 没有缩减。编译、proof/state 规则、容量与依赖仍须由原生完整门槛实际验证。

## 实际检查、限制与验收边界

本任务实际做了源码／测试／设计读取、Git 身份与十文件字节检查、官方 API 合同核对、历史失败日志核对、独立固定 hash 复算和 whitespace 检查；没有安装工具链，没有执行 Rust 编译／测试、cargo fmt、Clippy、Go test/vet/race/fuzz、Linux／Windows 原生执行或 CI 重跑。没有把测试定义、作者声明或旧候选结果记为 C4 通过。

`git diff --check base..C4` 实际 exit 2，唯一诊断为冻结设计第 185 行末尾新空行；排除此冻结设计的全部源码／测试范围 exit 0。此为非功能观察，不解冻或改写原设计，也不表述完整范围毫无诊断。

C1 native 格式失败、C2 native Clippy 失败、C3 native stdout 失败均保留历史原件。C4 的格式／Clippy／锁定构建、Ubuntu/Windows 默认与 funded 全 library/interfaces，以及既有 Go、100000 块、32+1 资源和四节点回归仍须对当前候选实际完成。特别是新 stdout 第七项必须走到字节／verify 后续断言并通过；仅重新得到前六项成功不能关闭验收阻断。

可信父目录、操作系统及文件系统仍是前提；不保证任意恶意瞬时替换再还原。最多 2048 段加 genesis／目录及整套 replay 克隆句柄的成本保留，1 GiB 是逻辑容量而非整机预算。全部历史／内存成本、真实断电或磁盘满、Windows 目录持久化、全容量、增量／快照、钱包及完整验证者恢复、外部安全审计均未由本阶段完成。P2 仍属开发中，NO-FUNDS 边界保持。

本结论仅绑定 C4 source `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736` / tree `3c44977028b58ddd387f52946632af594208edfb`。后续任何运行代码或测试修改均需新准确提交复审。当前为独立代码审核 PASS、原生／阶段验收待完成；不是零缺陷承诺或外部机构安全审计。
