# P2 真实付款与恢复资源基线

日期：2026-09-17。设计基线：`8324ec8bd153d9502e3e6761d25bfe281a5f3b44`。本文件固定本阶段验收目标；实际完成状态、准确源码、独立审核和测量另由验收报告记录。继续使用现有 NO-FUNDS LAB2／ZVTGEN03，不修改协议、账本／钱包格式、生产接口或任何现有限额。

## 固定负载与一致性

新建两个临时加密钱包，各获公开实验分配50000单位。奇数笔A向B付款，偶数笔B向A付款；每笔金额1000、费用1000，到期高度为准备时已提交高度加100。先正常提交32笔，再恢复后新建并提交第33笔；每块恰好一笔，没有空块或预制日志。次数、金额、费用和profile没有命令行覆盖选项。

Rust场景以显式`--active-resource-v1`选择该固定负载，默认及旧活动场景保持原行为。全部付款由真实`prepare_payment_to`生成并保存outbox；逐笔decode确认两个Orchard actions。正常worker与场景独立PoolStore均调用原prepare/commit路径，逐块比较完整Summary；钱包每个新高度完整同步。两个actions含填充，nullifier总数不等于真实花费输入数。

| 已提交付款 | commitments | nullifiers | 费用总计 | A/B保存记录 | A/B余额 |
|---:|---:|---:|---:|---|---|
| 0 | 2 | 0 | 0 | 2/2 | 50000/50000 |
| 8 | 18 | 16 | 8000 | 14/14 | 46000/46000 |
| 16 | 34 | 32 | 16000 | 26/26 | 42000/42000 |
| 24 | 50 | 48 | 24000 | 38/38 | 38000/38000 |
| 32 | 66 | 64 | 32000 | 50/50 | 34000/34000 |
| 33 | 68 | 66 | 33000 | 52/51 | 32000/35000 |

钱包保存记录不是付款数量。记录数和文件字节通过`storage_status`与实际文件元数据核对；账本逻辑容量按140字节头加实际提交帧累加，不仅计算交易字节。节点关闭后独立检查完整物理帧、checksum、连续高度／前驱、付款原始bytes与物理总量；这不是替代授权的验证器。

32笔后先采样并关闭第一代worker，新进程完整重放后核对原Summary和容量。场景另drop/open自己的PoolStore（新授权验证器），从独立保留receipt绑定的加密备份恢复两钱包，完整同步同一历史并核对相同记录数。随后才从恢复的钱包新建第33笔；再备份并重开这个待发送outbox，比较精确bytes，最终提交同一笔并核对收款可用、pending清除和上表状态。

关键边界检查坏签名和重复候选的选择／预览／最终化一致性；对仍未过期的已提交付款进行Check／Preview／Finalize重复拒绝，核对完整状态、容量和段bytes不变。有效第33笔已Finalize时，错误commit tag不得改变磁盘或破坏其待提交槽，原tag仍可正常提交。无跳过证明、直接置状态、放宽预算或改变存储限制。

## 资源和时间目标

固定Linux与Windows原生CI；Go1.27.1、Rust1.98.1、锁定依赖、release Rust、`RAYON_NUM_THREADS=2`。每个worker代际和Rust场景进程的OS报告resident生命周期高水位必须不超过1073741824字节。它是本小样本观测验收门槛，不是强制分配限制、私有内存或整个机器的内存预算；当前尚无实测保证可达。

