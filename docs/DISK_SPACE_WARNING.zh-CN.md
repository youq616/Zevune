# P2：显式磁盘可用空间预警

本增量为离线 `zevune-network storage` 增加 `--disk-reserve-bytes <正整数>`，分别输出账本重放结果和随后取得的操作系统空间样本。默认容量查询兼容原行为；它不是后台监控、磁盘空间预留或共识接受条件。仅用于既有 NO-FUNDS 本机实验。

## 接口与返回语义

`Network.InspectStorageWithDiskSpace(ctx, worker, workerPin, journal, reserveBytes, expected)` 是独立入口。`expected` 可为空，非空时先按值复制，并使用配置中固定 profile 的原检查点规则校验。上下文、profile、正阈值和检查点验证在打开磁盘目标之前完成。CLI 严格参数、成功告警和 JSON 字段见[离线存储检查](OFFLINE_STORAGE_INSPECTION.zh-CN.md)。

新入口先保留已有目标的只读句柄，再调用原完整 `inspectStorage`，保留配置、创世、worker 摘要、独占锁、真实授权重放和准确检查点校验。随后核对目标身份、查询可用字节、再次核对身份及上下文，显式关闭全部保留句柄，最后才把 `DiskSpace` 附入报告。任何一步失败均不返回成功报告；不从失败状态自动修复、截断、重建或重试。

原 `InspectStorage`、`InspectStorageAtCheckpoint` 和 `storage-copy` 不调用新探针。阈值不改变账本、交易、授权缓存、IPC、共识状态或任何容量上限。`golang.org/x/sys` 使用仓库已有固定版本 v0.30.0，仅由间接依赖改为直接依赖。

## 系统与路径语义

| 平台 | 测量对象与含义 |
| --- | --- |
| Linux | 对保留的旧 journal 文件或活动目录原始 fd 调用 `Fstatfs`；`f_bavail × f_frsize`，仅在 `f_frsize == 0` 时回退 `f_bsize`。块尺寸必须为正，乘法须可表示为 uint64。0 可用块是合法低空间样本。`f_bavail` 是文件系统报告的非特权可用块数，不泛化为调用者个人配额余量。 |
| Windows | `GetDiskFreeSpaceExW` 查询旧 journal 所在的父目录或活动目录，取 `freeBytesAvailableToCaller`，受该 API 的调用者配额语义约束。保留原目标及实际查询目录的句柄并在查询前后核对身份；不返回总容量以免混淆跨平台配额口径。 |
| 其他平台 | 显式磁盘检查返回不支持错误；未请求该选项的原容量路径不因此增加平台要求。 |

输入要求已有、规范的绝对路径：旧 profile 为普通文件，活动 profile 为目录。除根目录外不带尾部分隔符，不含待清理的 `.`、`..` 或重复分隔符；避免探针清理后检查的目标与 worker 收到的路径不同。Windows 允许统一使用正斜杠作为分隔符。拒绝目标符号链接；Windows 同时拒绝查询目录及目标的 reparse point。Linux 使用不跟随最终链接且不阻塞 FIFO 的打开方式。Windows 句柄请求属性读取及文件数据读取或目录列表权限，使其参与共享检查，但探针不读取账本正文；使用 `OPEN_EXISTING` 和拒绝跟随 reparse 的打开方式，共享读写而不共享删除，以兼容真实 worker 字节锁并阻止普通删除/改名。缺失路径不创建，查询目录缺少权限则失败。

身份检查以持有句柄的真实文件 ID 为锚，并与新取得的路径状态比较。Linux 使用原 fd 采样；Windows 系统 API 接受目录路径，因此同时保留并核对查询目录。前后检查检测普通的持久替换，不承诺在任意恶意主机上形成原子命名空间快照。父目录、操作系统和文件系统仍在信任边界内。

worker 在原重放入口返回前已经关闭，所以这不是同一时刻的账本与磁盘快照，也不保证采样时仍持有 worker 独占锁。可用空间可能立即被其他进程占用；`space_reserved:false` 不允许被解读为以后 write/fsync 必然成功。上下文在系统调用前后检查，同步内核查询本身不保证即时可取消。

没有写入探测文件、预分配、fsync 实验或钱包数据读取。工具不访问区块链 RPC；用户路径是否位于网络挂载由所在系统决定。读取可能更新文件访问时间，不承诺所有文件系统元数据完全不变。

## 验证范围

原生 Windows、Linux 的 operator 场景复用真实 Rust worker、Orchard 付款、活动四节点重启和继续付款，检查实际 CLI 的两种 profile、检查点、锁、错误 pin、损坏与源字节保持。单位测试覆盖阈值、换算溢出、路径和句柄失败。原有格式、Go 单测、静态检查、支持平台的 race 与有界 fuzz 门槛继续执行；以准确候选的实际 CI 和非作者审核记录作为验收依据。

将阈值设为 uint64 最大值，是用真实 OS 样本验证告警分支；它没有造成磁盘满，不能计为 ENOSPC、断电、写入持久性或 Windows 目录持久化验证。P2 整体仍在开发中，状态快照导入、迁移、完整容量压力和长期多机运行仍未交付。

系统语义参考：[Microsoft GetDiskFreeSpaceExW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdiskfreespaceexw)、[Linux statfs](https://man7.org/linux/man-pages/man2/statfs.2.html)、[glibc statfs 到 statvfs 的映射](https://github.com/bminor/glibc/blob/glibc-2.40/sysdeps/unix/sysv/linux/internal_statvfs.c)、[固定 x/sys v0.30.0 源码](https://github.com/golang/sys/tree/v0.30.0)。
