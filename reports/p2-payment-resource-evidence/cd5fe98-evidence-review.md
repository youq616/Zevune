# PR #11 C4 Windows 协议读取与有限诊断独立复审

结论：**PASS（本次代码与证据合同范围）**。未发现新增范围内阻断；EVIDENCE-01 的完整进度顺序修复保持有效。Windows 原生三个共享文件回归、真实 32+1 付款资源门槛及完整 CI 仍须由准确 C4 的原生证据确认，本记录不替代该验收。

审核任务：`/root/p2_resource_ci_review`。审核者未参与候选编写，未改动候选文件。本轮尝试唤醒既有 OS 辅助审核任务时受到代理线程上限限制，以下 OS/API 核对由主审独立完成。记录时间：2026-09-17 05:53 UTC。

## 精确身份与差异

- PR：<https://github.com/youq616/Zevune/pull/11>
- Base：`8324ec8bd153d9502e3e6761d25bfe281a5f3b44`
- C4 Head：`cd5fe98053ce64e1acc6796dae44ec0e822c124f`
- C4 Tree：`cc60276872b26bbd2be1b0a0a62fceac325f5b45`
- 直接父提交/C3：`9e46e03165250c6c51fa7031526d8de1bbdf27d6`

审核开始和结束均确认本地准确 C4、工作树 clean。C3→C4 仅有两个文件差异：

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `scripts/check_payment_resources.py` | 55719 | `e6eef3b5e194220bc72e2569bf9d12a6236cbbf3a4396b9a8e7e7c7bfd53e192` |
| `scripts/tests/test_payment_resources_windows.py` | 14886 | `116b67f4b9b37c9cde3924a152a3f93b97aa3b7aa98d1bbc3f3224e5531b3179` |

已按 Git 对象确认 `.github`、`integration`、`internal`、`docs` 整棵树，原有两个资源测试模块、`scripts/run_funded_rust.py`、`go.mod`、`.gitattributes` 均保持 C3 字节。另提取监督器函数/类的完整源码片段比较，确认 `expected_operations`、`checked_progress`、`checked_result`、`checked_event`、两平台进程探针、`ProtocolCollector`、`EvidenceFile`、`stop_test` 与 `collect_metadata` 均逐字节相同。

因此本次没有改变真实 Rust/Go 负载、181/362 顺序、九检查点、OS 内存测量、提交确认规则、1230 秒监督/清理截止时间、source/tree 校验、workflow 或预算。新测试被现有 `test_payment_resources*.py` glob 纳入。

C1/C3 原始审核均保持原文：

- `8f0de0d-evidence-review.md`：SHA-256 `2e4b26ca0040653f6af99029a6835761a72459e70f3db15b09f7056576ba866c`。
- `9e46e03-evidence-review.md`：SHA-256 `75224a00940a88ce3b216cb6d15a2a7e82ecd7688cde92a4ec956e95b1d6cc0a`。

## Windows 共享读取与所有权

新 opener 调用 `CreateFileW` 请求 `GENERIC_READ`、共享 READ/WRITE/DELETE、`OPEN_EXISTING` 和普通属性；没有写入、截断、创建或重试行为。共享 DELETE 允许读者与已持有 DELETE 访问的发布/重命名句柄共存，不能解释为授予本读者删除权限。参数为 NULL 的安全属性不允许创建时继承句柄，CRT 转换后又显式设为不可继承。[CreateFileW 官方合同](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)。

