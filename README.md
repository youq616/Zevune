# Zevune · 澄隐

**开发中，禁止真实资金。尚未形成可用隐私支付网络，没有完整钱包、发行规则或网络匿名，未经独立安全审计。**

项目分成三个独立模块，不能将其中一个模块测试通过理解为整条链已经完成：

| 模块 | 状态与范围 |
|---|---|
| M1/M2 根 Go 模块 `zevuned`，0.1.2-dev | 单机状态机、预执行、校验提交、可选日志与重启恢复；付款关闭 |
| M3 `integration/cometbft`，0.2.0-consensus-dev | 实际四进程 CometBFT 签名共识、空块推进与故障恢复；交易全部拒绝 |
| M4 `integration/orchard`，0.1.0 | 真实 Orchard/Halo 2 证明、RedPallas 授权签名、收款解密与连续两段转移测试；仅独立进程内实验，未接入共识 |

## M4：真实密码学集成

[integration/orchard](integration/orchard/README.md) 锁定 Orchard 0.15.5，使用已修复的 V2 电路，明确拒绝不安全的历史 V1。没有自写证明系统，没有接受假证明的开关，没有向中心服务上传见证、花费密钥或查看密钥。

自动化测试在内存中生成一次性的无价值初始票据，完成 A→B（含找零）→C：第二笔实际花费 B 从第一笔密文解出的票据。检查真实证明、花费签名、绑定签名、受信任历史根、重复花费标识、输出重复、费用与过期高度。包含能够被上游电路证明但在无外部注资规则下必须拒绝的负余额变化，避免把“证明有效”误认为“发行合法”。

当前签名上下文是带独立域的实验格式，不是最终网络协议或 ZIP-244。验证函数只读取调用方提供的可信账本视图，不负责落盘。网络字节编码、节点可信状态绑定、跨语言边界、钱包存储与同步、经济规则等均未完成。旧 Go 占位树和密文格式不能直接当作 Orchard 格式；本次没有迁移旧数据。

真实密码学测试和单项耗时不等于匿名性认证、网络最终性、端到端延迟或 TPS。整个网络的付款入口仍然关闭。

## 既有模块

M1/M2 根模块包含有边界的二进制信封、链/版本检查、重复标识检查、整块验证、确定性摘要、仅本机诊断 API、追加日志、重放与操作系统文件锁。`PreviewBlock` 不改变已提交状态；`CommitPreview` 重新检查后提交。

M3 使用 CometBFT v0.38.26，通过内部 ABCI 驱动原型账本。四个独立进程在同机 loopback 网络进行真实签名共识，测试节点离线、追赶、异常终止与全体重启。只允许空区块；不等于跨地域部署或独立运营者网络。两部分数据目录不混用，签名状态不重置。

## 验收方式

用户已验证 Windows 基础环境与 M1/M2。开发以自动回归和 CI 为主，不要求每个小版本重复手工验证。完整交付标准见 [整体验收要求](docs/INTEGRATION_ACCEPTANCE.zh-CN.md)，当前尚未达到。

根 Go 模块、嵌套 CometBFT Go 模块和独立 Rust 模块分别测试。根目录 `go test ./...` 不运行另外两个模块。CI 结论须对应明确提交，不能以旧版本结果替代当前结果。M4 构建使用提交的 Cargo.lock、固定工具链和 `--locked`；常规 CI 只读仓库，不自动改源码。

## 已有单机程序操作文档（无需本轮重测）

根模块仍无第三方依赖，不需要 Docker：

```powershell
go test ./... -count=1
go run ./cmd/zevuned -version
go run ./cmd/zevuned -data-dir "$env:LOCALAPPDATA\Zevune\devnet"
```

状态查询：

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/v1/status" | ConvertTo-Json -Depth 6
```

根程序依然显示 `software_version=0.1.2-dev`、`height=0`、付款和最终确认为 false。它不会自动变为 M3/M4 网络。不要把诊断接口公开到互联网；不要删除旧日志或防重复签名状态来“升级”。

## 资料

- [M1 存储](docs/LOCAL_STORAGE.zh-CN.md)。
- [M2 预执行](docs/BLOCK_PREVIEW.zh-CN.md) 与 [测试](reports/m2-remote-validation.md)。
- [M3 共识集成](integration/cometbft/README.md) 与 [验收](reports/m3-remote-validation.md)。
- [M4 密码学集成范围与测试](integration/orchard/README.md)。
- [历史缺失文档清单](docs/PUBLICATION_STATUS.zh-CN.md)。六份原始技术文档仍未重新提交，新模块说明不替代完整隐私协议规范。

不要上传运行时生成的私钥、种子、钱包数据、付款明文或节点签名状态。参见 [安全说明](SECURITY.md)、[许可证状态](LICENSE-STATUS.md) 与 [M4 第三方声明](integration/orchard/NOTICE.md)。源码公开不等于选择了整个项目的开源许可证，也不等于安全审计。
