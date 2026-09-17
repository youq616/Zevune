# PR #11 资源证据与原生 CI 独立审核

结论：**REQUEST_CHANGES**。精确候选存在一项中等严重性的证据验收阻断；不能合入或标为本阶段验收完成。实际 Go 付款流程的恢复顺序正确，本阻断位于监督器对进度证据的校验。

审核任务：`/root/p2_resource_ci_review`。审核者未参与编写候选，未改动候选文件。独立 OS 子项辅助任务：`/root/p2_resource_ci_review/resource_os_probe_review`，同样未参与实现。审核记录时间：2026-09-17 05:16 UTC。

## 精确身份与范围

- Base：`8324ec8bd153d9502e3e6761d25bfe281a5f3b44`
- Head：`8f0de0df649a0bae719b7ced789d8fc0857ca475`
- Tree：`e861d8af54cc33735b82e796a20e301e10bea137`
- PR：<https://github.com/youq616/Zevune/pull/11>
- 审核开始时本地 HEAD 与上述身份一致，工作树 clean；测试期间相关三个 Python 文件 SHA-256 前后相同。
- 冻结设计：`docs/PAYMENT_RESOURCE_BASELINE.zh-CN.md`，SHA-256 `f8fb0f009423f26afbfb84ad2293b13dbe9581032c31ba0bfc379d224a91789f`。

完整阅读 `scripts/check_payment_resources.py`、`scripts/tests/test_payment_resources.py`、`scripts/tests/test_payment_resources_evidence.py`、`.github/workflows/payment-resources.yml` 及 `internal/poolbridge/payment_resource_e2e_test.go`。核对范围包括严格 JSON 字段与数值、进度配对和完成计数、事件与内存采样、创建身份/父 PID/代际、退出确认、失败落盘与 ACK、提交结果不确定性、共享截止时间、Go 事件/退出合同、原生构建标签、源提交与 checkout tree、失败 artifact 和旧工作流范围。真实 Orchard/钱包/Rust 状态实现由另一个未参与实现的审核任务主审，本记录不替代该审核。

候选文件指纹：

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `.github/workflows/payment-resources.yml` | 5225 | `d83634ff4aebac9befeec9c9dbaa554b75d8e2b3ba8368d39c3cb2fcc9a7b2eb` |
| `internal/poolbridge/payment_resource_e2e_test.go` | 31671 | `502688e6c43df3521f0d364391b1cfd0bddf35d4bffaa152db73352c76826da7` |
| `scripts/check_payment_resources.py` | 51269 | `b5e6a4bb7cbc05f980689b16173bb8b479bcb990f47aea42c26dda9b6c314d7d` |
| `scripts/tests/test_payment_resources.py` | 25332 | `e5bc0f08eaf76beb875ec3a90509503faeec60d44419fcdce8d034ecea792fb9` |
| `scripts/tests/test_payment_resources_evidence.py` | 16191 | `8ca328f8779cc40a7aa9433239e5e7e51c70b55a97201e3132dd188415ee1fcd` |

## 阻断 EVIDENCE-01：恢复操作顺序可被重排后仍通过验收

严重性：**中等，阶段验收阻断**。

位置：`scripts/check_payment_resources.py` 的 `checked_progress()` 与 `checked_result()`。前者校验单个 started/completed 对及其局部付款/高度；后者对五类逐笔 core 操作检查顺序，但用 `Counter` 比较恢复等 extra 操作。因此 extra 的出现位置不受全局序列约束。

实际复现使用候选自带的合成协议 fixture `progress_sequence()`，没有执行或伪造真实付款：

1. 取完整 362 条进度；将 `wallet_recover` 的 started/completed 整对移至第 33 笔 `prepare` 与 `outbox_restore` 之后、`candidate` 之前。
2. 重新连续编号，使用 `validate_progress()` 检查，再将相同 completed 记录放入 result timings，调用 `checked_result()`。
3. 另取完整序列，将标记高度 32 的 `worker_reopen` 整对移动到所有操作之前，执行相同校验。

本审核者独立执行所得输出：

```text
wallet_recover ACCEPTED progress 362 pending None
worker_reopen ACCEPTED progress 362 pending None
```

另一独立审核任务 `/root/p2_resource_review` 也单独报告并复现该问题。当前 Go 代码确实先重开 worker、恢复钱包，再 prepare 第 33 笔；问题在于监督器仍会给违反冻结恢复时序的完整证据返回成功，不能用现有校验支持“恢复后才新建第 33 笔”这一验收断言。允许恢复高度在进度前缀中提前跳至 32，也会削弱失败报告的已确认高度语义。

建议修复：固定完整 181 个操作的有序合同，逐条验证 362 条 started/completed 的合法前缀，并保留完整结束条件。未知、缺少、重排、重复或提前出现的恢复操作必须失败；失败时保留此前已验证前缀和最后未完成操作。补充上述两个实际负例，并针对合法中途终止、提交结果不确定性作回归。无需修改 Rust/Go 真实负载、旧测试或任何预算。修复后提交新 head，重新取得独立审核与相关原生验收。

