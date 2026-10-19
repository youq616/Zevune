# Zevune 完整接续交接，2026-10-19

状态：开发中的 NO-FUNDS 独立隐私支付实验工程；完整项目未完成。此文是对现有GitHub候选、分支、证据及缺口的核验与交接，不批准合并、公开部署、付费资源或真实资金。

## 1. 先读这一页

- 当前重点运行候选：[PR #48](https://github.com/youq616/Zevune/pull/48)，open / draft / 未合并。head `5540cd494ad8a3655e8aa2dd77ed7fc91817de46`，tree `0a287892cfa97347e496b25a334f919847daecca`。
- head分支 `dev/pr47-evidence-windows-qualification`；PR目标 `dev/p4-wallet-checkpoint-sync`，观察到base `0984a41ee12633badfc892bc1b1e1c106530ddee`。本次只增加独立文档分支，运行候选与其基线不移动。
- main停在已合入PR39的 `0e5fd16abfebec3cc5a3db6bb99d1e4e7335c2f6`。PR36/C32合入 `ae04190a57bff9ccfbeb056e749f30a9a62c2e02`，PR38重建规范合入 `5b7174c292fbfaf9808d434b809904fac4da5844`。已合并模块并不代表整个P1—P8验收。
- head关联49个Actions runs：47成功、2失败；两次失败是Windows retained CometBFT lifecycle。Linux与race成功。见[完整CI核验](project-ci-2026-10-19.md)与[机器快照](project-state-2026-10-19.json)。
- 24个整体验收类别保持3 implemented、9 in_progress、6 not_implemented、6 evidence_missing，0 accepted。`candidate_commit`从旧C32更新为本次实际评估运行候选；不新增验收证据，不升级状态。
- [文档索引](../docs/INDEX.md)、[原八工作包蓝图](../docs/DELIVERY_PLAN.zh-CN.md)、[收尾路线](../docs/ROADMAP.md)为接续入口。2026-09-16的[旧交接](project-handoff-2026-09-16.md)仍完整保留，但它以PR7为当时终点，不能当作今日状态。

观察基准为2026-10-19约09:06 UTC的GitHub读取结果；后续运行、审核或分支移动必须重读，不能无限沿用本快照。

## 2. 当前分支地图

以下9个开发PR均为open / draft / 未合并。head是否包含于#48通过GitHub commit compare核对；“是”仅指祖先关系，不代表已接受。

| PR | 内容 | 精确head | 目标分支 | head在#48祖先链中 |
|---|---|---|---|---|
| [#40](https://github.com/youq616/Zevune/pull/40) | feat(p5): restricted loopback RPC gateway for private clients | `70438c1f46a33bff72dced6a7a99ca73b2ad40bf` | `main` | 否，分叉候选 |
| [#41](https://github.com/youq616/Zevune/pull/41) | feat(p4): exact-checkpoint constrained wallet rescan | `0984a41ee12633badfc892bc1b1e1c106530ddee` | `main` | 是 |
| [#42](https://github.com/youq616/Zevune/pull/42) | feat(p4): authenticated network sync to checkpoint-bound wallet scan | `de9766dc4da50f838549ec74e784f00944cc3755` | `dev/p4-wallet-checkpoint-sync` | 否，分叉候选 |
| [#43](https://github.com/youq616/Zevune/pull/43) | feat(p4): checkpoint-bound atomic payment preparation | `b091f8f596ffb87a597dfc931bcd9ed53c223c10` | `dev/p4-wallet-checkpoint-sync` | 否，分叉候选 |
| [#44](https://github.com/youq616/Zevune/pull/44) | feat(p4): authenticated network to checkpoint payment preparation | `bca4fd17b4ac026707701d271a81bc23ff04bde0` | `dev/p4-checkpoint-payment-prepare` | 否，分叉候选 |
| [#45](https://github.com/youq616/Zevune/pull/45) | feat(p4): authenticated recovery of exact saved pending bytes | `0bd78b1a31333149a67db7e7cdfccb14af05fc19` | `dev/p4-network-payment-prepare` | 否，分叉候选 |
| [#46](https://github.com/youq616/Zevune/pull/46) | feat(p4): submit the authenticated saved pending without manual transaction files | `d32f47a3ad6ddf741eaa50dc4ad187aca7e9ba88` | `dev/p4-authenticated-pending-recovery` | 否，分叉候选 |
| [#47](https://github.com/youq616/Zevune/pull/47) | fix(cometbft): join reactor consumers before store shutdown [native qualification] | `0c6e3ffaeebefa61a6aa088401c25d3964164f2b` | `dev/p4-wallet-checkpoint-sync` | 是 |
| [#48](https://github.com/youq616/Zevune/pull/48) | test(consensus): make Byzantine equivocation evidence deterministic | `5540cd494ad8a3655e8aa2dd77ed7fc91817de46` | `dev/p4-wallet-checkpoint-sync` | 本候选 |

#48含#41检查点重扫前置能力与#47的CometBFT生命周期来源/修复候选；不含#40、#42—#46各自最新head。网络准备、准确pending恢复、无手工交易文件提交等已经有草稿代码，不应被遗漏，也不能被写成当前#48已集成、完整在线钱包已交付。分叉与堆叠PR必须先重新核对base/head及实际差异，不能把不同分支的绿色结果拼成一个候选的验收。

本次没有合并、重放、强推、改写或替代任何开发分支，没有把这些未合并代码再次复制成一个不兼容主线。

## 3. 八工作包实际边界

| 工作包 | 保留的已有基础/候选 | 尚缺的完整交付 |
|---|---|---|
| P1 协议与升级 | LAB2创世域、收款身份、规范与签名向量 | 统一冻结审查、支持版本激活、未知版本停机、升级中断恢复 |
| P2 持续存储 | 活动分段、归档、完整重放、增量字节包、钱包整理、既有增长/付款与故障回归 | 经验证的状态快照导入、完整容量/持续交易增长、物理磁盘/断电、Windows持久化与Issue23延迟闭合 |
| P3 多机网络 | 固定四进程回环、签名头认证与完整重执行 | 真正多机运维、远端与动态验证者信任、至少四真实机器的付款/分区/故障证据 |
| P4 在线钱包 | 已有加密wallet/outbox；#41检查点重扫与#42—#46分别在草稿推进 | 同一候选中无需手工文件的完整收付、结果未知/断网/重启对账、伪回复拒绝与Windows产品验收 |
| P5 网络/查询隐私 | #39 onion-only/auth-only SOCKS客户端已合入；#40受限网关为独立草稿 | 真实Tor服务与流量实验、查询/广播/同步整合、端点与时序关联验收；客户端存在不等于整个P5完成 |
| P6 经济/验证者 | 无价值固定公开测试供给与费用守恒 | 主网经济规则评审与状态实现、加入/退出/处罚、开放参与/防女巫模型 |
| P7 性能/长期验证 | 历史100000块（空块为主）和32+1真实付款分别保留；Linux/race结果可读 | 隐私路径端到端p50/p95/p99与失败率、稳定负载、至少30真实天、Windows lifecycle与Issue23故障闭合 |
| P8 审查/发布 | 固定源码、六份重建规范、逐阶段审查流程、CometBFT来源与补丁清单 | 最终准确候选独立非作者审查、完整依赖许可与可信制品、恢复/升级演练、独立专业安全审计 |

Issue #37仍closed，已接受的C9恢复回归修复不撤销；[Issue #23](https://github.com/youq616/Zevune/issues/23)仍open，不能用当前短CI覆盖其Windows十万块增长时延问题。历史已验收的P2等子阶段继续引用各自原报告，而整个工作包不因此自动accepted。

## 4. 当前阻断及建议接续顺序

1. 先处理#48/#47的Windows retained lifecycle原生资格问题，保留失败日志与原测试。PR事件是WAL重放LastBlockID不匹配panic；push事件还包含WAL等待新块超时、签名状态文件rename拒绝；两者均有Unix socket bind失败。不能删测试、改成跳过、放大预算或仅凭Linux通过结案。
2. 将修复固定到一个新的明确候选，完整执行根Go、嵌套Go/retained模块、Rust及相关Python回归，取准确源码/树与两平台结果，再交给未写候选的独立审查任务。当前交接不声称已获得该最终代码审查。
3. 核对#40—#46分叉的真实依赖，再分阶段整合P4在线支付与P5入口。继续使用真实Orchard、全验证钱包与原Genesis/旧格式/容量约束；禁止把服务端余额、AppHash或本地ApplyBlock直接当作最终性。
4. 继续原蓝图关键路径：P1/P6规则与威胁模型审查，P2/P3基础，P4/P5整合，然后P7真实多机/隐私性能/至少30天，最后P8外部专业审查与发布演练。四真实机器、真实Tor、外审资源必须真实取得。

短CI、文档数量、提交数或若干草稿PR不会替代任何门槛。目标C仍只是待决定是否上线的候选，资金、公网与付费资源须另行授权。

## 5. 接手操作与验证

开始修改前读[AGENTS](../AGENTS.md)、[证明合同](../docs/PROOF_CONTRACT.md)、[架构](../docs/ARCHITECTURE.zh-CN.md)和相关实际调用方。建立临时文档/修复分支时固定上述候选SHA，不以默认main代替它。复核远端HEAD，保留base/head/tree与每次审查范围。

本次文档提交可用下列账本检查；报告合法但不完整退出0，要求完整的检查应退出2，不能为变绿删除类别或降低四机/30天门槛：

```text
python -B -m unittest discover -s scripts/tests -p test_project_completion.py -v
python -B scripts/check_project_completion.py --report
python -B scripts/check_project_completion.py --require-complete
```

运行时代码变更还需按AGENTS与精确工作流执行go test、go vet、支持的平台race与二进制decoder fuzz。根Go、integration/cometbft、retained third_party CometBFT、integration/orchard是不同发现范围，根目录`go test ./...`不会发现所有嵌套模块。当前工作仅更新文档和账本元数据，本地未重跑运行时资格测试；已有CI的具体通过/失败保留在上述报告，文档分支的新CI以其PR为准。

## 6. 文件来源、未推资料与仍缺材料

- 当前Git树中六份曾缺核心文档均存在，源于PR38按C32源码重新编写。`historical_originals_recovered=false`与规范runtime_base_commit仍保留；这些不是找回的历史原稿。
- `PROJECT_STATUS.json`历史blob `c84073bf8e084cab4c244a6c76a3dda7a83684d3`保持逐字节不变，`remote_source_complete=false`记录历史完整交付缺口，不改成true，也不误称这六条路径今天仍不存在。
- 可访问云工作区的文件名清点未发现额外Zevune源码/交接文件；现有压缩诊断附件和补丁属于其他工作，未混入本仓库。没有连接的用户电脑/远端工作区可供本次遍历，因此不能承诺每个设备的未推文件已找全。
- 仍缺历史原稿、Windows问题闭合与准确最终候选的完整审查包；真实Tor/流量、四机故障、30天连续观察、完整性能分布、全依赖许可/可信制品、专业外审和最终恢复/升级验收仍缺。
- 本次仅整理仓库公开可核验工程事实与新编写文档；未上传私人邮件、私钥/种子、钱包数据、凭据或无关材料。原始历史报告、旧交接和已有源码未删除。

## 7. 本次文档交付清单

- `README.md`：增加当前接续入口。
- `docs/DELIVERY_PLAN.zh-CN.md`、`docs/ROADMAP.md`：追加带日期的实际进度和缺口；保留原范围、预算与历史段落。
- `PROJECT_COMPLETION.json`：推进被评估的运行候选、刷新5项说明与来源；24项状态、evidence与权限不变。
- `docs/INDEX.md`：当前核心入口及候选树所有docs文件目录。
- 本交接、`project-ci-2026-10-19.md`及`project-state-2026-10-19.json`：完整候选/分支/CI/缺口证据。

这些文件是待审文档候选，不把其发布等同于工程验收。最新文档PR/提交身份由GitHub提交及PR记录承载；不在提交内猜测未来提交SHA。
