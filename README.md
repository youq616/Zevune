# Zevune · 澄隐

**开发中的隐私支付实验工程，禁止真实资金，尚不是可上线主网。** 已包含受限非零金额四节点支付、加密钱包存储、本地钱包控制台、本机网络操作工具和真实授权验证结果缓存；网络匿名、正式经济规则、生产存储与独立安全审计仍未完成。具体通过的检查以对应源码提交的 CI 和验收报告为准。

源码分为根 Go、嵌套 CometBFT Go 和独立 Rust 模块。根目录 `go test ./...` 不会运行全部嵌套模块。

当前活动账本分段的实现、双平台增长与付款恢复、独立复审和准确源码证据，见
[P2活动账本验收记录](reports/p2-active-ledger-validation.md)。固定32+1笔真实付款、恢复及进程资源观测另见
[P2付款资源基线验收](reports/p2-payment-resource-validation.md)。活动目录归档的冻结合同、已验收实现及证据另见
[P2活动归档与完整恢复](reports/p2-active-archive-validation.md)。双检查点活动归档的只读追加核验与范围计划见
[P2活动归档追加计划](reports/p2-active-incremental-plan-validation.md)。此前接手基线、PR #7独立审核及构建修复保留在
[2026-09-16接手记录](reports/project-handoff-2026-09-16.md)。
统一开发入口仍是 `dev/m12-genesis-domain`；整体交付范围见
[八工作包计划](docs/DELIVERY_PLAN.zh-CN.md)。

| 组件 | 范围 |
|---|---|
| 根程序 `zevuned`，0.1.2-dev | 原单机诊断、预执行、Go 日志恢复，付款仍关闭 |
| 原 M3 共识应用 | 原四进程空块实验，已有入口和数据保持兼容 |
| Orchard / Go-Rust 连接 / `poolapp`，0.3.3-proposal-selection-lab | 真实证明、签名、资产树、落盘、共识与重启；默认空创世，显式测试模式才提供初始资产 |
| 钱包核心与 `WalletStore` | 本地密钥派生、收款扫描、找零、加密备份、检查点、持久化待发送队列 |
| `zevune-wallet-local` 与 Python 控制台 | 创建、地址、备份/恢复、本地扫描、付款准备与签名文件导出；不联网、不广播 |
| `zevune-network` 本机操作工具 | 初始化/运行固定四验证者、独立执行并验证签名头部后同步参考账本、提交已有签名交易；不读取钱包秘密 |
| 构建与完整性工具 | 从准确 Git 对象隔离构建；用独立清单摘要核验交付文件，不把校验和当代码签名 |
| 授权缓存 | 有界地复用相同字节的成功密码学检查，仍逐笔检查当前账本许可 |


## 创世域绑定 V2（本机协议候选）

`TestGenesis::generate` 默认创建 `ZVTGEN02` 测试创世清单，加入独立部署随机标识。钱包从已经验证的历史获得
该清单摘要，使用 `ZVORLAB2` 将其纳入所有付款授权签名。即使另一部署拥有相同初始资产和
相同承诺树根，原交易也不能直接使用；修改域或降级到 LAB1 不会产生有效签名。账本在缓存
命中、预执行、提交和日志重放时均核对预期域，钱包待发送记录恢复也必须匹配。

旧 V1 清单与日志不自动迁移，仍属于旧实验协议，不会被宣称已经获得新保护。
01/02单文件profile使用IPC3；显式新建03活动profile使用独立IPC4指纹，不匹配组件拒绝握手。
03仍使用LAB2签名，将03完整清单摘要绑定到付款域；更新二进制不会升级已有02网络。完整复制同一份清单仍复用同一身份；
V2 不解决完全克隆网络、分叉、网络匿名或密钥泄露。详见
[协议候选与字段格式](docs/protocol/GENESIS_DOMAIN_V2.md) 和
[隐私保护边界](docs/PRIVACY_BOUNDARIES.zh-CN.md)。尚未完成外部独立安全审计，不能用于真实资金。

## 非零金额四节点实验