## 已核对且未发现新增阻断的范围

- 事件限定九个固定 phase/高度/代际，精确字段与整数检查拒绝布尔数值、浮点、未知字段、重复 JSON 键、非有限数值和超限输入。最终结果限定 33 笔、68 commitments、66 nullifiers、33000 费用及完整 checks；成功不能仅依靠 Go 退出码 0。
- 有效事件与有效超额内存样本先保存，再执行预算判断。采样缺失、创建身份异常、报告保存失败均不能得到成功 ACK。未通过字段校验的内容不进入公开报告。失败保留有效 progress、unfinished operation 和最后已确认提交数；未完成 `worker_commit` 明确标记结果不确定，未完成 `scenario_apply` 不会被表述为已完成应用。
- Go 的提交操作在真正 Commit 成功后更新本地提交计数，再核对 Status/Capacity。若后续核对失败而 completed 记录尚未保存，监督器只能保守保留该操作 started 时的确认高度和 unknown outcome，不能据此声称 Commit 没有发生。`prepare`、`candidate`、`worker_reopen` 等包含多次 RPC，其组合耗时不等于单次请求耗时。
- Linux 通过固定 proc 目录描述符、启动 tick、父 PID 和 pidfd 保留身份，内存前后再次验证；Windows 使用保留进程 handle、父 PID、创建 FILETIME 与真实工作集接口。两代 worker 和一个 scenario 不混合身份或生命周期高水位。OS 辅助审查未发现新增阻断。[Linux proc 官方说明](https://docs.kernel.org/filesystems/proc.html)、[Windows 内存读取权限](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getprocessmemoryinfo)、[Windows 计数字段](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters)。
- 正常成功要求三个已登记进程对象均已退出；Go 同时检查正常 Close/Wait 路径的错误。监督器中的退出确认本身不是子进程零退出码证明。清理等待均使用原始 `started + 1230s` 的剩余时间，重试和 finally 不重新获得 30 秒。首次 checkpoint 前硬崩溃的未登记子树清理仍明确未确认，不声称完整进程树或进程沙箱保证。
- 新工作流为双平台 2 jobs，显式编译并 vet `payment_resource_e2e`，固定 Go 1.27.1、Rust 1.98.1、release/locked 与两个线程；监督执行固定测试名和 20 分钟 Go 预算。新增 glob 同时覆盖两个资源测试模块。相对基线，全部旧 workflow 文件保持逐字节不变；本轮源改动应继续触发旧 9 个 PR 工作流/21 jobs，加新增 1 个工作流/2 jobs。触发数不等于通过数。
- setup JSON 清楚限定为最初的 `not_started` 观察。执行报告现场读取 source head、checkout commit/tree，并校验 source tree 与 checkout tree 相同及 tracked clean；PR 合成 merge commit 不冒充源 head。
- artifact 只上传 `ci-results/payment-resource-setup.json` 与 `ci-results/payment-resources.json`，使用 `always()` 和缺失文件报错策略。普通目录已修复初稿隐藏目录问题；本审核通过 GitHub 插件独立读到固定 action SHA 的官方 README，核实其默认排除隐藏路径。该遗漏在预审初稿中未被本审核者发现，后由 root 修正；准确候选已包含修复。[固定 upload-artifact 版本说明](https://github.com/actions/upload-artifact/blob/ea165f8d65b6e75b540449e92b4886f43607fa02/README.md)。仅有 setup artifact 表示设置/构建早期观察，不能用上传成功宣称资源场景成功。

## 实际验证与限制

本审核者在候选文件哈希稳定期间执行：

```text
python -m unittest discover -s scripts/tests -p 'test_payment_resources*.py'
Ran 39 tests in 1.251s
OK
exit_code 0; reviewed_files_stable True; platform linux
```

这 39 项包括合成证据校验与真实 Linux 自进程/子进程采样。合成 fixture 不证明 Orchard 授权或真实 32+1 付款；两个恢复重排反例是在这些现有测试通过后另行实际复现的，说明原测试覆盖不足。

独立 OS 辅助任务另执行 9 项现有定向 Python 测试，并自行启动临时 Python 子进程核对真实 Linux pidfd 存活、内存采样、终止、退出后拒绝采样和重复终止。该定向测试与 39 项存在重叠，不累计为额外独立功能覆盖。未运行 Windows 原生 API/taskkill、强制 PID 回收或完整 1230 秒故障场景。

本地没有 Go/Rust，未声称通过 gofmt、Rustfmt、Cargo、原生 tag 执行或真实 33 笔资源门槛。原生 CI 由 root 继续收集，尚未在本审核记录中完成 10 个 PR 工作流/23 jobs 的验收归档；已有旧阶段成功结果不能替代本候选。冻结设计中未覆盖的容量极限、64 项缓存淘汰、真实断电/磁盘满、多机运行、活动归档备份与生产用途保持未验收。

最终结论保持 **REQUEST_CHANGES**，等待 EVIDENCE-01 修复后的准确新提交复审。
