# P2 活动账本的实际空间耗尽与进程恢复

本阶段接续 [2026-09-19 接手审核](TAKEOVER_AUDIT_2026-09-19.zh-CN.md) 和 [PR #19](https://github.com/youq616/Zevune/pull/19)，基线为 `d7f1e39e16884db446fb8eec4a3c4c975aa652fe`。范围是 ActiveSegmentsV1 的真实操作系统故障回归及独立验收，P2 整体继续开发。准确候选、完整 CI、非作者复核和合入结果记在本阶段 PR；测试定义和工作流配置本身不构成通过证据。

## 1. 本阶段检查什么

已有私有 `cfg(test)` 故障点覆盖空新段、部分帧、同步前失败和同步后确认丢失。它们继续保留。本阶段另外增加实际内核空间耗尽、真实 worker 强制终止及真实成功应答丢失的证据。

| 场景 | 确定触发点 | 验收结果要求 |
|---|---|---|
| Linux 旧尾段空间耗尽 | 固定小型 tmpfs 已满；真实付款帧跨越尾段已分配页的剩余空间 | 目标 journal 的写系统调用返回 ENOSPC；原前缀保持，只留下不完整追加；没有成功提交回执，实例拒绝后续操作 |
| Linux 新段空间耗尽 | 正常提交接近原 1 MiB 段边界；下一笔真实付款需要轮换，tmpfs 数据空间已满 | 新段创建后写入返回 ENOSPC；旧头部和旧段不变，新段保持实际空文件；实例拒绝后续操作 |
| Linux / Windows 提交前强杀 | 真实 Finalize 成功，但尚未发送 Commit；直接调用实际进程的 Kill | 等待实际非成功退出，冷重开得到原完整 Summary 和容量；目录全部字节不变；旧 pending tag 拒绝，新 Finalize 才能提交 |
| Linux / Windows 提交回执丢失 | 测试包装器读到真实完整 Commit 成功应答并核对后，扣留应答，不交给 Client | 取消返回不可用及取消错误；客户端关闭，Commit 只发送一次；冷重放得到独立参考执行的新完整状态，重复付款拒绝，后续真实付款可继续 |

所有付款均为临时、无价值测试资产，使用现有真实 Orchard 证明和授权。活动 profile 的记录、字节、段数、单块交易和钱包上限保持原值。没有新生产故障开关、接受型替代验证器、尾部自动修复或自动重试机制。

## 2. Linux 空间耗尽的环境与证据

[`active-storage-faults.yml`](../.github/workflows/active-storage-faults.yml) 使用独立 Linux runner。先以普通用户编译固定 Rust 工具链和锁定依赖，再由 [`run_active_enospc.py`](../scripts/run_active_enospc.py) 在私有 mount / PID namespace 中创建每场景独立的 **8 MiB tmpfs**，限制 inode 数，并以普通 runner 身份执行编译好的测试。填充只发生在这个固定容量的专用文件系统，填充循环本身也有字节上限。

filler 位于 journal 目录之外，但属于同一 tmpfs。挂载类型、容量、设备与可用 inode 需要实际核对。原尾页仍可能有空间，因此尾段测试明确要求付款帧跨页，并检查故障后追加恰好停止于页边界；不会以一个小空块的失败与否代替该条件。轮换场景使用正常空块接近原段边界，再执行真实付款；空块不计作付款。

生产存储层将系统错误映射为 `PoolError::Storage`，仅看到这个错误和 filler 的 ENOSPC 不足以确认目标 journal 的系统调用结果。每例使用外部 strace，只有一个精确目标路径 `-P`；仅观察写入及同步调用，写参数采用 `raw`，只保留失败结果。`raw` 不解引用付款缓冲区，原始 trace 和任意进程 stderr 不进入公开回执。回执必须包含实际命中的 journal ENOSPC 及有限的环境、恢复和清理结果。

两个专用 Rust 测试定义于 [`active_enospc.rs`](../integration/orchard/tests/active_enospc.rs)，由 Linux + `local-funding-lab` 条件编译，并标记为需要专用挂载的 ignored 测试。普通 funded cohort 会发现它们但不会自行挂载；独立工作流必须用完整测试名、`--exact --ignored` 分别实际执行两例。环境能力不足、测试没有运行、未观测到目标错误、超时或清理失败都不能计为通过。其他平台没有取得 ENOSPC 验收。

测试进程和 trace 读取均有时间、输出上限。正常卸载及进程回收是验收条件；不能使用 lazy unmount 或忽略清理错误来取得成功回执。失败源目录在核验期间保留，最终回收的是整个临时实验环境，不是由生产存储实现删尾或修复数据。

提权监督器位于 namespace 外，使用固定的 TERM / KILL 期限。独立短时 probe 会实际运行忽略 TERM 的 root namespace，并在监督器结束后确认原 PID namespace 已无成员；普通用户对 sudo 的信号返回值不能代替这个检查。只有正常退出、两例普通卸载和完整回执均确认后才删除控制目录；超时、异常或缺少确认时保留有界目录，并明确记录清理状态未知。公开 CI 日志只输出固定字段的身份、计数、摘要和清理结果，原始 trace 不公开。

tmpfs 的固定容量耗尽会产生真实 Linux 文件系统 ENOSPC，但它不经过普通块设备路径。这个结果不证明物理磁盘、同步写故障、硬件缓存、Windows 磁盘满或断电持久性。

## 3. 空间耗尽后如何恢复

每例先通过正常 API 提交真实付款和必要的空块，在故障前的完整已提交状态下导出独立检查点，并在专用 tmpfs 之外创建好备份。故障后只使用该事前副本恢复，不能从故障目录生成一个较旧 pin 来抹去已知状态。

实际写入失败后，可能有不完整的日志后缀，因此不要求整个故障 journal 一律不变。本阶段分别检查原 genesis、旧段和原尾段前缀保持，以及实际留下的部分帧或空新段。关闭故障实例后，普通 open 和按原 pin 打开归档都必须拒绝，并且不得改变故障目录的字节或文件集合。

随后通过原 `ActiveArchive::copy_new` 路径，按事前保存的可信 pin，从好备份恢复到另一个全新目录。恢复后使用普通 PoolStore 完整重放，核对完整 Summary、布局检查点、余额和已花付款拒绝；未成功提交的那笔原付款仍需正常重新验证才能提交。再执行真实付款、核对资金守恒、重复付款拒绝和再次重开。签名和付款字节不写入报告。

恢复得到的是该独立 pin 对应的公开账本状态。较旧好备份不能被自动解释为最新链状态，也不能单凭它重启验证者。公开账本副本不包含钱包、共识数据库、WAL 或最后签名状态，仍不授予 `validator_ready`。

## 4. 进程终止与回执丢失

[`active_process_recovery_e2e_test.go`](../internal/poolbridge/active_process_recovery_e2e_test.go) 沿用明确的 `payment_resource_e2e` 标签和实际 worker / 钱包场景进程。[付款资源工作流](../.github/workflows/payment-resources.yml) 分别在 Linux 和 Windows 执行新测试；Linux 对新测试启用 race。原固定 32+1 付款资源场景、条件检查和预算保持，新增故障场景单独计数。

每例使用相同创世和确切付款，在另一个真实 worker 中独立执行，取得参考完整 Summary、容量和物理文件字节。参考进程先关闭，之后才读取文件，兼容 Windows 原有文件锁。受测 worker 在故障前证明竞争打开被拒，故障后等待 Cmd.Wait 完成，再读取原目录和启动新实例。

强杀场景先直接 Kill，不先关闭 stdin；因此不会把 EOF 有序退出当作强制终止。Kill 只针对实际 Rust worker 进程，不证明整套验证者进程树或宿主机掉电恢复。

回执丢失场景的包装器仅存在于测试文件，只扣留真实字节。它完整核对 magic、request ID、request digest、成功标志及独立参考 Summary，再等待明确取消；不会构造成功应答。写侧记录实际发送的完整请求，核对恰好一帧 Commit，且失效后的显式第二次 Commit 不再写入。关闭必须解除读取等待，不能形成取消与管道回收的死锁。

结果尚未知时，钱包场景保持旧参考历史，恢复原加密 outbox 并核对完全相同的待发送字节和 reservation。只有新 worker 完整重放确定实际结果后，才把对应区块交给参考钱包历史并同步付款状态。整个流程不重新签一笔替代付款。随后验证原 pending tag 不可复用、已花付款拒绝、新付款可继续，并检查两笔付款的完整物理记录和再次重开。

该场景明确验证成功应答丢失，不声称随机命中某一次 write 或 sync 的中间点，也不把一次客户端错误解释为交易肯定未提交。测试恢复的是账本和既有测试 outbox，没有声称已覆盖钱包进程强杀、所有支付界面状态或验证者签名恢复。

## 5. 验收与剩余范围

候选冻结后，由未编写候选的代理分别审核存储、Go 进程边界和 CI / 交付；修复阻断后复核准确提交。原生验收逐一检查当前 head 的 PR 工作流、完整日志、实际执行场景和平台条件。合入后再次核对完整 tree，不能以其他提交或同 head 的部分成功替代。

本阶段未测试钱包文件自身磁盘满；后续针对钱包同步追加及整理目标的实际 ENOSPC 合同见[钱包存储故障与恢复](WALLET_STORAGE_FAILURES.zh-CN.md)，不能把本阶段账本结果改记为钱包结果。P2 尚需完成快照状态导入与防回滚设计、真实物理存储故障及同步/断电试验、Windows 实际磁盘满与目录持久化、其余钱包故障、持续真实交易和完整容量负载。P3 多机、P4 完整钱包、网络隐私、经济规则、长期运行和外部专业审查继续按[八工作包计划](DELIVERY_PLAN.zh-CN.md)推进。`production_storage_ready`、`audited` 和 `real_funds_allowed` 保持 false。

上游依据：[Linux tmpfs](https://docs.kernel.org/filesystems/tmpfs.html)、[strace 手册](https://man7.org/linux/man-pages/man1/strace.1.html)、[strace v6.8 raw 输出](https://github.com/strace/strace/blob/v6.8/src/syscall.c)、[strace v6.8 路径过滤](https://github.com/strace/strace/blob/v6.8/src/pathtrace.c)、[unshare](https://man7.org/linux/man-pages/man1/unshare.1.html)、[Go 1.27.1 Process.Kill](https://github.com/golang/go/blob/go1.27.1/src/os/exec.go)。这些说明操作系统和工具行为，不是对 Zevune 的安全背书。
