# 历史交易纳入查询 v1

本模块回答一个限定的问题：**独立指定的交易ID，是否出现于某份完整验证过的历史账本中？**
它不再依赖恢复结果中是否存在pending文件，也不把没有pending等同于已经付款。
每次调用必须重新运行原 `zevune-pool-recovery verify-active`；没有缓存授权、服务器查询或新密码学。

## 使用

从可信源码目录运行，使用Python 3.10+及独立批准的原生恢复程序；不需要Tk、钱包或密码。

```powershell
python .\scripts\ledger_transaction_lookup.py --no-real-funds --journal 'C:\Zevune\stopped-archive' --checkpoint '<独立256位检查点>' --genesis-sha256 '<独立64位创世文件摘要>' --txid '<独立64位交易ID>' --backend 'C:\Approved\zevune-pool-recovery.exe' --backend-sha256 '<独立64位程序摘要>'
```

`--text`输出中文，否则输出UTF-8 JSON。输入必须完整，不接受缩写或自动寻找最新版本。路径需绝对且
不包含`..`，拒绝符号链接/reparse父级、硬链接及非普通文件。只读已停止写入的本地活动归档。
检查点和程序摘要须来自独立信任渠道，不能从待验证文件自算后当作可信来源。交易ID只识别完整交易
字节的SHA256；本工具不验证它是否对应操作者预期的收款人、金额或付款意图。

成功退出码为0；错误为1、参数错误64、用户中断130。未找到交易是一次完成的历史查询，仍退出0；
必须读取`state`或`historical_inclusion_verified`判断找到与否。原生错误/超时不能被改写成“未找到”。
输出写入/flush失败可能留下部分文本，任何非零退出的输出都不能当成有效查询结果。

## 核验顺序与空间界限

先完成全部输入检查，以原有流式归档指纹检查目录、创世头和独立检查点。仅允许原`verify-active`
命令进行完整Orchard授权和历史重放；返回字段、类型及检查点必须精确匹配。失败时不进入查询扫描。

原生通过后逐段读取原`ZVOBLK01`帧，以每段最多1 MiB的有界缓冲处理记录，最多记录一个匹配位置。
只解释原记录的高度、区块标识、交易长度和原始字节边界，不新增交易证明解码器或授权验证器。
保留原每块16笔、单笔28134字节、每段1 MiB、最多2048段/1000000记录/1 GiB规则。
逐帧验证校验和、连续高度、摘要衔接和精确末尾，重新计算原`ZVARLY01`布局摘要并匹配独立pin；
发现匹配后仍扫描完整剩余账本。重复匹配、截断、跨段拆帧、提前轮换或尾部损坏均拒绝，而非返回
不完整的“找到”或“未找到”。最后再核对全体原字节/文件身份和目录项，没有常驻索引文件。

全部预检查、原生执行、扫描及末尾复查共享一次300秒单调时钟预算；不续期、不自动重试、不接受
提高预算的参数。OS阻塞及原进程清理可能超过墙钟时间，但已超预算不能报成功。这不是硬实时保证。

## 输出的准确含义

找到时`state=included_in_verified_history`、`historical_inclusion_verified=true`，并返回
`occurrence`：历史记录高度、原记录block_id、从0开始的块内交易序号、物理段名、帧起点偏移和字节数。
这里的block_id只是已验证记录内的字段，不另称其为经过共识证书验证的区块哈希。
`subsequent_record_count`仅为检查点高度减纳入高度，**不是共识确认数**。

未找到时`state=absent_from_verified_history`，位置和后续记录数为null。它只说明这份指定的历史
归档未包含该精确交易，不证明其他分叉、更新高度或外部网络也未包含，不授权重复付款或清除预留。
两种结果都需要`ledger_replayed=true`及`historical_search_complete=true`。

所有结果保持当前高度未知、广播/结算unknown、`wallet_authenticated=false`、
`recipient_or_amount_verified=false`、`finality_verified=false`、`retry_authorized=false`、
`portable_proof_generated=false`、`real_funds_allowed=false`。这是本机验证观察，不是可独立传递的
Merkle纳入证明或带签名的付款凭证。查询交易ID、位置和公开元数据可能关联交易，应保护终端输出。

## 实现与验收边界

原钱包/账本/恢复器、C17桌面、格式、同步锁、授权、依赖和旧工作流均不改变。新增目录不能混入
旧v2-v9或固定10payload安装清单。无联网、钱包操作、交易导出、恢复、签名、广播或输入写入接口。
仍需可信解释器、本机、原程序及父目录，并停止其他写入。前后指纹不是跨文件原子快照、全程锁或
抵抗恶意文件系统恢复时间戳的保证，也不提供校验后监控、完整ACL或物理断电保证。

单元测试只验证公开记录边界及失败路径，合成交易没有有效Orchard授权，不能冒充成功重放。
原生驱动保留原恢复器的10场景，并对真实pending/empty/included/expired四类历史查询相同交易ID；
另执行实际CLI及账本损坏、真实重放后改写、扫描后插入文件的拒绝检查。成功路径必须用原Rust后端。
阶段尚需准确候选的Windows/Linux原生CI和非作者独立审核；作者复核和绿色测试不替代审核。

格式依据：`pool.rs::Record::{encode,decode}`、`pool/replay.rs`、`ACTIVE_ARCHIVE_V1.zh-CN.md`及
`internal/poolbridge/client.go`。预算依据Python官方`time.monotonic`文档：
https://docs.python.org/3/library/time.html#time.monotonic

## 独立审核整改：原生程序硬链接

原生可执行文件也必须只有一个硬链接，不能仅依赖摘要一致。查询专用的检查层在原摘要/路径/句柄
核验前后检查单链接和完整元数据；原传输层在启动前及结束后均调用这一检查层。保持所有原生
验证与清理规则，不改变其他入口的后端策略。校验期间新增链接或替换文件必须失败；这仍不是防御
恶意主机的执行锁。真实文件回归及原生程序副本回归验证正确摘要的硬链接文件也无法启动进程。
