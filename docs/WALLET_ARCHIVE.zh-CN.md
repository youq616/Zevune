# 加密钱包备份离线迁移模块 v1

`wallet_archive.py` 提供 `export`、`inspect`、`import` 三个命令，与既有
[备份目录模块](WALLET_BACKUP_CATALOG.zh-CN.md) 的创建、核验和恢复配合。
它把一个明确版本装入单个 `.zvbackup` 文件，供用户自行离线复制到另一台机器；工具不联网、
不上传文件、不广播、不重新签名、不选择“最新版本”，也不切换活动钱包。
准确提交的审核、原生验收和打包结果以本模块 PR 记录为准，本文不是预先验收或资金批准。

## 信任与安全边界

必须分别保留：来自可信来源的完整钱包回执（144个小写十六进制字符）、归档 SHA256，
以及实际使用的 Rust 后端可执行文件 SHA256。不要从同一个不可信归档旁的文本文件自动读取
这些值。回执是精确末端约束，不允许用旧祖先回执把更新后的文件当成旧备份；也不能仅凭回执
推断它是全局最新备份。SHA256 不是数字签名或代码签名。

归档原样保留现有 `ZVWJNL01` 加密钱包和已有密码，没有新增密码学算法、额外加密或换密码。
公开清单暴露钱包回执、文件摘要、保存代数和字节数；同一版本导出结果相同，可被关联。
`inspect` 只验证独立摘要、固定容器、公开钱包链及精确回执，始终返回 `authenticated:false`；
它不验证密码、AEAD、余额或共识最终性。导出和导入必须使用已固定摘要的真实 Rust 后端
进行原有 op9 认证，而不是把公开 hash 当作认证。

所有操作仍限 NO-FUNDS 实验。可信本地操作系统、规范父目录和批准的后端是前提；不承诺
恶意文件系统或已被攻破的主机安全。Unix 新文件0600、新版本目录0700；Windows继承父ACL，
目录同步沿用现有平台实现。Python密码内存不保证擦除；密码只从隐藏提示读入并经stdin交给后端，
不接受密码命令行参数或环境变量。没有物理断电、Windows实际磁盘写满或长期运行的新保证。

## 完整操作流程（Windows PowerShell 示例）

先从可信源码运行程序包校验器，核对独立取得的程序包清单摘要，再取得其中后端摘要。
下列 `$Pin`、`$BackendSha`、`$ArchiveSha` 为用户独立保留的值，不是从待验收归档推导的信任源。
Linux 使用相同 Python 命令，后端文件名去掉 `.exe`，使用自己的绝对路径。

### 1. 导出已有的明确备份版本

源目录应已由 `wallet_backup.py init/create` 建立。目标文件必须不存在，其父目录须已存在，
且目标必须在备份目录之外。导出先认证源钱包、核对源前后未变，再创建归档并回读校验。

```powershell
python .\wallet_archive.py --no-real-funds export C:\Zevune\backups C:\Offline\alice.zvbackup --pin $Pin --backend .\zevune-wallet-local.exe --backend-sha256 $BackendSha
```

隐藏提示输入原钱包密码。成功结果为 `archive_exported_not_synced`，包含
`archive_sha256`、`archive_bytes`、回执和版本ID；将摘要另行保留，通过独立可信渠道交接。
原钱包、备份目录和原有文件均保留。工具不自行复制到网络或外部服务。

### 2. 在目标机器只读检查

```powershell
python .\wallet_archive.py --no-real-funds inspect C:\Offline\alice.zvbackup --pin $Pin --archive-sha256 $ArchiveSha
```

此操作不请求密码、不运行后端、不创建目录或临时解包文件。成功返回
`archive_integrity_only`，其 `authenticated` 必须为 false。

### 3. 导入新的备份目录版本

```powershell
python .\wallet_backup.py --no-real-funds init C:\Zevune\received
python .\wallet_archive.py --no-real-funds import C:\Zevune\received C:\Offline\alice.zvbackup --pin $Pin --archive-sha256 $ArchiveSha --backend .\zevune-wallet-local.exe --backend-sha256 $BackendSha
```

