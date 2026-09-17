# C3 默认 Rust 原生日志的独立范围审核

审核任务：`/root/p2_archive_native_audit/source_expectations`。未编写候选。此原文直接检查下列原始日志，未以父任务派生摘要替代日志，未执行或触发测试。

- source：`7045af4ae254f0a5a5e4810f17004c91e649e474`
- source tree：`4017bee976c18767ed568d7ec8a33f6d668b8c22`（准确源码静态记录；不是日志独立输出的tree）
- base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`
- PR：13；两默认日志实际checkout均为 `11402e8d8db1e2ae9b6d8615ea9f6362e8676606`。

**结论：PASS，仅限所列两份默认 Rust 日志范围。C3 整体 NOT ACCEPTED：准确C3另有实际 funded interfaces 失败。不能把本范围通过替代 funded cohort 或阶段验收。**

## 原件身份

| 原件 | 字节 | SHA-256 |
|---|---:|---|
| job-105131816333.log（Ubuntu orchard-bridge） | 75,567 | `0ec080116464eee89985b82231ebae02f8d421cbed8021ecd0fbdb33cd25f3a1` |
| job-105131816703.log（Windows wallet） | 59,931 | `cec1e6f132a4780722b0e2874e91a048e6a8a47c0847c16f75b0e8fb98eb14de` |
| job-105131817273.log（Ubuntu funded接口失败，有限检查） | 76,073 | `64c3e286d1f0ba3ed339d3047793b2e6190ea056a0c2b1f9bc037b06d6ff53bb` |

以上原件实际bytes/SHA全部复算一致。没有修改日志或`source-test-expectations`原文。

## 默认执行证据

两个日志fetch精确synthetic SHA到`pull/13/merge`，checkout merge message为完整C3 source并入完整base，随后`git log -1 --format=%H`仍为该synthetic。日志本身未输出synthetic tree与parent对象；完整Git对象/API身份属于父任务证据，不在此日志结论中虚构。本地检查该synthetic对象不可用，没有fetch。

| 核对 | Ubuntu 105131816333 | Windows 105131816703 |
|---|---:|---:|
| 默认library实际具名用例 | 139 | 132 |
| Library结果 | 139 passed；0 failed/ignored/measured/filtered | 132 passed；0 failed/ignored/measured/filtered |
| Library原始报告时间 | 674.96s | 854.98s |
| 新增active archive库逐名`ok` | 18/18 | 17/17 |
| 完整结果份数 | 18：17个harness＋doc | 18：17个harness＋doc |
| 完整默认结果passed合计 | 153 | 146 |
| active_recovery_cli默认目标 | 0 tests | 0 tests |

准确C3源码提取的全部新增测试名已与原始单行`test <full name> ... ok`逐一比对，每个只出现一次；Ub新增位于日志505—522行，Win新增位于398—414行。包含新真实跨进程锁、只读源、部分/完整故障副本保留、最终source/target namespace和Windows真实rename/delete释放测试。两平台共同12项一般测试，namespace为Ubuntu6项/Windows5项；各自不适用cfg在编译阶段排除，不是被忽略后声称通过。

完整库平台集合差为11项Unix-only与4项Windows-only，全部与准确C3的对应cfg相符；其中新增差异是两个Unix替换/父别名用例和一个Windows释放用例，其余为原有平台用例。没有无法解释的用例缺失。

默认18份结果为1lib、2个无需funded feature的binary、14个integration、1doc。三个要求`local-funding-lab`的binary不在默认执行清单。所有18份结果均实际`ok`且failed/ignored/measured/filtered全0。`active_recovery_cli`仅0tests；此处没有给CLI七项、真实funded growth或段互换断言任何执行信用。

两平台日志实际输出 `rustc 1.98.1 (48a229cea 2026-09-01)`。`cargo fmt --all -- --check`及锁定metadata位于`bash -e -o pipefail`步骤，完整进入后续test步骤，没有fmt/error退出。两份默认Clippy命令均为`cargo clippy --locked --release --all-targets -- -D warnings`，实际Finished分别9.37s与16.57s，随后clean-source检查与正常post cleanup。Ubuntu另有普通锁定worker build Finished0.06s；此项不套用于Windows wallet工作流。此处未把Ubuntu该日志额外Go结果扩展成整个Go矩阵结论。

原始日志时间跨度，均为2026-09-17 UTC：

- Ubuntu：首行`08:45:30.8522201Z`，最后一行`09:00:39.6835274Z`；library从`08:47:42.9220944Z`开始计数，到`08:58:57.8861833Z`输出结果。
- Windows：首行`08:33:55.2142840Z`，最后一行`08:52:59.0797173Z`；library从`08:37:34.2722923Z`开始计数，到`08:51:49.2134259Z`输出结果。

## C3 必须保留的 funded 失败

另直接核对`job-105131817273.log`的哈希、checkout、target及失败段。它同样checkout C3 synthetic；调度计划包含全部19个interfaces目标和独立doc命令，但计划不是完成结果。实际`active_recovery_cli`七项中前六项（包含真实付款备份/恢复/第二跳）为`ok`，第七项 `active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable` 为`FAILED`。

原件第807—808行：panic位于`tests/active_recovery_cli.rs:106:5`，断言为`!output.status.success()`。第815行准确结果为`6 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 137.53s`。第818—819行输出`FUNDED_COHORT_NOT_COMPLETED: CalledProcessError`并以exit1结束；不存在`FUNDED_COHORT_COMPLETE interfaces`。后续目标/doc不以调度清单代替实际执行。

失败时间为`09:07:51.8971696Z`用例FAILED，`09:07:51.9063785Z`步骤exit1。此原文没有诊断根因，也不把随后候选修复推断为本候选通过。准确新候选必须重新取得独立审核与原生证据。

完整源码测试预期另见本目录`source-test-expectations.json`及`source-test-expectations-review.md`。本范围审核不替代整个23-job矩阵、funded两cohort、独立代码安全审核或外部专业审计。