`local-funding-lab` 是默认关闭的测试特性。创世清单有固定总量 100000、最多 16 项公开分配，独立核对摘要、资产开口及初始账本。**初始地址、金额和资产开口是公开的实验数据，不是匿名发行设计，也不是任意后续增发接口。** 正常付款仍必须通过真实 Orchard 证明、授权签名及状态检查。

整合测试执行 A→B→C、找零、手续费、加密备份恢复相同待发送交易、一个节点离线时继续付款、整网重启和重复付款拒绝。钱包的参考账本先核对真实共识提交签名及区块数据，再重放交易，结果与所有节点的签名头部应用摘要核对。四个节点仍位于同一台测试机，不等于跨地域或独立运营主体。

测试付款总额守恒、公开创世参数和独立检查点不应被称为网络匿名或最终主网发行。详见 [测试创世与支付整合](docs/FUNDED_TEST_NETWORK.zh-CN.md)。

## 本地钱包操作入口

控制台只使用 Python 3.10+ 标准库和本地 Rust 后端，不需要 Docker。密码使用不回显输入；付款地址、金额、手续费及有效期通过交互输入，不传入子进程参数或环境变量。Rust 请求解码有固定容量和字段数量，拒绝截断、尾随字节及未知操作。

```text
cargo +1.98.1 build --manifest-path integration/orchard/Cargo.toml --locked --release --features local-funding-lab --bin zevune-wallet-local
python scripts/zevune_wallet.py --help
```

`prepare` 在加密预留和完整签名交易持久化后才导出文件。`pending` 恢复同一组字节，不自动产生第二笔付款。`backup` 和 `restore` 只创建新文件，绝不覆盖旧钱包。超时、导出失败或进程中断不等于付款没有保存，必须先对账。

**这不是完整在线钱包：控制台仅扫描可信本地账本，不直接访问 RPC、广播或验证远程节点最终性。** 本地余额不是外部收款证明。`zvlab:` 是临时带校验和显示格式，不是正式主网地址。参见 [操作与故障边界](docs/LOCAL_WALLET_CONSOLE.zh-CN.md) 和 [加密钱包存储](docs/WALLET_DURABILITY.zh-CN.md)。

## 本机网络操作工具与参考账本

`integration/cometbft/cmd/zevune-network` 提供 `init`、`run`、`sync`、`submit` 和 `version`，不再只能通过测试函数启动网络。它只接受数字本机地址 `127.0.0.1`，固定四名验证者，保留原有签名状态和日志，不自动重新创世。共识引擎意外退出会返回失败，而不是留下看似仍在运行的操作进程。

**同步不是仅信任节点返回的余额或 AppHash。** 工具验证独立固定的配置、法定票权签名、区块内容和前后连接，实际执行交易，并在下一份已签名区块头的后置状态匹配后才落盘。错误后置状态即使有测试法定票权签名也会被拒绝。参考账本同步到已观察并验证的 tip-1，不声称单一提供者一定告知全网最新状态。

`submit` 只发送已由钱包生成的相同交易字节。交易池接收仍输出 `confirmed:false`；超时或单节点拒绝不解除钱包预留。真实操作进程测试覆盖非零金额 A→B→C、备份恢复、单节点离线、整网重启与重复付款拒绝。详见 [本机网络操作](docs/LOCAL_NETWORK_OPERATOR.zh-CN.md)。这是分离的开发操作工具，不是完整图形钱包、通用公网同步或匿名传输。

## 构建来源与交付校验

`scripts/build_local_lab.py` 从捕获提交的精确 Git blob 导出新临时源码目录，再按固定依赖构建；原工作目录中未跟踪或忽略的额外源码不直接作为输入。清单同时记录提交、树标识和每个文件的大小/SHA-256。这样补上“工作目录编译但清单只显示提交号”的来源缺口。

`scripts/verify_local_lab.py` 依据独立取得的清单摘要进行离线核验，拒绝多余/缺失/篡改文件、重复字段、非普通文件和超限数据；不执行下载的程序。仍需信任核验器、编译器、依赖和操作系统。没有签名发布、可复现构建或安全审计保证。详见 [构建完整性](docs/BUILD_INTEGRITY.zh-CN.md)。

