# 离线查询任务变更审计 v1

本模块比较两份按独立摘要校验过的 C26 查询任务，回答“具体改了哪些查询依据、ID 和顺序”。
它不是原 inspect 的重复包装，也不是可执行的修改计划：不创建/编辑任务，不执行查询，不读取账本，
不启动后端，不输出新的执行权限。旧任务、桌面和原生流程保持不变。始终 NO-FUNDS。

## 使用

从可信源码目录使用 Python 3.10+；无需 Git、Rust、Tk、钱包密码或原生程序。两边各自提供独立保存的
任务 SHA256，不从收到的文件自算摘要来赋予信任。before/after 只是操作者定义的比较方向，不证明时间
先后、作者、审批状态或新旧链关系。文件必须符合原规范 JSON/profile/大小/单链接/路径检查。

```powershell
python .\scripts\ledger_query_request_audit.py --no-real-funds --before 'C:\Tasks\before.json' --before-sha256 '<独立旧任务SHA256>' --after 'C:\Tasks\after.json' --after-sha256 '<独立新任务SHA256>'
```

独立包使用 `runtime` 替代 `scripts`。默认 UTF-8 JSON 输出任务摘要、计数和变更标志，不输出本机路径、
完整检查点、程序摘要或交易 ID。任务摘要也可能关联任务，不称为匿名或零知识报告。`--details` 明确显示
完整公开依据、前后清单和增删/位置明细；需要保护终端和 shell 重定向产生的文件。`--text` 输出中文说明，
可与 `--details` 联用。工具本身不创建报告文件、不写日志、不自动复制到剪贴板。

```powershell
python .\runtime\ledger_query_request_audit.py --no-real-funds --before 'C:\Tasks\before.json' --before-sha256 '<独立旧任务SHA256>' --after 'C:\Tasks\after.json' --after-sha256 '<独立新任务SHA256>' --details --text
```

退出0表示比较完成，不表示任务相同、更安全或可执行；读结果字段判断差异。损坏、错误摘要、格式/类型
不符或检测到输入变化返回1，无完整审计结果；参数错误64，中断130。输出写入或 flush 失败可能留下字节
前缀，消费者必须同时要求正常退出0和完整JSON，不能使用失败调用的部分输出。

## 变更语义

`changed_fields`列出 checkpoint、genesis_sha256、backend_sha256、txids 中发生变化的字段。
`changed_trust_fields`单独列出前三项；任何一项变化都保持可见，即使交易集合不变。数值高度增加不证明
新检查点是旧检查点的后继；同高度但不同承诺仍是检查点变化。工具不重放账本或比较账本前缀。

新增 ID 按 after 的顺序，删除 ID 按 before 的顺序，保留 ID 明细按 before 的顺序；所有索引从0开始。
`query_set_changed`表示成员增加/删除，`query_sequence_changed`表示整个有序列表变化。
`retained_order_changed`只比较交集成员的相对顺序，而 `retained_position_changed_count`统计交集成员的
数值索引变化。例如 [A,B] → [C,A,B]：新增1，相对顺序不变，2个保留 ID 的索引改变。不会把插入误报成重排。
计数必须满足 before = retained + removed，after = retained + added。

两文件内容相同或同一路径比较均支持，但双方独立摘要依然必填，没有单边信任缓存。`content_identical`
只描述当次观测到的内容，不声称两个文件是同一对象，也不能复用另一窗口以前的确认。每次执行仍应
走原桌面的明确确认或原 CLI 的显式 run。

## 检查与不变边界

所有参数先检查再读取。复用原任务 load/decode，包括外部摘要先于 JSON、重复键拒绝、规范编码、8KiB
限制和精确字段；不再实现一套宽松解析器。两文件均载入后计算差异，再完整重读两边，最后复查各自
元数据/父级链，以发现先读文件在后读文件检查期间的普通变化。相同字节的文件替换同样拒绝。

`audit_complete`、`request_integrity_verified`、`input_files_unchanged`只说明本次有界读取及复查。
执行、签名验证、账本重放、链关系验证、审批复用、最终性、重试许可和真实资金标志始终 false；
`requires_explicit_execution_confirmation=true`始终保留。纯函数 describe 仅比较公共字段，不附加文件
完整性声明。输出上限32KiB，每边沿用最多32个ID，不放宽原协议或任务格式。

