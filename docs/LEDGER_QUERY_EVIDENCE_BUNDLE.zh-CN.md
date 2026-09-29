# 离线证据交接包 v1

把已按独立摘要校验的任务和审计报告合成一个可移交文件，再按独立包摘要检查，并仅还原到全新目录。
这补齐现有任务/报告工具的跨目录交接路径；不执行查询、不备份钱包或账本、不自动导入桌面。
所有旧入口和格式保持不变，始终 NO-FUNDS。

## 包格式与边界

包是规范 UTF-8 JSON（`zevune-query-evidence-bundle-1`），不是 ZIP，也不是加密格式。
最多32个有序且不重复的条目，每条只有 kind、sha256、data_hex。data_hex 是原文件字节的无损小写
十六进制编码，**不是隐私保护**，其中包含完整公开查询 ID、检查点和程序摘要，必须保护整个交接包。
不保存原文件名、本机路径、URL、shell、程序字节、密码或自动执行指令。条目必须是原 task 或 report，
分别复用原解码器及8KiB/16KiB上限；报告内任务也由原规则重建，不能重算包摘要后伪造状态标志。

包最大1,100,000字节，编码约为原始文件字节的两倍，内存中处理整个有界包，不是流式大文件归档。
同一有序输入得到完全相同的包字节，无时钟、随机数、路径或平台依赖字段；改变顺序就改变包摘要。
重复(kind,sha256)条目拒绝，不静默去重；任务和对应报告虽任务内容相同，仍是两个不同证据文件。

包摘要由发送方独立渠道交接给接收方。不得从收到的包自行计算摘要，再把它当独立可信依据。
摘要不是签名、作者认证、执行确认或付款授权。包内各项摘要由独立包摘要约束，不代表另一次独立来源
认证。验证报告条目从不说明其原任务文件当前存在，也不验证报告所述过去调用曾成功结束。

## 四个显式命令

使用可信 Python 3.10+；无需 Git、Tk、Rust 或原生程序。所有路径必须绝对、无`..`且不超过原字节上限。
父目录需预先存在；文件和父级沿用链接/reparse检查，输入文件必须单硬链接。独立包中使用 runtime
代替 scripts。以下 PowerShell 命令中占位值必须换为各自独立保存的真实摘要。

```powershell
python .\scripts\ledger_query_evidence_bundle.py --no-real-funds pack --entry task 'C:\Tasks\query.json' '<独立任务SHA256>' --entry report 'C:\Tasks\audit.json' '<独立报告SHA256>' --destination 'C:\Handoff\evidence.json'
```

重复`--entry KIND PATH SHA256`指定1—32项。全部输入语法先校验，所有条目成功验证后才写目标。
目标必须不存在，包括已有空文件也拒绝覆盖。写后file fsync并回读，源文件在操作前后复验；所有失败
保留部分或完整目标，不删除、不续写、不自动重试。`selected_input_files_rechecked=true`只指本次
选择的输入文件，不把报告背后的原任务存在性视为已核验。

```powershell
python .\scripts\ledger_query_evidence_bundle.py --no-real-funds verify --bundle 'C:\Handoff\evidence.json' --bundle-sha256 '<独立包SHA256>'
```

先核对包摘要再解析严格JSON，拒绝重复字段、未知格式、额外路径字段、非字面false、非规范十六进制、
非法嵌套任务/报告和不完整清单。仅输出条目摘要、类型、生成文件名、任务内容摘要与ID计数，不输出
完整ID或本机路径。原件已删除也可验证，但`original_inputs_rechecked=false`；不能冒称读取原件。

```powershell
python .\scripts\ledger_query_evidence_bundle.py --no-real-funds unpack --bundle 'C:\Handoff\evidence.json' --bundle-sha256 '<独立包SHA256>' --destination 'C:\Handoff\restored-new'
```

整个包及每个条目全部通过后，才创建全新目录；已有空目录同样拒绝。文件名由程序固定生成：
`01-task.json`、`02-report.json`等，以包内顺序从01编号，不接受包提供的路径，避免路径穿越问题。
逐个独占创建、fsync并比对原字节，结束后检查完整目录清单、全部字节/文件身份、源包及父级身份。
任何错误都不能返回成功。故障可能留下新目录和已写入/部分文件，不回滚删除、不续装、不激活任何任务。
这是内容复制而非原文件身份/权限/时间戳恢复；POSIX新目录请求0700、文件0600，Windows不承诺完整ACL。

```powershell
python .\scripts\ledger_query_evidence_bundle.py --no-real-funds verify-directory --bundle 'C:\Handoff\evidence.json' --bundle-sha256 '<独立包SHA256>' --destination 'C:\Handoff\restored-new'
```

只读比对目录与整个独立固定包；缺少、多余、大小写错误、链接、改写或读取中换文件都拒绝。
成功只证明本次目录内容匹配，`unpack_call_success_verified=false`，不能推断原先某次失去回执的还原
操作已成功退出。完整故障残留可通过此命令另行核验；不允许因此跳过桌面的新确认或原生查询。

## 结果、故障与运行边界

所有命令成功0，检查/写入失败1，参数错误64，中断130；固定失败提示不回显底层路径或异常。
必须同时要求退出0和完整JSON；写入标准输出/flush失败可能留下前缀，不可据此前缀认定成功。
没有钱包或账本写入、native、网络、签名、广播、调度、重试许可；输出签名/账本/资金/审批复用标志为false。
“source”区分被选文件与报告对应的原任务；验证/还原不会去搜索原位置，包内也没有保存原位置。

使用前应停止所有外部写入，并信任主机、解释器及父目录。前后检查不是跨文件锁或原子快照，不对抗
恶意文件系统恢复时间戳，不保证返回后内容未变；没有目录fsync、物理断电或完整ACL保证。
同步IO可能阻塞，不借用或扩大原生核心300秒预算，也不承诺整个命令硬截止。部分写入测试是受控故障
注入，不冒称实际磁盘ENOSPC或物理断电实验。旧固定安装包/v2-v9清单不增加本模块。

## 验证

单元用原任务创建和审计导出生成真实无价值文件，覆盖32项、原字节回环、全部字段/类型/摘要、路径、
部分写入、fsync失败、丢失确认、同字节换文件、晚期变更、已有目标保护和中文路径。
离线集成实际启动12个CLI进程，测试32条目往返、原件删除后的验证、确定性与失败边界。
测试audit hook只限制回归进程的预期写入位置并拒绝native/网络/账本尝试，不是安全沙箱。
Windows/Linux工作流验证准确候选；本地测试/作者复核和CI不能替代独立代理审查。

接口依据：现有 ledger_query_request、ledger_query_audit、wallet_backup 的严格解码和独占创建路径。
Python文档： https://docs.python.org/3/library/json.html 和 https://docs.python.org/3/library/os.html 。