依赖归档盘点工具 `scripts/audit_crate_notices.py` 已提供，但其合成测试通过不表示所有实际依赖许可证都已核对完毕，也不构成分发许可结论。

## 速度优化不改变有效性规则

`AuthorizationVerifier` 先执行规范解码，只有真实证明及全部签名成功后的完整交易字节才进入最多 64 项的内存缓存。匹配同时比较摘要和全部字节；不导入或持久化缓存，不缓存“允许花费”的结论。

当前高度、过期、历史根、已花费标识、重复输出、费用和原子提交仍由账本检查。新进程冷启动重新验证。命中缓存不等于到账或最终性。参见 [精确授权缓存](docs/AUTHORIZATION_CACHE.zh-CN.md)。单项授权计时和带恢复操作的实验流程计时不是正式 p95 或 TPS 成绩。

## 验证与当前边界

工作流按改动路径验证 Go 根模块、原共识、Rust 密码学、跨语言授权、持久化共识、本地钱包、非零金额四节点整合、本机网络操作和离线工具。具体执行项目与结果必须对应准确提交，未触发或跳过的项目不算本轮通过。CI 固定依赖锁；各工作流工具链选择以 YAML 为准，普通检查只有读取权限。缺少真实证明或 worker 时应失败，不会用模拟验证器替代。

Orchard 0.15.5 使用固定修复电路。固定依赖不等于漏洞审计。没有全网查看密钥、透明支付回退、上传私密见证或跳过证明开关。正式网络/创世域绑定、签名协议、经济与升级规则、通用公网及动态验证者同步、网络层隐私、生产存储、可靠更新和独立审计仍待完成。完整验收依据 [验收要求](docs/INTEGRATION_ACCEPTANCE.zh-CN.md)。

钱包日志容量、旧备份回滚、操作系统和多副本使用都有明确边界。密码和 Python/系统内存副本没有完整擦除保证。旧 Go 树未被解释成真实 Orchard 树；不自动迁移或清空原数据。原诊断程序仍显示付款和最终性关闭，不会通过更新源码自动变成钱包网络。

[原诊断存储](docs/LOCAL_STORAGE.zh-CN.md) · [预执行](docs/BLOCK_PREVIEW.zh-CN.md) · [原共识](integration/cometbft/README.md) · [密码学模块](integration/orchard/README.md) · [真实资产状态](docs/ORCHARD_STATE.zh-CN.md) · [原共识连接](docs/ORCHARD_CONSENSUS.zh-CN.md) · [钱包核心](docs/LOCAL_WALLET.zh-CN.md)。

[六份历史文档](docs/PUBLICATION_STATUS.zh-CN.md)仍未恢复，本轮组件说明不是那些文档的替代副本。参见 [安全说明](SECURITY.md)、[许可证状态](LICENSE-STATUS.md) 与 [上游声明](integration/orchard/NOTICE.md)。禁止上传种子、私钥、查看密钥、钱包文件或真实付款明文。

## 统一开发基线

现行开发入口为 `dev/m12-genesis-domain`，采用已经接入钱包、真实签名、账本和共识的 Genesis-bound LAB2，不再把未调用的 Protocol v1 草稿结构作为支付实现。旧草稿提交保留在合并历史中，原诊断协议版本和编码不变。

Go 启动层新增有界的公开创世帧检查；无效清单在创建节点目录前拒绝，完整 Orchard 资产和密码学验证仍由 Rust 完成。真实命令与直接节点 RPC 均验证域替换、降级和未知格式拒绝，再继续非零金额付款及恢复测试。具体源码提交、测试范围和失败记录见 [M12 统一基线验收](reports/m12-consolidation-validation.md)，分支取舍见 [开发基线说明](docs/DEVELOPMENT_BASELINE.zh-CN.md)。

这是本机实验基线的整合，不是整个项目完成。旧数据不清空、不自动迁移，LAB1 不会自动获得 LAB2 保护。历史 M11 范围见 [原验收记录](reports/m11-remote-validation.md)。

## P1/P2 钱包网络身份与有界存储交付

