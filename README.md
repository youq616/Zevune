# Zevune · 澄隐

**v0.1.2-dev：单机状态机与可选本地日志工程骨架，不是已上线的区块链。没有真实零知识证明、钱包或共识；所有付款禁用，不得存入真实资产。**

中文名称：澄隐；英文名称：Zevune；节点程序：`zevuned`；Go 模块：`github.com/youq616/Zevune`。

## 当前进展

原型包含有边界的二进制交易信封、链/版本检查、重复标识检查、整块验证、确定性状态摘要和仅本机诊断 API。测试替身不进入可执行程序。

M1 提供可选本地追加日志：保存后同步、启动时重新验证并重放、操作系统文件锁，以及损坏日志拒绝。详细故障边界见 [本地存储说明](docs/LOCAL_STORAGE.zh-CN.md)。

M2 第一部分增加 `PreviewBlock` 与 `CommitPreview`：先在副本上验证候选区块，不修改已提交状态；真正提交时重新验证，并拒绝过期或被修改的候选。状态摘要改为流式编码，同时保持旧摘要与日志格式兼容。见 [接口说明与下一步共识要求](docs/BLOCK_PREVIEW.zh-CN.md) 和 [本地验证及基准](reports/m2-local-validation.md)。这还不是完整 ABCI 适配器，未接入 CometBFT。

真实证明系统、钱包、多节点共识和网络隐私仍未实现。不得使用模拟验证器开启实际支付。源码公开和测试通过不等于安全审计或真实转账能力。

## 本地运行

安装 Go 后，在项目根目录运行。当前代码仍无第三方依赖，不需要 Docker。

```powershell
go test ./... -count=1
go vet ./...
go run ./cmd/zevuned -version
go run ./cmd/zevuned
```

上面是纯内存模式。Windows 的可选持久模式：

```powershell
go run ./cmd/zevuned -data-dir "$env:LOCALAPPDATA\Zevune\devnet"
```

更新时先 Ctrl+C 停止旧进程，执行 `git pull --ff-only` 并重新测试；无需删除原日志。两种模式不能同时占用同一监听端口。另开 PowerShell 查询：

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/v1/status" | ConvertTo-Json -Depth 6
```

新增 `software_version=0.1.2-dev`。`payments_enabled=false`、`finality_available=false`、`height=0` 和 `/readyz` 返回 503 仍是预期结果。程序不会自动出块；没有提供 HTTP 区块预执行或提交入口。不要把本机接口暴露到公网。持久模式首次创建日志时 `storage.recovered=false`，同目录再次启动时为 `true`；不指定目录时 `storage.mode=memory`。

## 测试与性能口径

[M1 本地记录](reports/m1-local-validation.md)、[M2 本地记录](reports/m2-local-validation.md) 与远程 CI 分开记录。GitHub Actions 必须按源码提交核对，不能用旧提交的成功结果替代。

```powershell
go test ./internal/ledger -run '^$' -bench '^BenchmarkSummaryEncoding$' -benchmem -benchtime=200ms -count=3 -cpu=1
```

该基准仅比较合成状态的摘要计算，**不是转账延迟、TPS 或证明系统性能**。M2 的预执行和提交都会验证证明，目前没有省略验证的加速选项。

历史源码提交 `a56492d91e874919cf10a6f59d80c6c42c150a61` 的发布记录见 [历史核验](reports/publication-retry-2026-09-10.md)。历史报告只描述相应阶段。

原始交付包中六份技术文档此前未完成发布，本次未重新提交它们，名单见 [历史发布状态](docs/PUBLICATION_STATUS.zh-CN.md)。本次接口文档不替代缺失的隐私协议规范；缺失文档不参与当前 Go 编译。

## 目录

```text
cmd/zevuned/          本机诊断程序，支持 -data-dir 与 -version
cmd/latency-report/   合成样本统计命令，不是实测网络延迟
internal/protocol/   临时交易信封与编码
internal/ledger/     状态机、候选预执行、校验提交、可选本地日志
internal/merkle/     原型公共 SHA-256 树
internal/api/        无付款能力的诊断 API
internal/latency/    样本校验与统计
scripts/             本地测试脚本
.github/workflows/   Ubuntu/Windows 自动测试
```

历史 v0 链标识和域分离字节由兼容性测试保护；它们不是主网参数，不随品牌文字修改。见 [品牌说明](docs/BRANDING.zh-CN.md)。

参见 [安全状态](SECURITY.md) 和 [许可证待定说明](LICENSE-STATUS.md)。公开可读不等于已经选择开源许可证。
