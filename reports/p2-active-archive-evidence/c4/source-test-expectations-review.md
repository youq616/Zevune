# C4 stdout 修复的静态测试预期独立核对

任务：`/root/p2_archive_native_audit/source_expectations`，未编写候选。

- base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`
- parent/C3：`7045af4ae254f0a5a5e4810f17004c91e649e474`
- C4 source：`50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`
- C4 tree：`3c44977028b58ddd387f52946632af594208edfb`
- PR：[#13](https://github.com/youq616/Zevune/pull/13)
- 父任务交接的预期synthetic：`fb5ec39a59cb87aec0662c7706dce1f9e85e1962`；实际checkout/tree/parents仍由原生及API证据核对。

**准确C4静态挂载、修复调用链和测试预期已完成核对；此范围未发现阻断。尚未审核C4原生日志，不是C4编译/CI/阶段验收PASS。** 读取全部来自准确 `git show` 和完整 C3→C4 diff，没有读取作者工作树或执行测试。

C3此前的默认两日志仅获得默认范围通过；其Ubuntu funded CLI实际6pass1fail，cohort未完成，C3整体不接受。该事实与原件哈希已另存 `../c3/default-native-evidence-review.md`，不会被C4源码修复改写为C3成功。

## 修复与既有行为

Git diff精确只有 `src/bin/zevune-pool-recovery.rs` 和 `tests/active_recovery_cli.rs` 两文件。新active receipt helper持有stdout锁，使用OS句柄的owned duplicate转换为File，再write_all/flush，错误传至原main的exit1。Unix采用AsFd/OwnedFd，Windows采用AsHandle/OwnedHandle并先拒绝null；不会把原stdout交给File析构关闭。其他平台明确失败关闭。此处仅作源码调用/所有权核对，真实OS行为须由原生双平台回归证明。

自动逐字节比较确认原 `fn run(args:` 至文件末尾保持一致，包括命令参数解析、legacy输出与main错误退出；改动限于active receipt路径。全部workflow、依赖、锁文件、存储/资源预算、库测试、growth测试和冻结设计均未改。

## 第七项真实CLI回归

`active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable` 仍为同一个第七项测试，C4第696行起。其他六项及共同helpers除新增Write import外逐字节不变。

1. 先把真实 `verify-active` 子进程stdout定向到新建可写文件，读回文件，使用既有success helper核对精确JSON与成功状态；同时保留其余用例通过捕获pipe的成功路径。
2. 依次执行真实 `checkpoint-active`、`verify-active`、`backup-active`、`restore-active`。每次先用实际只读File尝试write_all并要求错误，证明fixture拒绝写入，再将这个句柄作为子进程stdout。
3. 四个模式逐项要求 `output.status.code() == Some(1)`，另检查既有failure helper、sink内容和source完整文件字节保持不变。
4. backup及restore分别留下完整准确目标；各自使用正常stdout运行独立实际 `verify-active`，要求成功。restore确实以先前备份目标为source，未用源目录冒充备份恢复。
5. 全部结束再次检查两个完整目标；既有备份重试不能覆盖已有目标的断言保留。

没有新增测试函数、cfg、ignore或早退；两个真实 `build_payment` 调用保持原样，未增加昂贵付款证明。

## 保持不变的运行预期

模块链仍为 `lib→pool→recovery→active→#[cfg(test)] tests→namespace_tests`，增强growth由原funded library挂载。新增库预期Ubuntu18／Windows17，CLI仅在 `local-funding-lab` 下各7项，默认CLI仍0项。默认完整library预期139／132、默认含其他targets总153／146，与C3源码未改的测试定义对应；这是C4预期，不把C3日志当成C4执行。

Cargo目标仍为1lib、5bin、14integration；funded interfaces完整19目标另doc，library完整`--lib`。调度器无test-name过滤，所有旧目标仍在原生执行要求内。完整funded总计与每个实际用例仍以准确C4日志为准；第七项内四mode/正向对照不能累计成额外测试数。

需在准确C4 Ubuntu/Windows日志看到 `active_recovery_cli` 七项全部实际ok、目标7passed/0failed、后续全部targets和doc完成，以及 `FUNDED_COHORT_COMPLETE interfaces`。新段互换依旧要求完整funded growth在两平台实际ok。独立源码预期和原始失败历史不代替运行成功证据。

准确C4全测试名、行号、feature/platform、源码哈希和差异说明保存在 `source-test-expectations.json`，46252字节，SHA-256 `4e7c7d5c8673df2cf3f39bf5e379a80758dd80f3e1c81d6a35daa5d67254d74c`。C1/C2/C3静态原文与C3默认日志审核共七份原件哈希均保持不变。
