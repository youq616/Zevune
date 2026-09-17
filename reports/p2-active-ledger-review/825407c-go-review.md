# Zevune PR #9：825407c Go / network / workflow 独立复核原始记录

审核任务：`/root/ci_code_review`。本记录由审核者本人撰写，审核者没有编写本阶段候选实现。本次只读检查候选源码及 Git 元数据，仅在仓库外写出此审核记录，没有修改候选或执行 GitHub 写操作。

## 准确对象与范围结论

**结论：PASS_WITH_LIMITATIONS。本审核负责的 Go/network/workflow 范围与此前已审核候选逐字节不变，原范围代码审核结论明确适用于本次准确提交；没有新增的范围内阻断。**

| 身份 | 独立核实的值 |
|---|---|
| PR | [youq616/Zevune #9](https://github.com/youq616/Zevune/pull/9) |
| 阶段基线 | `2b889d52c2e6c765f03ea683f42b8467d66e47f5` |
| 本次源码 Head | `825407cffd26884bd212cea0780dfb8d02de55bf` |
| 本次源码 Tree | `23414d127afe6d63041ff6e615bb0d2a5fcdf0d2` |
| 唯一 Parent | `951971f46e964d259275653063c2dc9c2dcfd104` |
| 父提交 Tree | `386d33907d86ac7b9ac4bfd6481c2298dd95686d` |

审核者通过 GitHub 插件只读获取 [本次 Git commit](https://github.com/youq616/Zevune/commit/825407cffd26884bd212cea0780dfb8d02de55bf) 的元数据，并独立读取本地 Git 对象，分别核实了完整 Head、Tree 和唯一父提交。本次不是只根据作者所报摘要作判断。

本结论是 **Go/network/workflow 范围的代码审核**，不代替新 Rust 根缓存实现的审核，不宣称当前 CI 已通过、阶段已验收或 PR 已合并。当前源码仍需准确提交的原生证据和对应 Rust 审核；本记录不替其他审核任务签署其结论。

## 本次修改清单与不变性证据

相对 `951971f46e964d259275653063c2dc9c2dcfd104`，完整 diff 仅有以下五个文件，共 192 行新增、2 行删除：

- `integration/orchard/src/pool.rs`
- `integration/orchard/src/pool/root_cache_tests.rs`
- `integration/orchard/src/pool/active_flow_tests.rs`
- `integration/orchard/src/pool/selection/tests.rs`
- `docs/DERIVED_COMMITMENT_ROOT.zh-CN.md`

审核者阅读了本次派生根说明，确认其描述的变更范围是私有 State 根缓存、等价性断言和相关文档；没有把说明文档本身当作正确性证明。Rust 缓存不变量、预提交/提交、拒绝前缀隔离、真实密码学及完整重放等实现判断由 Rust 审核任务负责。

对以下路径执行了**完整字节差异比较**，没有使用忽略空白选项，结果全部为空；又比较了父、新提交中的 Git tree/blob 对象 ID，逐项相同：

| 路径 | 两个提交中相同的 Git 对象 ID |
|---|---|
| `internal/poolbridge` | `eeff456645fbf6268473cc71d9edf17b3ccf3ec1` |
| `integration/cometbft` | `87f0df0885f69f7c747c42cef582678b6b516cbc` |
| `.github/workflows` | `63fbe0a3c0dc3c2ce017ad1e220d12e0038b6b90` |
| `scripts/run_funded_rust.py` | `300308b99bc3049ea5057aeef4798fc65e602827` |
| `scripts/tests/test_funded_rust.py` | `61d3cdc7a6ad6abcdc40e9dd847e935c5b9ec32b` |
| `integration/orchard/Cargo.toml` | `52cb6b759cd578845b29d319cd8da9111690f7d8` |
| `integration/orchard/Cargo.lock` | `2de27d6012d76201b124af81d4867f2d9db8f539` |

本次提交的 `git diff --check` 也通过。

由此可以确认：Go bridge、网络配置、InitChain、同步和容量检查的源码不变；原生 Go 增长测试的 100000 块目标、边界付款和恢复调用不变；工作流的测试目标选择、平台、依赖、权限、时间预算以及分片调度器不变。**这些结论不等于运行时间已改善或测试已成功**，新 Rust 行为仍可能影响真实执行，必须由本次准确源码的原生结果证明。

## 继承的实际审阅范围和复核链

原始累计报告为 `951971f-go-review.md`，本次保留原文件，未修改或覆盖。审核者重新读取该文件并核对其 SHA-256 仍为：

```text
2b03dd5cefd40ddc9e85111c7eac8a087ea89a7ffe2880b6f92d03c63a077f10
```

该原始记录包含以下已经实施的审查链：

1. **完整范围审阅。** 在阶段基线上检查 `internal/poolbridge` 的 client、genesis、profile、selection、capacity；检查 `integration/cometbft/poolapp`、`labnet`、网络命令行的全部阶段变更、真实调用方和对应测试。首先读取 `AGENTS.md` 与活动账本设计。冻结至 `514c8632027de6f14173c7a51c6117d6a9a7fe73`、tree `dc03b1ee32b2c0daca95a3bbb0d7294e6156adb8` 后，通过远端/本地身份及工作区/索引比较确认已审内容与准确树一致。
2. **格式及 source job 复核。** 对 `a11370b2f151bfef47fa85e9082723e2d9381bd5`、tree `7ed4b1a6ecd461c10ac469f4facdba718f671fed`，逐项检查四个 Go 文件仅为格式变更，并独立审核 source job：Go diff 后仍检查 Rust，任何差异或失败最终非零。审核者从准确提交提取嵌入 Python 脚本，实际执行了 12 种模拟 subprocess 结果组合，全部符合严格失败条件；辅助任务独立静态复核同一控制流。
3. **Rust 创世测试修复后的不变性复核。** 对 `951971f46e964d259275653063c2dc9c2dcfd104`、tree `386d33907d86ac7b9ac4bfd6481c2298dd95686d`，确认其唯一修改为 Rust 的 `genesis_domain.rs`，Go/network/workflows 全部字节不变，正式将原范围结论绑定该候选。
4. **本次再绑定。** 对 `825407cffd26884bd212cea0780dfb8d02de55bf` 完成上述远端/本地身份、完整修改清单、逐字节 diff 及 tree/blob ID 比较，确认本任务范围仍不变，因此将原范围结论明确绑定本次准确候选。

原完整审阅中的辅助独立任务为 `/root/ci_code_review/workflow_preservation`，负责网络配置/AppVersion、InitChain、签名头/同步及 source job 控制流。本次对象身份和范围不变性核对由主审核任务本人执行，没有虚构该辅助任务对新 Rust 实现的审核。

## 仍然成立的范围内判断

- profile、IPC 指纹和容量头长度由同一次通过摘要验证的清单派生，没有通过 Options、RPC 或容量回复提升规则的入口。
- legacy IPC3、普通回复布局及 10000 高度限制保留；active IPC4/op6 严格检查长度、请求绑定、状态和容量关系。
- 新容量请求沿用单入口串行交换和失败关闭；普通拒绝不会返回有效容量，畸形回复、进行中取消或不确定 I/O 不被报告为成功。
- 配置 V1/App2 与 V2/App3 严格匹配已固定清单；Info 和 FinalizeBlock 使用同一 client profile；InitChain 缺失或错误版本被拒绝。
- 同步受可信 Network 高度和版本限制，保持 tip−1、单次 128 块及下一已签名头与真实 preview/finalize/commit 的检查。
- active storage 从真实固定 worker 的同一次 committed summary 取得容量；独立 checkpoint 维持精确匹配；旧 storage-copy 在访问源或创建目标前拒绝 active profile。
- 既有双平台工作流仍选择活动四节点、legacy InitChain 及相应原生回归；接受型传输替身限定于 `*_test.go`。source job 与分片调度器没有因本次优化放宽退出条件或缩减目标。

## 保留的 P3 非阻断事项

**部分 RPC 取消错误身份被包装。** `labnet/sync.go` 的 RPC 包装把部分 `context.Canceled` 或 deadline 错误转换成 `ErrResponse`；入口预先取消返回 `ErrBounds`。调用者因此不能始终通过 `errors.Is` 识别取消原因。

前次独立审阅已与阶段基线核对，确认这是既有行为；本次整个 `integration/cometbft` 子树逐字节不变，因此它仍未修复，也没有被本次修改引入或加重。该行为不会把取消报告为同步成功，继续作为 **P3 非阻断项** 记录。若后续统一错误身份，应单独修复并添加 RPC 中途取消回归，不能在归档时将此项改写为已修复。

## 静态、模拟与原生证据的明确区分

| 证据类别 | 本审核实际做了什么 | 不能据此声称什么 |
|---|---|---|
| 本次静态和身份检查 | 远端 Git commit、本地 Git 对象、完整修改清单、范围字节比较、相同 tree/blob ID、diff 检查、旧报告摘要核对。 | 不证明新 Rust 实现已运行正确，也不证明性能改善。 |
| 既有控制流模拟 | `a11370…` 精确 source job 脚本的 12 种模拟 subprocess 结果均符合预期；本次对应工作流字节未变，没有重新冒称执行一套新模拟。 | 不等于实际 gofmt/Rustfmt、编译、密码学或四节点测试。 |
| 原生测试与 CI | 本审核任务没有本地运行 Go/Rust native、race、fuzz、Clippy、真实增长或四节点实验；没有独立读取本次 CI 日志来签署成功。 | 不可写成本次 CI 通过、旧 CI 可替代当前提交、阶段验收完成或性能目标达成。 |

活动四节点仍是低高度流程覆盖；超过 10000 的 worker 增长、签名头边界和真实四节点同步应分别计证。100000 次本地 worker 提交不能称为四节点共识 100000 块，也不证明支付 TPS、端到端延迟、超过 64 MiB 的增长或生产存储能力。

新 Rust 根缓存的设计和实现审核需引用对应审核者自己的准确提交记录；项目负责人所告知的其他审核结果或 CI 状态不能计成本审核者自己的执行证据。当前 CI 由独立验收流程判定，本文不替该流程作通过声明。

本报告属于独立 coding-agent 的有限范围代码审核，**不是外部机构安全审计、密码学协议审计或生产存储认证**。本机无资金边界不变。本报告不批准部署、付费资源、数据迁移、真实资金操作或合并；后续源码变更不能无条件继承本结论。
