# 钱包备份版本目录 v1

这是可直接使用的本地 NO-FUNDS 工具模块，不是测试专用入口。它管理原 `WalletStore` 的加密钱包副本，
提供初始化、版本列表、创建、认证核验和恢复五项操作。没有新密码学、网络访问、广播、付款签名、
自动挑选最新版本、删除旧版本或覆盖源文件。模块实现不代表整体 P2 或生产安全审计完成。

## 1. 使用前提与信任来源

需要 Python 3.10+、原 `zevune-wallet-local` 本机可执行文件，以及该文件**独立核对过的 SHA-256**。
新 v3 本地程序包同时包含三个 Python 文件（`zevune_wallet.py`、`wallet_backup.py`、
`wallet_backup_backend.py`）和本指南；也可直接从可信源码的 `scripts/` 运行。旧 v2 包仍可核验，
但不包含新工具，不能只改清单版本号当作升级。详细程序包校验见仓库 `docs/BUILD_INTEGRITY.zh-CN.md`。

先用可信源码中的核验器和独立取得的清单摘要验证程序包，再从这份已核验清单取得后端文件摘要。
不能从未经核验的下载自行计算摘要就宣称其来源可信。本工具再次固定后端摘要、限定请求操作并
检查运行前后文件身份；它不提供代码签名、不验证编译器安全，也不能抵御恶意本机在检查后替换程序。

创建、核验、恢复都要求**独立保存的精确末端回执**：原控制台返回的 `receipt`，由144个小写十六进制
字符组成，编码钱包标识、保存代数与日志摘要。它不是密码，但会关联同一钱包及其版本，应按私有
操作元数据保存。密码只经不回显输入和后端 stdin 传递，不支持密码命令行参数或密码环境变量。
Python/系统内存副本不保证安全擦除，强杀也不执行清零。

这个回执必须来自你此前信任的操作结果或独立记录。**不能仅从待验证目录的列表或清单取回执，
再把同一目录的内容称为可信。** 文件摘要和目录版本 ID 不替代钱包 AEAD 认证。所有认证操作真正
调用原 Rust 后端读取、解密、校验钱包，然后核对返回回执及原文件字节。

## 2. 五个命令

从源码仓库运行时使用 `scripts/wallet_backup.py`；解压程序包后在包目录运行时去掉 `scripts/`。
`--no-real-funds` 是每个命令都必须提供的显式实验边界，不会改变节点是否允许真实资金的状态。
所有父目录须事先存在，目录和文件名由你明确指定；工具不会递归创建未知父目录。

### 初始化和列表

```text
python scripts/wallet_backup.py --no-real-funds init <新备份目录>
python scripts/wallet_backup.py --no-real-funds list <已有备份目录>
```

初始化只接受不存在的目标。每个目录最多256个版本项，包括未完成项；这是本地目录管理的有界枚举
限制，不提高钱包256条保存记录的协议边界。满目录拒绝继续写入，可明确创建另一个目录，工具不
自行删除、整理或合并旧副本。单份钱包仍受原大小上限约束；工具不是磁盘空间配额或监控服务。

列表不需要密码、不启动后端，只报告目录中的版本 ID、可解析清单的保存代数/回执和
`metadata_complete`。这一字段仅指两项命名和清单结构完整，不验证钱包文件内容；
`authenticated` 始终为 false，`latest_not_inferred` 始终为 true。缺少清单或结构损坏的项保留并
标作未完成。列表按固定版本 ID 排序，不是时间顺序，也不能证明外部没有更新的副本。

### 创建、认证核验与恢复

```text
python scripts/wallet_backup.py --no-real-funds create <备份目录> <源钱包文件> --pin <独立精确回执> --backend <可信钱包后端路径> --backend-sha256 <可信后端SHA256>
python scripts/wallet_backup.py --no-real-funds verify <备份目录> --pin <独立精确回执> --backend <可信钱包后端路径> --backend-sha256 <可信后端SHA256>
python scripts/wallet_backup.py --no-real-funds restore <备份目录> <不存在的恢复目标> --pin <独立精确回执> --backend <可信钱包后端路径> --backend-sha256 <可信后端SHA256>
```

例如在 Windows PowerShell 中，先从独立可信记录设置 `$pin` 和 `$backendHash`，然后运行：

```powershell
python .\wallet_backup.py --no-real-funds init C:\ZevuneBackups\catalog-01
python .\wallet_backup.py --no-real-funds create C:\ZevuneBackups\catalog-01 C:\ZevuneData\wallet.journal --pin $pin --backend .\zevune-wallet-local.exe --backend-sha256 $backendHash
python .\wallet_backup.py --no-real-funds list C:\ZevuneBackups\catalog-01
python .\wallet_backup.py --no-real-funds verify C:\ZevuneBackups\catalog-01 --pin $pin --backend .\zevune-wallet-local.exe --backend-sha256 $backendHash
python .\wallet_backup.py --no-real-funds restore C:\ZevuneBackups\catalog-01 C:\ZevuneRecovery\wallet-restored.journal --pin $pin --backend .\zevune-wallet-local.exe --backend-sha256 $backendHash
```

