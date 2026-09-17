# C3 原生证据审核：CLI stdout 故障回归未通过

任务：`/root/p2_archive_native_audit`，未编写候选运行代码、测试或 workflow。
结论：**REJECTED_NATIVE_CLI_REGRESSION**。C3 不接受，不得合入为已验收阶段。

- PR：<https://github.com/youq616/Zevune/pull/13>
- base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`
- source：`7045af4ae254f0a5a5e4810f17004c91e649e474`
- tree：`4017bee976c18767ed568d7ec8a33f6d668b8c22`
- synthetic checkout：`11402e8d8db1e2ae9b6d8615ea9f6362e8676606`

source 与 synthetic 的 Git 对象及 parents/tree 见 `source-identity.json`；已保存日志的实际
checkout 与 synthetic 一致。准确源码、PR 合并检出和实际 main 合并是不同身份。

## 直接原生阻断

funded-wallet-consensus 的 Ubuntu interfaces job **105131817273**，run **35199878279**，
check-run 完成时间 `2026-09-17T09:07:53Z`，结论 failure。直接 job steps 显示格式、锁文件
及包含 funded Clippy 的步骤已成功，失败于 `Complete binary, integration and documentation tests`。

实际入口为 `python scripts/run_funded_rust.py interfaces`。它按 metadata 选择全部 5 个 bin、
14 个 integration targets 并计划另跑 doc；本次实际 cargo 命令及完整计划保存在
`native-audit-rejected.json`，命令没有筛测试名称或忽略失败。

进入新增 `active_recovery_cli` 后，前六项均实际 `ok`，包括
`active_cli_real_payment_backup_restore_and_receiver_spend` 的两笔真实付款及备份恢复。
第七项 `active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable` 失败：

```text
thread 'active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable' (9964)
panicked at tests/active_recovery_cli.rs:106:5:
assertion failed: !output.status.success()
test result: FAILED. 6 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out;
finished in 137.53s
FUNDED_COHORT_NOT_COMPLETED: CalledProcessError
##[error]Process completed with exit code 1.
```

准确 C3 的测试把一个真实只读 OS 文件句柄指定为子进程 stdout，然后调用共同的
`failure` helper；该 helper 的首个非零进程状态断言没有成立。
**直接证据仅证明该 fixture 调用返回了成功状态。** 日志没有给出 stdout OS errno、实际写入
错误或生产根因，不能把它描述成归档复制失败、目标被删除或某种已确认系统错误。
共同 helper 在这里 panic，因此后续目标字节/后验验证断言不获得本次执行信用。

失败原件 `job-105131817273.log`：**76,073 B**，SHA-256
`64c3e286d1f0ba3ed339d3047793b2e6190ea056a0c2b1f9bc037b06d6ff53bb`。
完整 UTF-8 原件含 BOM、全部运行输出与 runner cleanup；未用摘要替换原文。
该 cargo 调用实际取得 6 个 harness 结果，总计 20 pass、1 fail，其中新增 CLI 为 6 pass、1 fail。
没有 `FUNDED_COHORT_COMPLETE interfaces`。其余计划目标、doc、后续独立 bins build、
Python/Rust互操作及该 job 的 funded 四节点步骤不能记为本次通过。

## 已取得成功范围与未完成边界

此失败不意味着所有 C3 测试均未运行或失败。当前已保存 **6 份成功 PR job 完整日志和 1 份
失败日志**，共 **412,261 B**，全部原件清单在拒绝 JSON 中。

Ubuntu orchard-bridge job105131816333 的默认库139项、全部默认153项通过；Windows wallet
job105131816703 的默认库132项、全部默认146项通过，失败/ignored/filtered 均为0。
新增默认库18／17项已逐名取得实际 `ok`，两平台默认 fmt／Clippy 亦完成。
默认 `active_recovery_cli` 目标为 cfg 排除的0 tests，不能计作 funded CLI七项通过。
consensus-laboratory 双平台、Windows scaffold 和 Windows operator 的完整成功日志也已保存。

09:08:27 的 check-runs 快照观察到21个已实例化 PR jobs：7 success、1 failure、5 in_progress、
8 queued；第七个 success 的 Ubuntu wallet 当时仅有完成元数据，未另下载其完整日志。
完整预期门槛仍为10个PR工作流／23个任务；另外两个growth任务依赖source，尚未据本快照取得
完成证据。root指示C3保留已取得证据及失败，后续候选重新完整验收；不必等C3全部历史任务。

工作流列表曾返回 queued，同时某个矩阵成员的原始日志已证明实际运行或完成。所有这类
queued 信息只作为工具/API返回状态观察，不能推导全部成员实际未开始；不推测其机制。
原生时间优先使用日志与具体 job/check-run 完成元数据，并分别保留观察时间。

同源 push Windows orchard-bridge job105131805112 单独观察到 cancelled，起止元数据为
08:29:49–08:50:01 UTC。没有推断取消原因，没有下载重复 push 日志，也没有由本任务取消运行。
它不与必需 PR 任务合并计数，亦不被改写成成功。

任何修复必须形成新准确 source/tree 并重新通过必要原生测试和非作者审核。上述默认成功、
CLI六项成功和旧候选静态审核都不能替代下一候选的完整验收。
