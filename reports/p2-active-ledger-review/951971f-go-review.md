# Zevune PR #9：Go / network / workflow 独立代码审核原始记录

审核任务：`/root/ci_code_review`。

辅助独立任务：`/root/ci_code_review/workflow_preservation`，负责配置与应用版本、InitChain、签名头与同步路径，以及后续 source job 控制流的复核。

本记录由上述主审核任务直接撰写。审核者没有编写本阶段候选实现；审阅期间未修改仓库源码或执行 GitHub 写操作。本文件是审核者自己的原始结论，可原样归档，不能由后续摘要扩展其范围。

## 结论与准确对象

**代码审核结论：PASS_WITH_LIMITATIONS。最终准确候选在本审核范围内没有尚未解决的新增阻断缺陷。**

| 身份 | 已独立核实的值 |
|---|---|
| PR | [youq616/Zevune #9](https://github.com/youq616/Zevune/pull/9) |
| 阶段基线 | `2b889d52c2e6c765f03ea683f42b8467d66e47f5` |
| 最终源码提交 | `951971f46e964d259275653063c2dc9c2dcfd104` |
| 最终源码树 | `386d33907d86ac7b9ac4bfd6481c2298dd95686d` |
| 最终提交的唯一父提交 | `a11370b2f151bfef47fa85e9082723e2d9381bd5` |

最终对象可在 [GitHub 源码提交](https://github.com/youq616/Zevune/commit/951971f46e964d259275653063c2dc9c2dcfd104) 核查。审核者分别读取 GitHub Git commit 元数据与本地 Git 对象，核实了提交、树和唯一父提交，不只接受作者转述的 SHA。

该结论允许继续准确提交的原生验证和验收流程，**不等于 CI 已通过、阶段已验收或 PR 已合并**。CI 证据由独立流程判断，本记录不代替该流程，也不替项目负责人作合并或部署决定。

## 审核范围和实际调用方

首先读取了 `AGENTS.md` 和 `docs/ACTIVE_LEDGER_V1.zh-CN.md`，保留本机、无价值测试资产、真实 Orchard 验证、拒绝候选不得改变已提交状态、未知版本不得降级等既有约束。

| 范围 | 实际检查的内容 |
|---|---|
| `internal/poolbridge` | `client.go`、`genesis.go`、`profile.go`、`capacity.go`、`selection.go` 的全部阶段变更；对应新增和修改测试，以及原有 client/selection 的串行交换、取消、帧边界和失败关闭回归。 |
| `integration/cometbft/poolapp` | `app.go` 与 `genesis_e2e_test.go`；追踪 Info、InitChain、PrepareProposal、ProcessProposal、FinalizeBlock、Commit 和真实 worker 调用；检查已有原生测试调用关系。 |
| `integration/cometbft/labnet` | `network.go`、`sync.go`、`rpc.go`、`storage.go`、`storage_checkpoint.go`、`storage_copy.go`、`reference_checkpoint.go` 的变更；`profile_test.go`、`labnet_test.go`、`active_funded_e2e_test.go` 及相关既有 checkpoint/同步测试。 |
| `integration/cometbft/cmd/zevune-network` | `main.go` 和 `storage_checkpoint_test.go` 的变更；init/run/sync/submit/storage/storage-copy 的参数、可信配置加载、checkpoint 解析及结果返回调用。 |
| 原生增长测试连线 | 阅读 `active_growth_e2e_test.go` 中正常 worker 的调用、边界付款、重开和容量证据使用方式；核对它与低高度四节点测试的证据范围。高位增长执行证据与 Rust 存储实现的主审核不由本记录替代。 |
| 工作流 | 新 `active-ledger.yml`，以及已有 `network-operator.yml`、`orchard-consensus.yml` 的相关测试选择条件；后续精确复核 source job 的格式检查控制流。 |

没有将 Rust 活动存储、Rust worker/history、密码学集成或 Python 钱包实现的独立审核结论纳入自己的通过范围。那些内容由对应审核任务负责。

## 逐次冻结与复核链

### 1. 完整 Go/network 审阅及首次冻结

首次阅读的是阶段基线上未提交的实现草稿。其后作者停止修改并冻结以下对象：

- Head：`514c8632027de6f14173c7a51c6117d6a9a7fe73`
- Tree：`dc03b1ee32b2c0daca95a3bbb0d7294e6156adb8`
- Parent：`2b889d52c2e6c765f03ea683f42b8467d66e47f5`

审核者通过 GitHub GET 和本地 Git 对象核对身份；`git diff --cached <head>` 与 `git diff <head>` 均为空，确认已审阅的工作内容就是冻结树。`git diff --check` 通过。辅助任务也将其已审内容与准确对象比较并确认一致。

因此完整审阅结论正式绑定 `514c863…`，没有把未冻结草稿的结论无条件应用到未知源码。

### 2. 格式修复和 source job 控制流

第二个候选：

- Head：`a11370b2f151bfef47fa85e9082723e2d9381bd5`
- Tree：`7ed4b1a6ecd461c10ac469f4facdba718f671fed`
- Parent：`514c8632027de6f14173c7a51c6117d6a9a7fe73`

审核者分别核对了远端与本地对象。Go/network 范围只有 `network.go`、`profile_test.go`、`capacity_test.go`、`client.go` 四个文件的格式调整；逐项查看 diff，忽略空白与空行后的比较为空，没有改变执行逻辑。六个 Rust 文件的格式复核归 Rust 审核任务。

`active-ledger.yml` 的 source job 将 `gofmt -d` 从立即按非零抛错改为保存退出码，然后继续运行固定版本 Rustfmt，最后统一返回严格结果。检查如下：

| 条件 | 结果 |
|---|---|
| `gofmt -l` 执行错误 | `check=True` 抛错，Python 非零退出。 |
| Go 存在格式差异 | 输出 diff 后仍检查 Rust；最终非零退出。 |
| `gofmt -d` 返回非零 | 保留该退出码、继续检查 Rust；最终非零退出。 |
| Rustfmt 返回非零 | 最终非零退出。 |
| 全部无差异且成功 | 退出码为 0。 |
| 缺失命令等异常 | 未被转换为成功。 |

`growth` 保留 `needs: source`，没有新增 `continue-on-error`。审核者从**准确提交**提取嵌入 Python 脚本，用模拟 subprocess 结果实际执行了 12 种控制流组合，全部符合上述退出条件；Go diff 返回后均继续调用 Rust 格式检查。辅助任务独立静态复核同一控制流，未发现假成功路径。

这些是编排逻辑模拟，**不是原生 gofmt、Rustfmt、编译或密码学测试的执行证据**。

### 3. Rust 创世域测试断言修复后的范围不变核对

最终候选 `951971f46e964d259275653063c2dc9c2dcfd104` 相对 `a11370…` 只修改 `integration/orchard/tests/genesis_domain.rs`，共 13 行新增、4 行删除。

审核者再次通过 GitHub GET 与本地 Git 对象核对提交、树和唯一父提交。对 `internal/poolbridge`、`integration/cometbft` 和 `.github/workflows` 执行完整字节差异比较，结果全部为空，`git diff --check` 通过。

因此此前 Go/network/workflow 结论明确延续到最终 `951971f…`；Rust 测试断言修复是否正确由对应审核任务判断。本任务没有以“仅改测试”为由代替它的审核，也没有将旧提交 CI 自动计为新提交 CI 通过。

## 主要判断依据

1. **profile 来源与版本隔离。** `workerLaunch` 从同一次读取且通过摘要核验的完整清单派生 profile、头长度和启动参数。`Options` 没有容量或 profile override。Gen01/02 保持 IPC3；Gen03 要求精确 IPC4 指纹，混合或未知指纹关闭进程。RPC 或容量响应不能升级本地规则。

2. **旧边界保留。** 包级 BlockBytes、selection 和 summary 解码仍使用 legacy 的 10000 高度限制；已固定 client 的方法才使用 active 高度。每块交易数、交易字节、承诺和 nullifier 上限没有放宽。

3. **容量回复必须与同一 summary 绑定。** op6 仅 active 可发送，payload 必须为空，响应恰好 161 字节。先核验 ID、请求摘要、状态和 summary，再用独立固定清单的真实头长度检查逻辑字节下界、profile 上界、段数、尾长及完整帧关系。普通拒绝要求附加容量字段全零，畸形回复不能生成可用快照。

4. **并发、取消与不确定失败。** 新容量操作复用既有单入口队列和请求序号机制。原并发、入队前取消和进行中取消回归保留。没有新增自动重试 commit、继续使用畸形响应后的 client、或不确定 I/O 后报告有效容量的路径。

5. **配置和 InitChain。** `Load` 根据已固定清单同时核对配置 V1/V2 与 AppVersion 2/3；错误组合拒绝。`Info` 与 FinalizeBlock 使用同一 client 的 profile。InitChain 在版本缺失或不匹配时于 Status 前拒绝，同时保留创世摘要、初始高度、验证者和 vote extension 约束；拒绝不消费 pending。

6. **可信同步。** RPC tip、签名头高度/AppVersion、store/profile 一致性受本地可信 Network 限制。保持 tip−1、128 块单次限制及下一已签名头验证；preview、finalize、commit 结果按原路径核对。没有以远端响应选取较宽容量或取消下一签名头要求。

7. **存储操作与独立 checkpoint。** CLI 在加载可信 Network 前仅做有界语法检查，加载后按其 profile 解析高度。active storage 从真实固定 worker 读取同一 committed summary 的容量，并检查 Close 和取消结果。checkpoint 保持精确高度和 AppHash 匹配；active profile 的旧 storage-copy 请求在访问源或创建目标前明确拒绝，不隐式转换、覆盖或回退。

## 测试选择条件与未覆盖边界

- `network-operator.yml` 的全量 `operator_e2e` 命令在 Ubuntu/Windows 选择新增活动四节点场景，覆盖实际 init/run/sync/submit/storage、活动 InitChain 版本拒绝、真实 A→B、四节点全部重启、B→C、钱包历史恢复及重复拒绝。
- `orchard-consensus.yml` 的全量 `pool_e2e` 命令选择新增 legacy InitChain 版本拒绝测试，保留默认真实 worker 回归。
- Gen01/02/03 × 配置 V1/V2 × App2/App3 的 12 种组合、两个 profile 的签名头高度边界、checkpoint 解析和容量异常均有对应测试入口。
- op6 的错误长度、状态、ID、请求摘要、容量关系、截断、进程退出、超时和进行中取消有测试；新增接受型传输替身只存在于 `*_test.go`。
- 活动四节点是低高度流程测试。超过 10000 的正常 worker 增长、签名头边界与真实四节点同步不是同一份证据；100000 本地 worker 提交不能称为四节点共识提交 100000 块。
- active storage-copy 拒绝由方法级测试覆盖，本轮没有新增对应 CLI 端到端拒绝场景。这是测试范围说明，不是已证实的实现阻断。

上述内容只说明源码和工作流会选择哪些测试，**不说明测试已经在原生平台运行通过**。

## 非阻断既有问题

**P3：部分 RPC 取消错误身份被包装。** `labnet/sync.go` 的 RPC 包装将部分 `context.Canceled` 或 deadline 错误转换成 `ErrResponse`；入口预先取消则返回 `ErrBounds`。调用者因此不能在所有路径都用 `errors.Is` 区分取消原因。

辅助审核对照阶段基线确认，相关行为和入口取消测试原本存在，本阶段没有引入或加重。该问题不会把取消报告为同步成功，不阻断本次 profile/活动账本变更。如果后续统一错误身份，应单独修正并补充 RPC 中途取消测试，不能仅通过修改当前报告声称已经修复。

## 执行证据与限制

本审核实际执行的是：只读源码/调用方/测试检查、GitHub commit 身份读取、本地 Git 对象和完整字节差异比较、`git diff --check`，以及准确 source job 嵌入脚本的 12 种模拟控制流检查。

本审核会话的 shell 没有 Go 可执行文件；**审核者没有在本地运行 Go/Rust 原生测试、race、fuzz、Clippy 或真实四节点实验**。本记录也没有独立读取当前候选 CI 日志来签署 CI 成功。其他任务运行的编译、Python 或原生测试不能算作本审核者自己的执行证据。

最终阶段是否可验收，仍取决于准确源码的 CI、对应 Rust/其他实现审核、真实增长及故障证据、必要修复与复审。后续源码修改须重新核对，不能自动继承本结论。

本记录是独立 coding-agent 的有限范围代码审核，**不是外部机构安全审计、密码学协议审计、生产存储认证或真实资金准入批准**。本机无资金边界、真实磁盘/断电与平台限制保持，本文不授权部署、付费资源、数据迁移、真实资金操作或合并。
