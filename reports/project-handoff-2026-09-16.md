# Zevune 接手核查与 P2 分段备份验收记录

核查开始日期：2026-09-16；接续验证跨入2026-09-17。范围：接续现有 `dev/m12-genesis-domain` 与 PR #7，复核分段备份、完整重放派生的高度索引及测试分片。禁止真实资金；不是主网、生产存储或整个项目的验收。

## 精确基线

| 标识 | 值 |
|---|---|
| 仓库 | `youq616/Zevune` |
| 接手时 main | `91b6bd3bc76fc9a7dec0e9da1779e34fcb498b76` |
| 接手时 PR #7 head | `ab604c063e4095d46d878b4d250044e28f3851d9` |
| 接手时 head tree | `1eee00b2b7f46928bf405c0bb489e22c6cf4273b` |
| 接手修复候选 | `3d608130add287994df11382ea1916f36a217258` |
| 修复候选 tree | `350bda614193c89a686af63fa1189f7f579de510` |
| 已合入运行源码的 main 提交 | `db021cf554b5e126ee2b3fe8577db61f76339224` |
| 不变的 Orchard 子树 | `f04c0142133dde29323f2b23086ca4f0d405bad6` |

原 PR 相对 main 涉及19个文件，新增2881行、删除14行。接手修复只将 funded 最后构建命令改为显式 `cargo +1.98.1 build`，并补充对应说明；不修改 Rust/Go/Python 运行或测试源码、依赖、协议和存储限制。本文及后续项目状态说明是文档，不替代上述源码身份。

## 接手发现及处理