已接入本地收款地址的 LAB2 网络身份检查与付款前预检查，错误网络在签名前拒绝。新增 `storage` 和显式 `compact`：钱包日志满时可以保留完整待发送签名字节，将认证快照重新加密到一个新日志，恢复可追加额度。源文件不覆写、不删除；新文件使用新的独立回执，必须重新扫描，旧副本只能离线保留。不是节点账本扩容或跨副本锁。

本地付款准备现在有分段计时；它不包含网络共识和收款确认，不是端到端到账或 TPS 成绩。采用的八项交付范围仍见 [项目计划](docs/DELIVERY_PLAN.zh-CN.md)。P1/P2/P4/P7 均只完成部分增量，网络匿名、多机长期运行、完整在线钱包和主网准入仍未完成。

[精确源码与验收记录](reports/p1-p2-wallet-validation.md) · [钱包收款身份](docs/protocol/WALLET_RECIPIENT_IDENTITY.md) · [容量与恢复](docs/WALLET_CAPACITY_RECOVERY.zh-CN.md) · [整理与故障边界](docs/WALLET_COMPACTION.zh-CN.md)。

## P7 增量提案筛选

`PrepareProposal` 已接入单次有界 Go/Rust 请求，最多检查原始前64项、选择最多16笔。在一个临时候选状态上逐笔尝试，不再为每笔候选重跑全部已接受前缀。失败交易不留下部分更新；历史根取自区块前已提交状态，筛选不改变已提交账本或待最终提交槽。

完整提案验证、最终执行、提交和日志重放仍执行原有真实授权与账本检查。原单文件profile的IPC第3代组件必须成套更新，旧组件握手失败；P7筛选改动本身未改变交易、签名、创世和日志格式，不迁移现有数据。活动profile的IPC4与新格式另见[P2活动账本设计](docs/ACTIVE_LEDGER_V1.zh-CN.md)。三笔真实付款的应用计数对照为旧前缀方法6次、新方法3次，这不是实际速度倍数、TPS或端到端5秒到账承诺。

P7仍为开发中，完整负载、隐私路径和端到端延迟验收尚未完成。[实现与兼容边界](docs/INCREMENTAL_PROPOSAL_SELECTION.zh-CN.md) · [精确源码与验证记录](reports/p7-proposal-selection-validation.md)。

## P2 分段备份与历史高度定位

`zevune-pool-recovery` 已接入独立检查点绑定的 `pack`、`verify-segments`、
`restore-segments`、`index` 和 `locate-height`。分段备份保存原账本的完整字节，
恢复只创建新日志；完整真实授权重放、EOF和源归档身份核验通过后才返回结果。
历史索引由完整区块记录派生，支持记录跨越分段边界，不接受外部索引作为状态或授权。

这些旧单文件备份/索引接口仍受原64 MiB日志、10000条记录等限制；每次CLI索引调用都重新完整校验，明确拒绝活动profile。
活动节点分段存储已作为独立增量实现；活动目录的完整归档使用独立合同和验收记录，旧命令不自动扩宽。迁移、快照和增量备份仍未完成，P2继续保持开发中。
[分段备份](docs/SEGMENTED_BACKUP.zh-CN.md) · [重放派生索引](docs/REPLAY_DERIVED_INDEX.zh-CN.md)。


## P2 活动账本分段

新建无价值资产实验网络可以显式选择 `ActiveSegmentsV1`：`generate_active` 生成
`ZVTGEN03`，本机场景程序通过 `--active-segments-v1` 选择它。
`zevune-network init` 根据已独立固定的创世清单选择匹配的配置与应用版本；没有容量覆盖开关。

| 项目 | 原单文件profile | ActiveSegmentsV1 |
|---|---|---|
| 创世 / 账本头 | 01/02 / 01/02 | 03 / 03 |
| IPC / 配置 / AppVersion | 3 / 1 / 2 | 4 / 2 / 3 |
| 最高记录数 / 逻辑字节 | 10000 / 64 MiB | 1000000 / 1 GiB |
| 活动段 | 单文件 | 完整记录按1 MiB轮换，最多2048段 |

