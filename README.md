# Zevune · 澄隐

**开发中，禁止真实资金。尚无完整钱包、发行规则或网络匿名，未经独立安全审计。M7 的零金额协议交易不是已完成的隐私支付产品。**

源码分为根 Go、嵌套 CometBFT Go 和独立 Rust 三个模块。工程进展与范围：

| 阶段 | 范围 |
|---|---|
| M1/M2 根程序 `zevuned`，0.1.2-dev | 原有单机账本、预执行、日志恢复；付款关闭 |
| M3 `integration/cometbft` 原 `app`，0.2.0-consensus-dev | 原有四进程空块共识实验，运行入口和数据不变 |
| M4 `integration/orchard`，0.1.0 | 真实 Orchard/Halo 2 证明、授权签名、解密与进程内两段转移测试 |
| M5 `internal/orchardbridge` | Go 调用真实 Rust 授权验证器，有界本地通信 |
| M6 Rust `pool` | 真实 Orchard 资产树、原子验证、持久化与密码学重放 |
| M7 `poolbridge`、`poolapp` 和持久化 worker | 将真实 Orchard 状态与 CometBFT 连接，整合测试使用零金额真实证明交易；不是钱包付款或主网 |

## M7：不再只是各模块单独运行

连接路径：CometBFT → ABCI `poolapp` → Go `poolbridge` → 本机 Rust `zevune-pool-worker` → Orchard `PoolStore`。每个测试节点有自己的进程、Rust worker 和日志。

`Preview` 不持久化；`FinalizeBlock` 固定待提交区块的全部字节和预期状态，仍不落盘；`Commit` 引用相同候选并执行真实验证、写入和同步。`Info` 始终暴露最后已提交高度及状态摘要，以供 CometBFT 恢复握手。回复错配、进程故障和不确定提交不能被当成验证成功，也不会自动重试。

新网络只通过带 `pool_e2e` 标签的本机测试初始化，没有新增公网支付启动器。公开存储仍只支持空创世，没有发行或注资接口。因此四进程测试使用**真实零知识证明的零金额交易**检查广播、入块、树更新、持久化和整网重启，不声称完成 A 向 B 的非零金额支付。

测试逐个验证真实提交签名、区块 ID、验证者集合以及区块头中上一高度的应用摘要，并通过另一个新 Rust 状态进程独立重放公共块。另测 Finalize 后中断、重新打开、同一候选重放、Commit 后再次打开、重复交易拒绝与提案原子性。当前只有单机 loopback 网络，不是跨地域或独立运营主体。

设计、容量、故障边界和未完成项见 [M7 连接说明](docs/ORCHARD_CONSENSUS.zh-CN.md)。测试结果必须查对应源码提交的 Actions，不以旧结果认证新的修改。

## 密码学与存储边界

Orchard 锁定 0.15.5，使用已修复 V2 电路，拒绝不安全历史 V1。真实证明、逐个花费/绑定签名及收款解密来自上游，没有自写电路、跳过证明开关、全网查看密钥或私密见证服务。实验签名摘要与链标识仍不是经过外部评审的最终协议；不同测试网的 genesis 域绑定与升级策略仍待完成。

M6 存储使用真实 Orchard 哈希与增量树，重开逐条重新验证交易。只读检查不等于落盘，日志校验和不等于认证；完整旧日志回滚还需独立可信共识对账。日志和状态有明确容量上限，不自动删除历史绕过限制。实际断电、恶意操作系统、生产级存储和完整恢复策略不在已验证保证中。

M1/M2 的旧 Go SHA-256 树和日志没有被重新解释成 Orchard 格式。原有 M3 空块程序也保持独立，不读取新实验的日志。

## 自动验证与整体交付

用户已验证 Windows 基础环境，开发以自动回归和 CI 为主，不要求每个小版本手工测试。完整交付门槛仍是 [整体验收要求](docs/INTEGRATION_ACCEPTANCE.zh-CN.md)，当前尚未达到。

五套工作流分别覆盖根模块、原共识实验、Rust 密码学、授权连接和新增持久化共识整合。根目录 `go test ./...` 不自动执行嵌套 Go/Rust 模块。常规 CI 使用已提交格式、锁文件和固定工具链，仅有读权限；测试不能改源码或依赖。缺少真实 worker 或真实样本时整合测试失败，不会跳过冒充成功。

未完成：完整钱包及加密存储、同步/备份/恢复、经过审查的创世发行与费用奖励、正式网络协议、网络隐私与拒绝服务防护、生产存储、端到端性能和独立安全审查。零金额入块、空块时间、单项证明耗时都不能当成完整到账延迟、TPS 或匿名性认证。

## 原有诊断程序（无需本轮重测）

根程序及已有用户数据不迁移，不需要 Docker：

```powershell
go test ./... -count=1
go run ./cmd/zevuned -version
go run ./cmd/zevuned -data-dir "$env:LOCALAPPDATA\Zevune\devnet"
```

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/v1/status" | ConvertTo-Json -Depth 6
```

它仍显示 `software_version=0.1.2-dev`、`height=0`、付款和最终确认为 false，不会自动变成 M7 网络。不要开放诊断端口，不要删除日志或防重复签名状态来升级。

## 资料

- [M1 存储](docs/LOCAL_STORAGE.zh-CN.md) 与 [M2 预执行](docs/BLOCK_PREVIEW.zh-CN.md)。
- [M3 共识](integration/cometbft/README.md) 与 [M4 密码学](integration/orchard/README.md)。
- [M5/M6 连接和资产状态](docs/ORCHARD_STATE.zh-CN.md) 及 [验收报告](reports/m5-m6-remote-validation.md)。
- [M7 持久化共识连接](docs/ORCHARD_CONSENSUS.zh-CN.md)。
- [历史缺失文档](docs/PUBLICATION_STATUS.zh-CN.md)：六份原始文档仍未恢复，新说明不是替代副本或完整协议规范。

不要上传私钥、种子、查看密钥、钱包数据、付款明文或节点签名状态。参见 [安全说明](SECURITY.md)、[许可证状态](LICENSE-STATUS.md)、[第三方声明](integration/orchard/NOTICE.md)。源码公开不等于选择了整个项目的开源许可证，也不等于安全审计。
