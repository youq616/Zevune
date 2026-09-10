# M1：本地账本日志与重启恢复

版本：0.1.1-dev。仅用于无真实资金的单机原型。持久化不是共识、钱包、真实隐私或安全审计。

## Windows 启动与验证

先在运行旧程序的窗口按 Ctrl+C。进入已有源码目录，拉取更新并测试：

```powershell
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "更新失败，未启动程序。" }
go test ./... -count=1
if ($LASTEXITCODE -ne 0) { throw "测试失败，未启动程序。" }
go run ./cmd/zevuned -data-dir "$env:LOCALAPPDATA\Zevune\devnet"
```

数据目录会在首次使用时创建。不要使用网络共享、同步盘、他人可修改的目录或真实钱包目录。不需要管理员权限来写入这个个人数据目录。不指定 `-data-dir` 时仍然是旧的纯内存模式。

另开 PowerShell：

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/v1/status" | ConvertTo-Json -Depth 6
```

首次创建时，`storage.mode` 为 `journal`、`storage.recovered` 为 `false`、`storage.available` 为 `true`。Ctrl+C 停止后，用同一条带 `-data-dir` 的命令再次启动；第二次 `recovered` 应为 `true`。它仅说明本次打开并验证了既有日志，不表示之前崩溃过。

`height` 仍为 0，`payments_enabled` 与 `finality_available` 仍为 false。服务没有出块入口、自动出块器或可用证明系统；运行多久都不会因此产生真实区块。交易重放与重启后重复花费拒绝的场景只使用 `_test.go` 内的合成测试数据。

`veil-local-devnet-1` 是保留的 v0 兼容性参数，不是接入另一个网络。不要修改协议固定字节来做品牌替换，也不要把一个数据目录交给不同 chain-id 使用。

## 保存和恢复规则

文件名为 `ledger.journal`。首条记录绑定日志版本、链标识、协议版本、电路标识与调用方给定的初始承诺。之后按顺序追加区块记录，含长度、二进制信封和前后关联的 SHA-256 校验值。重启时重新执行现有验证规则，而不是直接信任序列化的余额或状态摘要。

持久模式的 ApplyBlock 先验证整块，再追加记录并执行 File.Sync，最后才更新对调用方可见的内存状态。若写入或同步失败，该引擎拒绝后续检查和提交。同步失败的磁盘结果可能不确定：记录也可能已经完整写入；不能将错误解释为一定回滚，必须关闭并重新验证日志。

文件锁由操作系统维护；第二个使用同一日志的进程会失败而不是同时写入。进程退出后锁随文件句柄释放。已存在的空文件、损坏记录、不完整尾部、错误配置或超出限制的文件都会拒绝打开，不静默清空、截断或自动修复原文件。

## 范围和限制

当前限制为 64 MiB 日志和 10,000 个区块记录，无压缩、裁剪、快照或迁移。验证和状态复制仍随历史增长，不是高速生产数据库，更没有证明主链 TPS 或转账延迟。

校验和不是签名或加密，不能阻止有文件写权限的人重算校验值、替换文件或删除完整尾部记录。无外部可信锚点时，完整旧日志回滚可能被接受。只应使用可信本地文件系统；不抵抗恶意本机管理员及路径替换竞争。

已请求对文件同步，但不能承诺所有硬件、文件系统和断电条件下零丢失。Windows 不提供本实现中的目录 fsync 保证；网络磁盘、突然断电、磁盘损坏未做实机验收。Windows 文件访问控制取决于用户目录的 ACL，不能把 Unix 的 0600/0700 当作 Windows 隔离保证。

备份仅在程序完全停止后进行。发现损坏时保留原文件和错误，不删除数据来掩盖错误。此阶段不接收真实资产、密钥、钱包备份或支付明文。

## 实现参考

- Go File.Sync、Rename、OpenFile：https://pkg.go.dev/os
- Windows LockFileEx：https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex

这里避免使用重命名覆盖来宣称跨平台原子保存：Go 文档明确指出非 Unix 平台上的 Rename 不是原子操作。当前选择的是有边界的追加日志，用于验证恢复行为；正式数据库选型仍需单独评审。
