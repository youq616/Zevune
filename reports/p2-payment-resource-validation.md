# P2 真实付款与恢复资源基线验收

日期：2026-09-17。范围：新建 LAB2／ZVTGEN03 无价值资产实验的固定32+1笔真实付款、完整重放、钱包恢复、精确待发送记录恢复及进程资源观测。P2整体仍为开发中。

## 准确源码与结论

| 项目 | 准确身份或状态 |
|---|---|
| 阶段基线 | `8324ec8bd153d9502e3e6761d25bfe281a5f3b44` |
| 最终运行源码 head | `cd5fe98053ce64e1acc6796dae44ec0e822c124f` |
| 最终运行源码 tree | `cc60276872b26bbd2be1b0a0a62fceac325f5b45` |
| 最终运行源码父提交 | `9e46e03165250c6c51fa7031526d8de1bbdf27d6`；保留 C1／C2／C3 修复历史，不以 PR base 冒充直接父提交 |
| [PR #11](https://github.com/youq616/Zevune/pull/11) 测试合成提交 | `caece5bb6e82adc11156601880d7e1b4f2b5f463` |
| PR测试合成提交 tree / parents | `cc60276872b26bbd2be1b0a0a62fceac325f5b45`；父为 `8324ec8bd153d9502e3e6761d25bfe281a5f3b44` / `cd5fe98053ce64e1acc6796dae44ec0e822c124f` |
| 两路独立实现复审 | PASS（准确C4代码范围） / PASS（准确C4代码与证据合同范围） |
| 必需原生PR矩阵 | 10个PR工作流 / 23个任务全部成功；23份完整原始日志均已核对 |
| PR #11实际合并 | [1de1df40c0e7a43c23ab21862992a5895c54f609](https://github.com/youq616/Zevune/commit/1de1df40c0e7a43c23ab21862992a5895c54f609) |
| 实际合并 tree / parents | tree cc60276872b26bbd2be1b0a0a62fceac325f5b45；parents 8324ec8bd153d9502e3e6761d25bfe281a5f3b44 / cd5fe98053ce64e1acc6796dae44ec0e822c124f |
| 本阶段结论 | 固定32+1真实付款及恢复资源基线已通过两路独立代码复审、完整原生CI与独立原始证据审核，并通过PR #11合入；P2整体仍为 `in_progress` |

源码、PR合成提交与实际合并必须分别记录，逐项核对tree及父提交。资源JSON中的 `metadata.source_head/source_tree` 表示待验收源码，`checkout_commit/checkout_tree` 表示真正编译的检出；PR合成提交不冒充source head。后续纯文档提交只更新说明和原始证据，运行代码、测试、依赖与工作流必须保持逐字节一致，其继承范围与独立文档审核记录在对应文档PR中。

## 固定真实负载与恢复路径

验收设计在实现前冻结于[资源基线设计](../docs/PAYMENT_RESOURCE_BASELINE.zh-CN.md)，SHA-256为 `f8fb0f009423f26afbfb84ad2293b13dbe9581032c31ba0bfc379d224a91789f`。本阶段不改变生产PoolStore／Wallet／Client接口、交易或日志编码、依赖锁、容量上限与旧工作流。显式 `--active-resource-v1` 只为实验场景选择此负载；原默认及活动增长模式保留。

两个临时加密钱包各有50000公开测试单位，奇数笔 A→B、偶数笔 B→A，每笔金额1000、费用1000，到期高度为准备时已提交高度加100。先正常提交32笔，完成恢复后再新建第33笔；每个区块恰好一笔真实付款，共33块，没有空块或预制日志。每笔由原 `prepare_payment_to` 构造真实授权并保存outbox，正常worker与场景独立PoolStore分别调用原prepare／commit；Go逐块核对完整Summary和实际两个Orchard actions。两个actions含填充，actions或nullifier数不是实际花费输入数。

32笔后采样并关闭第一代worker，独立检查完整物理日志，启动第二代worker从原日志完整重放，核对相同Summary和容量。场景还会重开其独立PoolStore，使用独立保留的receipt从加密备份恢复两钱包并重新完整同步。随后才从恢复的钱包准备第33笔，再单独备份／重开这一笔待发送记录，比较精确bytes，最终提交相同交易并核对收款可用及pending清除。活动节点归档恢复不是本次实现；这里的账本恢复是重开现有活动日志，备份恢复对象是加密钱包。

| 检查点 | 已提交付款 / 高度 | commitments / nullifiers | 费用总计 | A/B钱包记录 | A/B余额 | 原始字段核对及运行断言 |
|---|---:|---:|---:|---|---|---|
| 创世 | 0 | 2 / 0 | 0 | 2 / 2 | 50000 / 50000 | 两平台JSON字段一致；余额/可用额/pending由成功原生运行断言核对 |
| 付款8 | 8 | 18 / 16 | 8000 | 14 / 14 | 46000 / 46000 | 两平台JSON字段一致；余额/可用额/pending由成功原生运行断言核对 |
| 付款16 | 16 | 34 / 32 | 16000 | 26 / 26 | 42000 / 42000 | 两平台JSON字段一致；余额/可用额/pending由成功原生运行断言核对 |
| 付款24 | 24 | 50 / 48 | 24000 | 38 / 38 | 38000 / 38000 | 两平台JSON字段一致；余额/可用额/pending由成功原生运行断言核对 |
| 付款32及两种重开恢复 | 32 | 66 / 64 | 32000 | 50 / 50 | 34000 / 34000 | 两平台JSON字段一致；余额/可用额/pending由成功原生运行断言核对 |
| 第33笔outbox恢复，尚未提交 | 32 | 66 / 64 | 32000 | 51 / 50 | 34000 / 34000 | 两平台JSON记录51/50一致；可用额16000及精确outbox/pending由原生运行断言核对 |
| 第33笔已提交 | 33 | 68 / 66 | 33000 | 52 / 51 | 32000 / 35000 | 两平台JSON字段一致；余额/可用额/pending由成功原生运行断言核对 |

上表列出冻结目标及两平台实际结果；最后一列分别关联原始字段核对与成功原生用例中的运行断言。

commitments、nullifiers、费用、钱包记录与文件字节可从原始JSON逐项核对。余额、可用额及pending状态由准确候选的Rust／Go运行断言验证，未作为数值字段保存于公开JSON；18000单位整张note的说明来自固定负载和现有选择策略，不作为独立note数量测量。

准备第33笔时，A预留整张18000单位大note，余额仍为34000而可用额为16000；不能只从余额扣除付款金额来推算预留状态。钱包保存记录数不等于付款数或当前note数。第32笔时两文件各1647472字节；第33笔完成时A/B分别1713368/1680420字节，须由 `storage_status` 和真实文件元数据核对。

| 平台 | 32笔逻辑字节 / 段 / 尾段字节 | 33笔逻辑字节 / 段 / 尾段字节 | 33笔A/B钱包文件字节 | 完整物理检查 |
|---|---|---|---|---|
| Ubuntu | 299404 / 1 / 299264 | 308756 / 1 / 308616 | 1713368 / 1680420 | PASS，32和33关闭worker后的完整物理扫描 |
| Windows | 299404 / 1 / 299264 | 308756 / 1 / 308616 | 1713368 / 1680420 | PASS，32和33关闭worker后的完整物理扫描 |

逻辑容量按140字节头与真实交易对应的完整记录帧累加；实际tx长度来自解码响应，不用预估长度替代。worker关闭后才跨进程扫描genesis与完整物理帧，保留Windows独占锁；检查实际交易bytes、checksum、连续高度、前驱／结果AppHash、规范轮换、EOF和容量。物理扫描不是授权验证器，worker与场景重开仍执行原真实授权和全部状态规则。

坏签名及仍未过期的已付款重复候选必须拒绝，拒绝前后完整状态、容量和磁盘字节一致。第33笔有效Finalize后，错误commit tag、历史候选或选择请求不得破坏待提交槽；原tag仍可提交。这些检查不引入跳过证明、外部状态导入或接受替身。

## 测量口径与实际资源

每代worker和场景进程的OS报告resident生命周期高水位门槛固定为1073741824字节，即1 GiB。该值是本次小样本验收门槛，不是内存分配硬限制、私有堆保证或整机预算。Linux使用 `/proc/<pid>/status` 的VmRSS／VmHWM，统计可能近似；Windows使用WorkingSetSize／PeakWorkingSetSize，不能与PrivateUsage混称。完整字段定义与平台来源见冻结设计及两平台原始JSON。

| 平台 | 角色与代际 | 最后采样checkpoint | PID与创建身份 | 观测到的OS生命周期高水位（字节） | MiB（字节÷1048576） | ≤1 GiB |
|---|---|---|---|---:|---:|---|
| Ubuntu | worker 1 | payment_32 | PID 6457 / linux_proc_starttime_ticks 13353 / parent 6446 | 11509760 | 10.977 | PASS |
| Ubuntu | worker 2 | complete_33 | PID 6487 / linux_proc_starttime_ticks 27697 / parent 6446 | 11649024 | 11.109 | PASS |
| Ubuntu | scenario 1 | complete_33 | PID 6452 / linux_proc_starttime_ticks 12597 / parent 6446 | 180588544 | 172.223 | PASS |
| Windows | worker 1 | payment_32 | PID 7028 / windows_creation_filetime_100ns 134340990207206767 / parent 6524 | 13123584 | 12.516 | PASS |
| Windows | worker 2 | complete_33 | PID 5236 / windows_creation_filetime_100ns 134340992022066555 / parent 6524 | 12767232 | 12.176 | PASS |
| Windows | scenario 1 | complete_33 | PID 6540 / windows_creation_filetime_100ns 134340990111168437 / parent 6524 | 118714368 | 113.215 | PASS |

同一代的高水位取所有有效checkpoint中 `os_lifetime_peak_bytes` 的最大值，并保留最后采样值核对；每行只对应同一PID及创建身份。`current_bytes` 是当次resident，完整九检查点趋势保留在原始JSON，不称为每阶段峰值。两代worker分别报告；场景始终是同一进程，包含两个钱包、第二本账本、prover、授权缓存、历史和Argon2成本。Python监督器及Go协调器不在这三行角色范围内，最终清理也不属于负载观测窗口。

固定九事件顺序如下。最终候选在Ubuntu／Windows各有9事件、9个完整内存checkpoint、18个角色采样及3个已登记身份；两平台均完整取得上述记录、362条进度及181项完成操作。

| 事件seq | phase | 已提交高度 | worker代际 | 场景代际 |
|---:|---|---:|---:|---:|
| 1 | genesis | 0 | 1 | 1 |
| 2 | payment_8 | 8 | 1 | 1 |
| 3 | payment_16 | 16 | 1 | 1 |
| 4 | payment_24 | 24 | 1 | 1 |
| 5 | payment_32 | 32 | 1 | 1 |
| 6 | worker_reopened_32 | 32 | 2 | 1 |
| 7 | wallet_recovered_32 | 32 | 2 | 1 |
| 8 | pending_restored_33 | 32 | 2 | 1 |
| 9 | complete_33 | 33 | 2 | 1 |

监督器保留父PID与创建身份，避免PID复用继承旧峰值；采样、身份核验和报告持久化成功后才ACK。指标缺失、身份变化、超额、超时或保存失败均失败，不能返回0或跳过。有效超额样本在判预算前写入失败报告；未知或未经验证的字段不抄入公开结果。正常成功还要求Go退出码0、三个登记身份均确认退出及有效最终result，上传artifact成功本身不是验收通过。

## 逐笔计时和失败证据

固定操作合同共有181项，分别写started／completed，共362条不可覆写进度文件。最终候选必须逐条接受合法前缀，并以完整有序操作合同核对最终timings；不只比较计数或集合。已修复的完整序列验证及对应拒绝回归结论：两路准确C4复审PASS；C1的两种重排负例均已拒绝，C3独立枚举180种相邻整对换序均拒绝、362个合法未完成前缀均仅作为部分观察接受；C4逐字节保留该完整顺序校验。

操作从 `scenario_start`、`worker_create`、创世 `wallet_sync` 开始。每笔执行 `prepare`、`candidate`、`worker_commit`、`scenario_apply`、`wallet_sync`；在8/16/24/32/33笔后追加重复拒绝检查。第33笔的prepare之前必须依次完成 `worker_close`、`disk_check`、`worker_reopen`、`wallet_recover`，其prepare之后再执行 `outbox_restore`；末尾为最终 `worker_close`、`disk_check`、`finish`。付款序号、started／completed已提交高度和全局顺序一并校验。

| 计时项 | Ubuntu（毫秒） | Windows（毫秒） | 起止与范围 |
|---|---:|---:|---|
| scenario_start | 7547 | 9578 | 场景启动至有效ready与初始状态 |
| worker_create | 2087 | 2753 | 首代worker启动、握手与状态核对 |
| prepare，33笔合计 / 最慢单笔 | 120409 / 4045 | 149122 / 5210 | 真实历史／钱包检查、证明构造、加密保存和IPC等组合 |
| candidate，33笔合计 | 8846 | 11996 | 选择／预览及周围状态核对；包含多次请求 |
| worker_commit，33笔合计 | 823 | 1333 | 正常Finalize／Commit与状态、容量核对 |
| scenario_apply，33笔合计 | 1299 | 1777 | 场景独立执行并持久化 |
| wallet_sync，创世及33笔合计 | 13935 | 17865 | 全历史状态执行及两钱包同步 |
| worker_reopen | 3132 | 4120 | 新PID启动、完整重放、状态与容量核对 |
| wallet_recover | 5611 | 7465 | 同场景重开PoolStore、新验证器及两钱包备份恢复 |
| outbox_restore，第33笔 | 3431 | 4446 | 恢复已新建的第33笔原始待发送bytes |
| Go场景 `result.timings.total_ms` | 169314 | 215236 | 含记录文件、握手、检查等整体开销 |
| `supervised_process_elapsed_ms` / `supervisor_elapsed_ms` | 169395 / 169468 | 215561 / 216311 | 分别保留子测试监督窗口与监督器总历时 |

上述合计由同一原始JSON的completed记录按operation求和，不另造逐笔数据；完整181条耗时与33笔明细留在artifact。单项计时在调用前开始、回复核对后停止，不含随后资源ACK；组合操作可能包含多次RPC，不能与单次请求预算等同。多个CI runner的单次记录不用于推导平台性能倍数、生产TPS或端到端支付分位数。

worker启动60秒、worker请求60秒、场景ready／单响应90秒、资源ACK15秒、Go整项20分钟保持固定；监督器自原始启动时刻起统一1230秒期限，包含最多额外30秒清理，不在重试或finally中重置。`wallet_history()`完整执行状态历史，但可命中本PoolStore的64项授权缓存；新worker／重开PoolStore使用新验证器。同一场景恢复保留prover／allocator，OS文件缓存可能温热，不能称全新钱包进程或冷磁盘。

进度在可能阻塞操作前先写started，成功后才写completed及duration。中途失败保留已验证前缀、已完成耗时、最后未完成操作、失败原因及最后观测到的确认计数；缺失的duration不补成功值。若未完成操作是worker_commit，已提交数只是此前确认的高度，实际磁盘可能已提交，`commit_outcome_uncertain` 必须保留；不能据此声称付款未发生。`commit_outcome_uncertain`仅标记最后已观察到的pending是否为worker_commit；false也不证明此后磁盘没有提交。I/O诊断记录首次失败的位置，清理期间还可能采回较后的有效进度，因此不能用最终前缀倒推首次失败文件序号。首次checkpoint前的硬崩溃可能留下未登记子树，其清理未得到保证；成功路径的三个登记身份退出核对不等于通用进程沙箱或所有崩溃路径证明。

## 准确候选的原生CI

CI汇总生成时间：2026-09-17T06:56:51.171037+00:00。各原始API快照保留其实际观察时点，重复push的统计按对应冻结时点解释。必需PR矩阵为10个工作流、23个任务：原有9个工作流／21个任务文件保持字节不变，新增资源基线双平台2个任务。实际成功、失败、取消及条件跳过统计：10工作流、23任务全部success；283步骤，success 274、skipped 9；任务failure/cancelled/skipped均0，条件步骤skip不算执行通过。下表链接和结论均来自最终source head的真实运行，不继承历史候选或上一阶段的执行结果。

| PR工作流 | Ubuntu实际任务、链接与结论 | Windows实际任务、链接与结论 | 任务数 |
|---|---|---|---:|
| scaffold-tests | tests (ubuntu-latest)：[105091658406](https://github.com/youq616/Zevune/actions/runs/35187184944/job/105091658406) PASS | tests (windows-latest)：[105091658117](https://github.com/youq616/Zevune/actions/runs/35187184944/job/105091658117) PASS | 2 |
| consensus-laboratory | integration (ubuntu-latest)：[105091658437](https://github.com/youq616/Zevune/actions/runs/35187184977/job/105091658437) PASS | integration (windows-latest)：[105091658260](https://github.com/youq616/Zevune/actions/runs/35187184977/job/105091658260) PASS | 2 |
| orchard-cryptography-laboratory | tests (ubuntu-latest)：[105091658428](https://github.com/youq616/Zevune/actions/runs/35187185001/job/105091658428) PASS | tests (windows-latest)：[105091658125](https://github.com/youq616/Zevune/actions/runs/35187185001/job/105091658125) PASS | 2 |
| orchard-bridge | boundary (ubuntu-latest)：[105091658239](https://github.com/youq616/Zevune/actions/runs/35187184961/job/105091658239) PASS | boundary (windows-latest)：[105091658320](https://github.com/youq616/Zevune/actions/runs/35187184961/job/105091658320) PASS | 2 |
| orchard-consensus-integration | integrated (ubuntu-latest)：[105091658266](https://github.com/youq616/Zevune/actions/runs/35187184995/job/105091658266) PASS | integrated (windows-latest)：[105091658449](https://github.com/youq616/Zevune/actions/runs/35187184995/job/105091658449) PASS | 2 |
| wallet-laboratory | wallet (ubuntu-latest)：[105091658291](https://github.com/youq616/Zevune/actions/runs/35187185026/job/105091658291) PASS | wallet (windows-latest)：[105091658198](https://github.com/youq616/Zevune/actions/runs/35187185026/job/105091658198) PASS | 2 |
| funded-wallet-consensus | funded-library (ubuntu-latest)：[105091658355](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658355) PASS；funded (ubuntu-latest)：[105091658522](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658522) PASS | funded-library (windows-latest)：[105091658433](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658433) PASS；funded (windows-latest)：[105091658599](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658599) PASS | 4 |
| local-network-operator | operator (ubuntu-latest)：[105091658662](https://github.com/youq616/Zevune/actions/runs/35187185059/job/105091658662) PASS | operator (windows-latest)：[105091658402](https://github.com/youq616/Zevune/actions/runs/35187185059/job/105091658402) PASS | 2 |
| active-ledger-growth | source：[105091658097](https://github.com/youq616/Zevune/actions/runs/35187184931/job/105091658097) PASS；growth (ubuntu-latest)：[105098784268](https://github.com/youq616/Zevune/actions/runs/35187184931/job/105098784268) PASS | growth (windows-latest)：[105098784318](https://github.com/youq616/Zevune/actions/runs/35187184931/job/105098784318) PASS | 3 |
| payment-resource-baseline | resources (ubuntu-latest)：[105091658303](https://github.com/youq616/Zevune/actions/runs/35187185033/job/105091658303) PASS | resources (windows-latest)：[105091658502](https://github.com/youq616/Zevune/actions/runs/35187185033/job/105091658502) PASS | 2 |

| 关键原生检查 | Ubuntu实际结果 | Windows实际结果 |
|---|---|---|
| 根Go test／vet，平台支持的race与解码fuzz | PASS：根Go test／vet、支持平台的race及二进制解码有界fuzz；source步骤的no-tests-to-run仅编译，不计为运行测试 | PASS：根Go test／vet及相应整合用例；Linux专属race／fuzz条件步骤保持skip，逐项列于CI，不计为Windows执行通过 |
| 原生gofmt、rustfmt、Clippy、锁定构建及无源码漂移 | PASS：原生格式、固定工具链锁定构建、Clippy及无源码漂移；实际命令与目标范围见CI逐任务日志 | PASS：原生格式、固定工具链锁定构建、Clippy及无源码漂移；实际命令与目标范围见CI逐任务日志 |
| funded完整Rust library | 140通过，0失败、0ignored、0filtered；1个目标与结果逐一对应；[105091658355](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658355) PASS | 134通过，0失败、0ignored、0filtered；1个目标与结果逐一对应；[105091658433](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658433) PASS |
| funded二进制／整合／文档目标 | 49通过，0失败、0ignored、0filtered；19个目标与结果逐一对应；[105091658522](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658522) PASS | 49通过，0失败、0ignored、0filtered；19个目标与结果逐一对应；[105091658599](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658599) PASS |
| Python全部标准库测试 | 135项运行：132通过、3项Windows原生用例skip，0失败/错误（operator原始日志） | 135项运行：134通过、1项Linux proc专属skip，0失败/错误（operator原始日志） |
| 三个资源Python测试模块 | 53项运行：50通过、3项Windows原生用例skip，0失败/错误 | 53项运行：52通过、1项Linux proc专属skip，0失败/错误；三个Windows原生回归及deadline fixture均实际ok |
| Python／Rust钱包互通及旧真实四节点付款恢复 | PASS：原Python／Rust钱包互通、真实四节点付款、独立receipt绑定备份／待发送记录恢复及全网重启；见funded与operator任务 | PASS：原Python／Rust钱包互通、真实四节点付款、独立receipt绑定备份／待发送记录恢复及全网重启；见funded与operator任务 |
| 活动100000增长与低高度四节点操作 | PASS：100000正常worker块后完整重放并继续100001；低高度活动四节点付款和全网重启另行通过，见growth任务 | PASS：100000正常worker块后完整重放并继续100001；低高度活动四节点付款和全网重启另行通过，见growth任务 |
| 显式payment_resource_e2e编译、vet及真实32+1资源验收 | 编译及vet PASS；完整真实33笔PASS，Go测试169.32秒 | 编译及vet PASS；完整真实33笔PASS，Go测试215.25秒 |

funded-library任务还单独运行13项cohort监督器测试；这些是完整Python suite中的子集，不能额外相加为新的独立覆盖。

Windows未执行的Linux专属检查保持明确的skip，不计为Windows通过。资源模块含真实Linux进程测量测试，Windows该用例按平台条件跳过。实际跳过记录为 `test_proc_pinned_identity_rechecks_both_sides_of_memory_read`，原因 `Linux proc descriptor semantics`；三个新增 `test_delete_*` Windows原生用例均实际ok，并将其与GitHub工作流的条件步骤skip分开。上述计数均按最终候选实际日志核对；同套测试在多个工作流中重复执行时，按单次suite报告，不将重复数量相加为独立覆盖。C1本地121项及C1独立39项是历史测试，不填最终候选计数。作者已报告C4的Linux本地运行135项，132通过、3项Windows原生测试按平台跳过；其中资源pattern运行53项，50通过、3跳过。新增三个Windows原生场景已在该平台实际执行，这些本地结果不替代最终候选两平台CI和实际skip记录。

最终PR矩阵之外，同head的push、development-source、实际merge及后续文档触发运行属于另行观察：在2026-09-17T06:48:04.656Z的冻结观察中，同head另有8个push工作流／17任务，success 16、pending 1，仅16份已完成日志获得核对；未完成重复运行不增加验收覆盖。合入事件另见合入记录，后续纯文档提交的精确审核与观察见其PR。crate-notices未触发，不推导实际许可证盘点已完成。未完成、取消、未触发的运行不算通过；crate-notice是否触发及实际许可证盘点状态保持独立。资源基线固定构建使用Go1.27.1、Rust1.98.1、Cargo锁定release和 `RAYON_NUM_THREADS=2`；原有工作流的工具链与执行目标仍以各自YAML和原始日志为准。两平台artifact记录实际Python／Cargo版本与三个可执行文件SHA-256，见 两份原始资源JSON的 `metadata.toolchains` 和 `executables_sha256`；Ubuntu Python3.12.3、Windows Python3.12.10，均Cargo1.98.1 / rustc1.98.1 / Go1.27.1。三个可执行文件逐平台保留完整SHA-256，不把跨平台二进制视为字节相同。

## 独立审核、阻断与修复历史

设计最初仅在最终result保存耗时，异常退出无法保留逐笔失败阶段。独立设计审核要求补充不可覆写的操作开始／完成进度；冻结设计加入该协议后得到PASS。原始设计请求修改与通过记录保留，不将设计PASS当作实现通过。

第一版实现 C1 为 `8f0de0df649a0bae719b7ced789d8fc0857ca475`，tree `e861d8af54cc33735b82e796a20e301e10bea137`，直接父为阶段基线；其PR测试合成提交为 `b829fa3f6a0acb614a79ed8195a8bd119da82b6a`，tree相同。两路未编写实现的独立任务分别返回：`/root/p2_resource_review` 为 **CHANGES_REQUESTED**，`/root/p2_resource_ci_review` 为 **REQUEST_CHANGES**；均实际复现同一中等严重性证据阻断。

当时Python只验证局部started／completed配对、付款core顺序及额外操作的计数集合。将 `wallet_recover` 整对移到第33笔prepare和outbox恢复之后，或将高度32的 `worker_reopen` 移至场景启动之前，重新编号并令final timings匹配，仍会被接受。真实Rust／Go执行顺序正确；缺陷在验收证据合同，不能将其描述为生产付款或密码学绕过，也不能因真实流程正确就忽略阻断。

C2 `b6df89561eb6f2a75ed6fdc630e38d366d299f44`（tree `629af7982da8ac9f2e8476308dbca86626d81490`，父为C1）修复Python完整181操作／362进度的有序合同及语义拒绝回归，要求逐条校验付款序号、已提交高度和合法前缀，并在最终result再次核对完整顺序；付款路径、32+1负载、预算、冻结设计和旧回归保持。完整资源模块由39项增加为44项，本地全部Python由121项增加为126项。C2只是过渡提交；最终独立复审、原生验收与文件指纹均绑定C4，C2／C3保留各自历史结论。

C1的[Windows资源任务](https://github.com/youq616/Zevune/actions/runs/35184653050/job/105084001321)实际运行39项Python测试，结果1 error、1 skip：`test_cleanup_does_not_restart_its_existing_deadline` 在构造 `mock.patch.object(os, "killpg")` 时因Windows没有该属性而报AttributeError。后续原生格式、构建与32+1工作负载未执行，artifact只有初始setup，不能宣称Windows付款或内存实测通过。Linux专属proc描述符语义测试为显式skip，真实Windows自进程／子进程内存测试在此次Python运行中已通过；这些有限历史通过不替代最终候选验收。

C3 `9e46e03165250c6c51fa7031526d8de1bbdf27d6` 仅将该Linux模拟fixture中的 `os.killpg` 和 `signal.SIGKILL` 用 `create=True` 显式提供，并断言固定模拟信号9，使同一deadline测试可在Windows执行。测试不向真实进程发信号，没有跳过原deadline断言或修改生产清理预算。C3的Windows资源Python测试实际44项运行、43通过、1项Linux专属skip；两路代码复审虽PASS，后续真实负载仍失败，故C3没有获得阶段接受。

| 独立任务 | 最终候选审核范围 | 原始最终结论与链接 |
|---|---|---|
| `/root/p2_resource_review` | Rust／Go真实调用方、不变量、恢复顺序与跨组件证据合同；核对未改文件继承范围 | PASS：[准确C4原文](p2-payment-resource-evidence/cd5fe98-code-review.md) |
| `/root/p2_resource_ci_review` | Python OS采样、身份与清理、完整进度／最终结果、失败证据、工作流与source身份 | PASS：[准确C4原文](p2-payment-resource-evidence/cd5fe98-evidence-review.md) |
| `/root/p2_resource_native_audit` | 准确source／checkout、实际原生CI、artifact白名单、字段和计数、资源与清理原始数据 | PASS：[准确C4原生独审](p2-payment-resource-evidence/cd5fe98-native-audit.md)；[跨平台原始数值核对](p2-payment-resource-evidence/cd5fe98-resource-cross-platform-consistency.json) |
| 文档独立审核任务 | 实際接受后的报告、状态、准确引用与纯文档继承边界 | `/root/p2_resource_handoff_review`：准确文档候选的原始审核留在其文档PR，由 [PR #11](https://github.com/youq616/Zevune/pull/11) 关联；不把本文当作自身的提交身份或审核证明 |

实现审查是分离任务读取差异、实际调用方、不变量及负例后的结论，不能用作者自检、CI或重跑测试代替。上述任务标识用于本开发会话追溯，不是GitHub人工批准、外部安全机构或专业密码学审计。Windows／Linux真实执行和预算是否达到仍由准确候选CI单独证明。

C1的Ubuntu资源任务曾完成真实32+1运行并生成结构化结果，但在独立审核阻断下未获得阶段接受；该JSON仅为历史诊断，不并入最终候选成功矩阵。来源为 [C1 Ubuntu资源任务](https://github.com/youq616/Zevune/actions/runs/35184653050/job/105084001391)。C1／C2／C3的已观察历史另按准确时间点归档于[历史诊断](p2-payment-resource-diagnostic-history.json)。未取得最终观察的其他旧运行不记为通过、失败或取消；本阶段没有主动取消运行，也没有将旧候选的局部通过用于C4接受。

C3（head `9e46e03165250c6c51fa7031526d8de1bbdf27d6`）虽获两路限定代码范围的PASS，其Windows真实资源任务仍失败，未被阶段接受。原始报告保留27笔最后确认提交、4个完整检查点／8个样本、283条有效进度／141项完成操作及最后观察到的 `prepare(28)` started；result为null、Go退出1，监督总历时162188毫秒。记录的固定错误码是 `protocol_file_read_failed`，没有保存具体I/O阶段或系统错误号，不能把本次历史失败追认为已观测的Windows错误32，也不能仅凭最终前缀推定第一处失败读取的文件序号。C2 Windows另有实际44项测试／1 error／1 skip的同一旧killpg fixture失败，原日志和诊断分别保留。

C4只修正监督器的Windows读取方式并补充诊断和回归。微软说明，重命名的新文件名可能在DELETE访问句柄关闭前已经可见；不共享DELETE访问的普通读取可能在此窗口失败。新读取器使用只读权限及READ／WRITE／DELETE共享，并继续核对文件身份、大小、摘要、JSON和完整进度顺序，没有增加重试或改变预算。[微软对重命名共享窗口的说明](https://devblogs.microsoft.com/oldnewthing/20211022-00/?p=105822)。新增三个Windows原生测试显式保留DELETE访问句柄，核对旧Win32共享掩码的错误32及普通CRT拒绝、新读取成功、真实替换路径与追加大小仍被拒绝；该固定窗口不声称执行了真实rename，也不还原C3未采集的系统错误。另六项可移植测试覆盖句柄所有权、受限诊断、六个I/O阶段与最先发生的读取错误保留。诊断只存固定阶段、受限errno／winerror、协议种类和序号，不公开路径或异常正文。

## 原始证据、来源与完整性

最终证据保存在 `reports/p2-payment-resource-evidence/`；文件从原始采集结果逐字节复制，禁止重写旧review结论或用新观察覆盖旧时间点。下列链接指向已归档原件；完整文件长度、SHA-256与来源见[原始文件清单](p2-payment-resource-original-manifest.json)。CI快照中的 `file` 名称通过证据目录和原始文件清单定位；ZIP保留GitHub artifact来源、成员、大小与摘要，仓库保存其精确JSON原件，不重复存放ZIP。源码tree证明编译输入，文件SHA-256用于关联取证原件；二者都不是代码签名或安全审计。新资源证据目录及其JSON快照关闭Git文本换行转换，以保留Windows日志的BOM／CRLF及JSON原始字节；已在 `core.autocrlf=true` 的独立临时Git仓库核对blob与检出字节一致。

| 原始文件或快照 | 来源与范围 | 字节 / SHA-256 |
|---|---|---|
| [设计初审](p2-payment-resource-evidence/design-review-3f9bf22-changes-requested.md) | 独立任务原文；初稿请求修改 | 8544 / `85c9deeded8fc21d071da69b59c8173322a443fb3a0e3b621976e82f9ba3061c` |
| [冻结设计复审](p2-payment-resource-evidence/design-review.md) | 独立任务原文；仅设计PASS | 9243 / `e2db677553229e4426d3d7fa5c62338f081ab21caacd03f29f0b295d5e96a4c9` |
| [Rust组件预审](p2-payment-resource-evidence/rust-preliminary-review.md) | 原文；只有准确组件范围，不是C1整体验收 | 6790 / `236fd10d97d9c78037ed2174ca3f7dbc63f3f48497257fcbe25fc25d98361e4a` |
| [Go组件预审](p2-payment-resource-evidence/go-preliminary-review.md) | 原文；只有准确组件范围，不是C1整体验收 | 10356 / `aea5f947c2a59d0fab167bfd27945bceaa5b7b36f4259e0a1f67fe7ea57c1388` |
| [C1代码审核](p2-payment-resource-evidence/8f0de0d-code-review.md) | 独立请求修改原文 | 11993 / `348a1f8523b4f6eadfddad00802c350da67eb000ee188fb931d172397fe7be71` |
| [C1证据审核](p2-payment-resource-evidence/8f0de0d-evidence-review.md) | 独立请求修改原文 | 9508 / `2e4b26ca0040653f6af99029a6835761a72459e70f3db15b09f7056576ba866c` |
| [C1 Ubuntu原始资源JSON](p2-payment-resource-evidence/8f0de0d-ubuntu-payment-resources.json) | artifact 10482041012内原文件；仅历史、不是最终接受 | 130207 / `0ab169c45dc3bcee60846c16263a207ed31483a7a0efaaaafd015578a61bfa3e` |
| [C1 Ubuntu初始setup JSON](p2-payment-resource-evidence/8f0de0d-ubuntu-payment-resource-setup.json) | 同一artifact；`not_started`只表示最初设置观察 | 456 / `b4fa11bb737a8aeb0763b867183ac3f5ad25ebc4a2ef7cb48a95f0ec16bcc0a3` |
| [C1 Windows初始setup JSON](p2-payment-resource-evidence/8f0de0d-windows-payment-resource-setup.json) | artifact 10482241079；该ZIP仅此一项，Python error之后未执行真实负载 | 466 / `da00b308d6b136517e66bfd65d2d5cfb37fd292602e5bbc90a3c9f9674ef95c0` |
| [C1双平台原生诊断](p2-payment-resource-evidence/8f0de0d-native-diagnostics.json) | 独立原生任务05:24:14 UTC的原始历史观察 | 4329 / `cf7f75f5a32f750eb636094544b30f5d2a4f5aeeee9cb7136ec3d1cce4f0030c` |
| [C1 Windows失败日志](p2-payment-resource-evidence/8f0de0d-job-105084001321.log) | 实际job日志；保留39项、1 error、1 skip及后续未执行事实 | 34545 / `5817f00333e332c20e793b9c8f31f08faefd47802ea91c894ff5f1f4fa0ac038` |
| 最终Ubuntu资源JSON及setup JSON | [artifact 10481864543](https://github.com/youq616/Zevune/actions/runs/35187185033/artifacts/10481864543)；[资源JSON](p2-payment-resource-evidence/cd5fe98-ubuntu-payment-resources.json) / [setup](p2-payment-resource-evidence/cd5fe98-ubuntu-payment-resource-setup.json) | 资源JSON 130207 / `267237f2487d95c9833fe64739673430ad1b3670c9788912558971b1c640ac16`；setup 456 / `fd92cc0d16d9024bcc2fdbdeeaa5a6db2d9d95d6d1fd4690ccdf1b6205632db3` |
| 最终Windows资源JSON及setup JSON | [artifact 10483445741](https://github.com/youq616/Zevune/actions/runs/35187185033/artifacts/10483445741)；[资源JSON](p2-payment-resource-evidence/cd5fe98-windows-payment-resources.json) / [setup](p2-payment-resource-evidence/cd5fe98-windows-payment-resource-setup.json) | 资源JSON 131239 / `443f57a7366f2149535dc95459c4f8b104c8569de4dc70fca7310b18c5ad0a96`；setup 466 / `a9093653512c527190852ad0899a8fbd9bfc73c48c46110aa99579aa136ff550` |
| 最终两路独立复审原文 | [C4代码](p2-payment-resource-evidence/cd5fe98-code-review.md) / [C4证据合同](p2-payment-resource-evidence/cd5fe98-evidence-review.md) | 代码 12800 / `b58be49baff48e6306ec9dfd9f300f9cf0f442dd874d709c84bdfcde26fe16d1`；证据 8842 / `2280bed9a5523a53d62cea1b4cf51843b5d7b05700f7bc46a2caa291b3a1ab74` |
| 最终原生独立审计原文 | [准确C4原生独审](p2-payment-resource-evidence/cd5fe98-native-audit.md) | 22126 / `260bc4ca7a61b1e2b9b8eb3eb903168906b1495afcc0fff804df03f6fd3f8849` |
| [PR矩阵CI快照](p2-payment-resource-ci.json) | 最终source的实际run／job、状态、checkout与日志摘录 | 1349246 / `4f0dc512e6c636c09358f302eb4d28fe2ea3d9b06afe649fe0b10f0ec0757c88` |
| [合入与后续运行记录](p2-payment-resource-merge.json) | 另行观察，不改原CI快照时间 | 153849 / `584e6b6a6db6284db3113c32dac47eec816c5dd5418309dddd5b8e274e5e4569` |
| [历史诊断记录](p2-payment-resource-diagnostic-history.json) | C1请求修改、C1／C2 fixture失败、C3代码PASS但真实负载失败的准确历史 | 43416 / `ff0741c584378be2d7e099d784517d54f42fad23209acc863713f81800062054` |

GitHub artifact只允许 `ci-results/payment-resource-setup.json` 和 `ci-results/payment-resources.json` 两个公开JSON；最终两平台ZIP的实际成员核对为 两平台均恰为 `payment-resource-setup.json` 和 `payment-resources.json`；ZIP摘要与GitHub artifact digest逐一相符，解压JSON按原始字节保存。setup只记录最初 `observed_execution_status: not_started`，即使上传成功也不证明付款场景执行。资源JSON只保存源码／工具链／公开状态／计时／进程身份，不包含钱包、秘密创世见证、付款原始bytes、密码或被测进程的环境与命令行。另行归档的Actions原始日志包含CI自身的公开构建命令、工具链设置与测试输出，不等同于采集被测钱包进程的环境或命令行。报告中的 `result_sha256` 是内部规范result的摘要，不能当作整个资源JSON的文件SHA-256。

## 未覆盖范围与下一步

本阶段只补上固定32+1笔真实付款及恢复资源基线。33笔带来68 commitments／66 nullifiers，并未触达65536承诺、64项授权缓存淘汰、64个anchor、256条钱包保存记录、1 GiB账本逻辑容量、1000000条记录或活动段轮换边界，也不证明持续付款负载、最大容量或生产吞吐量。

上一阶段正常worker提交100000块的证据继续单独保留，其中99998为空块、2块含真实付款，完整重开后继续到100001；独立低高度四节点付款／全网重启另有场景。它不因本次33笔基线变成100000笔付款、四节点共识100000块或最大容量验收。见[原活动账本验收](p2-active-ledger-validation.md)与其原始CI／审核记录。

P2下一优先项为固定活动账本归档及备份恢复合同，并实现可校验的完整恢复；快照加增量恢复、剪枝、容量告警、长期真实付款增长、真实断电／磁盘满、Windows目录持久化及跨机器长期运行仍需独立验收。永久防双花状态、钱包恢复历史和验证者签名状态不能因归档而丢弃，节点签名状态也不能用账本恢复代替。

网络隐私、完整在线Windows钱包、开放验证者／经济规则、签名发布、实际许可证盘点、外部独立安全审计和六份历史缺失文档仍未完成。真实资金、公开部署、生产存储及整体支付产品状态保持未准入；八工作包未全部完成。
