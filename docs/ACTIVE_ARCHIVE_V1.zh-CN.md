# P2 活动账本的检查点绑定归档与完整恢复

设计日期：2026-09-17。阶段基线 `6913d4ab2fda6956db37e0ceb49790a4518c2762`，
tree `5e039b41e00f7a0a2e78937c796a40fbe68bfb0c`。
状态：实现前设计候选，需独立设计审核；本文不是实现、测试或合入成功证明。

## 范围与兼容

本阶段交付既有 LAB2 / ZVTGEN03 / ActiveSegmentsV1 活动账本的完整公开字节备份与恢复，
连接已有 `zevune-pool-recovery` 命令行。归档保持原目录的 `genesis` 及从
`00000000.journal` 开始的连续完整记录段，不增加 MANIFEST、包装目录、快照或另一种分片。
原段长度、顺序与字节精确保留；复制后的目录由正常活动 PoolStore 打开并完整重放。

新的独立检查点格式认证这一精确副本；归档没有可自行决定可信身份的清单。旧
`ZVPRCP01` 120字节检查点、`ZVPSEG01` 分段备份、旧派生索引及所有旧命令保持原含义。
旧接口仍拒绝活动profile；新接口明确拒绝legacy，且不支持格式的请求不使健康store失效。
不改签名域、Orchard证明/授权、交易/活动日志编码、IPC、状态规则、固定容量或依赖。
已有五文件交付包不变，本阶段通过原 cargo recovery 可执行文件交付；不增加Go网络恢复入口。

这不是增量备份、状态导入、剪枝、迁移或完整验证者恢复。归档不包含钱包、密码、密钥、
CometBFT数据库/WAL或最后签名状态。任何副本继续作为验证节点之前都需另行协调签名状态；
不得同时启动具有相同验证者身份的两个副本。全部操作限定本机NO-FUNDS实验。

## 固定检查点编码

新增 `pool::recovery::active::ActiveRecoveryCheckpoint`，字段私有，
`ACTIVE_CHECKPOINT_BYTES = 128`，所有整数为大端：

| 字节范围（半开） | 字段 |
|---|---|
| 0..8 | 固定magic `ZVARCP01` |
| 8..40 | 原活动genesis头SHA-256，即State.genesis |
| 40..48 | 已提交高度u64 |
| 48..80 | 该高度原AppHash |
| 80..88 | 逻辑总长u64：genesis与所有完整段字节之和 |
| 88..92 | genesis物理长度u32 |
| 92..96 | 活动物理段数u32 |
| 96..128 | 规范布局SHA-256 |

规范布局摘要的输入必须精确为以下字节序列，使用原有SHA-256依赖：

1. 8字节ASCII域 `ZVARLY01`。
2. genesis长度u32，以及该文件的全部原字节。
3. 段数u32。
4. 按0开始递增的每段：序号u32、实际捕获长度u32、该段全部原字节。

不加入路径字符串、平台时间、私有数据或可选字段，不把原字节替换成另一套逐段hash编码。
长度和序号使相同逻辑流的不同物理分段也绑定不同摘要；这仍只是完整性绑定，不能代替
真实授权、独立可信检查点或共识证明。

`from_bytes` 在任何文件读取/按输入分配之前，检查准确128字节、magic、三个非零hash，
并以checked运算检查：

- 高度不超过1000000；逻辑字节不超过1073741824；段数不超过2048。
- 头长范围为76至 `76 + 32 * MAX_COMMITMENTS`，且减76后为32的倍数。
- 高度0当且仅当段数0，此时总长恰好等于头长。
- 非零高度时，1 ≤ 段数 ≤ 高度；记录字节至少为150×高度，且不超过段数×1048576。
- 总长、乘法和减法均须通过有界检查，不能用截断整数或overflow回绕接受。

这些只是结构下界和上界。完整文件验证还必须解析真实03头及曲线点/签名域，核对实际
段长度、记录数、所有真实授权、规范轮换及最终状态；不能据结构合法就接受来源。

pin必须由独立可信渠道保留。随不可信归档一起收到的未认证pin不证明来源；旧合法pin可
认证旧历史，不证明最新高度。SHA-256不称为安全签名、隐私或网络finality。

## 公开接口和真实调用

新增接口限于：

- `PoolStore::active_recovery_checkpoint(&mut self) -> Result<ActiveRecoveryCheckpoint, PoolError>`。
- pin的 `from_bytes / to_bytes / height / app_hash / length / segment_count`，以及需要的只读头长访问。
- `ActiveArchive::open(path, pin)`、`checkpoint()`、`verify(&mut self)`。
- `ActiveArchive::copy_new(&mut self, target) -> Result<ActiveRecoveryCheckpoint, PoolError>`。