输入 `IMPORT` 明确确认，再输入隐藏密码。目标目录中该版本必须不存在，总版本项不超过
原有256项（未完成项也占用额度）。导入在已有目录排他锁下验证输入，创建新加密钱包文件，
调用原Rust后端认证，复查输入和目标未变，最后才写规范清单并同步。成功返回
`archive_imported_not_synced`、`authenticated:true`、`active_wallet_replaced:false`。

### 4. 明确恢复到另一个新钱包文件

```powershell
python .\wallet_backup.py --no-real-funds verify C:\Zevune\received --pin $Pin --backend .\zevune-wallet-local.exe --backend-sha256 $BackendSha
python .\wallet_backup.py --no-real-funds restore C:\Zevune\received C:\Zevune\restored.wallet --pin $Pin --backend .\zevune-wallet-local.exe --backend-sha256 $BackendSha
```

按原恢复命令输入 `RESTORE`。恢复后必须扫描可信历史并核对待发送付款状态，不能因为导入成功
就解除余额预留、生成替代付款或从多个副本并行支出。归档中的已有待发送签名字节和预留原样保留；
导入本身没有签名、支付、广播或活动钱包覆盖能力。

## 故障处理合同

错误摘要、错误精确回执、截断、尾随数据、未知版本、越界长度、未知/重复/非规范清单字段、
链接或非普通源文件都在导入写入前被拒绝。归档路径不能位于目标备份目录内。重复版本、目录已满、
锁冲突或目标文件已存在都不覆盖、不静默跳过。

导入需要文件路径供原Rust认证，因此错误密码、后端错误或中途写入错误可能留下**没有有效清单的
不完整版本目录**。不会自动删除、补写清单、回滚或覆盖重试；`wallet_backup.py list` 会把它标为
`metadata_complete:false`。保留归档、独立摘要和回执，检查错误后使用新的空目录进行明确操作。

失败也可能发生在完整文件/清单已经写出以后，故“返回失败”不等于“没有输出”。必须明确重新核验，
不能猜测磁盘结果。源归档和原目录均不自动清理。完整的清单也不使只读列表获得密码认证属性。

## 可移植文件格式：无路径、无压缩、无执行内容

所有整数使用固定大端标准大小，不使用本机结构体填充：

| 区域 | 字节 | 内容 |
|---|---:|---|
| Magic | 8 | ASCII `ZVWBPK01` |
| 清单长度 | 4 | 无符号大端整数，1至4096 |
| 加密钱包长度 | 4 | 原有72字节头加1至256条32948字节记录 |
| 清单 | 指定长度 | 既有`zevune-wallet-backup-1`的精确规范JSON和末尾LF |
| 加密钱包 | 指定长度 | 原`ZVWJNL01`完整字节，不重加密 |

总长度必须精确为16+清单长度+钱包长度，最大为16+4096+8434760字节。不允许额外尾部、拼接归档、
压缩数据、目录列表、文件名、相对路径、软硬链接、扩展对象或任意文件解包。解析器仅按既定布局
读取一个有界密文，按独立回执与钱包公开摘要重建唯一清单逐字节比较，不解释不可信JSON对象。
元数据和密码认证仍是不同步骤。

直接运行两个备份CLI时禁用本地模块字节码缓存，避免在已核验程序包中生成`__pycache__`；
不用用户额外设置`-B`或环境变量。作为库导入时不修改宿主解释器的缓存策略。

Python `struct` 的 `>` 使用标准大端大小且无隐式填充，依据官方文档：
https://docs.python.org/3/library/struct.html 。这只是编码依据，不是项目安全认证。

## 测试和交付

本模块包括格式/路径/只读/拒绝回归、与原目录的共同纯字节验证、实际Git提交身份校验、
真实后端导出→导入→恢复→原pending字节及预留一致性验证。真实测试另验证：错误密码只留下
未完成项，以及重算全部公开摘要的密文篡改仍被Rust AEAD拒绝。合成帧测试不当作真实授权。

v4本地程序包增加 `wallet_archive.py` 和本指南，为10个payload加1份manifest；新校验器继续按
精确旧合同支持v2（5payload）与v3（8payload），不把旧包自动升级为新格式。
`.zvbackup` 被Git忽略，测试钱包和归档不上传为CI附件。专用双平台CI固定准确审阅head与tree，
重新编译真实Rust后端，不沿用其他候选的通过结论。
