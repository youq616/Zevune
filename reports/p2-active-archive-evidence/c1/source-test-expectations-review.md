# C1 源码测试预期独立核对

审核任务：`/root/p2_archive_native_audit/source_expectations`，未编写该候选。

- base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`
- source head：`c5f60ac440ac39032f8f8efefc2fbfbf6e299a90`
- source tree：`10fb6d729c610aa1c935c96891c99e05f81d7dd1`
- PR：[#13](https://github.com/youq616/Zevune/pull/13)

结论：**本任务完成只读测试挂载、目标枚举及关键断言核对，未发现此范围内的静态阻断。此结论不是编译、测试、原生 CI 或候选验收 PASS。** 所有候选读取均通过准确提交的 `git show`，没有读取作者正在修改的工作树，也没有运行 Cargo、触发 CI 或轮询 GitHub。父任务告知 C1 原生 fmt 失败并准备 C2；失败日志由父任务审核，本记录不认证 C2。

## 准确测试清单与平台条件

完整测试全名、C1 行号、平台、feature 和冻结验收点逐项列于 `source-test-expectations.json`。库挂载为 `lib → pool → recovery → active → #[cfg(test)] tests → namespace_tests`；`active_flow_tests` 另有 `test + local-funding-lab` 条件。

| 新增范围 | 源码函数数 | Ubuntu 实际运行预期 | Windows 实际运行预期 | feature |
|---|---:|---:|---:|---|
| active/tests.rs | 12 | 12 | 12 | 默认与 funded |
| namespace_tests.rs | 7 | 6 | 5 | 默认与 funded |
| active_recovery_cli integration | 7 | 7 | 7 | local-funding-lab |

namespace 为 4 项双平台、2 项 Unix、1 项 Windows；因此新增库测试是 Ubuntu18／Windows17。funded 新增独特测试数为 Ubuntu25／Windows24，默认与 funded 的重复执行不能相加当作新覆盖。默认 CLI 被文件级 cfg 排除，零用例不能称七项通过；这些文件没有 `#[ignore]`。

## funded 自动调度

准确 C1 的 Cargo 清单和源文件结构预期有 1 个 lib、5 个 bin、14 个 integration target，共20。`active_recovery_cli` 是顶层自动发现 integration；`tests/support/fixtures.rs` 和 `src/bin/operator_support/timing.rs` 是辅助模块，不是独立 target。

`run_funded_rust.py` 从启用 `local-funding-lab` 的 `cargo metadata --no-deps --locked` 获取清单。library 使用完整 `--lib`；interfaces 为全部 bin/test 名称逐一添加 Cargo 目标参数，共19目标，并另跑 `--doc`。只对目标进行分组，没有测试名称过滤；未知/禁用目标、未选 feature、关闭 doctest、重复目标或错误 workspace 均失败。所有 subprocess 使用 `check=True`，全部命令成功后才打印相应 `FUNDED_COHORT_COMPLETE`。两平台两个 cohort 均由 workflow 直接运行，保持每个 job30分钟原限制。

此处清单是**源码推导预期**；原生 Cargo metadata、每个目标实际结果及完整并集仍须由父任务的准确候选日志确认。

## 关键冻结断言

1. 12 项新库测试覆盖精确128字节codec、所有截断/尾字节及结构边界、独立固定layout hash向量、创世与提交状态精确复制、PreparedBlock保留、profile不poison、同长历史与genesis变化、重算pin后物理头/帧/状态拒绝、目标独占、6类私有故障及最后验证。
2. namespace 测试使用真实独立子进程检查独占writer与共享archive，检查多个读者及最后drop释放。Unix涵盖链接、文件/目录持久替换和父别名；Windows真实rename/delete在最后读者释放前失败、释放后成功，含正向对照。不能将子进程重复的单项测试结果累加到顶层library总数。
3. 增强的 `pool::active_flow_tests::real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` 保留默认1MiB段容量：6963次正常空提交后，真实付款在6964高度触发第二段；准确 source→archive→restored 后，普通恢复writer继续到10001并提交真实第二跳付款。10001再次生成pin、准确归档恢复，再到10002；保留重复拒绝、容量、钱包历史、pending和余额/手续费守恒断言。只有两笔真实付款，不把其余空块称为同等数量的付款。
4. `pool::active_flow_tests::active_profile_domain_rejections_preserve_bytes_reservations_and_legacy_contract` 实际调用增强 helper：破坏真实付款binding signature，重算record checksum和完整layout pin，普通open与ActiveArchive::open均明确要求 `PoolError::Authorization`，且原文件字节保留。其有效未改控制可正常验证。CLI损坏用例保留原pin，只获得失败关闭覆盖，不单独获得授权层拒绝信用。
5. 七项新CLI测试启动 Cargo 提供的真实 recovery 可执行文件。真实付款用例中 Bob 首次收款扫描来自恢复目录，再构造第二跳付款；另验证零段、严格参数/exact tip、跨进程锁、profile/旧JSON、损坏目标创建前拒绝及真实只读stdout句柄失败后完整目标仍可显式验证。

## 原生验收保留条件

父任务仍需核对每个预期用例的实际 `ok`、目标并集、完整日志与准确源码/checkout身份、原有100000块、32＋1、四节点及全部Go和静态要求。本任务未执行测试，不替代非作者代码审核。C2如仅格式修正，须先核对准确新head/tree和所涉源码差异，再决定本记录可复用的部分；不得直接给C2套用C1身份。

私有故障不证明实际断电、磁盘满或Windows目录持久化。任意瞬时替换再还原、全容量、增量备份、快照及验证者签名状态恢复均不在本结论内。

JSON 原件：`source-test-expectations.json`，32025字节，SHA-256 `7a5d254e983907adf54f6c4bf96b4d2499c19d204dc7b4a42b384445dba48f74`。