官方说明确认，重命名使新名称可见之后，原 DELETE 句柄仍可能尚未关闭。保留真实 DELETE holder 的测试对应这一共享状态，但成功读取用例并未执行重命名本身，也不能证明 C3 历史故障一定由该窗口导致。[Microsoft 对该窗口的说明](https://devblogs.microsoft.com/oldnewthing/20211022-00/?p=105822)。

所有权路径符合 CRT 合同：转换失败时仍由 opener 负责尝试关闭原 Win32 handle；`open_osfhandle` 成功后由 CRT fd 持有底层句柄，后续设置继承或创建流失败只关闭 fd，不再对原 handle 二次 CloseHandle；成功时由返回的流关闭 fd/handle。[CRT 所有权说明](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/open-osfhandle?view=msvc-170)、[Python msvcrt 接口](https://docs.python.org/3/library/msvcrt.html#msvcrt.open_osfhandle)。这描述的是代码在异常分支中的释放责任，不能承诺操作系统拒绝关闭时仍已成功回收资源。

新读取路径仍检查 lstat→fstat 的文件身份，且新增同时比较打开时大小；读完关闭后再检查路径身份和大小。若 fstat/read 已失败，关闭流的 OSError 不覆盖原始读取异常；正常读取后的 close 失败则明确记录 close 阶段。对身份/大小变化或非法内容依旧失败，不通过共享选项绕过内容和记录不变性校验。

原生 Windows 测试的静态核对范围：

1. 真实 DELETE holder 下，旧 share=3 的 CreateFileW 必须得到错误 32，旧 CRT 读取也必须失败；新共享读者取得精确 JSON 和原始 SHA-256。
2. 在 lstat 与 open 之间真实替换为相同字节/大小的另一个文件，仍因文件身份不同而失败。
3. 使用保留的可写 holder 在实际读取后追加一个字节并 flush，仍因大小改变而失败。

这些测试中的 JSON 都是合成公开数据，不是钱包、付款或密码学证明。

## 有限诊断与失败进度语义

`ProtocolReadError.public()` 只保存固定错误码以及有限的 `stage`、`errno`、`winerror`、`protocol_kind`、`seq`。阶段为六个已知读取动作，位置仅从严格匹配的 event/progress/result 名称推导；未知名称变为 unknown/None。数值只接受有界的真正整数，布尔、浮点、负数、过大值和其他类型变为 None。路径、原文件名、原异常文字和上下文不进入公开结果。非法协议 JSON 也不会因新增诊断而进入 collector 的公开事件或进度。

本审核特别检查首次错误与清理阶段的区别：主运行路径保留原始读取异常，再尝试收集已出现的合法进度并清理。因此最终报告中的 `io_diagnostic.seq` 是该原始错误的位置，最终 progress/last_confirmed 可以是清理期间随后观察到的更长合法前缀；两者不必一致，也不能从最终前缀倒推首次失败文件。

`commit_outcome_uncertain` 沿用已有窄语义：**最后已观察到的未完成操作是否为 worker_commit**。它为 false，不证明观察窗口外没有发生后续 Commit，更不证明磁盘最终高度等于 last_confirmed。last_confirmed 仅是已验证进度中的确认下界。本轮没有发现将该 false 用作成功验收或磁盘未提交证明的调用，因此不据此新增代码阻断；最终交付报告必须保留上述语义，不能扩大该布尔字段的断言范围。

我另外执行了一个纯协议故障模拟：首次读取 seq 2 失败，后续收集继续接受至 seq 13，报告同时保持 first_error_seq=2、later_observed_prefix=13、last_confirmed=1、pending=scenario_apply、commit_outcome_uncertain=false。模拟没有磁盘状态断言，且原错误路径/文字不出现在公开对象中。

## C3 历史证据的准确边界

已读取原始 `9e46e03-native-diagnostics.json`。C3 的 Windows 原生运行在资源场景失败；证据保留 4 个事件、283 条进度、141 个完成操作、last_confirmed=27，最后观察到 prepare 第 28 笔的 started，最终 result 为 null。[C3 Windows 原生失败任务](https://github.com/youq616/Zevune/actions/runs/35185652786/job/105087032307)。

该历史报告只有 `protocol_file_read_failed`，没有 errno、winerror 或读取阶段/位置；所以不能认定历史错误必为共享冲突、必发生于 seq 284，或已有 32 笔被确认。C4 的新测试和诊断是对可复现共享语义及未来错误记录的改进，不改变 C3 未验收的历史结论。

## 独立实际验证与未测范围

在三个既有资源模块及新模块哈希前后稳定的情况下，本审核者执行：

```text
python -m unittest discover -s scripts/tests -p 'test_payment_resources*.py'
Ran 53 tests in 1.772s
OK (skipped=3)
exit_code 0; files_stable True; platform linux
```

准确计数为 **50 项实际通过、3 项 Windows 原生测试按平台跳过**，不是 53 项全部执行通过。原有严格序列与结果校验回归保持通过。新增 6 项可移植测试覆盖句柄转换/流创建异常、有限诊断与六个 I/O 阶段、读取错误不被关闭错误覆盖。

此外我独立注入转换失败/关闭返回失败、设置不可继承失败/关闭 fd 失败，确认两种路径都保留原始异常、遵循各自 handle/fd 所有权；这些是合成异常测试，不是 Windows 原生 OS 故障注入。

本轮没有 Windows 执行环境，也没有本地 Go/Rust，未运行三个真实 Win32 回归、真实 32+1 付款或整个资源预算。因此准确 C4 的 Windows/Ubuntu 原生验收、实际 memory 高水位、完整十个 PR 工作流及两份公开 artifact 仍由原生 CI 审核单独核验。OS 采样近似性、同场景恢复非冷启动、未登记子树清理未确认、容量/断电/归档/多机等既有未测边界继续有效。

最终结论：**PASS（代码与证据合同范围）**，无新增范围内阻断，保留准确候选的独立原生验收要求。