ActiveArchive私有持有只读源句柄，不返回可写PoolStore、状态导入对象或接受外来索引。
备份与恢复使用相同copy_new实现，无需两个不同复制算法。

检查点导出针对已拥有的活动store：取得committed Summary；核对全部目录/文件字节和身份；
使用新AuthorizationVerifier重新完整重放，比较整个committed Summary及容量；再次核对
原字节和namespace，全部成功才输出pin。不包含尚未提交PreparedBlock，也不修改其状态。
不支持profile先拒绝且不poison；真实存储/身份/历史错误使store按既有规则不可用。

普通活动open与新归档/目标验证共用内部完整重放路径：真实State::from_storage_policy、
新AuthorizationVerifier、Replay::next_block/finish，以及对每条真实记录调用
ActiveJournal::validate_frame。不是仅比应用摘要、layout hash或复用一次缓存成功结论。

归档首先在保留的genesis物理文件内解析03头，要求头长恰好等于捕获物理长度和真实EOF；
不得让伪造头长度从第一个journal段继续取字节。随后才建立逻辑reader、完整重放，并
逐帧拒绝跨物理段拆分、非规范提前轮换、空段和错误尾字节。完整状态在最后EOF、pin匹配、
字节与namespace再检查之前不可对外发布。

每次verify重新执行上述完整流程并创建新验证器。源目录摘要与namespace检查夹在重放前后；
检查点的头摘要、高度、AppHash、逻辑字节、头长、段数和布局摘要须全部匹配。

## 名称、锁与精确复制

保留当前ActiveJournal的严格目录清单：只有genesis和连续八位十进制journal段。
拒绝未知名称、缺号、重复、symlink、Windows reparse point、Unix多硬链接和非普通文件。
Unix保留设备/inode绑定；Windows目录及各文件使用既有不共享DELETE的保留句柄。
可信父目录、操作系统和文件系统是前提；不声称防任意恶意瞬时替换再还原。

现有普通活动open保持读写句柄和genesis独占锁。新增归档源以只读句柄和genesis共享锁
打开，合作中的实时writer因独占根锁阻止源打开，多个归档读者可共存。不得先打开可写store
后解锁重开成读者，不在已经持锁的原句柄/克隆上重复加锁。

copy_new的顺序固定：

1. 先核验源路径与保留句柄绑定。目标必须为绝对路径、父目录已存在；canonicalize可信源
   目录及目标父目录，拒绝源内部目标和通过父别名指向源内的目标，拒绝相同/已有目标。
2. 在创建任何目标之前完整verify源。错误pin、损坏或真实重放失败不能产生新目标。
3. 非递归create-new目标目录；Unix权限0700。逐文件create-new，Unix0600，
   保留目标目录/文件句柄，目标genesis持独占锁，64 KiB有界缓冲复制全部准确原字节。
4. 每个文件sync_all；Unix同步目标目录和父目录。Windows不增加未实现的目录持久化承诺。
5. 直接通过这些原创建且持续持锁的目标句柄核对完整字节、namespace并真实重放。
   不得为了验证而drop/unlock后从路径重新打开。
6. 返回成功前再次完整验证源和检查其字节/namespace，并核对目标的最终字节/namespace，
   然后返回原pin。copy_new不会启用目标为运行节点。

句柄克隆可能共享游标；摘要、复制和重放串行执行，每次读取明确定位，不能因Windows
seek_read影响共享游标而依赖偶然顺序。每个真实文件读完声明长度还必须验证实际EOF，
I/O失败的reader继续保持失败关闭；不自动跳过、修补或重试整个操作。

任何创建后失败都可能留下部分或完整新目标，不能删除、截断、覆盖或自动重建。完整文件
已同步但成功回复丢失时，随后独立验证可以接受完整副本；错误返回不证明没有完整副本。
测试注入仅为cfg(test)私有路径，不增加生产故障参数或被测能力捷径。

源与目标各最多持有2048段、genesis及目录，重放reader还会克隆整套句柄。保留并报告这一
句柄成本及完整历史/内存成本；不能沿用旧分段备份的64段/66句柄口径，也不能宣称1GiB
逻辑容量就是整机内存/文件描述符预算。主机资源不足必须失败关闭。

## 命令行合同

