# 完整基线与多增量包备份交付 v1

模块入口 `ledger_backup.py`，配套已实现的 `ledger_restore.py`。本模块把一组已停止写入、各有独立
检查点的公开账本归档，制作为一个完整基线加最多八个增量包的交付目录。不含钱包、验证者签名状态、
共识 WAL、节点密钥或网络配置。所有操作仍为 NO-FUNDS，不能恢复或激活完整验证者。

## 1. 独立信任输入

使用 1..9 个规范绝对目录及各自独立保存的 128 字节 ZVARCP01 检查点（256个小写十六进制字符）。
顺序必须同创世、同头部长度、高度及逻辑长度严格增加，段数不减少。不从归档或清单自行推断可信
检查点，不挑选所谓“最新”，不把 app_hash 当作最终性。不接受旧单文件钱包/账本或状态快照格式。

各输入是已有的完整历史视图，不是同一活动目录附带多个旧检查点；请先按原归档流程保存明确版本。
调用者必须停止所有相关写入并保留原件。原 Rust 后端有逐操作锁，但 Python 编排没有全流程全局锁；
身份/字节重查可拒绝观测到的变化，不构成恶意本机竞态防护。使用可信OS、规范父目录及独立核验摘要
的 `zevune-pool-recovery` 后端。

## 2. 创建

Windows PowerShell 示例，从程序包目录运行；源码方式在脚本前加 `scripts\`。各变量来自独立可信记录，
不是从待检查的 BACKUP.json 读取。Linux 使用对应绝对路径及不带 `.exe` 的后端。

```powershell
python .\ledger_backup.py --no-real-funds create D:\LedgerDelivery\set-001 --source D:\Archives\h0 $P0 --source D:\Archives\h1 $P1 --source D:\Archives\h2 $P2 --backend .\zevune-pool-recovery.exe --backend-sha256 $RecoverySha --reserve-bytes 67108864
```

目标必须不存在且其父目录已存在；输入 `BACKUP-CHAIN` 确认后执行。只有一个 source 时也为完整支持的
基线备份。最多八个增量，不覆盖、复用空目录、续写、删除旧版本、自动重试或递归创建父目录。

实际处理顺序：

1. 有界捕获全部源文件身份与摘要；原 Rust `verify-active` 完整重放每个源。
2. 原 `plan-active-incremental` 核验每对相邻来源真正的字节前缀关系。两端各自有效但属于不同分叉仍拒绝。
3. 所有源和相邻关系均通过后，按全部目标文件同时占用量及显式 reserve 检查空间，重查来源，然后独占创建目录。
4. 原 `backup-active` 创建 `base`；原 `pack-active-incremental` 创建每个增量。随后再次调用原
   `verify-active-incremental`，使用独立前一完整来源验证新包，保留其完整字节指纹并在结束时复查。
5. 再次认证输出基线，核对源/输出字节及目录身份，最后创建规范 BACKUP.json，按原规则同步并回读。

不修改原生产Rust授权、完整重放、同步/锁、账本格式、1MiB段或其他容量边界。不会签名付款、广播或
导入不经验证的状态。输出固定为：

```text
set-001/
  base/                    # 完整原始genesis和连续journal段
  increment-01.zvaipk       # 原ZVAIPK01增量包；单基线时没有此文件
  increment-02.zvaipk
  BACKUP.json              # 规范索引，最多4096字节
