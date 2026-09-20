# P2：首次付款保存遇到真实空间耗尽

基线：PR #25 合入 `444113ac219f997a6a20c443d5d8d62741f6e7c5`。
本文定义新增实验及边界，不是预先通过验收的声明；准确候选、独立审核和原生结果以本阶段 PR 为准。

## 问题与范围

已有钱包 ENOSPC 场景分别覆盖已付款后的同步追加和整理目标写满。本场景补充首次付款的
`WalletStore::prepare_payment_to`：真正生成 Orchard 证明、签名及内存预留后，保存加密记录时遇到
操作系统 ENOSPC。没有生产故障开关、接受任意证明的替代实现、广播或自动重试。

测试使用独立 `wallet_prepare_enospc` 集成目标和 `wallet_prepare` 固定 suite；原 active、wallet
各两项测试及各自预算不变。仍由普通 runner 编译，原 root watchdog 和新 mount/PID namespace
监督固定 8 MiB / 256 inode / 4 KiB 页的 Linux tmpfs，降权后执行测试和 strace。只对
`source/wallet.journal` 追踪失败写系统调用，禁止解码写缓冲、注入 errno 或上传原始输出。
填充仅发生在这个明确验证过的临时文件系统，不能指向普通宿主目录。

## 状态与独立证据

钱包创建、按真实创世历史同步后为 generation 2：没有 pending/outbox，可用额等于全部测试资产。
在故障之前，将完整加密文件和独立 72 字节回执保存在另一文件系统。旧文件长度为
`72 + 2 × 32948 = 65968` 字节。填满 tmpfs 后首次付款保存必须返回 `StoreError::Io`，不返回
任何 `Payment`；故障实例的 view、receipt、status、pending、sync、preflight、prepare、backup、
compaction 接口均拒绝，不能通过另一个入口提取未完成持久化的签名交易。

真实源文件的原前缀必须逐字节保持；同一 dev/inode 的尾部只能增长到 69632 字节，留下 3664
字节不完整第三条记录。记录公开前缀必须是 generation 3 及原回执摘要。损坏文件按有/无独立 pin
重开均拒绝，且不改变该文件。真实账本 Summary 与全部文件在错误前后完全一致。

不释放填充文件、不截断损坏钱包。显式从事前已固定 pin 的备份复制到另一个新文件，重开后必须先
扫描真实历史；恢复的是**原本空的 outbox**，不能声称恢复了失败时未返回的签名字节。只有此实验
明确观察到局部写入、没有返回和没有广播的前提下，才在新健康副本中显式准备一笔新付款。

这笔成功付款保存为 generation 3，保留其独立回执，关闭并重开钱包后核对完全相同的 pending
签名字节和预留。实际提交、完整重放、拒绝重复付款及旧历史回滚；确认后 generation 4、outbox
为空，余额与费用守恒。再次关闭/重开钱包和账本，状态仍相同。原坏文件、事前备份和 pin 始终保留。

收集器除验证专属完整 JSON schema、类型、固定长度和布尔断言，还独立检查目标 inode、原加密
前缀、三份真实 pin、备份 tip、恢复钱包的 generation 2/3 祖先及 generation 4 tip 的完整公开链。
普通摘要并非认证，真正 AEAD、授权和状态核对由原生测试完成。无精确 ignored 测试清单、无目标
写 ENOSPC 证据、无回执、无空间耗尽或未完成正常卸载，都不能通过。原清理不确定时保留控制目录。

## 验证与未覆盖边界

```text
python -m unittest discover -s scripts/tests -p test_wallet_prepare_enospc.py -v
python -m unittest discover -s scripts/tests -p test_active_enospc.py -v
```

新增 suite 使用与原 suite 相同的每项 180 秒、namespace 420 秒、root watchdog 430 秒和外层
450 秒限制；CI 原每作业 30 分钟和执行步骤 10 分钟不变。工作流显式编译新 test target，并验证
准确一项 ignored 测试被执行。原完整 Python/Rust/Go 回归仍执行，不以零项 Windows/Linux
默认 feature 发现冒充该 Linux 专用故障实验。

tmpfs 在内核缓存中，不构成物理磁盘、断电、Windows 空间耗尽或设备同步故障的证明。
本场景不覆盖写完或同步完却丢失回执的首次付款；此类不确定结果不能依据本实验自动恢复旧备份、
解除预留或重新签名。钱包 CLI 导出/备份复制真实写满、持续交易增长和快照状态导入仍需后续工作。
Issue #23 时延根因继续开放；不改变任何存储上限、生产同步/锁、依赖锁或 NO-FUNDS 边界。

上游语义：[Rust Write::write_all](https://doc.rust-lang.org/std/io/trait.Write.html#method.write_all)
允许错误前的部分写入；[Linux tmpfs](https://www.kernel.org/doc/html/latest/filesystems/tmpfs.html)
描述独立大小/inode 限制和非物理介质边界。它们不是对本项目安全或验收的背书。