提交、容量查询、完整授权重放、钱包历史和参考同步已接入同一profile。
已执行的增长验收是正常worker/Go提交100000块，其中99998个空块和2个真实付款块，
关闭后完整重放并继续到100001；活动四节点另有低高度付款及全网重启验证。
每个平台的准确字节、段数和时间见[验收与CI证据](reports/p2-active-ledger-validation.md)。
这些结果不证明四节点共识100000块、支付吞吐量或全部容量上限。

旧数据不自动升级或迁移。每块16笔、65536承诺及钱包日志256条保存记录的限制保持。

State复用从真实承诺树推导的当前根，减少空块和完整重放的重复根计算；缓存不落盘，
不改变摘要、授权或anchor规则，等价性由优化前完整摘要算法核对。见[派生根复用](docs/DERIVED_COMMITMENT_ROOT.zh-CN.md)。
固定32+1笔的内存与恢复历史成本基线已验收；活动归档的单独实现和验证见下节。持续真实交易增长、容量边界、快照、增量备份、真实断电和长期多机运行仍需验收。
2048是分段数上限，完整读取器还会复制整组文件句柄；峰值资源并非限制在2048个句柄。
Windows目录持久化及主机资源边界见[验收限制](reports/p2-active-ledger-validation.md)。

## P2 真实付款与恢复资源基线

显式 `--active-resource-v1` 以两个临时加密钱包完成32笔真实付款；重开worker并完整重放、从独立回执绑定备份恢复两钱包之后，再新建第33笔，恢复其精确待发送字节并提交。同一交易由worker和场景独立账本分别验证，全状态、实际日志帧、钱包保存记录及拒绝后的非变更均核对。

双平台验收记录9个检查点与181项操作的开始/完成进度，分别观测两代worker和同一场景进程的OS驻留内存生命周期高水位。每进程1 GiB是本次样本的观测门槛；场景包含prover、独立账本、两个钱包和Argon2，Go/Python协调进程不在该统计中。33笔不会触达全部容量、缓存或历史边界，也不代表TPS、冷磁盘或长期多机验收。

[冻结设计](docs/PAYMENT_RESOURCE_BASELINE.zh-CN.md) · [原生数据、独立审核与失败修复记录](reports/p2-payment-resource-validation.md)。这些历史测量不包含活动归档操作，P2整体继续开发。

## P2 活动目录归档与完整恢复

