# PR #11 C3 资源证据与 CI 合同独立复审

结论：**PASS（本次代码与证据校验范围）**。原阻断 **EVIDENCE-01 已关闭**，本次复审未发现新增范围内阻断。真实 32+1 付款、Windows 原生测量与完整 CI 验收仍由独立原生结果审核判定；本记录不将合成协议测试当作阶段资源门槛通过。

审核任务：`/root/p2_resource_ci_review`。审核者未参与编写 C1、C2 或 C3 候选，未修改候选。独立顺序核对辅助任务：`/root/p2_resource_ci_review/resource_os_probe_review`。记录时间：2026-09-17 05:29 UTC。

## 精确身份和继承范围

- PR：<https://github.com/youq616/Zevune/pull/11>
- Base：`8324ec8bd153d9502e3e6761d25bfe281a5f3b44`
- C3 Head：`9e46e03165250c6c51fa7031526d8de1bbdf27d6`
- C3 Tree：`072da4de0b426e619c80b504dedf019a0808201b`
- C3 直接父提交：`b6df89561eb6f2a75ed6fdc630e38d366d299f44`
- 已审 C1：`8f0de0df649a0bae719b7ced789d8fc0857ca475`，tree `e861d8af54cc33735b82e796a20e301e10bea137`。

本地切换到 C3 后核对 HEAD/tree 与上述值完全相符、工作树 clean。按 Git 对象比较，C1 至 C3 仅以下三个 Python 文件变化；`.github`、`integration`、`internal`、`docs` 整棵树，以及 `scripts/run_funded_rust.py`、`go.mod`、`.gitattributes` 的 Git 对象身份均相同。因此原 Rust/Go 负载、OS 采样与清理代码、workflow、设计、依赖和预算没有随本次修复变化。C1 中该部分的已审范围继续保留，C1 的原生结果不能被重标为 C3 已验收。

| C3 文件 | 字节 | SHA-256 |
|---|---:|---|
| `scripts/check_payment_resources.py` | 51410 | `0eb6d68612bc4ba2fc9b5d396dc2663494450703b8fa56361e3c2985f03768ca` |
| `scripts/tests/test_payment_resources.py` | 26198 | `fdc03d1ea09e782e90aea3a86511dd6cc0eb049515217acb5bf6b1fb775cff15` |
| `scripts/tests/test_payment_resources_evidence.py` | 22574 | `6da831e50633d4e4782efc5c1c7d41168c2d0825045abfbff6d107b4220da23e` |

原始 C1 审核文件 `8f0de0d-evidence-review.md` 保持原文，SHA-256 仍为 `2e4b26ca0040653f6af99029a6835761a72459e70f3db15b09f7056576ba866c`；其 REQUEST_CHANGES 结论作为当时准确候选的真实历史保留。

## EVIDENCE-01 关闭依据

监督器现以 `expected_operations()` 明确固定全部 181 项元组：操作名、付款序号、started 时确认数、completed 时确认数。每条进度的 seq 决定唯一元组及 started/completed 奇偶位置，错误操作、提前恢复、错序、重复、跳号或错误计数均无法先进入公开进度列表。

该序列与未变 Go 真实调用核对相符：初始化三项；第 1 至 32 笔各五项及指定高度的重复拒绝；第一代 worker 关闭、物理检查、第二代 worker 重开、钱包恢复；第 33 笔准备后精确 outbox 恢复，再正常选择/提交/独立应用/钱包同步/重复拒绝；最后关闭 worker、物理检查、场景退出。

`worker_commit(n)` 是唯一将确认计数从 `n-1` 改为 `n` 的操作。合法 started 不含 duration；其 completed 必须重新校验准确的前一条 started。若真实提交已发生但该组合操作的后续核对失败、completed 尚未保存，仍保留 started 和提交结果不确定性，而不声称提交没有发生。

`checked_result()` 现在先要求完整 362 条进度，再从 seq 1 起重新验证全部记录。即使调用者跳过 collector、令 result timings 与被改动的 progress 一起重排，直接调用最终校验也不能绕过此顺序门槛。原先只比较 extra 操作多重集合的逻辑已删除。

