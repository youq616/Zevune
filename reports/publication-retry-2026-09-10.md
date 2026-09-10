# Zevune 发布重试与核验报告

日期：2026-09-10。仓库：youq616/Zevune。对象是禁止真实资金进入的单机原型，不是生产区块链。

## 已核验的源码提交

- 原样重试状态机源码成功：`cacfb7c5bc832901b7836dfa05ee307e0436f5f0`。
- 运行源码、测试、脚本、样本和 CI 进入 main：`a56492d91e874919cf10a6f59d80c6c42c150a61`。
- 使用非强制 fast-forward 更新，保留已有历史；未改变仓库可见性。
- 全部 15 个 Go 文件、go.mod 和 CI 工作流的 Git blob 哈希与本地交付源码一致。

## 实际验证结果

| 检查 | 结果与范围 |
|---|---|
| 本地单元测试 | 50 个顶层 Test 通过，0 失败 |
| 本地 go vet、gofmt、race | 通过；同一份与远端哈希一致的源码 |
| 本地 Linux 构建 | 通过 |
| 本地 Windows amd64 交叉编译 | 通过；不冒充 Windows 实机运行 |
| GitHub Ubuntu 测试任务 | success；格式、单元测试、vet、race、短时 fuzz 均通过 |
| GitHub Windows 测试任务 | success；格式、单元测试、vet 均通过；race/fuzz 按配置不在 Windows 执行 |
| 原生 git clone 拉回本执行环境 | 未完成：Could not resolve host: github.com |
| 连接器远端读取 | 成功；据此核对文件对象哈希 |

GitHub Actions 运行编号：`34469933126`，核验源码提交为 `a56492d91e874919cf10a6f59d80c6c42c150a61`。

- 运行：https://github.com/youq616/Zevune/actions/runs/34469933126
- Ubuntu job：`102847209330`；Windows job：`102847209643`。

GitHub 运行环境实际执行了 checkout 和测试；本执行环境没有成功完成原生 git clone。两者不能混为一谈。本文之后的状态记录更新不改变运行源码，所列 CI 结论只对应上述明确提交。

## 仍未解决的文档上传拦截

最后一批 6 份技术文档的写入请求返回：

> This tool call was blocked by OpenAI because we couldn't determine the safety status of the request.

该返回没有给出具体命中规则、文件/行定位、GitHub HTTP 错误码或可查询请求编号。不能据此断言是某个关键词、某份文档、账号权限或代码编译错误；也不能把重试成功说成已经修复平台的根因。

未纳入远端的文件：

- docs/ARCHITECTURE.zh-CN.md
- docs/PERFORMANCE.zh-CN.md
- docs/PROOF_CONTRACT.md
- docs/ROADMAP.md
- docs/SOURCES.md
- docs/THREAT_MODEL.zh-CN.md

没有修改、改名、转码或换通道重投被拦截的这一批内容。已完成此前获接受的运行源码和测试发布，并分别记录文档缺失。这些文档不参与当前 Go 程序编译。

本执行环境的 DNS 失败是另一项独立限制，不是该安全拦截的解释。

## 发布口径

原型运行源码及测试已发布并通过两平台 CI；完整原始交付包仍因上述 6 份文档缺失而不完整。协议实现、支付能力、隐私审计和真实速度均未完成。后续平台排查可使用本报告中的时间、错误原文、操作类型和目标仓库，不需要提供密码或令牌。
