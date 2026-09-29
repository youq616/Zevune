# 离线查询任务审计报告 v1

本模块补齐 C26 任务文件的留档和离线复核，不重复执行查询，也不是新的审计认证机构或付款证明。
报告保存已固定任务的完整公开内容、摘要、字节数、ID数量和检查点高度，支持报告独立校验及连同
当前任务复核。原 C26/C27 CLI、桌面、查询核心、密码学与账本都不修改，始终 NO-FUNDS。

## 四个命令

可信 Python 3.10+；不需要 Git、Tk、Rust、钱包密码或原生程序。独立包将下面的 scripts 换为 runtime。
在 Windows PowerShell 中，路径必须绝对，任务摘要必须来自独立保存的创建回执或可信交接渠道。

```powershell
python .\scripts\ledger_query_audit.py --no-real-funds inspect --request 'C:\ZevuneTasks\query.json' --request-sha256 '<独立任务摘要>'
python .\scripts\ledger_query_audit.py --no-real-funds export --request 'C:\ZevuneTasks\query.json' --request-sha256 '<独立任务摘要>' --destination 'C:\ZevuneAudits\query-audit.json'
python .\scripts\ledger_query_audit.py --no-real-funds verify --audit 'C:\ZevuneAudits\query-audit.json' --audit-sha256 '<独立报告摘要>'
python .\scripts\ledger_query_audit.py --no-real-funds recheck --audit 'C:\ZevuneAudits\query-audit.json' --audit-sha256 '<独立报告摘要>' --request 'C:\ZevuneTasks\query.json' --request-sha256 '<独立任务摘要>'
```

inspect 只读当前任务，输出可复现的报告和 audit_sha256，不写文件。export 只创建全新的报告文件，
即使目标是空文件也拒绝覆盖；父目录须已存在，源和目标不能相同。保存成功回执中的 audit_sha256，
通过独立渠道交接。不能从收到的报告或任务自算摘要并把它当成独立可信依据。

verify 只读取报告及其内嵌的任务内容。它明确输出 source_file_rechecked=false；原任务已经删除，
仍可能通过报告核验，不能因此声称原文件仍然存在或没有改变。recheck 需要报告和任务两个独立摘要，
重新读取当前任务并核对全部内容；成功才输出 source_file_rechecked=true。这只是该次读取期间的
观察，不意味着从导出至今文件从未变化。移到另一台电脑、或开始复核前创建的同内容副本可以通过；
复核期间的同内容换文件会按身份变化拒绝。报告不绑定导出机器的文件标识。

## 报告合同

固定格式 zevune-ledger-query-audit-1，上限16 KiB，输出JSON上限32 KiB。内嵌任务仍使用原8 KiB
上限、原固定profile、1—32个互异有序交易ID；不排序、不截短、不改写原任务。报告摘要先于JSON解析
核验；严格拒绝重复键、额外字段、非有限数值和非规范编码。每个汇总字段都由内嵌原任务重新计算，
精确规范字节比较也拒绝用数字0替换false、用浮点数替换整数。

报告不存本机路径、机器名、文件标识或时间戳，同一任务和独立摘要产生相同字节。报告包含完整公开
交易清单和检查点，可能关联交易活动；应保护文件、屏幕、终端与备份。不得把内容摘要叫作隐私保护。

query_executed、signature_verified、backend_verified、ledger_replayed、retry_authorized 和
real_funds_allowed 固定为false。这里的 query_executed=false 表示本审计操作没有执行查询，不是
证明该任务从未被别人运行。报告不是执行事件日志、带签名认证、操作者身份证明或产生时间证明。
程序摘要只是任务内的数据；本模块不打开后端文件，不验证其当前存在性，也不读取账本、查询网络、
认证钱包或改变任何执行权限。核验通过不证明任务内指定的账本真实存在或可通过原生重放。

## 文件操作与失败

沿用原普通文件、单硬链接、路径/句柄身份和父目录链检查，拒绝符号链接、reparse路径、管道及超限
输入。export 使用原仅创建写入及文件fsync，回读校验报告，再检查源任务和报告的身份/字节，防止
将已变化的内容报告为成功。任务只读；只有明确 export 才写一份新报告。

任何失败保留已经创建的部分或完整目标，不删除、不续写、不自动重试。丢失确认后留下完整报告，
另一次 verify 可能通过；这不能倒推之前的 export 已成功。没有目录fsync、物理断电、完整Windows
ACL、全程锁、跨文件原子快照或恶意内核/文件系统竞态保证。需可信解释器、主机和父目录，并停止
外部写入。本地IO可能阻塞；没有新增硬实时预算，也不修改原查询核心的300秒预算。

正常输出UTF-8 JSON；成功0，失败1，参数错误64，中断130。输出失败可能留下前缀，只有完整结果和
退出0同时满足才可使用。错误仅固定提示，不输出路径或底层异常。没有执行命令或持久后台服务。

## 测试与独立验收

真实任务/报告文件测试覆盖篡改、严格字段、复制与缺失源、文件替换、错误摘要、短写/fsync失败及
确认丢失。纯内容测试不是密码学接受替身。离线集成驱动在真实Python子进程中开启审计钩子，禁止
启动其他进程、网络操作和账本文件访问；测试四种实际CLI、32ID、源缺失、已存在目标和修改拒绝，
任何尝试被捕获并吞掉也会导致测试失败。钩子是测试防线，不宣称给不可信程序提供安全沙箱。

新Windows/Linux工作流执行原任务测试和本模块离线流程；按设计不构建或运行Rust后端。其它模块的
原生CI与本模块结果分开记录，不把“无需原生调用”写成“已通过原生授权”。准确版本非作者复审和
双平台结果完成前不标记验收。原v2-v9、固定10payload清单及全部旧工作流不改变；P2/P4/P8整体和
历史问题不会因这个模块自动完成，main不因单模块提交自动推进。

实现参考：Python官方 json.object_pairs_hook 与 os.open/O_EXCL、fsync 文档；实际IO规则沿用原
ledger_query_request.py 和 wallet_backup.py。SHA256完整性校验不替代独立安全审计。