示例父目录 `C:\ZevuneBackups`、`C:\ZevuneData`、`C:\ZevuneRecovery` 必须先由用户创建并限制权限。
不要在共享或不可信目录执行。恢复前必须键入 `RESTORE` 确认；取消、密码错误、文件存在或回执
不匹配时返回失败。Windows 原目录 ACL 沿用父目录继承，工具没有实现全面 ACL 审核/修正。
Linux/macOS 的目录管理层要求当前用户私有的0700类目录，文件创建为0600；本模块原生端到端
验收目标是 Linux 和 Windows，其他平台不应以纯 Python 测试代替实际后端验收。

## 3. 创建与恢复的完整语义

创建先检查公开帧结构和**精确 tip**，然后由真实后端认证源。原 Rust API 允许回执作为祖先下限；
目录层有意收紧为精确末端，防止用户以旧回执备份一个已继续保存的钱包而误标版本。源有任何
后续写入或身份变化，操作拒绝，不偷偷选新回执。目录源钱包必须在目录外，建议先停止并发钱包操作。

每个版本 ID 是带域标记的回执摘要。版本目录只创建一次，重复备份同一回执拒绝，而不是覆盖。
调用原后端完成加密字节复制后，再认证目标，比较源/目标摘要与长度，重查源及目录身份，最后
才以 create-only 方式写入清单。原源钱包不会被修改、删除或停用。这些顺序及检查不是恶意目录
竞态沙箱；仍依赖可信父目录、内核和合作进程。

恢复由外部回执计算明确的版本 ID，不信任清单指向的任意路径。源副本经认证与身份检查后，
用原后端只创建一个新文件，并再次认证目标及比对完整加密字节。现有目标（包括链接）或目录内
目标均拒绝。不自动覆盖当前钱包、不切换应用配置、不改变付款状态、不撤销其他副本的花费能力。

**所有成功核验/恢复都只证明本地存储可认证，输出明确 `requires_rescan:true`、`not_synced`。**
它们不查询账本、不保证这个回执是最新版本、不证明付款未广播或已经确认。恢复后必须用原钱包
对独立验证过的本地账本重新扫描并核对待发送付款；应导出原已保存的相同付款，而非自动重签。
备份与活动钱包不要同时用于花费。整理生成新钱包日志标识后，新回执成为另一独立版本；旧目录
条目保持原身份，不声称新旧日志天然构成可信回滚关系。

## 4. 文件、锁与失败处理

目录固定保存 `CATALOG.json` 和 `.lock`；每个64位小写十六进制版本目录仅含 `wallet.journal`
与 `MANIFEST.json`。严格校验拒绝未知文件、重复JSON键、非规范编码、额外字段、错误类型、超限、
符号链接、Windows reparse point、钱包文件硬链接以及身份变化。目录清单不储存密码或明文金额。

所有目录操作持有操作系统的非阻塞独占锁：Unix `flock` 或 Windows `msvcrt.locking`。
另一个进程正操作同一目录时失败而非等待；进程退出会由操作系统释放锁，`.lock` 文件永久保留，
不能以“看起来旧了”为理由删锁。这个锁只协调本工具，不控制原钱包控制台或外部手工复制行为。
每个后端调用也保留原 WalletStore 独占锁语义；目录工具不绕过它。

每次后端调用最长300秒，输出流分别有4096/1024字节上限；超时、异常退出、输出越界、额外stderr、
错误响应或程序身份变化都返回固定失败信息，不打印密码、后端原始输出或私有路径。可信后端
不创建子进程；恶意已获批准的可执行文件、逃逸子进程及操作系统被攻破不在保护承诺内。

**失败保留部分文件和目录，不自动删除、不重试，也不把发出 kill 当作完成持久化核验。**
若复制已完成但响应丢失，可能留下完整钱包但没有清单；若目标创建中断，也可能只有部分记录。
列表可显示未完成项，但不会自动补写清单或接管它。停止活动操作后保留证据，按独立回执使用原
钱包诊断/恢复流程核验；必要时选择新的目录和新目标。不得仅依据超时解除预留或恢复更旧的状态。

文件执行原同步写入，Unix另同步目录；Windows不宣称等同Unix目录同步保证。此模块不新增物理
断电、恶意存储、真实空间耗尽、远程备份、自动保留策略或持续在线故障转移的保证。

## 5. 交付与验收

模块包括五命令实现、受限后端传输、目录/路径/回执/并发锁/拒绝路径单测，以及使用真实 Rust
钱包的端到端测试。真实测试创建三代备份，恢复非零付款的相同待发送签名字节和余额预留，验证
旧回执、错误密码、覆盖目标、目录内恢复和损坏副本均拒绝；只用随机无价值资产，不广播。
单测中的合成公开帧仅检查拒绝和目录行为，不能充当加密或授权验证。

```text
python -m unittest discover -s scripts/tests -p test_wallet_backup.py -v
python scripts/check_wallet_backup_backend.py <已构建的可信钱包后端路径>
```

本模块的固定二进制和操作系统依赖语义参见官方 Python
[fcntl.flock](https://docs.python.org/3/library/fcntl.html#fcntl.flock)、
[msvcrt.locking](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking) 和 Rust
[File::sync_all](https://doc.rust-lang.org/std/fs/struct.File.html#method.sync_all)。
它们不是对本项目安全性的背书。准确候选、独立非作者审查、各平台真实执行和未测范围以模块 PR
验收记录为准。`real_funds_allowed`、生产存储就绪与外部审计状态不因模块完成而改变。
