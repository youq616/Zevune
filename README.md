# Zevune · 澄隐

**开发中，禁止真实资金。尚未形成可用隐私支付网络，没有完整钱包、发行规则或网络匿名，未经独立安全审计。**

项目的源码分为根 Go、嵌套 CometBFT Go 和独立 Rust 三个模块。工程阶段如下，不能把单个模块测试成功理解为整条链完成：

| 阶段 | 状态与范围 |
|---|---|
| M1/M2 根程序 `zevuned`，0.1.2-dev | 单机状态机、预执行、校验提交、可选日志与重启恢复；付款关闭 |
| M3 `integration/cometbft`，0.2.0-consensus-dev | 实际四进程 CometBFT 签名共识、空块推进与故障恢复；交易全部拒绝 |
| M4 `integration/orchard`，0.1.0 | 真实 Orchard/Halo 2 证明、RedPallas 授权签名、解密与连续两段转移测试 |
| M5 `internal/orchardbridge` 与 Rust worker | 有界交易字节、本地验证子进程、真实 Go→Rust 证明验证；不是共识支付入口 |
| M6 Rust `pool` | 真正 Orchard 资产树、整块原子验证、日志保存与密码学重放；未接入 M3 或钱包 |

## 本轮：真实验证连接与资产状态

[M5/M6 设计与边界](docs/ORCHARD_STATE.zh-CN.md) 说明了新接口及存储格式。Go 不实现替代证明算法，而是调用固定版本的真实 Rust 验证程序。协议握手和完整字节摘要绑定每次回复；程序摘要不符、超时、异常退出或回复错配均不放行。真实证明有效还不等于未重复花费，可信账本检查仍是独立职责。

Rust `PoolStore` 使用上游 Orchard Merkle 哈希和增量树，不使用旧 Go 占位树。候选执行在副本上进行，正式提交再次验证，日志同步成功后才推进内存；重启时重新检查历史交易的真实证明、签名及状态转换。公开创建入口只支持空创世状态，没有发行接口；非空初始测试资产只存在于自动化测试的私有初始化路径。

测试包含 A→B、落盘重开、B→C、再次重开、重复花费拒绝、竞争候选失效、损坏日志和写入故障。校验和不是防篡改认证；完整旧日志的回滚仍需与独立可信检查点对账。本模块没有完成共识恢复握手，且有明确容量上限，不是生产数据库。

M5 的 Go/Rust 授权验证通道、M6 的 Rust 本地状态库和 M3 的共识应用仍未连接成一个支付网络。钱包加密存储、同步、恢复、创世发行、费用/奖励、网络隐私及完整网络性能仍未完成。没有迁移旧日志，没有增加全网查看密钥，没有开启付款。

## 已有密码学与共识模块

[integration/orchard](integration/orchard/README.md) 锁定 Orchard 0.15.5，使用已修复 V2 电路，拒绝不安全历史 V1。复用真实证明、花费与绑定签名、收款解密，不自写电路，不上传私密见证。实验签名摘要不是经过独立审查的最终交易协议或 ZIP-244；单项密码学耗时不等于真实到账速度。

M3 使用 CometBFT v0.38.26，通过内部 ABCI 驱动原型账本。四个独立进程在同机 loopback 网络进行签名共识，测试离线、追赶、异常终止与全体重启。只允许空区块，不代表跨地域或独立运营者网络。数据目录不混用，签名状态不重置。

## 验收方式

用户已验证 Windows 基础环境与 M1/M2。开发以自动回归和 CI 为主，不要求每个小版本重复手工验证。完整交付标准见 [整体验收要求](docs/INTEGRATION_ACCEPTANCE.zh-CN.md)，当前尚未达到。

根目录 `go test ./...` 不运行另外两个独立模块。四套工作流分别检查根模块、共识模块、Rust 模块和跨语言联调。结果须对应明确提交；Cargo.lock 和固定工具链随源码提交，使用 `--locked`，常规 CI 只读仓库，不自动修改源码、格式或依赖。缺少真实 worker 或真实证明样本时跨语言测试失败，不会以跳过冒充成功。

## 已有单机程序操作文档（无需本轮重测）

根模块仍无第三方 Go 依赖，不需要 Docker：

```powershell
go test ./... -count=1
go run ./cmd/zevuned -version
go run ./cmd/zevuned -data-dir "$env:LOCALAPPDATA\Zevune\devnet"
```

状态查询：

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/v1/status" | ConvertTo-Json -Depth 6
```

根程序仍显示 `software_version=0.1.2-dev`、`height=0`、付款和最终确认为 false。新库不会自动改变其运行行为。不要公开诊断接口，不要删除日志或防重复签名状态来“升级”。独立模块的构建命令是开发文档，不要求用户重复安装 Rust 或验证每项功能。

## 资料

- [M1 存储](docs/LOCAL_STORAGE.zh-CN.md)。
- [M2 预执行](docs/BLOCK_PREVIEW.zh-CN.md) 与 [测试](reports/m2-remote-validation.md)。
- [M3 共识集成](integration/cometbft/README.md) 与 [验收](reports/m3-remote-validation.md)。
- [M4 密码学](integration/orchard/README.md) 与 [历史验收](reports/m4-remote-validation.md)。
- [M5/M6 连接与真实资产状态](docs/ORCHARD_STATE.zh-CN.md)。
- [历史缺失文档清单](docs/PUBLICATION_STATUS.zh-CN.md)。六份原始文档仍未重新提交，新说明不是恢复副本或完整协议规范。

不要上传私钥、种子、钱包数据、付款明文或节点签名状态。参见 [安全说明](SECURITY.md)、[许可证状态](LICENSE-STATUS.md) 和 [第三方声明](integration/orchard/NOTICE.md)。源码公开不等于已选择整个项目的开源许可证，也不等于安全审计。