本运行阶段已验收并通过 [PR #13](https://github.com/youq616/Zevune/pull/13) 合入。准确 C7 经过两路非作者完整代码审核及独立原生审核，10 个 PR 工作流、23 个必需任务全部在 attempt 1 成功；实际合入树与验收源码一致。默认／funded 测试、平台条件跳过、历史失败及精确 source/tree/merge 身份见[本阶段记录](reports/p2-active-archive-validation.md)。最终文档的独立复核及合入记录见 PR #13 所链接的文档 PR。

活动归档保留活动目录的原 `genesis`、连续完整记录段及逐文件精确字节，不增加 MANIFEST 或重新分片。独立保留的 `ZVARCP01` 检查点固定128字节，命令行使用256个小写hex字符，绑定可信高度、AppHash及完整物理布局；随不可信归档一起收到的未认证pin不证明来源，也不证明最新状态。

`zevune-pool-recovery` 的 `checkpoint-active`、`backup-active`、`verify-active` 和 `restore-active` 明确选择活动profile，均要求 `--no-real-funds` 和绝对路径。备份与恢复共用只创建新目标的完整复制路径；只读源共享锁、目标原创建句柄持锁验证、每次使用全新验证器完整重放及源/目标前后检查均由冻结合同要求。旧命令仍保持原格式、输出和活动profile拒绝。

新增的[固定公共验证密钥合同](docs/FIXED_VERIFYING_KEY.zh-CN.md)已通过两路独立设计审核：`wire::AuthorizationVerifier` 只将编译期固定电路的不可变公共密钥保留在进程私有 `OnceLock`，每个新实例仍新建独立空授权缓存。复制中的源、目标和末次源三次完整真实重放、原测试与时间预算全部保留；密钥常驻至进程退出，不能导入或选择外部密钥。新增真实证明回归检查并发使用与缓存隔离，不宣称冷首次初始化竞争、构建panic或归档资源峰值已经测量；实现及完整双平台原生证据已按准确 C7 核对，范围见本阶段记录。

创建后失败可能留下部分或完整目标，不能自动清除或覆盖；完整副本可以按原pin另行验证。归档不含钱包、密钥、共识数据库/WAL或最后签名状态，成功也明确 `validator_ready:false`，不能直接当成可启动的完整验证者备份。Windows目录持久化、真实断电、磁盘满、快照、增量备份和长期全容量仍需后续验收；本阶段没有新增归档资源测量。

[冻结合同](docs/ACTIVE_ARCHIVE_V1.zh-CN.md) · [实现、原生CI与独立审核记录](reports/p2-active-archive-validation.md)。P2保持开发中。

## P2 活动归档追加关系与只读增量计划

`zevune-pool-recovery plan-active-incremental` 比较两份分别由独立可信 `ZVARCP01` 检查点固定的活动归档，完整验证后确认较后归档是否沿原物理字节追加，并输出所需的新字节范围。只接受 LAB2／ZVTGEN03／ActiveSegmentsV1；旧段及分段位置必须保持，旧尾段可以增长或保持不变后新增连续段。同内容、同高度返回空计划；回退、不同网络及改写旧历史的分叉均拒绝。

使用前停止两端对应的写入进程，并分别准备独立可信保存的 128 字节检查点（各为 256 个小写 hex 字符）。两个随不可信目录一起收到的未认证 pin 不能互相证明来源。下列 Bash 示例在仓库根目录执行；先将两个变量设置为实际可信 pin，并替换两个绝对目录：

```bash
cargo +1.98.1 run --manifest-path integration/orchard/Cargo.toml --locked --release --features local-funding-lab --bin zevune-pool-recovery -- \
  plan-active-incremental --no-real-funds \
  --base /srv/zevune/archive-earlier --base-checkpoint "${BASE_CHECKPOINT:?请先设置较早归档的可信检查点}" \
  --source /srv/zevune/archive-later --checkpoint "${LATER_CHECKPOINT:?请先设置较后归档的可信检查点}"
```

成功返回单行 ASCII JSON，格式为 `zevune-active-incremental-plan-1`。`ranges` 按段索引列出 `segment_index`、`offset`、`length`，长度之和等于 `appended_bytes`；`reused_bytes` 包含 genesis 和旧尾段前缀，`unchanged_segment_count` 只计整个文件不变的旧 journal 段。空计划沿用同一格式，追加字节为 0、范围为空。命令不接受 `--output`，不改写归档、不创建增量包或导入状态；JSON 明确保留 `incremental_backup_written:false`、`snapshot_imported:false`、`finality_verified:false`、`validator_ready:false` 和 `real_funds_allowed:false`。stdout 写入失败会非零退出，但可能已写出部分 JSON，必须同时检查退出状态。

库接口为 `base.incremental_plan(&mut later)`，返回字段私有的 `ActiveIncrementalPlan` 和只读范围。两份归档保持共享锁；成功 CLI 的两次打开与方法内两次核验合计四次完整真实重放，每次使用独立空授权缓存。对两个已打开实例单独调用方法则新增两次重放。全部复用字节比较后还会再次核对两端完整字节、布局和目录身份。计划只描述本次已核验的历史，不能认证以后路径中的文件，也不证明最新状态或共识最终性。

本运行阶段已通过两路非作者完整代码审核和独立原生审核，并经 [PR #15](https://github.com/youq616/Zevune/pull/15) 合入。准确 C2 的 10 个 PR 工作流／23 个必需任务全部在 attempt 1 成功；实际合入树与验收源码一致，最终文档复核与合入记录见 PR #15 所链接的文档 PR。持久增量包、应用增量的恢复入口、快照导入和生产存储仍待开发，P2 保持开发中。

[冻结设计](docs/ACTIVE_INCREMENTAL_PLAN.zh-CN.md) · [准确源码、原生结果与独立审核](reports/p2-active-incremental-plan-validation.md)。
