# 发布状态：运行源码已核验，6 份技术文档仍缺失

日期：2026-09-10。仓库：`youq616/Zevune`；分支：`main`。未重建仓库，未修改公开状态，未强制覆盖历史。

## 已完成

原样重试状态机源码成功：`cacfb7c5bc832901b7836dfa05ee307e0436f5f0`。

完整的原型运行源码、测试、脚本、合成样本及 CI 配置随后进入主分支，源码提交为 `a56492d91e874919cf10a6f59d80c6c42c150a61`。全部 15 个 Go 文件、go.mod 和 CI 配置的远端文件对象哈希与本地源码一致。

GitHub Actions 运行 `34469933126` 的 Ubuntu 和 Windows 测试任务均为 success。Ubuntu 包含格式、单元测试、vet、race 和短时 fuzz；Windows 包含格式、单元测试和 vet。

## 未完成

最后一批技术文档请求被执行平台安全检查拦截。错误没有指出具体规则或哪一份文件触发，不能认定是 GitHub 权限、某个关键词或代码编译错误。

- `docs/ARCHITECTURE.zh-CN.md`
- `docs/PERFORMANCE.zh-CN.md`
- `docs/PROOF_CONTRACT.md`
- `docs/ROADMAP.md`
- `docs/SOURCES.md`
- `docs/THREAT_MODEL.zh-CN.md`

这些文档未纳入远端，不参与当前 Go 编译。因此运行源码可构建，但完整原始交付包仍不完整。

原生 git clone 在本执行环境因无法解析 github.com 而失败；这与前述安全拦截是两件事。远端核验通过已授权连接器读取文件对象完成，GitHub 运行环境实际执行了 checkout 和测试。没有宣称本执行环境成功重新克隆。

详细错误原文、测试范围及提交证据见 [重试核验报告](../reports/publication-retry-2026-09-10.md)。这里没有已上线网络、真实支付或独立安全审计。