```

BACKUP.json 的检查点来自调用者，文件名由固定序号决定。它仅记录基线布局摘要、包大小/摘要及固定
安全边界；不接受文件提供的任意路径或后端命令。摘要只是损坏检查，不替代原生密码学验证。

## 3. 只读检查不等于认证

```powershell
python .\ledger_backup.py --no-real-funds inspect D:\LedgerDelivery\set-001 --checkpoint $P0 --checkpoint $P1 --checkpoint $P2
```

inspect 不请求后端、不写文件、不执行原生重放，也不检查外部源是否仍保留；它用外部检查点及实际文件重建唯一规范清单并逐字节
比较，拒绝缺项、尾随/非规范清单、多余文件、错配的增量包头及摘要变化。成功明确返回
`replay_verified:false`、`inspection_is_authentication:false`。攻击者重算公开摘要的伪造不能靠此操作
排除，完整恢复必须使用下一节原恢复模块。create 的 `replay_verified:true` 仅表示该次真实原生操作
完成，不因写入清单而形成永久授权。复制或后来修改文件后必须重新验证。

## 4. 直接恢复与演练

备份目录生成的原始基线和增量包可直接输入原恢复模块，无需转换或解压：

```powershell
python .\ledger_restore.py --no-real-funds restore D:\Recovery\run-001 --base D:\LedgerDelivery\set-001\base --base-checkpoint $P0 --step D:\LedgerDelivery\set-001\increment-01.zvaipk $P1 --step D:\LedgerDelivery\set-001\increment-02.zvaipk $P2 --backend .\zevune-pool-recovery.exe --backend-sha256 $RecoverySha --reserve-bytes 67108864
python .\ledger_restore.py --no-real-funds verify D:\Recovery\run-001 --checkpoint $P0 --checkpoint $P1 --checkpoint $P2 --backend .\zevune-pool-recovery.exe --backend-sha256 $RecoverySha
```

恢复仍需明确 `RESTORE-CHAIN` 确认，保留各完整阶段且需为它们另行预算；备份的数据空间预算不是
恢复空间预算。恢复成功也保持 `snapshot_imported:false`、`finality_verified:false`、
`validator_ready:false`、`real_funds_allowed:false`。不是完整节点恢复或开放资金的批准。

## 5. 失败与资源边界

先验证全部来源和关系再创建输出，可提前拒绝可确定的坏输入。写入后失败仍可能留下部分或完整
基线、一个或多个包，甚至完整清单。原件和残留一律保留，不截断、删除、自动补清单或重试。
输出名已存在时，即使上次只创建了空目录也拒绝。未取得成功回执不能推断磁盘上未写入。

单一1800秒期限覆盖从入口开始的身份检查、文件读取、预算、原生调用和最终核验；复用的单命令300秒
预算包括后端摘要检查/启动，收尾使用原单次5秒退出及2秒读取线程窗口，不重新开始计时。无法抢占
阻塞的内核IO，超期返回时仍拒绝；这不是对任意系统调用的硬实时保证。输入指纹流式读取，不加载
整个1GiB账本到内存，清单/输出日志有界。

目标预算基于实际完整基线文件大小、原生计划计算的增量包长度、4KiB清单及显式保留量。Linux各文件
按分配单元取整，并包含两个新目录与各文件的inode需求；Windows沿用调用者可用空间及未知项语义。
不预留磁盘，不保证其他进程、元数据、COW、配额、ACL或设备错误不会让后续写入失败；没有减少同步。

## 6. 验证与交付

v9 包增加本脚本和本指南，为22个payload加manifest；v2-v8精确文件合同保持兼容。普通Python入口
在本地模块导入前禁写字节码，不要求用户传 `-B`。库导入不改变宿主策略。

专用原生测试重新构建原Rust后端和独立源码fixture，以真实Orchard付款形成两个增量，实际运行创建、
inspect、原恢复和恢复后真实付款/再次重放；检查源和所有包字节保持、分叉拒绝、单基线和确认拒绝。
丢失晚期包回复的受控测试先真正执行原生打包，再抛错，要求保留每个完整输出且无虚假完成清单。
该受控错误不是物理断电、进程强杀或真实ENOSPC。准确提交的审核/原生结果以本模块PR记录为准。

本模块不新增加密原语、钱包/签名接口或网络传输。AGENTS.md 提及的两个早期设计文件在本基线缺失，
适配依据是实际原生CLI、ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md、LEDGER_RESTORE.zh-CN.md及
现有NO-FUNDS规则，不以缺失文件作已读证据。Issue #23、完整P2、外部专业安全审计仍未完成。
