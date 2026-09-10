# Zevune · 澄隐

**开发中，禁止真实资金。尚未实现真实隐私支付、钱包、发行规则或网络匿名，未经独立安全审计。**

项目包含两个明确分离的程序：M2 单机诊断原型 `zevuned`（0.1.2-dev），以及新增的 M3 CometBFT 四节点空区块实验模块（0.2.0-consensus-dev）。后者不是已完成的隐私主链，也不会替换前者的数据目录。

## 当前进展

M1/M2 根模块包含有边界的二进制信封、链/版本检查、重复标识检查、整块验证、确定性状态摘要、仅本机诊断 API、可选追加日志、重启重放和操作系统文件锁。`PreviewBlock` 在副本上执行，`CommitPreview` 重新检查并提交；流式摘要保持旧摘要及日志格式兼容。测试替身不进入可执行程序。

M3 位于 [integration/cometbft](integration/cometbft/README.md)，接入固定版本 CometBFT v0.38.26，通过内部 ABCI 驱动原账本。包含四个独立进程的本机网络启动器、提案检查、FinalizeBlock/Commit 分离、持久化握手、真实提交签名验证和故障恢复测试。**只允许空区块，所有交易仍拒绝。** 四节点均由同一台测试机控制，不代表独立运营者或跨地域去中心化。

真实证明、钱包、支付、经济规则、生产存储、网络隐私和独立审计尚未完成。源码公开、CI 成功和空块高度增长不能替代这些工作，也不能证明真实到账速度。

## 验收安排

用户已完成 Windows 基础环境与 M1/M2 验证。后续以开发者回归测试和 GitHub CI 为主，不要求用户对每个小版本重复手工测试。整合支付版本的交付门槛见 [整体验收标准](docs/INTEGRATION_ACCEPTANCE.zh-CN.md)。

根模块与嵌套共识模块有不同的 CI。根目录 `go test ./...` 不会自动运行嵌套模块测试。每次验收按明确提交查看对应 Actions，不能用旧记录替代当前结果。

## 单机原型（原有方式保留）

根模块仍无第三方依赖，不需要 Docker。以下是操作文档，不是要求用户本轮再验证：

```powershell
go test ./... -count=1
go vet ./...
go run ./cmd/zevuned -version
go run ./cmd/zevuned -data-dir "$env:LOCALAPPDATA\Zevune\devnet"
```

不带 `-data-dir` 时为内存模式。启动后可在另一终端查询：

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/v1/status" | ConvertTo-Json -Depth 6
```

该单机程序继续显示 `software_version=0.1.2-dev`、`height=0`、付款/最终确认为 false；不会自动出块。M3 实验网络是单独程序和链标识，需要新目录，不能拿旧日志直接当作共识数据库。M3 的具体命令和容量限制见其 README。

## 自动化测试与资料

- [M1 存储说明](docs/LOCAL_STORAGE.zh-CN.md) 与 [本地记录](reports/m1-local-validation.md)。
- [M2 预执行接口](docs/BLOCK_PREVIEW.zh-CN.md)、[本地测试与摘要基准](reports/m2-local-validation.md)、[远程核验](reports/m2-remote-validation.md)。
- [M3 共识模块](integration/cometbft/README.md)：锁定依赖、两平台真实四进程测试、恢复验证及限制。
- [历史发布核验](reports/publication-retry-2026-09-10.md) 与 [历史缺失文档名单](docs/PUBLICATION_STATUS.zh-CN.md)。

原始交付包中六份技术文档此前未成功发布，仍未在本次重新提交。M3 文档不替代完整隐私协议规范。合成摘要基准不是支付延迟或 TPS；本轮没有测量实际隐私转账速度。

## 目录

```text
cmd/zevuned/          原有单机诊断程序
cmd/latency-report/   合成样本统计，不是网络测速
internal/ledger/     状态机、预执行、校验提交、本地日志
internal/protocol/   临时信封与编码
internal/merkle/     原型公共 SHA-256 树
internal/api/        无付款能力的诊断接口
internal/latency/    样本统计
integration/cometbft/ 独立 Go 模块，真实共识/空块实验与启动器
.github/workflows/   根模块与共识模块各自的跨平台测试
```

历史 v0 链标识与固定字节不随品牌修改，见 [品牌说明](docs/BRANDING.zh-CN.md)。不要上传运行时生成的验证者密钥、签名状态、钱包数据或日志目录。参见 [安全状态](SECURITY.md) 与 [许可证待定说明](LICENSE-STATUS.md)；公开可读不等于已选择开源许可证。
