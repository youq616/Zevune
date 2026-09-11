# Zevune · 澄隐

**开发中，禁止真实资金。已实现本地钱包核心，尚无完整网络钱包、发行规则或网络匿名，未经独立安全审计。M8 的非零金额本地付款与 M7 的零金额四节点交易不能混称完整支付网络。**

源码分为根 Go、嵌套 CometBFT Go 和独立 Rust 三个模块。

| 阶段 | 范围 |
|---|---|
| M1/M2 根程序 `zevuned`，0.1.2-dev | 原有单机账本、预执行、日志恢复；付款关闭 |
| M3 原 `integration/cometbft/app`，0.2.0-consensus-dev | 原有四进程空块共识，运行入口和数据不变 |
| M4 Rust Orchard | 真实 Halo 2 证明、授权签名、解密 |
| M5 `internal/orchardbridge` | Go 调用真实 Rust 授权验证器 |
| M6 Rust `pool` | 真实资产树、原子验证、持久化与密码学重放 |
| M7 `poolbridge`、`poolapp` 和持久化 worker | 四节点真实证明、零金额入块、落盘和整网重启 |
| M8 Rust `wallet`、`wallet::vault`、`pool::history` | 本地钱包、非零金额付款/找零、待确认预留、加密备份及重扫恢复；未接入非零金额共识付款 |

## M8：钱包核心，不再手工拼装后续付款

钱包本地生成种子，通过上游 ZIP32 派生测试密钥与收款地址，扫描外部收款和内部找零，选择真实未花费票据，生成并验证真实付款证明及签名。多个输入共用一次资产树路径计算，复用公开证明参数。没有伪证明放行、全网查看密钥、明文种子导出、遥测或上传见证。

待确认交易预留输入；加密备份保留种子、同步检查点及预留，恢复后必须重扫经本地完整重放的账本才能得到余额。拒绝较旧历史和祖先不一致的更长历史，过期高度采用包含端点的规则。构造交易不是广播或到账确认。

备份用锁定的 Argon2id 与 XChaCha20-Poly1305，固定资源参数和 620 字节格式，整个头部认证；错误口令或篡改密文会拒绝导入。创建备份不覆盖旧文件。密码强度、恶意设备、旧备份回滚、多进程协调、Windows ACL 和应用级保存/广播原子性仍需单独处理，不能称为生产钱包。

自动测试使用私有测试初始票据，真实分配两笔收款；钱包合并付款、识别找零、加密恢复、到期释放后再次付款，关闭并重开账本后余额保持一致。全部余额和累计费用对账，不设置任意增发或充值接口。详见 [本地钱包范围与安全边界](docs/LOCAL_WALLET.zh-CN.md)。

## M7：已有的真实共识连接保持不变

CometBFT → ABCI `poolapp` → Go `poolbridge` → 本机 Rust `zevune-pool-worker` → Orchard `PoolStore`。每个测试节点有自己的进程、worker 和日志。Preview 不落盘；FinalizeBlock 固定完整有序候选；Commit 重新验证、同步日志并核对结果。Info 只返回已提交状态。故障、回复错配或不确定提交不会被当作成功或自动重试。

公开存储仍只支持空创世，无发行或注资接口；非空启动仍限制在私有测试代码。因此四进程路径继续以零金额真实证明交易检查广播、签名共识、入块及恢复，不声称已完成钱包间非零金额网络支付。测试比较真实提交签名和独立重放的应用摘要；网络限同机 loopback，非跨地域或独立运营者。详见 [M7](docs/ORCHARD_CONSENSUS.zh-CN.md)。

## 密码学与存储边界

Orchard 锁定 0.15.5，使用修复后的 V2 电路和真实上游加密、证明、签名，不改写密码电路。实验交易摘要、主网/创世域与升级规则仍待外部审查。依赖锁不是漏洞审计。

M6 日志重开逐条验证真实授权及状态转换；M8 的历史读取还与已打开账本的已提交摘要比较。校验和不是外部认证，本地完整节点不是轻客户端，回滚与共识必须另行对账。日志、记录和状态有明确容量上限，不自动删除历史绕过限制。任意断电、恶意操作系统及生产存储不在当前保证中。

原有 Go 占位树与日志未重新解释为 Orchard；M1/M2 和原 M3 的程序、版本、数据路径不迁移。

## 自动验证与整体交付

用户已验证 Windows 基础环境。开发依赖自动回归及 CI，不要求每个小版本手工测试。整体验收仍依据 [完整验收要求](docs/INTEGRATION_ACCEPTANCE.zh-CN.md)，当前尚未达到。

六套工作流分别覆盖根模块、原共识、Rust 密码学、授权连接、持久化共识连接和本地钱包。根目录 `go test ./...` 不运行两个独立嵌套模块。正式 CI 检查已提交源码格式和固定依赖，只有读取权限，不在检查中修改源码。结果必须对应明确提交；缺少真实 worker/证明样本时整合检查失败而不是跳过。

未完成：用户钱包 UI/CLI、分发与安全更新、认证网络同步、多设备和可靠广播、非零金额四节点付款、受审查的发行/奖励规则、正式协议、网络隐私、生产存储、端到端性能及独立安全审计。没有支付 p95/TPS 成绩，不把单项加密耗时、空块间隔或测试时间当到账速度。

## 原诊断程序文档（本轮无需操作）

```powershell
go test ./... -count=1
go run ./cmd/zevuned -version
go run ./cmd/zevuned -data-dir "$env:LOCALAPPDATA\Zevune\devnet"
```

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/v1/status" | ConvertTo-Json -Depth 6
```

它仍显示 0.1.2-dev、height=0、payments_enabled=false、finality_available=false，不自动变成钱包网络。不要开放诊断接口，不要删除账本或防重复签名状态来升级。

## 资料

[M1 存储](docs/LOCAL_STORAGE.zh-CN.md) · [M2 预执行](docs/BLOCK_PREVIEW.zh-CN.md) · [M3 共识](integration/cometbft/README.md) · [Rust 密码学](integration/orchard/README.md) · [M5/M6](docs/ORCHARD_STATE.zh-CN.md) · [M7](docs/ORCHARD_CONSENSUS.zh-CN.md) · [M8 本地钱包](docs/LOCAL_WALLET.zh-CN.md)。

[六份历史文档](docs/PUBLICATION_STATUS.zh-CN.md)仍未恢复，新说明不是替代副本或完整协议。不要上传种子、私钥、查看密钥、钱包文件、付款明文或验证者签名状态。参见 [安全说明](SECURITY.md)、[许可证状态](LICENSE-STATUS.md)、[上游声明](integration/orchard/NOTICE.md)。源码公开不等于整个项目已确定开源许可证，也不等于独立审计。
