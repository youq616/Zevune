# 对账结果账本绑定复核 v1

本模块是原文件查看器的独立加强入口。它不是新的恢复器或验证算法：每次成功都必须调用独立批准的
原 `zevune-pool-recovery`，执行一次 `verify-active` 完整重放。原轻量查看器的行为和标志不变。
始终 NO-FUNDS；不将本模块完成视为 P1/P4 全阶段、独立审计或主网验收。

## 输入与使用

需要原恢复结果目录、独立报告 SHA256、独立 ZVARCP01 检查点、独立创世文件 SHA256（LAB2签名域），
以及与该检查点精确对应的已停止写入的活动账本/归档目录、独立核验过的恢复程序路径和程序 SHA256。
所有路径为绝对路径，不接受链接、reparse 父目录、额外目录项或同目录互相嵌套的证据和账本。
不从收到的报告/程序自行计算摘要并赋予信任，不下载程序，不自动选择“最新”检查点。

```powershell
python .\scripts\reconciliation_ledger_check.py --no-real-funds --directory 'C:\Zevune\result' --report-sha256 '<独立64位报告摘要>' --checkpoint '<独立256位检查点>' --genesis-sha256 '<独立64位签名域>' --journal 'C:\Zevune\stopped-archive' --backend 'C:\Approved\zevune-pool-recovery.exe' --backend-sha256 '<独立64位程序摘要>'
```

默认输出 UTF-8 JSON；追加 `--text` 输出中文解释。需 Python 3.10+ 和原恢复程序，不需 Tk、钱包密码
或本地 Git。退出码0才代表本次成功；错误1、参数64、用户中断130。失败只有固定提示，无成功JSON，
不回显路径、密钥或原始交易。它不自动导出文件；操作者的shell重定向是独立行为。

这是显式执行的 CLI 模块，不会因打开原桌面查看器而后台重放，也没有自动刷新/重试。大型账本重放
可能耗时，整个检查共享一次300秒预算（含读入/重放/末尾校验）；不允许用参数放大或重新获得预算。
系统IO及原进程/读取线程收尾可能超过墙钟时间；超期不能报成功，但并非硬实时终止保证。

## 比原文件查看器多确认了什么

先按原C13规则核验报告、公开钱包链、pending文件及外部pin。按原 `archive_snapshot` 有界指纹化
账本。活动账本 `genesis` 文件的原头为 ZVOPOL03：8:40为固定实验网络，40:72为签名域，72:76为初始
承诺数量。它不是 ZVTGEN03 创世文件，也不是检查点8:40中的池创世承诺。

预检查只比较该原头中的签名域与独立输入，严格保持原长度/数量范围；不重新实现Orchard验证。之后
原生 `verify-active` 在原共享锁和全量授权验证规则下核对独立检查点、完整物理布局、全部区块和最终
状态。只有其固定完整回执匹配，且前后证据/账本字节、身份及精确文件集合一致，才返回：

- `ledger_replayed=true`：指定历史账本通过本次原生完整重放。
- `checkpoint_domain_relation_verified=true`：通过该精确账本，检查点所绑定的池状态与报告签名域匹配。

这两个新true标志只出现在本模块的成功结果。轻量文件查看器继续保留false；历史成功不作为本次许可。
代码仅允许原 `verify-active` 命令，继承transport上的恢复、备份、增量命令或其他路径均被本模块拒绝。

## 仍不能据此推出的结论

保留 `wallet_authenticated=false`、`transaction_authorization_verified=false`（指待发送文件）、
`pending_transaction_inclusion_verified=false`、`finality_verified=false`、`retry_authorized=false`。
广播与结算仍为unknown，当前链高度仍为null。即使账本通过重放，也没有在本模块检索待发送交易的
纳入证明，更不能据无pending文件宣称已付款或清除预留。

`genesis_manifest_validated=false`：本模块不读取完整创世文件、解析其分配或验证原始发行；原生账本
验证从独立pin约束的初始承诺开始，不替代创世文件全部语义验证。`original_recovery_success_verified=false`：
有效的现存文件不能证明过去那一次恢复调用成功退出。完整性、账本授权与结算三个层次严格分开。

## 不变条件和测试边界

不认证或修改钱包，不扫描钱包、不签名、不广播、不清理预留，不创建/覆盖/删除输入文件，没有输出
目录、自动恢复、网络或shell接口。原后端、加密原语、存储/报告格式、限额、锁、旧工作流和v2-v9及
固定源码交付清单不变。新模块须从可信工具目录使用，不塞入旧固定清单目录。

前后指纹/元数据复查不能防御恶意内核、文件系统竞态、恢复原mtime的攻击或校验后变化。没有跨目录
全局锁、原子快照、Windows完整ACL或断电安全保证。停止所有写入并信任解释器、程序和父目录仍是前提。
标准输出含交易ID/回执，可能关联钱包；不包含原始交易、地址、金额、种子、密码或私钥。

单元检查只有公开预检查及拒绝路径，不伪造一次成功重放。专用原生驱动执行完整原恢复10场景并观察
pending/empty/included/expired四类真实结果；新增真实CLI、真实账本损坏拒绝、真实重放成功后文件改写
拒绝。修改仅在驱动自有无价值临时fixture内，结束还原/清理；不添加生产故障开关。双平台工作流保持
固定Rust工具链、锁定依赖、20分钟作业和600秒原生驱动监督。独立非作者审核未通过前不标记验收、不合main。

依据：`integration/orchard/src/pool/replay.rs`、`pool/recovery/active.rs` 及原
`ledger_recovery_backend.py`，不是另造协议或状态验证器。
