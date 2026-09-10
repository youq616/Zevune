# Zevune · 澄隐

**v0.1.0-dev：单机状态机工程骨架，不是已上线的区块链。没有真实零知识证明、钱包或共识；所有付款禁用，不得存入真实资产。**

中文名称：澄隐；英文名称：Zevune；节点程序：`zevuned`；Go 模块：`github.com/youq616/Zevune`。

## 发布与验证

**原型运行源码和测试已经进入 main，并通过 GitHub Ubuntu、Windows 两个平台的自动测试。** 已核验源码提交：`a56492d91e874919cf10a6f59d80c6c42c150a61`；[对应 CI 运行](https://github.com/youq616/Zevune/actions/runs/34469933126)。全部 15 个 Go 文件、go.mod 和 CI 工作流的远端 Git blob 哈希与本地测试源码一致。

**整个原始交付包仍未全部发布：6 份技术文档上传时被执行平台安全检查拦截。** 缺失名单见 [发布状态](docs/PUBLICATION_STATUS.zh-CN.md)。这些文档不参与当前 Go 程序编译。

[本次发布核验报告](reports/publication-retry-2026-09-10.md) 区分源码提交、哈希验证、GitHub CI 和本地测试。之前的 `reports/validation.md`、`reports/local-validation.md` 是历史阶段记录，不代表本次远程测试。后续仅更新状态文档的提交不改变上述已测运行源码；CI 结论按明确提交编号记录。

## 已实现的原型范围

- 有边界的二进制交易信封与链/版本检查。
- 内存状态机、重复标识检查、整块原子更新和确定性摘要。
- 缺少真实验证器时拒绝付款的验证边界。
- 仅本机诊断接口、带合成数据标识的延迟统计工具及测试。

真实证明系统、钱包、多节点共识、持久化和网络隐私均未实现。不得使用模拟验证器开启实际支付。上传成功和 CI 通过不等于安全审计或真实转账能力。

## 本地运行

安装 Go 后，在项目根目录运行；当前 Go 代码没有第三方依赖，不需要 Docker。

```powershell
go test ./... -count=1
go vet ./...
go run ./cmd/zevuned
```

另开 PowerShell：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/v1/status
```

`payments_enabled=false`、`finality_available=false` 和 `/readyz` 返回 503 均为预期结果。不要把本机诊断接口暴露到公网。

```powershell
go run ./cmd/latency-report -input ./examples/latency-SYNTHETIC.jsonl
```

该输出是合成示例，不是实际转账速度。

## 目录

```text
cmd/zevuned/          仅本机诊断程序
cmd/latency-report/   样本统计命令
internal/protocol/   临时交易信封与编码
internal/ledger/     内存状态机与拒绝式验证边界
internal/merkle/     原型公共 SHA-256 树
internal/api/        无付款能力的诊断 API
internal/latency/    样本校验和统计
scripts/             本地测试脚本
.github/workflows/   自动测试配置
```

历史 v0 链标识和域分离字节保留，由更名兼容性测试检查；它们不是主网参数。见 [品牌说明](docs/BRANDING.zh-CN.md)。

参见 [安全状态](SECURITY.md) 和 [许可证待定说明](LICENSE-STATUS.md)。公开可读不等于已经选择开源许可证。
