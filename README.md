# Zevune · 澄隐

**开发中的独立隐私支付实验工程；整个项目尚未完成，禁止真实资金和公开部署。**

当前主线包含真实 Orchard 授权、固定四节点支付实验、分段持久账本、加密钱包/待发送恢复、可信参考账本同步，以及离线核查和证据工具。它仍不是完整在线钱包、多机隐私网络或可上线主网。根 Go、嵌套 CometBFT Go 和独立 Rust 是三个测试范围，根目录 `go test ./...` 不能代表全部通过。

## 按整体验收推进

2026-09-29，PR #36 的工具与恢复回归阶段已在完整 CI 和非作者整合复审后合入 `main`，merge `ae04190a57bff9ccfbeb056e749f30a9a62c2e02`。Issue #37 的 C9 测试修复已验收关闭，Issue #23 的 Windows 十万块增长时延根因仍未确定。合并源码不是交付主网、开通资金或开展公开部署的许可。

后续以原[八工作包计划](docs/DELIVERY_PLAN.zh-CN.md)为唯一完整范围，不再以追加离线工具代替核心产品。当前状态与证据缺口统一列入 [PROJECT_COMPLETION.json](PROJECT_COMPLETION.json) 和[收尾路线](docs/ROADMAP.md)。其中 `implemented` 不等于 `accepted`，缺少最终证据的工作包不会因为文件存在或测试变绿被自动验收。

```text
python scripts/check_project_completion.py --report
python scripts/check_project_completion.py --require-complete
```

第一条报告当前记录；第二条在目标 C 的任一最终验收类别未满足时退出 **2**。维护记录不合法退出 **1**。工具只核验范围、证据字节及记录的一致性，不证明实验真实发生、审核者独立，也不授予发布或资金权限。四真实机器、30天连续观察和独立专业审计仍需实际完成；短CI或模拟时钟不替代它们。

## 当前规范

[架构与调用链](docs/ARCHITECTURE.zh-CN.md) · [证明/签名合同](docs/PROOF_CONTRACT.md) · [威胁模型](docs/THREAT_MODEL.zh-CN.md) · [性能验收](docs/PERFORMANCE.zh-CN.md) · [来源说明](docs/SOURCES.md)

这六份核心路径是按当前源码**重新编写**的规范，不是找回的历史未公开原稿，不代表协议冻结或安全审计通过。原 [PROJECT_STATUS.json](PROJECT_STATUS.json) 保留历史字节和当时的缺失记录；当前路径及未找回原稿的事实另见 `PROJECT_COMPLETION.json.specifications`。此前完整功能目录和历史验收链接逐字节保存在 [C32 README档案](reports/project-state-c32/README.md)；档案内相对链接以原仓库根目录为上下文。

| 工作包 | 已有基础 | 尚缺的完整交付 |
|---|---|---|
| P1 协议 | LAB2独立域、收款身份、原格式检查 | 统一审查和冻结、升级/停机/恢复执行 |
| P2 存储 | 分段、归档、全量重放、钱包整理 | 状态快照恢复、容量与时延故障收尾 |
| P3 网络 | 四进程回环操作、签名头和完整重执行 | 真正多机操作、远端/动态验证者信任及四机故障验证 |
| P4 钱包 | 加密钱包、pending、控制台与诊断UI | 普通用户完整在线收付与重启流程 |
| P5 隐私 | 明确的当前公开信息和威胁边界 | 私密广播/查询/同步、无直连回退与流量验收 |
| P6 经济 | 无价值公开创世与费用守恒 | 主网规则、加入/退出/处罚及开放验证者机制 |
| P7 验证 | 真实增长/付款实验和阶段计时 | 隐私路径端到端分布、稳定负载与至少30天观察 |
| P8 发布 | 固定源码与逐阶段代理复审 | 全依赖许可/可信分发、演练、外部专业安全审计 |

## 工程入口与固定边界

根诊断代码使用 Go 1.23.0+；原受控原生CI按仓库工作流固定 Go1.27.1、Rust1.98.1。Orchard依赖0.15.5，固定 `FixedPostNu6_2`，CometBFT0.38.26。不要擅自替换锁定依赖或因更换二进制修改现有账本头。实际编译及平台可用性以对应源码的工作流结果为准。

```text
go test ./...
go vet ./...
go test -race ./...
python -B -m unittest discover -s scripts/tests -p test_project_completion.py -v
```

运行原生模块前先读 [AGENTS.md](AGENTS.md)、[证明合同](docs/PROOF_CONTRACT.md)、[本机网络工具](docs/LOCAL_NETWORK_OPERATOR.zh-CN.md)和[钱包控制台](docs/LOCAL_WALLET_CONSOLE.zh-CN.md)。当前网络命令只接受数字回环地址，私有worker不提供公网接口；钱包准备交易与网络提交仍分离，不把现有入口描述成完整在线产品。

历史可见资产为 opt-in `local-funding-lab` 固定100000无价值单位，最多16项公开初始分配，不是匿名发行或主网分配。proof通过、缓存命中、mempool接收、AppHash、文件校验和本地历史纳入分别具有有限范围；任何一项都不能单独称为最终性。超时不等于取消，未知结果不得自动重签、清预留或重复付款。

默认保留原同步写入、文件锁、版本/容量及严格拒绝规则。大账本、大包或OS IO可能阻塞，前后检查不等于跨文件原子快照。禁止假证明、后门查看密钥、透明付款回退和把公开哈希包装成零知识隐私。独立审计和最终分发许可仍未完成，见 [SECURITY.md](SECURITY.md) 与 [LICENSE-STATUS.md](LICENSE-STATUS.md)。
