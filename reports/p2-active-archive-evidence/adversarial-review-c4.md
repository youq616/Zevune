Zevune P2 活动账本归档：C4 独立对抗复审原文

结论：**PASS（准确 C4 的独立代码与测试设计复审；不是原生 CI 通过证明）。** 本次覆盖完整阶段 base..C4、相关调用方、全部新增测试与冻结不变量。未发现仍需阻止该代码候选合入的已知缺陷；AR-C1-01 的段交换测试源码缺口保持关闭，AR-C3-02 的 stdout 错误传播缺陷已由 C4 的实际输出路径修复，并保留、强化原失败条件。准确 C4 的原生测试和其完整日志认证仍是独立且必需的阶段门槛，本报告不宣布阶段已接受。

审核任务 `/root/p2_archive_adversarial_review`；日期 2026-09-17 UTC。本人没有编写、修改或格式化候选源码、测试、设计和工作流；没有用另一审核者的结论替代判断。审核只读 git 对象、候选文件、既有原始失败日志和官方技术资料，执行了独立 Python 摘要复算及只读 git 检查。仅新增本报告及配套 JSON。

| 身份 | 精确值 |
|---|---|
| 仓库 / PR | [youq616/Zevune PR #13](https://github.com/youq616/Zevune/pull/13) |
| 阶段 base | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| 准确 C4 source | `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736` |
| C4 tree | `3c44977028b58ddd387f52946632af594208edfb` |
| 第一父提交 C3 | `7045af4ae254f0a5a5e4810f17004c91e649e474` |
| 父任务提供的 C4 PR synthetic | `fb5ec39a59cb87aec0662c7706dce1f9e85e1962` |
| 冻结设计 SHA-256 | `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee` |

source、tree、parent 已由本地 git 独立核对，审核起止工作区均干净。synthetic 对象不在本地对象库，表中值明确来自父任务，不能当作本人核实了 CI checkout 或合成树。审核依据是准确 C4 source 的树。

**历史原件与已知运行反例。** C1 原审查为 REQUEST_CHANGES；C3 的初始静态 PASS 随后被原生反例纠正，独立补充明确 REQUEST_CHANGES、C3 未接受。这些原件均保留原字节，不能将这次 C4 结论倒写成 C3 已被接受。

| 原件 | 字节 | SHA-256 |
|---|---:|---|
| `adversarial-review-c1.md` | 12848 | `1b2f12b42dffb0a5bd5bea9c7f48945062534d46580c43ea194b9d6766b9b915` |
| `adversarial-review-c3.md` | 12629 | `127d9ef1b798aeb008542e58af6241a8efe24799cba59ef2014bc4ec7c7f0f2b` |
| `adversarial-review-c3-addendum.md` | 7094 | `abf56bdc75c9f1db074f1b04085330a8a9746fe409a3585f49ea385e441b5437` |
| `c3/job-105131817273.log` | 76073 | `64c3e286d1f0ba3ed339d3047793b2e6190ea056a0c2b1f9bc037b06d6ff53bb` |

上述日志属于 C3 Ubuntu funded interfaces：checkout `11402e8d8db1e2ae9b6d8615ea9f6362e8676606`，合成说明为 C3 合入上述 base；active CLI target 为 6 passed、1 failed，失败断言位于通用 `failure()` 第一条 `!output.status.success()`。所以该次执行没有到达其后的 stderr/stdout、源/目标字节、显式 verify 和已有目标重试断言。C3 的这些后验断言不能被记为运行通过。配套 JSON 还记录并核对了 C1/C3 两份 JSON 原件的长度和 SHA-256。

**AR-C3-02 / P2：C4 代码层关闭；准确 C4 原生回归待认证。** C3 标准 stdout 的 `write_all` 会经过 Rust 的 `handle_ebadf`：Unix 只读 fd 写入产生的 EBADF 在到达 CLI 的 `map_err` 之前被转成成功，随后 stdout flush 也可成功。这是实际回执路径的错误传播问题，不能仅更换测试 fixture 来掩盖。[Rust 标准 I/O 源码](https://doc.rust-lang.org/src/std/io/stdio.rs.html)、[Rust Unix 标准 I/O 源码](https://doc.rust-lang.org/src/std/sys/stdio/unix.rs.html)

C4 的 `integration/orchard/src/bin/zevune-pool-recovery.rs` 第 53 行新增私有 `write_active_receipt`，第 123 行由四个 active 命令共同调用。它在整个写入期间持有 StdoutLock，通过安全稳定的 AsFd/AsHandle 借用并复制成 owned 句柄，再转换为 File 直接 `write_all`。复制及直接写错误均传到既有失败路径；owned 副本析构不关闭原 stdout，没有 unsafe、重开路径或新依赖。Windows 显式拒绝 NULL，因为标准 owned handle 实现允许复制 NULL 成功；没有把“复制完成”等同于可写。[BorrowedFd](https://doc.rust-lang.org/std/os/fd/struct.BorrowedFd.html)、[Windows owned/borrowed handle 实现](https://doc.rust-lang.org/src/std/os/windows/io/handle.rs.html)

File 的写入不经过 stdout 的 EBADF 容错层；它的 flush 在 Unix/Windows 当前是无额外动作的成功返回。因此本报告确认的是直接写的 OS 错误传播，绝不把该 flush 称为回执文件 fsync 或下游已经消费回执的保证。另经 GitHub 插件读取 Rust 1.98.1 官方 Windows 源码：File::write 委托 Handle::write，而 Windows stdio 在 UTF-8 控制台及非控制台也调用同一 Handle::write。当前 active JSON 只含固定 ASCII、数字和十六进制，没有新增非 ASCII 终端转换需求；交互控制台未由本人实际运行。[Rust File 写与 flush 实现](https://doc.rust-lang.org/src/std/fs.rs.html)、[Rust 1.98.1 Windows File](https://github.com/rust-lang/rust/blob/1.98.1/library/std/src/sys/fs/windows.rs)、[Rust 1.98.1 Windows stdio](https://github.com/rust-lang/rust/blob/1.98.1/library/std/src/sys/stdio/windows.rs)

C4 第七个 CLI 测试 `active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable` 从第 696 行开始，保留真实只读 File 作为子进程 stdout，并增加以下实质断言：

- 先将 `verify-active` 的 stdout 重定向到真实可写新文件，从文件重新读回准确成功 JSON；这是其他用例捕获管道之外的文件正对照。
- 分别执行 checkpoint-active、verify-active、backup-active、restore-active；每次先用将被继承的同一 File 做实际失败写探针，证明测试条件确实拒绝写入，再启动真实 CLI。
- 四次都明确要求退出码 `Some(1)`，排除用 panic 或信号退出充当正常 CLI 失败；继续执行原 stderr、无泄漏及 sink/source 原字节断言。
- 对 backup 和 restore 分别核对完整目标字节，再以良好 stdout 的独立命令显式 verify；循环后检查两个完整目标，并保留已有目标不可覆盖的重试负例。

这没有移除原失败条件、隐藏测试或把回执失败改成删除目标。目标在回执之前已经完成认证与同步，之后输出失败仍非零，完整目标可留下，符合冻结合同。这是源码控制流与断言完整性判断；C4 的上述后验断言只有真实原生日志成功记录才算运行证据。

**AR-C1-01 / P2：段交换源码缺口保持关闭。** C4 的 `active_flow_tests.rs` 与已复审 C3 字节完全相同，第 599 行起仍使用真实正常提交到 10001 后已经存在的两段，交换它们的完整原字节。原 pin 明确 Corrupt；`repin_layout` 经公开 codec 构造新 pin，实际生产 layout_hash 与其字段相等后释放这组检查句柄；再解码交换后的第一条记录，要求其高度为首次真实付款高度且 base_hash 不等于 genesis 初始 AppHash，随后新 pin 仍明确 Corrupt。Replay 在真正执行前比较前序 AppHash，与该拒绝层一致。两次失败后原源和交换目录字节不变，随后原正常恢复及 10002 提交继续。没有新增证明、缩小段容量或以旧 hash 不匹配冒充重放拒绝；精确候选 funded library 运行仍另需认证。

**完整阶段范围和调用方。** base..C4 为 10 文件、2770 行新增/28 行删除；C3..C4 仅 CLI 与 CLI 集成测试两文件、90 行新增/22 行删除。18 个已读取范围文件均与准确 git 对象及工作区匹配，其中其余 16 个与已审 C3 字节相同。复审覆盖冻结设计、PoolStore 普通 open/共享 replay、ActiveJournal 物理存储、旧 recovery 挂载、新 pin/archive、底层既有 namespace 与 Replay/AuthorizationVerifier、全部新增 core/namespace/CLI 测试、扩展的真实增长测试以及 funded target 计划。完整路径、各自 SHA-256 和测试源码名称在 JSON 中逐项保存。

完整不变量复核结果如下；这是准确源码的结论，不是测试运行计数：

1. **独立 pin 与有界 codec。** ZVARCP01 准确 128 字节、私有字段、三个非零摘要、1000000 高度、1 GiB 逻辑容量、2048 段、03 头长和 32 字节对齐、零高度关系、150×高度记录下界及段容量上界齐全。固定长度先检查再切片，checked 减乘避免接受回绕值；C3 的 is_multiple_of 保留短路减法保护，固定除数非零。旧 120 字节 pin、ZVPSEG01 和 legacy 不被重新解释。

2. **物理 genesis 与当前来源绑定。** 从保留 genesis 内按捕获长度单独解析，要求实际物理 EOF；伪造 commitment count 不能借用第一 journal 段。逻辑头字段必须一致，真实 State 构建后必须匹配调用方独立 expected_genesis；普通 open 来自预期头，导出来自已拥有 store，归档来自独立 pin。不是只在第一次开文件时比较。同 inode 同长度头修改用例不靠 Windows 锁失败解释来源拒绝。

3. **完整真实重放。** 三种调用使用共享 replay_active_handles，每次创建新 AuthorizationVerifier；逐条真实 Replay 执行并验证物理帧完整、规范轮换，末尾 require_eof/finish/namespace 成功前不发布状态。归档不返回可写 State/PoolStore。签名损坏测试重算 record checksum 和完整 layout pin 后明确 Authorization；错误后状态、错头、跨段拆帧、提前轮换及尾字节用例保留正确拒绝层。

4. **已提交状态与反复检查。** 导出对整个 committed Summary、genesis、容量和重放前后原字节进行核对；PreparedBlock 不被消费、修改或认证。legacy 不支持先拒且不 poison，真实错误使活动 store 不可用。archive 每次 verify 重做 bytes、真实重放、tip 和末次 bytes/namespace，不把旧成功或缓存当花费授权。

5. **规范 layout 独立复算。** Python 按文档编码重算固定 76 字节 header，SHA-256 为 `07782393f4021cabba3a8a09f0d2747e6ae4404457475c6e9df85100f734bc1e`；92 字节布局输入的 SHA-256 为 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`，与固定向量一致。它仅证明编码一致性，不能证明来源、授权、最新高度或 finality。

6. **源权限和锁。** 源只读句柄加 genesis 共享锁，writer 仍独占；reader 克隆不重复加锁。双进程探针启动真实当前 test 可执行文件、exact 名称、检查 `1 passed`，避免零测试成功；两个读者及剩一个读者期间 writer 被拒，最后 drop 后有成功正对照。只读源测试在 Windows 获取任何锁前实测写打开 error 5，然后归档并在正常可写目标提交。这些平台行为需实际 runner，不能由 cfg 源码代替。

7. **名称与替换。** Unix 使用目录/文件 dev、inode 和 nlink，拒绝 symlink、多硬链接、未知、缺号和非普通文件。Windows 保留无 DELETE 共享及 reparse 保护句柄，目录附加 BACKUP_SEMANTICS；没有用时间戳和长度伪造身份。Windows 负例检查原文件可写，两个/一个读者时实际 rename/delete 拒绝，全部 drop 后同操作成功；失败 open 释放句柄有正对照。其合同依据与既有实现一致。[Rust Windows OpenOptionsExt](https://doc.rust-lang.org/std/os/windows/fs/trait.OpenOptionsExt.html)、[Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[Microsoft LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)

8. **创建前验证与不可覆盖。** 先验证源路径与原句柄绑定、绝对目标、可信 canonical 父目录、源内/别名目标及已存在目标，再完整验证源。底层非递归建新目录及 create_new 文件，Unix 0700/0600；没有 overwrite、truncate、删除、修复或自动重试。非法源在建目标前失败；创建后错误允许留下新目录，错误文案不声称它不存在。

9. **原目标句柄认证。** 首次写 genesis 前获取独占锁，64 KiB 有界缓冲逐文件复制准确原字节，逐文件 sync_all、Unix 同步目标及父目录。目标首次全验直接持有原创建句柄，期间无 unlock/drop/reopen；之后重新全验源，再对目标末次 bytes/namespace 检查，才返回原 pin。没有释放锁后改用路径认证另一个对象。

10. **偏移、EOF 与失败状态。** 摘要和复制显式偏移；物理头 clone 后 rewind；ActiveReader 每个文件独立逻辑偏移；append 明确尾部 seek。Windows 克隆游标共享不会依赖偶然顺序。短读继续、Interrupted 重试，捕获长度后的真实 EOF 必查；I/O 失败 reader 持续失败关闭，错误 Replay 的隔离状态不能被续用认证。

11. **中断及末次检查。** 私有 cfg(test) 故障 1/2 留部分 genesis/段；3 仅有过程可见完整字节、未完成最后同步；4 在同步之后但无成功确认。完整目标后验 verify 的设计不等于断电持久性证明。5/6 在不同末次检查前增加未知目录项，必须 Corrupt；它们确实改变目录集合，只保证原文件字节保留。生产没有注入开关或弱化验证路径。

12. **真实恢复与兼容范围。** 真实增长 fixture 在首次付款触发第二段后备份/恢复，恢复目录继续第二跳至 10001，再次恢复后提交 10002；CLI fixture 两笔真实非零付款，收款方扫描实际恢复历史后花费，并检查重复花费和余额。四个新命令要求绝对路径、规范小写 pin/高度和 NO-FUNDS，03 manifest/trusted tip 绑定完整；旧命令、旧 JSON、旧 Go 活动 profile 拒绝保留。新增测试挂载且进入现有 funded 全 library/interfaces 计划，没有改 runner、工作流、锁定依赖、协议限制、32+1 资源测试或四节点测试来绕开门槛。

本次测试源码清单为新核心 12 个、namespace 7 个（Unix/Windows cfg 不同）、新 funded CLI 7 个；原 active_flow 4 个测试保留并扩展。上述是源码名称计数，本报告不计入任何 C4 native 成功数。特别是第七个 CLI 用例没有新增 ignored、平台豁免或修改 cohort 过滤。

**未测限制与阶段边界。** 本地 rustc、cargo、go 均不可用；本人没有编译、cargo fmt/Clippy、Rust/Go 测试或实际 Windows 执行，没有认证 C4 CI 日志。只读 `git diff --check base..C4` 退出 2，仅报告已冻结设计第 185 行的结尾空白行；它是非运行的文档空白提示，原字节保持不变，不能写成所有工具检查通过。C4 本次静态结论不继承 C3 的 CI 结果，也不自动适用于后续代码或测试修改。

独立 pin 不证明归档来源、最新性或共识 finality；这是完整公开历史复制，不是钱包、签名状态、共识数据库/WAL、快照或剪枝恢复。可信父目录、OS 和文件系统仍是前提，未证明任意恶意瞬时替换、映射视图干预、真实断电/磁盘满或 Windows 目录持久化。源和目标各可持有最多 2048 段句柄，reader 再克隆；全容量句柄、整机内存和归档性能没有新增测量，不能复用旧 32+1 指标作保证。P2 仍在开发中，不能标为验证者就绪或允许真实资金；独立编码代理复审也不是外部机构安全审计。