本审核者直接复现原两例，得到：

```text
wallet_recover_after_prepare33 REJECTED unexpected_progress_step first_bad_seq 341
worker_reopen_before_start REJECTED unexpected_progress_step first_bad_seq 1
```

此外独立执行以下合成协议检查：

- 全部 363 个合法前缀（空前缀及 362 个非空前缀）可以保留；其中 362 个尚未完整的前缀均不能通过最终 complete 验收。
- 全部 180 种相邻完整操作对交换均在首条偏离记录被拒绝，且直接 `checked_result()` 也拒绝。
- 在四个分散位置替换为未知操作，逐条校验和直接结果校验均拒绝。
- 已新增测试覆盖缺少/重复操作、恢复与 outbox/关闭/物理检查边界、合法恢复中途前缀、错误记录不得覆盖已保存前缀、未完成提交/独立应用的不同确认语义。

独立辅助任务按未变 Go 源码另外展开全部 181 个元组，与 C3 逐项比较相等；其另行生成的 362 个未知操作变体、362 个确认计数变体及 180 种相邻交换也全部在首条修改记录拒绝。这些检查与主审存在重叠，不累计为额外真实付款覆盖。

## Windows deadline 测试夹具修复

本审核者读取了 C1 的原始 Windows 任务日志 `8f0de0d-job-105084001321.log`。该运行执行 39 项测试，结果为 `FAILED (errors=1, skipped=1)`；错误明确来自 deadline 纯测试强制走 Linux 分支，但 `mock.patch.object(resource.os, "killpg")` 在 Windows 上找不到原属性。[C1 Windows 失败任务](https://github.com/youq616/Zevune/actions/runs/35184653050/job/105084001321)。

C3 在这个纯测试中显式提供 `killpg` 与 `SIGKILL` 的假属性，并使用 `create=True`，仍检查同一个已存在的截止时间、两次剩余一秒等待、一次进程组信号和协调器终止。没有修改生产清理逻辑，没有修改 1230 秒上界，没有新增 skip，也没有弱化测试断言。

我在本地 Linux 的一个独立 Python 进程中，暂时移除 `os.killpg` 与 `signal.SIGKILL` 后执行该测试。测试通过；退出 patch 后临时属性不残留，再恢复原进程属性。这个验证仅模拟 Windows 缺少 Linux 属性的条件，**不是 Windows 原生 API 或 taskkill 验收**。

既有 Linux proc 专属测试仍在 Windows 合理跳过；最终原生报告须分别记录 pass/error/skip，不能将 `Ran 44 tests` 自动写成 44 项全部实际执行通过。

## 实际测试与本次未测边界

本审核者独立执行，前后三个 Python 文件哈希一致：

```text
python -m unittest discover -s scripts/tests -p 'test_payment_resources*.py'
Ran 44 tests in 1.827s
OK
exit_code 0; files_stable True; platform linux
```

44 项包含合成协议/失败处理与真实 Linux 自进程/子进程采样；不将其描述为 44 笔真实付款或 44 次原生资源基线。前述额外前缀、交换和缺属性检查也都属于协议/测试夹具验证。

本轮没有本地 Go/Rust 工具链，不声称本地完成 gofmt、Rustfmt、Cargo、新 tag 原生执行、Windows 原生测量或完整 32+1 负载。准确 C3 的原生 workflow/任务、两个公开 artifact、真实角色内存高水位及失败历史由专门的原生 CI 审核继续关联；只有实际 CI 与该代码审核共同满足，才可给出阶段验收结论。

未变的边界仍有效：OS resident/working set 不等于私有内存；生命周期 peak 不等于阶段 peak；同场景进程恢复不等于冷进程/冷磁盘；首次事件前硬崩溃的未登记子树清理未确认；注册进程退出不等于完整进程沙箱保证。64 项授权缓存淘汰、完整容量边界、真实断电/磁盘满、活动归档、多机长期运行及外部安全审计继续未验收。

本次复审结论为 **PASS（代码与证据校验范围）**，EVIDENCE-01 已关闭，无新增范围内阻断；保留独立原生验收要求。
