Zevune P2 活动账本归档：C3 独立审核补充原文

结论：**REQUEST_CHANGES；C3 未接受。** 原生 CI 提供了先前静态检查没有识别的真实反例：active CLI 在 stdout 指向只读文件句柄时可以退出 0，而没有成功写出回执。这违反冻结设计的“stdout 失败返回非零”合同，记为 **AR-C3-02 / P2：active CLI 回执错误传播缺陷**。必须修复运行输出路径并通过准确后续候选的独立复审及原生测试，不能仅修改测试来规避该条件。

审核任务 `/root/p2_archive_adversarial_review`；补充时间 2026-09-17 09:12 UTC。本人未参与候选实现，没有修改代码、测试、工作流、冻结设计或既有审核原件。本次补充仅依据准确 C3 git 对象、实际失败日志及 Rust 官方源码。本文不对 C4 或任何尚未审核的后续候选作出结论。

| 身份 | 准确值 |
|---|---|
| 仓库及 PR | [youq616/Zevune PR #13](https://github.com/youq616/Zevune/pull/13) |
| 阶段基线 | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| C3 source | `7045af4ae254f0a5a5e4810f17004c91e649e474` |
| C3 tree | `4017bee976c18767ed568d7ec8a33f6d668b8c22` |
| C3 第一父提交 C2 | `7477d9e0656ed751f525a4b6fe9f6649b995ede6` |
| 失败 native job | `105131817273`，Ubuntu funded interfaces |
| 日志中的实际 checkout | `11402e8d8db1e2ae9b6d8615ea9f6362e8676606` |
| 日志中的合成提交说明 | Merge C3 `7045af4ae254f0a5a5e4810f17004c91e649e474` into base `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| 完整原始日志 | `c3/job-105131817273.log` |
| 原始日志字节 | `76073` |
| 原始日志 SHA-256 | `64c3e286d1f0ba3ed339d3047793b2e6190ea056a0c2b1f9bc037b06d6ff53bb` |

日志本地绝对位置为 `/workspace/scratch/1753b04c9dbb/zevune-p2-active-archive/c3/job-105131817273.log`。我读取了 checkout 身份及该失败用例相邻记录，并计算完整日志的长度与 SHA-256；本补充不代替 native auditor 对全部 job、步骤或源树的汇总认证。

原静态审核原件不改写：

| 原件 | 字节 | SHA-256 |
|---|---:|---|
| `adversarial-review-c3.md` | 12629 | `127d9ef1b798aeb008542e58af6241a8efe24799cba59ef2014bc4ec7c7f0f2b` |
| `adversarial-review-c3.json` | 16155 | `d151ef84e2e9aa35fdef9f07b3530651d53025ba222b70b950dfd1521253c825` |

这两个文件记录的是取得本次原生日志之前的静态审查及 AR-C1-01 段交换测试源码缺口关闭。原件明确未运行或认证 CI；它们不能当作 C3 阶段已接受的证据。更具体地说，先前对 stdout 错误传播路径的静态肯定没有识别 Rust 标准输出对 EBADF 的特殊处理，被这次运行反例纠正。保留原件是保留审查历史，并不意味着在已知反例后继续允许 C3 合入。

**实际观察。** 该日志在 2026-09-17 09:02:42 UTC 记录合成 checkout；09:05:34 开始 `active_recovery_cli` 的 7 个测试；09:07:40 记录 `active_cli_real_payment_backup_restore_and_receiver_spend ... ok`；09:07:51 记录 `active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable ... FAILED`。失败位置是 `tests/active_recovery_cli.rs:106:5`，断言为 `!output.status.success()`。该测试 target 最终为 **6 passed、1 failed、0 ignored、0 filtered out**；funded cohort 随后报告未完成，job 退出 1。

该用例将真实 `File::open` 得到的只读句柄作为子进程 stdout，调用 `backup-active`，并预期命令非零。失败位于通用 `failure()` 的第一条断言，所以该次运行没有继续执行其后的 stdout/stderr 检查、sink 字节检查、源/目标字节不变检查、目标显式 verify 以及已有目标拒绝重试断言。因此不能把 C3 的这一失败用例记为“完整目标保留已经实测通过”。账本复制能够走到输出路径是控制流分析；那些后验断言的实际运行成功需要修复后的证据。

**独立根因分析。** C3 的 `run_active` 在归档操作成功、JSON 构造完成后调用标准 stdout lock 的 `write_all` 和 `flush`，每个返回错误都映射为命令失败。这里没有漏写 `?`，问题在被调用的标准 I/O 抽象：Rust 1.98.1 官方 `std/io/stdio.rs` 中，StdoutRaw 的 write、write_all 等方法经过 `handle_ebadf`；其底层错误满足 `stdio::is_ebadf` 时，标准输出返回成功值。Unix 对只读 fd 的普通写会产生 EBADF，而 Unix stdio 的 flush 自身直接成功。于是错误在到达 C3 的 `map_err` 之前已经被转换，命令走成功退出路径。该机制与实际非零断言失败一致。[Rust 标准 I/O 源码](https://doc.rust-lang.org/src/std/io/stdio.rs.html)、[Rust Unix 标准 I/O 源码](https://doc.rust-lang.org/src/std/sys/stdio/unix.rs.html)

缺陷分类是运行回执错误传播，而不是密码学或账本恢复失败。测试注释对“只读 OS 句柄写入会直接传到 std::io::stdout 错误”的假设不成立，但不能因此只把该测试换成另一种会被 stdio 传播的错误。冻结合同要求 stdout 失败非零，原测试构造的 OS 条件真实存在；换测试会留下这个已知的零退出反例。

**保持合同的修复建议，尚非候选批准。** 可以在 active 回执路径保持 StdoutLock，以稳定安全 API 将其借用 fd/handle 复制为 owned 对象，转换成 File 后直接写完整 ASCII JSON，借此绕过标准 stdout 的 EBADF 容错。复制、直接写和必要的 flush 错误均应传回原来的非零失败路径；不能关闭原 stdout、重开路径、删除已完成目标或重试复制。Unix 的 BorrowedFd::try_clone_to_owned 保留同一底层 file description；Windows 的相应 API 保留同一对象，并使用相同访问权限。这些 API 已稳定，不需要新的 unsafe、依赖或修改旧命令。[BorrowedFd 官方合同](https://doc.rust-lang.org/std/os/fd/struct.BorrowedFd.html)、[BorrowedHandle 官方合同](https://doc.rust-lang.org/std/os/windows/io/struct.BorrowedHandle.html)

Windows 还有需要明确检查的细节：官方实现允许 NULL BorrowedHandle，并在复制 NULL 时返回 NULL owned handle，因此“复制成功”本身不证明 stdout 可写或存在。修复应显式拒绝该句柄，或用经确认的直接 File 写入行为可靠传播错误。应保留现有只读 stdout 测试，补充合适的正对照，并在 Ubuntu/Windows 上验证相同成功 JSON、真实付款恢复以及失败后目标保留。这里没有声称该建议已经实现或已通过测试。[Rust Windows owned/borrowed handle 实现](https://doc.rust-lang.org/src/std/os/windows/io/handle.rs.html)、[StdoutLock 官方接口](https://doc.rust-lang.org/std/io/struct.StdoutLock.html)

本地仍无 Rust/Cargo/Go，本人没有本地编译、执行子进程或写入候选 fixture。已执行的是只读日志/源码检查及文件 SHA-256 计算；实际运行反例来自上述准确 native job。AR-C1-01 在 C3 的测试源码关闭记录仍成立；新增 AR-C3-02 在本补充时尚未由任何已审核候选关闭。**C3 未接受，C4 及后续结果未知。**