1. **原 CI 的“仍在等待”描述已过时。** 接手时八套 PR 工作流、18个任务已完成成功，需按实际日志更新，而不能继续引用先前未完成状态。
2. **发现并修复固定工具链缺口。** 原分片改动把最终构建移到仓库根目录，仅传 `--manifest-path`，无法依靠下级目录的 `rust-toolchain.toml` 选择1.98.1。测试在 crate 目录运行，但随后提供给互操作/四节点的二进制可能由 runner 默认编译器重建。修复使用显式工具链参数；其他选项、全部目标、两种平台、权限及超时不变。依据：[rustup工具链选择](https://rust-lang.github.io/rustup/overrides.html)。
3. **项目状态记录滞后。** `PROJECT_STATUS.json` 的最新 CI 说明仍指向 P7 提案筛选；P2共享重放、分段备份与高度索引应分别记实，不得将 P2 整体标为完成。
4. **六份历史技术文档仍未恢复。** 当前树及可访问的全部分支历史中未找到既有列出的六条路径。对六份文件名和简化标题的资料检索也无直接原稿匹配；已定位早期 `veil-pay-prototype-v0.1-dev.zip`、`veil-pay-github-ready.zip`、`Zevune-v0.1.0-dev.zip` 及相关bundle，但三次读取尝试均返回HTTP 502，尚未取得内容及哈希，不能断言文档在归档中存在或不存在。保留缺失标记，不将后来报告或新写说明冒称原始文档。即使后续取得早期原稿，也需明确其单机原型时点，不能直接视为当前LAB2规范。

## 已有行为与限制

- `pack` 将原公开账本字节拆成固定1 MiB的不可变备份段；清单与全部段绑定独立检查点，输出必须是新目录。
- `verify-segments` 跨段完整重放；`restore-segments` 仅创建新的原格式日志。保持真实 Orchard 授权、创世域、状态、EOF、段和源路径身份检查。
- `index` / `locate-height` 在完整校验后提供记录位置；不导入外部索引，不向活动账本提供花费许可或快照。只有同一个已构造索引内的后续查询是 O(1)，每次 CLI 调用仍完整验证。
- 段边界可以切开记录；索引以完整区块记录为单位，报告覆盖的首尾段。高度0是创世头，不能作为区块记录查询。
- 仍保留64 MiB账本、10000条记录、65536个承诺、每块16笔等原限制。尚无活动节点分段存储、快照导入、增量备份、剪枝或扩容。
- Unix 恢复目标仍按持有句柄验证，没有在返回前重新绑定目标 pathname。可信父目录/OS仍是前提；源归档名称检查不能被表述为目标也具有相同保护。后续应增加目标身份复核与持久替换回归，仍不称通用竞态沙箱。

## 独立审核

以下任务均独立于候选作者；实际读取了差异、调用方和测试。任务标识属于本次协作会话，报告保留结论与范围，不能当作外部安全机构审计。

| 任务 | 核对内容 | 结论 |
|---|---|---|
| `/root/storage_review` | main到原head的分段备份、身份核验、共享重放、索引、CLI和测试；随后比对修复候选的整个Orchard子树 | 存储范围无P0/P1/P2阻断；恢复目标pathname为低优先级（P3）后续硬化。修复候选的运行及测试源码逐字节不变，原审核继续适用 |
| `/root/ci_code_review` | 原最后一笔分片改动；其辅助任务 `/root/ci_code_review/workflow_preservation` 核对工作流保留情况 | 原head发现工具链P2阻断；显式固定1.98.1后，复审确认该阻断关闭、无新增阻断 |
| `/root/ci_handoff_audit` | 独立读取GitHub run、job、步骤和funded日志，核对checkout及Git树 | 修复候选全部14次运行/31任务成功；准确来源、平台差异与原head历史失败均已核对 |

原有 [GitHub独立代理回复](https://github.com/youq616/Zevune/pull/7#issuecomment-5694790079) 仅针对 `ab604c063e` 的高严重性问题范围，不自动批准后续修复，也没有替代本轮发现的工具链问题。

## 本次本地验证

- Python 3.12.14 执行 `python3 -m unittest discover -s scripts/tests -v`：81项通过。
- 用独立 YAML 解析比对修复前后语义树：唯一工作流语义差异为最后构建命令增加 `+1.98.1`。
- `git diff --check` 通过；Rust/Go/Python源码及依赖路径与原head逐字节一致。
- 本次环境没有Go/Rust工具链，官方Go下载元数据请求超时；没有本地运行Go、Rust、clippy或四节点。不得把此前会话的本地结果列成本次执行。原生执行证据来自以下GitHub CI。

## 远端验证

### 修复候选

`3d608130add287994df11382ea1916f36a217258` 的独立代码复审及准确源码CI已经通过。
2026-09-17 00:23:24 UTC最终核对：八套PR工作流、18个任务全部成功；全部事件14次运行、
31个任务也全部成功，无失败、无取消。独立审核任务逐份检查31个任务日志。

PR运行实际检出 `18147ab0b465a5083e4c54b5ab7b21c536dff23a`，其父为原main与
修复候选；该合成提交和修复候选的树均为 `350bda614193c89a686af63fa1189f7f579de510`。
原push运行直接检出修复候选，两种来源分别核对，未将后来提交混入统计。

| 工作流 | PR run | 原生任务数 | 结果 |
|---|---|---:|---|
| consensus-laboratory | [35164221107](https://github.com/youq616/Zevune/actions/runs/35164221107) | 2 | success |
| scaffold-tests | [35164221220](https://github.com/youq616/Zevune/actions/runs/35164221220) | 2 | success |
| orchard-bridge | [35164221124](https://github.com/youq616/Zevune/actions/runs/35164221124) | 2 | success |
| wallet-laboratory | [35164221228](https://github.com/youq616/Zevune/actions/runs/35164221228) | 2 | success |
| orchard-consensus-integration | [35164221123](https://github.com/youq616/Zevune/actions/runs/35164221123) | 2 | success |
| funded-wallet-consensus | [35164221102](https://github.com/youq616/Zevune/actions/runs/35164221102) | 4 | success |
| orchard-cryptography-laboratory | [35164221181](https://github.com/youq616/Zevune/actions/runs/35164221181) | 2 | success |
| local-network-operator | [35164221244](https://github.com/youq616/Zevune/actions/runs/35164221244) | 2 | success |

PR 222个步骤中213成功，9项是Windows上按配置跳过的Linux专属race/fuzz；对应Ubuntu步骤成功。

| 平台 | library | interfaces | Rust合计 | Python | 互操作/四节点恢复 |
|---|---:|---:|---:|---:|---|
| Ubuntu | 121 | 49 | 170 | 81 | 均通过；四节点场景83.25秒 |
| Windows | 116 | 49 | 165 | 81 | 均通过；四节点场景113.03秒 |

两份PR interfaces日志均实际执行了 `cargo +1.98.1 build`，并完成后续钱包互操作和真实四节点恢复。
四组均有完成标记。Cargo的failed/ignored/filtered out为0；doc tests为0个示例；81项Python已经包含
13项调度测试，不再次相加。场景耗时仍不是付款延迟指标。结构化的准确身份、全部任务链接和
有限的无秘密验证摘录见 [CI证据](p2-backup-index-ci.json)。

[PR #7](https://github.com/youq616/Zevune/pull/7) 已在上述验证和独立复审之后合入main，
合并提交为 `db021cf554b5e126ee2b3fe8577db61f76339224`。该合并提交与已验证候选的树相同。
本接手记录、README、PROJECT_STATUS和CI证据是后续纯文档更新；运行代码、测试、依赖和工作流
须与已验证源码逐字节保持一致，并独立审查文档。合并或文档更新自动触发的新运行不计为上述验证结果。


### 接手时的原候选历史结果

原head `ab604c063e4095d46d878b4d250044e28f3851d9` 的PR CI实际检出
`478014ef4dbd6f5ed605b4d2b463aa006115338e`，其两个父提交是接手时main与原head。
该PR合成提交与原head的树均为 `1eee00b2b7f46928bf405c0bb489e22c6cf4273b`；
main的树并不等同于该候选树。该组结果确实覆盖原候选源码。

| 工作流 | PR run | 任务数 | 结果 |
|---|---|---:|---|
| funded-wallet-consensus | [35076116541](https://github.com/youq616/Zevune/actions/runs/35076116541) | 4 | success |
| scaffold-tests | [35076116594](https://github.com/youq616/Zevune/actions/runs/35076116594) | 2 | success |
| wallet-laboratory | [35076116520](https://github.com/youq616/Zevune/actions/runs/35076116520) | 2 | success |
| consensus-laboratory | [35076116751](https://github.com/youq616/Zevune/actions/runs/35076116751) | 2 | success |
| orchard-consensus-integration | [35076116440](https://github.com/youq616/Zevune/actions/runs/35076116440) | 2 | success |
| orchard-bridge | [35076116602](https://github.com/youq616/Zevune/actions/runs/35076116602) | 2 | success |
| orchard-cryptography-laboratory | [35076116484](https://github.com/youq616/Zevune/actions/runs/35076116484) | 2 | success |
| local-network-operator | [35076116690](https://github.com/youq616/Zevune/actions/runs/35076116690) | 2 | success |

八套PR工作流18任务均成功；222个步骤条目中213成功，9个为Windows上按配置跳过的Linux专属竞态/短时fuzz，对应Ubuntu步骤均成功。不是全部步骤均执行。

| 平台 | 库测试 | interfaces测试 | 合计 | Python/Rust互操作 | 真实四节点付款恢复 |
|---|---:|---:|---:|---|---|
| Ubuntu | 121 | 49 | 170 | 通过 | 通过，完整场景80.20秒 |
| Windows | 116 | 49 | 165 | 通过 | 通过，完整场景121.47秒 |

两平台的所有Cargo结果汇总均无失败、忽略或名称过滤；其中doc tests实际为0条示例。
数量差异来自7个Unix专属与2个Windows专属库测试，不能把Linux数字复制为Windows结果。
四节点时间是整套测试场景耗时，不是付款延迟。两平台均实际执行非零A→B→C、找零、
加密outbox恢复、单验证者离线、整网重启、签名状态核对与重复拒绝。

全部事件另有重复push：总计15 runs（14成功、1取消），33 jobs（32成功、1取消）。
[取消的Windows桥接任务](https://github.com/youq616/Zevune/actions/runs/35076112585/job/104728811986)
运行20分13秒后在Go回归步骤取消，与配置20分钟预算吻合，但日志没有明确取消来源，
只能记录为疑似触及时限。其后Go/Rust联调未执行；同树的
[PR Windows桥接任务](https://github.com/youq616/Zevune/actions/runs/35076116602/job/104728824364)
实际完成了该验证。此重复取消不构成PR覆盖缺口，也不能被改写成成功。


## 接续顺序

继续使用本项目既有八工作包和统一开发分支，不另起平行协议路线。

1. 当前分段备份/索引阶段的代码修复、独立复审、准确源码CI与PR #7合入已完成；本记录补齐验收证据和接手状态。
2. P2下一优先项转向活动节点账本的可持续增长：先冻结并独立审查容量/版本兼容与活动段轮换设计，再打通正常worker/Go路径跨越10000条记录、重启完整重放并继续提交的闭环。Rust状态校验、重放计数、Go通信/摘要校验及网络同步都有限制，不能只改一个常量。保持真实Orchard校验与原状态摘要规则，不把备份索引当作状态快照；承诺容量与钱包历史读取仍需各自验收。增量备份排在这个关键路径之后，恢复目标身份与磁盘/中断故障测试并入存储质量要求。
3. 按P2/P3接口再接完整钱包流程。多机网络、Windows钱包、网络隐私、经济/验证者规则、性能长时运行、独立审计和安全发布保持各自未完成状态。

下一项活动存储工作必须先处理以下实际调用方，而不是增加未接入的存储类型：

| 层次 | 现有入口/限制 | 下一步必须核对 |
|---|---|---|
| Rust状态和提案 | `pool.rs`、`pool/selection.rs` 的高度有效性判断 | 超过10000涉及有效区块规则，必须有明确版本/激活与混用拒绝设计 |
| 追加与重开 | `PoolStore`、`pool/replay.rs` 的总记录数与总字节限制 | 活动轮换、同步确认、重开完整重放及继续提交使用一致规则 |
| Go通信与同步 | `internal/poolbridge`、`integration/cometbft/labnet/rpc.go` | 不让Go摘要解码、预执行、提案或同步入口在10001处拒绝Rust已提交状态 |
| 钱包与恢复 | `wallet_history.rs`、`pool/recovery.rs` | 已验证历史仍可读；旧检查点含义不被静默扩大；原待发送交易保持一致 |
| 支付状态增长 | 内存承诺/防双花集合、累计状态摘要与状态复制 | 65536承诺边界、峰值内存和恢复成本分别度量，不被空块增长测试掩盖 |

下一阶段验收应覆盖正常worker/Go路径的9999/10000/10001连续提交、多次活动段轮换、
重开再提交、跨界前后真实付款与重复拒绝、错误写入/同步/丢失确认，以及Linux/Windows。
计划中的100000区块增长目标约含15 MB空块帧，不能同时证明跨越64 MiB或支付状态容量；
记录数量、累计字节和真实付款/承诺增长必须分开验收。此处记录后续范围，不修改当前限制。

日常代码、测试、独立复审及GitHub提交按既有授权处理。必须真实机器执行的任务才交给本地agent，给出一整段提示词，并把所需文件先放到GitHub；不反复要求用户验证小版本。实质协议/经济治理决定、真实测试资源和最终资金/部署准入仍各有明确边界。

验收状态：分段备份/索引的运行源码已经通过独立复审与准确源码CI，并随PR #7合入main。P2整体仍为开发中；后续纯文档更新的审核记录另见其PR。
