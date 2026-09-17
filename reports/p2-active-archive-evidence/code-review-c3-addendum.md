# C3 独立代码审核补充：stdout 失败合同未满足

记录时间：2026-09-17。审核者：非作者独立审核代理 `/root/p2_archive_review`。本补充只读核对 C3 的 Git 对象、原生日志与 Rust 官方源码，没有修改候选或运行测试。

**结论：C3 不可接受，存在必须修复的验收阻断 AR-C3-02（Medium）。** 原 `code-review-c3.md` 的静态审核结论遗漏了 Rust 标准输出对 EBADF 的特殊处理；我承认此漏检。原件及 observation JSON 保留原字节，本补充记录后验反证，不覆盖旧记录。C3 的静态 PASS 不能作为本阶段通过或合并依据。

精确对象：source `7045af4ae254f0a5a5e4810f17004c91e649e474`，tree `4017bee976c18767ed568d7ec8a33f6d668b8c22`，stage base `6913d4ab2fda6956db37e0ceb49790a4518c2762`。冻结设计仍为 SHA256 `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee`，第 152 行明确要求 stdout 失败返回非零。

证据为 Ubuntu funded interfaces 原生日志 `c3/job-105131817273.log`，76073 字节，SHA256 `64c3e286d1f0ba3ed339d3047793b2e6190ea056a0c2b1f9bc037b06d6ff53bb`。新 `active_recovery_cli` 共 7 项，6 passed / 1 failed；`active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable` 在 `tests/active_recovery_cli.rs:106:5` 的首个断言 `!output.status.success()` 失败，09:07:51 UTC 记录该结果。其后 cohort 标记 `FUNDED_COHORT_NOT_COMPLETED`，job exit 1。不能由此日志宣称该 cohort 后续目标或本阶段全部门槛通过。

C3 `run_active` 使用 `std::io::stdout().lock()` 后的 `write_all` 和 `flush` 返回值决定成功。测试确实把 stdout 绑定到 `File::open` 获得的只读 OS 文件句柄，子进程却成功退出。Rust 官方源码显示，`StdoutRaw` 的写入与刷新经由 `handle_ebadf`，该函数把匹配的错误转换为调用方提供的成功结果；Unix 对此错误的识别就是原始 OS EBADF。这解释了为何仅对这两个 `Result` 使用 `?` 无法落实该失败合同。此处是结合官方实现与实际失败得出的因果分析，未声称对 CI 所带 libstd 二进制逐字节鉴定。[Rust std/io/stdio.rs 官方源码](https://doc.rust-lang.org/src/std/io/stdio.rs.html#139-208)、[Rust Unix stdio 官方源码](https://doc.rust-lang.org/src/std/sys/stdio/unix.rs.html#46-94)。

断言执行边界必须保留：`failure` 首个状态断言已经 panic，因此该次失败测试没有执行随后 stdout 文件内容不变、源目录字节不变、完整目标字节相等、目标 `verify-active`、再次创建同目标拒绝及最终目标不变的断言；连 `failure` 内后续 stdout/stderr 断言也未到达。不能把测试名称或后面的代码当成这些性质已通过的证据，也不能据此断言此次目标必定完整或不存在。

修正应使 active CLI 的实际 OS 输出错误可见并返回非零，继续保留创建后回执失败时的目标和源字节语义；不得把上述非零断言放宽为成功。修复需对精确新候选独立复审并取得新的 Linux / Windows 原生验收。本补充没有 C4 结论，也未验证待修实现。

保留的原件：`code-review-c3.md`，14909 字节，SHA256 `7c864c3e9288c4dbae9149fc9bddec3de9113926a014ff6c092c2d5db12b05cf`；`code-review-c3-observation.json`，7955 字节，SHA256 `2a21882b231dbd935b57057e3325fe9fcadf0532d9f3b52946d537b66707d0a1`。