前后复查不是跨文件原子快照、全程锁、对抗恶意内核/恢复时间戳的保证，无法保护返回后的变化。
必须信任解释器、本机和父目录，并停止外部写入。普通文件IO可能阻塞；本工具不调用原生核心，因此
没有复用或延长其300秒预算，也不承诺自身硬实时截止。文件读取可能更新操作系统访问时间；“不写入”
指不主动改写任务内容，而不是文件系统绝无元数据副作用。

## 验证与验收

测试使用原 create 生成的真实无价值任务文件，覆盖独立 pin、两边完整 schema、32项、插入/删除/重排、
同高度不同承诺、反向对比恒等式、跨文件变更/同字节替换和明确明细输出，正常/错误 CLI 均实际执行。
固定种子随机测试是公共集合运算检查，不是钱包授权或密码学成功替身。双平台工作流只执行文件/CLI
与原任务合同测试，无需重编 Rust 或运行账本；既有原生工作流未改。

独立非作者审核和准确候选双平台验证状态必须按实际结果记录，不能由作者自查代替。新模块不加入旧
v2-v9或固定10文件交付目录；不能把本模块完成宣称为P2/P4整体或真实资金上线批准。

实现依据：原 `ledger_query_request.py`、`wallet_backup.py`、`ledger_recovery_backend.Checkpoint`；
JSON严格解析机制参考 Python 官方 https://docs.python.org/3/library/json.html 。


## C28报告兼容整合（C29候选）

在实际远端C28之上接入原本地双任务比较逻辑，不覆盖C28单报告审计器、任何旧桌面或查询核心。
原`ledger_query_request_audit.py`命令/API保持两个任务文件比较；新增统一证据比较入口支持每侧明确
选择`task`或`report`，没有格式猜测或失败回退。`report`严格复用原C28报告摘要与规范内容重建，
`task`复用原C26加载器；比较只调用同一份纯差异算法，不建立第二份任务或报告解码规则。

```powershell
python .\scripts\ledger_query_evidence_compare.py --no-real-funds --before 'C:\Tasks\old-report.json' --before-sha256 '<独立报告摘要>' --before-kind report --after 'C:\Tasks\new-task.json' --after-sha256 '<独立任务摘要>' --after-kind task
```

另有`task/task`、`task/report`、`report/report`三种组合，仍需分别提供独立输入摘要；任务摘要不能替代
报告摘要。报告自带的任务摘要只是已核验报告所绑定的内容，不当作另外一次独立读取的原任务。
返回每侧`kind`、输入文件摘要、任务内容摘要及`request_digest_basis`，明确其信任来源。
`source_file_rechecked=true`只用于直接读取的任务文件；报告输入为false，即使其中任务内容与另侧
相同，也不证明对应原文件存在。报告文件本身仍须在本次比较中读取并完整复查。

同一任务与其报告可得到`difference.content_identical=true`且`input_bytes_identical=false`。两份报告
在原任务均删除后仍可比较；这不是当前源文件复核，不能复用以前的执行确认。`before/after`只是用户
选择的标签，不验证时间顺序。默认只输出摘要与差异统计；`--details`才显示ID和完整公开依据。
`--text`输出中文；两种格式都标识输入文件与任务内容摘要，区别报告和任务。

所有输入参数在读取任一文件前检查；两端完整读取、差异计算、输出大小检查完成后再各自完整回读，
最后复查文件身份和父目录链，拒绝过程中替换。无跨文件原子快照或恶意文件系统保证。最大输入保持
原任务8KiB、原报告16KiB，每端最多32个ID；输出上限32KiB。不创建、导出、执行或删除文件，
不查询账本/程序/网络。CLI退出0才代表本次完整比较成功，失败1、参数64、中断130。

新离线集成驱动实际执行四组合及报告源缺失、错误类型、错误摘要、篡改拒绝；其Python audit hook
只作为可信代码回归的观测手段，禁止写文件、开进程、联网或读取账本的尝试，不称为安全沙箱。
C28原报告创建/导出/验证/源复核CLI回归也同时执行。没有用这些文件测试冒充原生授权验证。

技术语义参考：Python官方JSON的重复字段/object_pairs_hook说明与sys.addaudithook的非沙箱限制。
https://docs.python.org/3/library/json.html
https://docs.python.org/3/library/sys.html#sys.addaudithook