保留全部旧命令和旧输出；新增以下明确命令，所有路径均绝对，必须有
`--no-real-funds`，pin使用准确256个小写十六进制字符：

```text
zevune-pool-recovery checkpoint-active --no-real-funds --source <活动目录> --genesis <独立03清单> --genesis-sha256 <64hex> --height <可信高度> --app-hash <可信AppHash>
zevune-pool-recovery backup-active --no-real-funds --source <活动目录> --output <不存在的归档目录> --checkpoint <256hex>
zevune-pool-recovery verify-active --no-real-funds --source <归档目录> --checkpoint <256hex>
zevune-pool-recovery restore-active --no-real-funds --source <归档目录> --output <不存在的新活动目录> --checkpoint <256hex>
```

checkpoint-active由TestGenesis::read_pinned读取独立03清单，检查profile后通过原open_pool
和check_checkpoint绑定可信高度/AppHash，再导出新的pin。该导出沿用普通store持锁打开，
会要求既有读写访问权，但不修改账本字节。其余三命令通过只读ActiveArchive打开；
backup-active/restore-active都调用同一copy_new。

禁止自动猜测profile、自动接受最新pin或兼容错误长度。拒绝缺失、重复、未知参数，
非规范高度/hex和相对路径。成功JSON保留operation/checkpoint/height/bytes及
replay_verified:true、finality_verified:false、validator_ready:false、real_funds_allowed:false；
active成功额外明确ZVARCP01/ActiveSegmentsV1、app_hash和segment_count。旧成功JSON不改。
错误输出不得泄漏用户路径、私密内容或把失败的新目标称为不存在；stdout失败返回非零。

## 冻结验收要求

1. 新pin准确codec、所有截断/尾字节、旧新magic互斥、所有容量/算术/零高度关系；
   至少一组固定输入的独立规范布局hash向量。
2. 创世无段和正常多段的完整目录归档/恢复，所有原始文件字节相等，普通活动open成功。
   真实正常提交跨1 MiB物理段，恢复后真实收款再花费及重复付款拒绝；钱包历史/状态一致。
3. 复用已有活动增长fixture：第一笔真实付款触发第二段后归档恢复，在恢复目录继续到10001
   并执行原第二跳真实付款；10001高度另验证新pin、精确复制、完整恢复和继续提交。
   保留原域/容量/选择/错误候选/非变更断言，不以空块计数声称相同数量真实付款。
4. 真实签名损坏后重算record checksum和新的完整layout hash/pin，仍明确Authorization拒绝；
   错误后状态、错03头/域、损坏/交换/截断/追加/多余文件、跨段拆帧和提前轮换均拒绝。
   测试应说明实际拒绝层，不把锁失败或未重算hash当成授权拒绝。
5. 实际双进程/句柄锁、多个只读归档、drop后释放；Unix链接/文件和目录持久替换，
   Windows真实rename阻止至drop；源内目标及父路径别名、已有文件/目录均拒绝且保持原字节。
6. 新目标部分genesis/段写入、完整写入但未完成返回、完成同步后丢失确认等私有故障注入；
   原源不变、目标不被自动删除，完整目标允许显式后验验证；末次源/目标校验错误不得成功。
7. 实际CLI创建/验证/恢复、低高度真实付款恢复后第二跳、旧命令回归和参数/错误profile拒绝。
   保留旧Go网络CopyStorageAtCheckpoint对活动profile拒绝，不暗中升级为验证者恢复能力。
8. Ubuntu/Windows原生Rust默认与funded完整library/interfaces、格式/Clippy/锁定构建和全部
   既有Go test/vet/race/fuzz、100000块增长、32+1资源及四节点回归仍按准确候选实际执行。
   不因新增测试而漏掉原cohort，不以未运行/跳过项冒充通过。

全部CI和非作者独立代码审核通过后方可合入，并另行保存精确base/head/tree、原日志、
实际测试计数和限制。若设计本身改变，先记录变更并重新独立审核相关合同。
P2仍为开发中；长期全容量、真实断电/磁盘满、Windows目录持久化、增量/快照、签名状态
恢复和外部安全审计均不由此阶段完成。

文件行为依据为Rust std File/Read和Windows OpenOptionsExt官方合同：
[File](https://doc.rust-lang.org/std/fs/struct.File.html)、
[Read](https://doc.rust-lang.org/std/io/trait.Read.html)、
[Windows OpenOptionsExt](https://doc.rust-lang.org/std/os/windows/fs/trait.OpenOptionsExt.html)。

