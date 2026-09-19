# P2/P7：活动账本增长诊断（调用边界计时）

起点：`356b68eacab59111df575bab75e664fce90aed18`（PR #22 已合入）。
本文件定义测试观测合同，不是阶段验收或外部安全审计结论。
准确候选、代码树、原生执行、独立审核及是否合入，以本阶段 PR 为准。

## 问题和本轮范围

[Issue #23](https://github.com/youq616/Zevune/issues/23) 记录 Windows 十万块增长测试
首次在第 99634 块 Commit 超时，而同代码、同工作量、同预算的一次诊断复跑成功。
原失败和未知根因继续保留；本轮不是靠增加超时、减少区块或重复求绿来“修复”。

本轮只修改测试和 CI，增加调用边界计时、进度证据及观测器自身的反向测试。
不改变生产 worker、钱包、IPC、锁、目录完整性检查、密码学或同步写入策略。
保持原 100000 块（99998 空块、2 个真实付款块），完整重放后继续到 100001；
保持 20 分钟场景 context、25 分钟 Go 超时、原启动/请求预算及工作流预算。
所有原有状态、容量、物理帧、双花拒绝、钱包恢复和余额/费用断言保留。

## 统计什么

`ACTIVE_GROWTH_OBSERVATION` 是固定 schema 的公开 JSON。各阶段记录完成次数、
累计纳秒及单次最大纳秒；按同一进程内的 `time.Now` / `Sub` 单调时钟测量。
计时区间不嵌套，不把失败调用或未完成调用计入成功累计值。

| 阶段 | 含义 |
|---|---|
| setup / funded_start | 测试目录准备及真实场景子进程启动、初始就绪检查 |
| worker_create / boundary_worker_replay / full_worker_replay | 实际 worker 的创建、付款边界重开、十万块完整重开 |
| payment_prepare / outbox_recovery | 实际付款准备调用及精确 outbox 重开验证，分别计时 |
| finalize_empty / finalize_paid | 空块与付款块的 Finalize 往返和原返回值检查 |
| commit_empty / commit_paid | 空块与付款块的 Commit 往返和原返回值检查 |
| boundary_select_preview / pending_checks | 原选择、预览、伪标签拒绝以及不改变状态的断言组 |
| scenario_apply / wallet_balances / wallet_history_recovery | 独立场景重放、余额（含相邻容量检查）及钱包全历史恢复 |
| spent_rejection / worker_close / physical_check / state_checks | 原重复支付拒绝、显式关闭、物理帧核对及状态/容量核对 |

这些数值是 **Go 调用边界的整体开销**。Commit 包含 IPC、worker 内检查和存储操作，
并不是 fsync 独立耗时；段轮换、命名空间检查、磁盘同步、CPU 时间和证明初始化内部
分项尚未单独测量。先用这些统计定位慢在哪个调用组，再确定内部剖析范围。
不能用空块平均值代表支付 TPS、支付延迟或四节点共识性能；不提供虚构的 p95。

## 部分进度和失败

只有 Commit 成功返回且原 Summary 相等检查通过后，才增加 `last_confirmed_height`。
Finalize、预览或生成付款都不算提交；`attempted_height` 与确认高度分别记录。
合法 Commit 尚未通过返回值检查时终止，记录 `commit_outcome_unconfirmed=true`，
不能推断该块一定写入或一定没写入，也不自动重试。

`pending` 保存固定阶段名、公开高度及截至观测点的经过时间。若 FailNow 后清理耗时，
此经过时间可能包含清理等待，**不是一个已完成调用的精确延迟**。相应 completed、
total_ns、max_ns 不增加。时钟倒退或越过观测范围时标记 measurement_valid=false，
未知经过时间为 null，而不是把它编造成零。

最终报告在最后一个 `t.Cleanup` 执行，能看到先前清理产生的测试失败。
`checks_completed=true` 还要求原测试走到最后的实际断言、确认高度为 100001、
无未完成操作，并满足付款/空块次数、两次物理检查、完整重放、钱包恢复等观测清单。
所有五个进度检查点都必须发布。计数清单只验证观测接入，不代替原真实密码学检查。

硬 Go 超时、进程强杀或宿主丢失可能阻止最终 cleanup 执行。这时只保留此前检查点，
最后检查点只是已确认进度的下限；缺少 final.json 不能报告场景完成。
即使文件中 checks_completed=true，也必须同时核对准确提交的整个 CI 作业成功；
写入/同步证据失败会令作业失败，部分文件不得单独用作验收。

## 有界证据与身份

CI 在工具链安装前创建 setup.json，记录准确 source_head、checkout_commit、
checkout_tree、平台、run_id、run_attempt 和所需工具链；execution_started=false
只描述最初观测，不表示后续测试成功。所需版本不等同于已执行版本，实际工具链以日志为准。

测试在初始、25000、50000、75000、100000 高度分别创建 checkpoint-0.json 到
checkpoint-4.json，另创建 final.json。每份至多 16 KiB，共六份；setup.json 至多 2 KiB。
阶段统计只占固定数组，不保留每块事件或所有交易。旧文件和失败部分写入均不覆盖。
CI 的 always 上传步骤只列出这七个固定文件，artifact 名含平台、checkout SHA 和 attempt，
不上传测试目录、钱包、交易字节、子进程原始输出或其他文件。

新增 JSON 不含口令、种子、密钥、地址、交易明文、原始错误文本或本地私有路径。
输出目录来自 CI 的专用 RUNNER_TEMP；本地可使用 ZEVUNE_GROWTH_EVIDENCE_DIR 指定
已存在的专用绝对目录（目录自身不能是符号链接），不设置则仅输出有界日志。
仍假设可信本地文件系统；没有新增恶意父目录、Windows ACL、物理磁盘损坏或断电保证。

GitHub 的复跑视图可能以新 job ID 引用旧成功作业。对比时间、attempt 与日志，
不能因为 ID 变化便虚增实际执行次数；不要删除原失败来美化结果。

## 验证命令与后续

观测单元测试（不需要 worker，不是十万块真实执行）：

```text
cd integration/cometbft
go test -mod=readonly ./poolapp -run '^TestGrowthObservation' -count=1 -timeout=60s
go vet -mod=readonly -tags=pool_e2e,funded_e2e ./poolapp
```

Linux 增加同一组测试的 -race 检查；CI 两平台使用固定 Go 1.27.1。
实际增长命令仍是原 TestActiveSegmentedLedger100000BlocksBoundaryPaymentsAndRestart，
使用真实 Rust 1.98.1 构建的两个可执行文件，工作量和超时不变。
观测器反向测试包含真实子进程 FailNow、清理失败、Go 硬超时、缺失/重复检查点；
辅助入口在普通发现时跳过，由父测试实际启动，不把跳过项计为通过。

本轮是 Issue #23 的第一步诊断接入。即使原生回归通过，也不能关闭“未知超时根因”问题，
不能宣称长期稳定性、完成 P2 全部里程碑或批准真实资金。NO-FUNDS 及原 ready/audited/
real_funds_allowed 边界保持不变。
