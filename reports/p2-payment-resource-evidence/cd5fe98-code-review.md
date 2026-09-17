# PR #11 C4 独立代码复审原文

审查者：`/root/p2_resource_review`。本审查者未编写或修改本阶段候选 Rust、Go、Python、工作流、设计或测试文件；本次操作仅为读取、独立验证及保存仓库外审查记录。

审查日期：2026-09-17（UTC）。

## 准确候选身份

- PR：https://github.com/youq616/Zevune/pull/11
- Base：`8324ec8bd153d9502e3e6761d25bfe281a5f3b44`
- Head（C4）：`cd5fe98053ce64e1acc6796dae44ec0e822c124f`
- Tree：`cc60276872b26bbd2be1b0a0a62fceac325f5b45`
- Parent（C3）：`9e46e03165250c6c51fa7031526d8de1bbdf27d6`
- 本地仓库：`/workspace/scratch/1753b04c9dbb/Zevune`
- 独立读取 Git 身份并确认工作树 clean；远端 PR 元数据的 base/head 与上述身份相同。
- C3 → C4 只有两条路径变化，392 insertions、4 deletions：
  - `scripts/check_payment_resources.py`，SHA256 `e6eef3b5e194220bc72e2569bf9d12a6236cbbf3a4396b9a8e7e7c7bfd53e192`。
  - 新增 `scripts/tests/test_payment_resources_windows.py`，SHA256 `116b67f4b9b37c9cde3924a152a3f93b97aa3b7aa98d1bbc3f3224e5531b3179`。

结论：**PASS（本次独立代码复审范围）**。没有发现 C4 新增的阻断性代码问题；C1 R1 保持关闭。此结论不表示 C4 原生 Windows 已通过，不表示全阶段已验收或可以声称真实 33 笔付款在本次候选的两个原生平台均已完成。C4 原生 CI 的准确 head、各 job、实际付款进度及资源 artifact 必须由原生审计另行确认。

## 本次变化与相同字节范围

完整阅读 C3 → C4 两文件差异、新测试全部内容、新 Windows opener、公开 I/O 诊断类型、read_public_json 的全部读取和清理分支，以及监督器捕获异常、保留证据和发送失败 ack 的调用路径。

以 git diff 验证 `integration/`、`internal/`、`.github/`、`docs/` 与既有两份资源 Python 测试在 C3 → C4 完全不变。Rust 真实付款场景、Go 端到端流程、九事件与 181 操作合同、工作流、冻结设计与旧场景兼容性的既有代码审查，在这个严格相同字节范围内继承 C3 结论。

另以 AST 比较 C3 与 C4 的 `expected_operations`、`checked_progress`、`checked_result`，三者结构相同；C4 并未借文件共享修复更改操作次序、成功门槛、计数、计时或超时预算。Base → C4 的 `git diff --check` 通过。

保留原始报告，不覆盖历史结论：

- C1：`8f0de0d-code-review.md`，SHA256 `348a1f8523b4f6eadfddad00802c350da67eb000ee188fb931d172397fe7be71`，原结论 CHANGES_REQUESTED。
- C3：`9e46e03-code-review.md`，SHA256 `1261947e8dfa2d4918d934fb09b5b849e9fb1699a2c8c5f31bc031f3cd7a9012`，原结论为代码范围 PASS。
- 本次末尾重新计算上述历史报告哈希，与保存时一致。设计与 Rust/Go 初审原文亦未修改。

## C4 文件共享修复

`windows_public_binary` 使用 CreateFileW，以 GENERIC_READ、OPEN_EXISTING、FILE_ATTRIBUTE_NORMAL 和空 security attributes 打开既有公开协议文件。共享标志为 READ | WRITE | DELETE；增加共享许可不等于获得写入或删除访问权。没有改动真实钱包、账本或交易文件的打开方式，也没有放宽协议格式或读取上界。

