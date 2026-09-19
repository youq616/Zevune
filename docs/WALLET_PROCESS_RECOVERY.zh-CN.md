# P2 钱包持有进程强杀与冷恢复

日期：2026-09-19。起点为 `180a2063353684c4ff085d0c54456726ceda2b30`（PR #21 已合入）。
本文件描述新增测试合同；不是阶段验收、主网批准或外部安全审计结论。
准确候选 base/head/tree、运行结果、独立审核及合入状态以本阶段 PR 为准。

## 范围和故障边界

此前 [活动存储故障](ACTIVE_STORAGE_FAILURES.zh-CN.md) 强杀的是账本 worker；
[钱包空间耗尽](WALLET_STORAGE_FAILURES.zh-CN.md) 覆盖钱包追加和整理目标的实际 Linux ENOSPC。
本阶段补充的是**持有真实 WalletStore 的独立进程**被操作系统强制终止后的恢复。
使用现有加密日志、真实 Orchard 授权及活动账本，没有替换验证器、改写生产钱包或增加故障开关。

固定两个故障边界：

| 场景 | 强杀时已完成的操作 | 必须验证的恢复结果 |
|---|---|---|
| 待发送付款已保存 | 子进程 `prepare_payment` 已成功返回；预留和精确签名字节已经按现有代码同步保存，付款尚未提交账本 | 相同 outbox、交易 ID 和预留恢复；不得另建第二笔付款；原交易正常提交并同步后才清除预留 |
| 付款确认已保存 | 父进程已独立提交付款；子进程通过真实账本历史 `sync` 成功保存确认结果 | 冷打开后仍需同步历史，但不得复活旧 outbox 或旧预留；余额与完整重放一致 |

两例均在原钱包文件上冷打开，并检查全部加密文件字节、相同收款地址、精确回执、
独立账本 Summary、旧备份拒绝及后续 B→C 的真实付款。随后拒绝两笔付款的重复提交，
检查拒绝前后账本 Summary 与物理字节不变，再次关闭和完整重开账本、钱包后核对结果。
测试使用固定的无价值资产数量；不测量支付吞吐量或网络最终性。

**本次强杀发生在写入与文件同步已经成功返回之后，不发生在 write/fsync 的中间。**
操作完成由测试专用观察文件标记；观察文件不是生产 CLI 回执，不能声称覆盖生产 CLI
成功响应丢失。被杀进程运行真实钱包存储库，但不是 `zevune-wallet-local` CLI 本身。

## 独立回执和防止错误恢复

父进程在强杀之前通过测试观察通道保存最新 StoreReceipt；该回执不从待验证备份推导。
用这个较新的回执打开故障前的完整、有效旧备份必须返回 `Rollback`，且旧备份字节不变。
还验证现有 API 语义：较旧回执是**祖先下限**，不是精确最新 tip；它允许打开包含该祖先的
新文件，返回的新回执必须仍为最新回执。测试不更改这一兼容合同。

文件重新打开和解密不等于账本已同步。`balance`、`available_balance` 和 `pending_payment`
在提供真实验证历史之前必须返回 NotSynced；对同一已保存检查点重新同步不得额外追加日志。
准备阶段恢复出的原签名字节由调用者显式提交，不在恢复或进程重启时自动广播。

## 进程监督、隐私及清理

子进程是同一原生 Rust 测试可执行文件中的一个显式忽略 helper；父测试用固定名字单独启动它。
普通测试发现时 helper 保持 ignored，但两个父场景都会实际启动 helper，不能把 ignored 计作通过。
强杀前同时检查子进程仍活着、钱包独占锁仍被占用以及正常析构标记不存在。
Linux 必须直接观测 SIGKILL 退出状态；Windows 必须观测原生非成功退出状态。
强杀后正常析构标记仍必须不存在，子进程必须已经被 `try_wait` 确认退出。

准备就绪等待上限为每个子进程 120 秒，停止确认上限为 5 秒。显式停止失败后析构清理不得
重新开始计时。子进程没有孙进程，标准输出和错误输出直接丢弃；不会积累管道日志或让
继承输出管道拖住清理。另有三个真实短子进程回归：没有就绪的停滞进程、未就绪但成功退出、
错误就绪标记，均不得被认作操作成功。

测试目录为随机创建的专有临时目录；Unix 使用 0700 目录及 0600 观察文件。
随机测试口令只经 stdin 传递，父、子内存使用 Zeroizing；不进入 argv、环境变量或文件。
观察交易文件只含公开签名 envelope，不含钱包密钥，也不作为 CI artifact 上传。
断言不打印 envelope 或钱包文件字节。Windows 目录 ACL、恶意本地进程、交换分区、
核心转储及恶意文件系统不在这个测试的保护承诺内。

只有确认子进程退出后才允许删除测试目录；无法确认时测试失败并保留有界目录。
成功场景还显式验证目录删除成功，不将“发出了 kill”视为“已清理”。

## 原生运行

在仓库根目录使用锁定工具链，Linux / Windows 均运行：

```text
cargo +1.98.1 test --manifest-path integration/orchard/Cargo.toml --locked --release --features local-funding-lab --test wallet_process_recovery -- --test-threads=1 --nocapture
cargo +1.98.1 clippy --manifest-path integration/orchard/Cargo.toml --locked --release --features local-funding-lab --test wallet_process_recovery -- -D warnings
cargo +1.98.1 fmt --manifest-path integration/orchard/Cargo.toml --all -- --check
```

专用 `wallet-process-recovery` 工作流分别在 Linux 和 Windows 原生执行。
现有 funded 接口测试的 Cargo target 自动发现也会纳入这个新 integration target；
不删除、筛掉或提高原有工作流、密码学验证、资源与时间门槛。
当前测试清单为五个父测试与一个显式子进程 helper；实际通过数量和跳过原因须从准确候选日志核实。

## 验收和剩余范围

作者复核、原生 CI 和非作者独立代理审核分别记录。[AGENTS.md](../AGENTS.md) 规定的独立审核
必须针对准确候选并返回实际结论；无响应、仅表情或过期审核都保持 REVIEW PENDING，不能合入 main。

本阶段仍不覆盖钱包首次保存写满、备份复制/CLI 导出写满、写入中间点强杀、真实 Commit
应答丢失、物理磁盘/断电/目录持久性、共识 signer/WAL、Windows 实际磁盘满、快照状态导入、
持续大规模交易或长期多机运行。其他阶段已完成的场景保留原记录，不与本阶段混计。
`production_storage_ready`、`audited`、`real_funds_allowed` 及 `snapshot_state_import_implemented`
均保持原 false 状态；完整 P2 范围继续依据[交付计划](DELIVERY_PLAN.zh-CN.md)。

上游依据：[Rust Child 的 kill、try_wait 与清理责任](https://doc.rust-lang.org/std/process/struct.Child.html)。
上游 API 文档不是对本项目安全性的认证。
