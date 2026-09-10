# M2 远程验收记录

日期：2026-09-10。软件版本：0.1.2-dev。仓库：youq616/Zevune。

## 源码与主分支

- 已核验源码提交：`6c234ba19f86dff2f292b97b08b930a2c279eced`。
- 基线：`fedf03bc7e9a2fdfc6f864a8e66781d443c57b4e`。
- 开发分支 `dev/m2-block-preview` 的 CI 成功后，main 已非强制 fast-forward 到同一源码提交；保留原历史和仓库可见性。
- 本次共新增或修改 11 个文件，其中 7 个 Go 文件。7 个 Go 文件的远端 blob SHA 均与本地测试版本一致。

## GitHub 实际测试

运行编号：`34479191542`。对应源码提交与上面相同。

运行地址：https://github.com/youq616/Zevune/actions/runs/34479191542

- Windows job `102877407698`：completed / success；格式、单元测试和 go vet 通过；race 与 fuzz 按配置跳过。
- Ubuntu job `102877407851`：completed / success；格式、单元测试、go vet、race、交易解码短时 fuzz、日志解码短时 fuzz 均通过。

GitHub 环境实际执行了代码检出和测试。本执行环境原生 git clone 的 DNS 失败仍然存在，未将连接器读取表述为本机克隆成功。

## 文件一致性

| 文件 | Git blob SHA |
|---|---|
| internal/ledger/engine.go | b0a520182ec48e4d8c9449440de57d917eb4cb03 |
| internal/ledger/preview.go | a9840d7605743c10aaad69339e179a965c63d1b8 |
| internal/ledger/preview_test.go | 4a15a1b98d15584773e1f56baad4247955c07930 |
| internal/ledger/summary_test.go | baf3d97e2d983e95409f023a69d302e796e27bae |
| internal/api/server.go | 71bd3edbee7757e8bce7ba271ca5ef8b4532d316 |
| internal/api/version_test.go | a8ef54b5517b97d62086e41dbca9d58225bfb1ae |
| cmd/zevuned/main.go | 8a7a9266fdd967e37496805cf59adfd855c74efa |

本地 91 个顶层 Test、故障测试、重启检查及摘要编码基准详见 [本地报告](m2-local-validation.md)。摘要基准不是链上 TPS 或转账延迟。本文件是验收后的文档提交，不修改源码；这里的 CI 结论仅对应明确列出的源码提交，不预先认证后续改动。

付款、真实证明、钱包、共识与网络匿名仍未实现；六份历史缺失技术文档未重新提交。本轮完成的是区块预执行、带校验提交和保持兼容的摘要计算优化，不是可用的隐私测试网。