Microsoft 的 CreateFileW 文档区分 desired access 和 share mode，并说明当既有打开请求包含 DELETE 访问时，新打开需要相容的 FILE_SHARE_DELETE。Microsoft 对 Windows rename 的机制说明指出，目标名称可以在重命名调用结束、相关 DELETE 句柄关闭之前已可见；普通 CRT 允许读写共享仍可能拒绝这一时间窗口。该机制足以支持这里使用兼容共享方式的局部修复。[CreateFileW 官方文档](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[Microsoft 对 rename 与共享删除的说明](https://devblogs.microsoft.com/oldnewthing/20211022-00/?p=105822)。

句柄所有权分为三个明确阶段：

1. CreateFileW 成功至 CRT 接管前，原始 HANDLE 由 helper 拥有；open_osfhandle 失败时只关闭该原始 HANDLE。
2. open_osfhandle 成功后，CRT descriptor 拥有底层句柄；set_inheritable 或 fdopen 失败时只关闭 descriptor，没有同时 CloseHandle 造成重复关闭。
3. fdopen 成功返回后，stream 拥有 descriptor，由读取路径的 close 释放。descriptor 被显式设为不继承。

这与 Microsoft 对 open_osfhandle 接管操作系统句柄所有权的说明相符。[open_osfhandle 官方文档](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/open-osfhandle?view=msvc-170)。

本地独立注入 set_inheritable 失败，确认已转换的 descriptor 只关闭一次、不再关闭 raw HANDLE；也使用真实 Linux descriptor 与模拟 Win32/CRT 入口确认成功 stream 的所有权转移、非继承属性和最终关闭。上述是可移植分支检查，不构成原生 Windows 句柄测试。

## 文件身份、内容与失败证据

read_public_json 保持原来的公开协议文件保护：

- 初始 lstat 要求普通文件且大小不超过既有上界。
- 打开后用 fstat 比较文件身份，并在 C4 增加与初始大小一致的检查。
- 读取 maximum + 1 字节，以便已有 JSON 解码器拒绝超限内容。
- 关闭后重新 lstat，拒绝路径替换或大小变化。
- JSON 严格解析、未知字段等后续 schema 检查及原始字节 SHA256 不变。

READ | WRITE | DELETE 共享不使这些变更检查失效。独立使用实际 Linux 文件验证：在 lstat 与打开之间替换为大小和内容完全相同但身份不同的文件，仍被拒绝为 protocol_file_changed；读取后追加内容改变大小，也被拒绝。新 Windows 原生测试包含对应检查，但本地没有执行其 Windows 部分。

这些检查适合本项目由 Go 生成后不再覆盖的不可变协议文件合同；它们不是对任意恶意同权限进程的文件内容锁定证明。相同 inode、相同长度的原地修改无法仅靠 stat 保证不存在，此边界没有由 C4 新增，也不应把共享模式称为不可变性或安全隔离机制。

新 ProtocolReadError 仅增加受限诊断，不公开异常原文：

- error_code 固定为 protocol_file_read_failed。
- stage 只允许 lstat_before、open、fstat、read、close、lstat_after。
- 文件信息只映射为 event/progress/result/unknown；event 序号为 1–9，progress 为 1–2048。
- errno/winerror 只允许不含 bool 的有界整数；未知或非法值输出 null。
- 不输出完整路径、未知文件名、异常字符串、命令、环境变量或协议原始内容。
- 读取失败后关闭也失败时，保留原始读取错误及其 stage，不让第二个关闭异常覆盖主失败。
- 监督器总结果通过 public() 收集此受限对象；失败 ack 仍只使用固定公开错误码。

本次没有加入重试，没有放宽检查点握手、worker 请求、scenario 响应、完整场景或清理期限，没有把 I/O 失败转换为成功、跳过或零内存。

## C1 R1 与继承的实际付款合同

C1 的 medium 阻断 R1 是完整证据可以在全局次序错误时被接收：其一把 wallet_recover 移到 prepare 第 33 笔及 outbox_restore 之后；其二把高度 32 的 worker_reopen 移到 scenario_start 之前。C3 已用严格 181 操作 / 362 progress 记录序列关闭这一问题，逐条约束开始和完成、operation、payment_index、committed_blocks 与对应时长。

本次 53 项资源测试内包含上述两个原反例，均被拒绝；还包含恢复、关闭、磁盘检查、outbox 边界移动及合法 partial prefix 的回归检查，均通过。AST 相等和 Go 字节相同进一步支持 R1 仍关闭。本次没有重复声称执行 C3 报告中的全部 180 个相邻交换及全部 362 个合法前缀穷举；该组详细结果严格作为 C3 已执行、相同代码范围继承的证据。

真实付款与恢复源代码继续保持：两个实际钱包各 50,000 创世资金，交替 1,000 金额与 1,000 fee，每块一笔，前 32 笔增长后重开 worker 全重放；钱包在高度 32 恢复，再准备第 33 笔，恢复 outbox 并比较相同 bytes，最后继续真实付款。仍核对实际 PoolStore/Wallet 调用、提交后 state/fees/commitments/nullifiers、wallet records_used、完整物理 frames、错误 pending 提交拒绝与原待提交保留。C4 未更改这些调用或生产 API。

源代码结论不代替原生执行结果；32 + 1 笔是有界的小样本付款与恢复基线，不能声称生产 TPS、容量上限、全面账本轮转、真实断电或任意长期运行已获证明。

## 实际执行的 C4 本地验证

执行命令：

```text
python -m unittest discover -s scripts/tests -p 'test_payment_resources*.py' -v
```

实际结果：**Ran 53 tests in 2.500s；OK (skipped=3)**。即 **50 项通过、3 项明确的 Windows 平台专属跳过、0 failure、0 error**。包含既有 44 项资源测试和新增 6 项可移植测试。本地实际 Linux /proc 自身与子进程身份、常驻内存读取测试正常执行；三个 Windows 原生测试没有执行。

新增可移植测试覆盖：CRT 转换失败的原始句柄清理、stream 创建失败的 descriptor 清理、六个 I/O 阶段的公开诊断、协议位置及 OS 错误码的受限保留、未知名字和非法标量过滤，以及 read 与 close 同时失败时主错误保留。

另外独立执行并通过四项检查：

1. set_inheritable 故障注入：descriptor 只关闭一次，无 raw HANDLE 双重关闭。
2. 以真实 Linux descriptor 配合模拟 Win32/CRT 的成功返回：stream 读取准确字节，descriptor 不继承，关闭后 fstat 确认为 EBADF。
3. 实际 Linux 文件的同字节、同大小身份替换：拒绝。
4. 实际 Linux 文件的读取后大小变化：拒绝。

这四项中的 Win32 入口是模拟；没有把它们称为原生 Windows 实验。

另执行 Git 身份、工作树、差异范围、SHA256、AST 相等与 diff --check 检查，结果均满足本次身份及范围约束。

未执行：本地 Go/Rust 编译、原生付款 e2e、Windows CreateFileW / msvcrt 的原生行为，以及 C4 CI 的 33 笔付款、两个 worker 代际与九事件完整资源验收。本地环境没有 Go/Rust 工具链；本审查没有安装工具链或声称执行其编译。作者报告的更宽 135 项测试不是本审查自行执行的结果。

## C3 原生失败不能被重新解释为已证明原因

本审查实际阅读仓库外 `9e46e03-native-diagnostics.json`。记录指向 C3 准确 head 的 Windows 原生资源 job：

[GitHub Actions run 35185652786 / job 105087032307](https://github.com/youq616/Zevune/actions/runs/35185652786/job/105087032307)。

该记录为失败：最后确认 27 笔、283 条 progress、141 项已完成操作、4 个事件，最后未完成操作为准备第 28 笔；结果只有 protocol_file_read_failed，没有 errno、winerror 或具体失败阶段。不能由这份旧证据推定确切就是共享冲突，也不能把部分内存样本合规解释成完整 33 笔或恢复成功。

新原生测试显式持有 DELETE 访问句柄，再验证旧共享方式失败、新 reader 获得相同 JSON 和 SHA256，具有直接检查兼容机制的价值。它没有实际执行 Go rename，并且在本次本地测试被 Windows 平台条件跳过。因此只能在 C4 的真实 Windows 测试和完整付款工作流实际通过后，分别记录“兼容机制原生验证通过”和“准确候选完整场景通过”；不能追溯断言旧失败原因已被精确还原。

## 发现、严重性与剩余验收边界

- 新增 blocker / high / medium 代码问题：**无**。
- C1 R1（medium，操作顺序证据漏洞）：**保持关闭**。
- C4 代码符合本阶段冻结设计及有限修复范围：**是**。
- C4 Windows 原生机制和完整 Linux/Windows 场景：**本审查尚无执行通过证据，必须由原生审计完成**，不是本地 PASS 的外推结论。
- 指标仍为每个被跟踪 worker/scenario 进程生命周期的 OS 常驻内存或工作集峰值，1 GiB 为观测验收门槛，不是私有堆、阶段峰值、硬分配上限或系统合计预算；Go/Python 父进程不纳入该计量。
- 首个 genesis 事件前若 Go 极端硬崩溃，尚未取得所有子 PID 的情况下不保证全部后代清理；这是已公开的既有失败边界，C4 没有改变。
- 本次代码 PASS 不推进 P2 为全面生产就绪，不改变 NO-FUNDS 约束，不代表已授权或执行合并。

原始结论：**PASS — independent code review for exact C4 head cd5fe98053ce64e1acc6796dae44ec0e822c124f / tree cc60276872b26bbd2be1b0a0a62fceac325f5b45, with native acceptance explicitly pending.**