Linux读取`/proc/<pid>/status`的VmRSS/VmHWM并转换为字节；其统计可能近似。Windows通过GetProcessMemoryInfo读取WorkingSetSize/PeakWorkingSetSize，不能用PrivateUsage替代。保留父PID与创建身份核验，同PID复用不得继承旧结果。每个检查点和每代退出前握手保证进程存活时采样；指标缺失、身份不符、平台不支持、超额或握手超时均失败，不能返回0或跳过。参考：[Linux proc](https://docs.kernel.org/filesystems/proc.html)、[Windows memory counters](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters)。

Python监督器和Go协调器不计入这两个角色；场景进程包括两个钱包、独立账本、prover、授权缓存、历史和Argon2，不是单钱包内存。新worker代际单独报告；当前resident用于检查点趋势，OS peak属于整代生命周期，不称为阶段峰值。采样后最终清理不属于负载观测窗口。

新场景worker启动目标60秒（比旧100000块场景的5分钟更严）；worker请求60秒、场景单响应90秒。Go整项测试20分钟，单次资源握手15秒；监督器最多额外30秒清理时间。失败后不得悄悄调高原目标。运行时间逐笔保留，不只记录成功样本；未完成运行必须保留已完成事件和失败阶段。

计时分开记录：场景冷启动及worker创建；逐笔准备（历史验证／钱包扫描、构造证明、加密保存和IPC的组合）；worker选择／预览及Finalize／Commit；场景独立执行／持久化；提交后全历史与两钱包同步；新worker启动加完整重放和状态／容量核对；同场景进程重开账本加钱包备份恢复；第33笔精确outbox恢复。每段计时在相关调用前开始、验证回复后停止，不包含之后的资源握手。总历时另含监督和检查开销。

`wallet_history()`完整执行历史状态规则，但可命中该PoolStore的64项授权缓存；不能每次都称冷证明重放。新worker与drop/open PoolStore构造新验证器；同场景恢复仍保留prover／allocator，且OS文件缓存可能温热，不称冷磁盘或全新钱包进程。所有数据用于此32+1笔基线，不计算生产TPS、网络最终性、隐私路径延迟或跨平台性能倍数。

## 测试监督协议

新Go端到端测试位于`internal/poolbridge`同包且仅在`payment_resource_e2e`构建标签启用，使用实际Client及其测试内可见PID，不增加生产查询。Python编译后监督该测试二进制，设置`ZEVUNE_RESOURCE_HANDSHAKE_DIR`、`ZEVUNE_POOL_WORKER`及`ZEVUNE_FUNDED_SCENARIO`；秘密始终保留在Rust场景内，不输出或上传临时钱包、genesis私有见证、交易bytes、密码、环境或命令行内容。

在新建私有临时目录中，Go原子创建`event-01.json`至`event-09.json`，等待对应`ack-01.json`等。每个事件包含`schema_version=1, seq, phase, height, paid_blocks, processes`；processes恰好为`worker`与`scenario`两项，每项只有`role,generation,pid`。还包含`state`（commitments/nullifiers/fees/logical_bytes/segments/tail_bytes）、`wallets`（两项records_used/file_bytes）及`elapsed_ms`。Python核验并持久化采样后才写`{schema_version:1,seq:N,ok:true}`；失败ack的ok为false并附固定错误码。

固定事件顺序：`genesis`、`payment_8`、`payment_16`、`payment_24`、`payment_32`、`worker_reopened_32`、`wallet_recovered_32`、`pending_restored_33`、`complete_33`。高度依次0/8/16/24/32/32/32/32/33；worker代际前五项为1，后四项为2；场景始终为1。payment_32与complete_33分别是两代worker关闭前的最后采样，complete_33也是场景最后采样。pending_restored_33时仍已提交32笔，钱包记录应为51/50。

为保留失败中的逐笔计时，Go在每项可能阻塞操作开始前、完成后分别原子新建递增`progress-0001.json`等文件（最多2048条、每条最多65536字节，不覆盖已有文件）。内容为`schema_version=1,seq,operation,payment_index,committed_blocks,status`，status为`started`或`completed`，completed另含`duration_ms`。operation只允许`scenario_start,worker_create,prepare,candidate,worker_commit,scenario_apply,wallet_sync,worker_reopen,wallet_recover,outbox_restore,duplicate_rejection,disk_check,worker_close,finish`。同一时刻最多一项started，后继completed须匹配operation/payment_index；started不声称完成。付款序号0至33，已提交数0至33，均由实际执行状态给出。

progress与九个内存事件独立，不增加握手。监督器持续收集并在Go退出后再读取完整序列，将已完成记录和最后尚未完成操作保存在结果中；中途退出或超时的具体失败原因取自实际退出／监督错误，未完成记录不能伪装为成功耗时。序列缺失、字段错误、进度保存失败同样失败。使用新文件避免Windows上覆盖正被读取的文件。

全部检查和关闭后，Go原子写`result.json`，含`schema_version=1,complete=true,paid_blocks=33,height=33,actions_per_payment=2,commitments=68,nullifiers=66,fees=33000,logical_bytes,segments,tail_bytes,wallet_records,wallet_bytes,checks,timings`。checks逐项说明真实付款、完整Summary一致、精确容量、钱包记录、物理帧、完整重放、恢复后新建付款、精确outbox和拒绝非变更均通过；timings保留固定阶段和33笔逐笔计时，并与progress完成记录核对。监督器仅在九事件、有效result、全部门槛及Go退出码0同时满足时成功。原始结构化结果含源码／checkout tree、平台、工具链版本、固定目标、角色／PID／创建身份、指标来源和失败记录。保存失败本身也使验收失败。

本场景不覆盖64项授权缓存淘汰、64个anchor边界、65536承诺、256次钱包保存、活动段轮换或完整容量上限；上一阶段轮换结果保持独立。活动归档／备份恢复、快照、剪枝、真实断电／磁盘满、多机长期运行及外部安全审计继续未完成，P2整体保持开发中。
