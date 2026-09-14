# P2：检查点绑定的账本备份与恢复

范围：本机、无价值测试资产。完整复制并重放现有 Orchard 日志；不是状态快照、快速同步、日志分段/裁剪或生产级长期存储。现有容量常量、签名、电路、共识、IPC 和日志格式不变。

## 信任与格式

`PoolStore::recovery_checkpoint()` 对当前已提交日志执行历史检查，并比较重放前后的文件摘要，导出固定 120 字节的检查点。它不包含未提交提案、钱包、密钥或私密见证。

| 字节范围 | 字段 |
|---|---|
| 0–7 | ASCII `ZVPRCP01` |
| 8–39 | 原日志创世头 SHA-256 |
| 40–47 | 已提交高度（大端 u64） |
| 48–79 | 对应应用状态摘要 |
| 80–87 | 原日志精确字节长度（大端 u64） |
| 88–119 | 原日志全部字节 SHA-256 |

命令行使用对应的 240 位小写十六进制。检查点必须独立保留；从同一不可信提供者取得备份和检查点，不构成身份认证。修改检查点仍可能表示另一段有效历史，它不是签名证书、共识终局证明或全网最新高度证明。旧检查点只认证旧高度的文件。

`RecoveryArchive::open()` 以只读句柄和共享锁读取。校验文件类型、长度、整体摘要、创世身份，然后通过与正常启动共用的原重放实现重新检查每笔真实授权、域、历史根、双花、重复输出、费用和逐块状态。重放之后再次核验整体字节。只验证文件哈希绝不足以通过此接口。

## 复制与失败行为

`copy_new()` 使用原子仅创建模式和目标独占锁。完整复制后同步文件，Unix 上尝试同步父目录；使用持有锁的同一目标句柄重放验证，避免 Windows 二次打开锁冲突。最后再次核验源文件。成功保持完全相同的日志字节及检查点。

源文件不覆写、不截断、不删除、不退休，也不改变付款预留。目标已存在、目标是源路径或现有硬链接时拒绝覆盖。普通符号链接/Windows reparse point 会在文件类型检查时拒绝。父目录、操作系统与文件系统仍须可信：此接口不是对恶意本机路径替换的沙箱。文件锁仅协调遵守锁的进程，不宣称抵抗恶意内核、存储固件或任意路径竞态。

失败可能留下部分写入文件，也可能在完整写入已同步后丢失确认。禁止自动重试、覆盖、清理或把失败解释为“新文件肯定不存在”。先用原检查点显式 `verify`；未通过者不能使用。Windows 没有在本实现中获得与 Unix 父目录同步完全相同的承诺；故障注入不是任意断电保证。

## 可执行入口（本轮不要求用户手工验证）

从准确源码构建：

```text
cargo build --manifest-path integration/orchard/Cargo.toml --locked --release --features local-funding-lab --bin zevune-pool-recovery
```

此独立实验工具目前不加入原五文件交付包。`--help` 可查看参数。所有操作要求 `--no-real-funds`；路径使用绝对路径。程序不连接网络、不接受钱包密码、不启动节点。

```text
zevune-pool-recovery checkpoint --no-real-funds --source <原日志> --genesis <公开创世清单> --genesis-sha256 <独立固定摘要> --height <可信高度> --app-hash <可信应用摘要>
zevune-pool-recovery backup --no-real-funds --source <原日志> --output <不存在的备份路径> --checkpoint <独立保留检查点>
zevune-pool-recovery verify --no-real-funds --source <备份> --checkpoint <独立保留检查点>
zevune-pool-recovery restore --no-real-funds --source <备份> --output <不存在的恢复路径> --checkpoint <独立保留检查点>
```

`checkpoint` 使用已有正常启动验证，需要可打开且没有其他拥有者的日志；先停止所属 writer。`backup/verify/restore` 只需可读源文件，共享锁阻止与遵守锁的活动 writer 同时操作。参数错误返回非零退出码，失败文本不回显路径。JSON 成功响应明确保留 `finality_verified:false`、`validator_ready:false` 和 `real_funds_allowed:false`。

## 不是完整验证者恢复

只备份一个 Orchard 账本不包含 CometBFT 区块数据库、WAL、节点身份、验证者密钥和最后签名高度。恢复副本首先只代表指定高度的应用账本。不得删改 `priv_validator_state.json`、回滚签名记录或把旧副本直接替换活动验证者目录；那需要单独的共识/签名状态一致性恢复流程。当前工具没有该流程，也不自动把副本启用成节点。

保留完整历史是为了让恢复继续走真实验证和钱包扫描路径。后续快照/分段方案必须独立审查状态来源、历史可用性与防回滚约束，不能把此次全量复制改名为快速同步。
