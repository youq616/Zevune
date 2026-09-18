# P2 活动账本持久增量包与新目录恢复

设计日期：2026-09-18。基线 `2cc87a2207d502ac5cfe00ea52e525c1516917e5`，
tree `b5841120084a72c5948b0a2754f712e5f67ad602`。
状态：实现前设计候选；独立设计审核不等于代码、原生测试或阶段验收。

## 交付及信任范围

将已验收的双检查点只读追加计划接入实际持久备份流程：创建一个只含新增公开账本字节的
包文件，结合独立可信的基线归档完整验证，并恢复成一个全新活动目录。提供实际 CLI。
只接受 NO-FUNDS LAB2 / ZVTGEN03 / ActiveSegmentsV1。旧格式、命令、存储上限、真实
Orchard 授权、完整重放、各验证器独立空授权缓存、所有旧测试和工作流预算保持。

调用者分别提供可信 base 与 later 的 ZVARCP01 检查点，各128字节。包内的检查点只是
待比对的数据，不能建立信任。既有 ActiveArchive 固定 base；later pin 由调用者另行传入。
成功确认的是精确公开账本字节及完整重放结果，不是最新状态、共识最终性、验证者签名
状态或钱包恢复。包和计划都不能成为未来免验证的权限。无状态快照导入、剪枝或迁移。

本轮闭合交付后可按准确验收将有限范围的 incremental_backup_implemented 记为 true；
snapshot_state_import_implemented、production_storage_ready、audited、real_funds_allowed
保持 false，P2 整体仍为 in_progress。实现和完整验收之前不得提前更新这些状态。

## 二进制包 ZVAIPK01

使用单个新文件，保留完整原始字节，不压缩、不重新编码交易、不接受外来路径或文件名。
所有整数均为大端无符号数，格式精确如下：

| 顺序 | 长度 | 内容 |
|---|---:|---|
| 1 | 8 | ASCII magic `ZVAIPK01` |
| 2 | 128 | 独立 base pin 的精确 ZVARCP01 编码 |
| 3 | 128 | 独立 later pin 的精确 ZVARCP01 编码 |
| 4 | 4 | u32 范围数 N |
| 5 | 12 × N | 每范围依次为 u32 segment_index、offset、length |
| 6 | later.length − base.length | 按范围顺序紧密连接的原始增量字节 |

固定头268字节，N最多2048，元数据最多24844字节。文件长度必须精确等于元数据加
增量字节数，拒绝截断、尾随、未知版本、溢出和多余记录；不设置可忽略扩展区或保留字段。
包内不另存一个被误认为授权的普通 checksum。可信 later pin 的完整物理 layout_hash、
可信 base 的完整验证及组合历史的真实重放共同认证重建内容。元数据在每次检查时逐字节
对照已捕获值，完整 payload 则由组合布局核验覆盖，不能只检查文件长度或元数据。

重建活动账本仍受原1 GiB逻辑字节、1000000记录、2048段以及1 MiB完整记录段限制。
包的格式开销另计，保守文件大小上界为1 GiB + 24844字节；从不据外部长度一次分配整个
payload。固定头、范围表及正文始终从同一个原始保留句柄读取。元数据分配前先校验 N
及文件物理上界，使用 checked 算术和 try_reserve；完整EOF属于整个包，不属于中间range。

## 唯一、严格的追加布局

两pin须与已验收只读计划相同地检查创世/头长度、高度不回退、同高只有完全相同pin、
增长时长度严格增加和段数不减少。包内两pin必须精确等于调用者提供的两个pin。

所有范围按段索引严格递增，长度非零，offset+length不超过1 MiB。旧段中至多允许旧
尾段一个范围，且其 offset 必须精确等于 base 实际保留尾段的长度；仅检查 offset>0
不足以接受外来描述。其他旧段全长复用。新段从 base.segment_count 连续到
later.segment_count−1，offset 必须为零，不能跳过、重复、重叠或重新切分旧历史。
允许旧尾不增长而直接新增段；base无段时后续所有段均为新段。

每个重建段的长度均从实际base长度与range推导，段数和全长必须与later pin一致。
范围长度和精确等于later.length−base.length；reused_bytes包含genesis与旧尾段前缀；
unchanged_segment_count只计整个字节不变的旧journal段；new_segment_count为段数差。
同内容/同pin时N=0，文件恰268字节，仍须完整验证并可恢复到新目录。

组合视图必须逐帧执行与现有 ActiveJournal 相同的物理边界及规范轮转判定：禁止拆帧、
过早轮转或以包range边界替代真实记录边界。可提取现有纯布局判定作为共享私有辅助函数；
不改变既有活跃账本和旧恢复的授权、状态执行或记录解释。

## 公共 API 和完整验证

新增 `pool::recovery::active::package::ActiveIncrementalPackage`，字段私有，只有只读
元数据访问 `plan() -> &ActiveIncrementalPlan` 和 `package_bytes() -> u64`；不返回
File、State、PoolStore、可变range或导入缓存，不接受调用者构造的计划作为恢复权限。

```text
base.pack_incremental_new(&mut later, new_package_file) -> ActiveIncrementalPackage
ActiveIncrementalPackage::open(package_file, &mut base, independently_trusted_later_pin) -> Self
package.verify(&mut base) -> ()
package.restore_new(&mut base, new_directory) -> ActiveRecoveryCheckpoint
```

所有调用返回 Result<…, PoolError>。open仅在完整verify后发布对象；创建返回的对象
始终保留原创建句柄和排他锁，正常open对象保留只读共享锁，drop之前不解锁重开。
package.plan只描述最后已验证的历史；verify/restore每次重新核验，不缓存授权成功结果。

一次 package.verify：

1. 核对独立pin与base对象身份、严格范围及物理长度，base.verify完成一次新的完整真实重放。
2. 用base与包的原句柄构造私有只读组合视图，检查双方完整字节、元数据、物理布局及名称。
3. 先从base的genesis文件单独读取完整物理头，再从组合reader读逻辑头，两者长度、初始
   状态与域一致；不得让恶意头长度从journal借字节。创建隔离State及新的真实
   AuthorizationVerifier，对完整组合历史执行原Replay，每个实际frame检查物理边界。
4. 验证最终genesis、height、app_hash和完整length；再次检查base全部字节、包全部
   payload与元数据、完整组合layout及双方名称，全部成功才返回。没有部分状态外泄。

只读组合reader使用显式偏移及有界读取，不依赖克隆句柄的共享游标，正确处理short read、
Interrupted、EOF及错误。只读视图本身不执行/缓存授权；成功信用只来自上述完整gate。

## 创建与恢复顺序

创建包首先在任何输出产生前核对目标路径和可创建条件，并调用既有incremental_plan：
两源各新重放一次，精确比较全部复用字节并完成末次核验。编码有界元数据，以create_new
建立文件、取得排他锁，从later原保留句柄流式复制所列字节，写满精确长度后sync_all，
再同步父目录（Unix）。通过原创建句柄构造包，调用完整package.verify(base)；最后
核对base、later的完整字节与名称，以及包的全部字节/元数据/父目录身份，才返回。
写包时不通过用户路径重新打开later，不重用旧计划授权另一次写入。

恢复首先检查全新目标及源身份，在创建任何目录前执行完整package.verify(base)。
随后从同一组合视图流式创建完整新活动目录：精确复制genesis与所有旧段，在旧尾后
拼接对应payload，并创建连续新段。所有文件使用create_new，保留原始创建句柄；逐文件
sync_all，完成后同步目录及Unix父目录。用这些创建句柄构成私有ActiveArchive，按
later pin完整真实verify目标。再执行一次完整package.verify(base)，最后重检目标
全部字节与名称，全部通过才返回later checkpoint。无需旧later目录即可完成验证和恢复。

两种输出都禁止覆盖已存在对象、自动删除、截断、修复、清理或重试；不得向现有PoolStore
追加或更改已提交状态。目标父目录须预先存在并可保留为真实目录；通过canonical父路径
检查拒绝在base或later归档内部写包，恢复目标同样不能在base内部。包所在父目录只校验
身份，不禁止无关兄弟文件，以允许在旁边创建恢复目标。既有文件须拒绝symlink、Unix
多链接和Windows reparse point；保留Unix命名inode检查及Windows禁止DELETE sharing。

失败可能留下部分或完整的新包/目录，包括同步完成但确认丢失、以及最终核验或stdout失败。
不得据函数失败断言“目标不存在”；再次指定同一路径必须拒绝，调用者可另行显式验证。
合作文件锁、保留句柄及最后检查仍依赖可信父目录、OS和文件系统；不宣称任意敌对瞬时
改写下的原子快照。Windows可移植目录持久化、真实磁盘满/物理掉电仍未因此得到保证。

完整成功路径的重放次数明确为：pack方法4次（计划2次＋包验证2次）；verify/open各2次；
restore方法5次（写前包验证2次＋实体目标1次＋写后包验证2次）。包含独立打开base/later
的CLI，pack合计6次，verify合计3次，restore合计8次。早期错误不必完成所有重放。
现有归档及只读计划的验证次数保持；此阶段不声称减少重放时间或测得整个进程资源峰值。

## CLI 与回执

```text
pack-active-incremental --no-real-funds --base <absolute base archive> --base-checkpoint <256 lowercase hex> --source <absolute later archive> --checkpoint <256 lowercase hex> --output <NEW absolute package file>
verify-active-incremental --no-real-funds --base <absolute base archive> --base-checkpoint <256 lowercase hex> --source <absolute package file> --checkpoint <256 lowercase hex>
restore-active-incremental --no-real-funds --base <absolute base archive> --base-checkpoint <256 lowercase hex> --source <absolute package file> --checkpoint <256 lowercase hex> --output <NEW absolute directory>
```

两pin在打开任何输入前解码。沿用显式参数白名单、NO-FUNDS、绝对路径、缺失/重复/未知
参数拒绝、通用无路径错误和安全File-backed stdout；不改变旧命令。pack的source是later
目录，verify/restore的source是包文件；不自动寻找基线或信任包内pin。

成功单行ASCII JSON首字段 `format:"zevune-active-incremental-package-1"`，随后按序为
operation、package_format（ZVAIPK01）、package_bytes、base_checkpoint、checkpoint、
base_height、height、base_bytes、bytes、reused_bytes、appended_bytes、
unchanged_segment_count、new_segment_count、ranges（每项segment_index/offset/length）。
随后 `replay_verified:true`、`byte_prefix_verified:true`；incremental_backup_written
仅pack为true，archive_restored仅restore为true；snapshot_imported、finality_verified、
validator_ready和real_funds_allowed始终false。先有界完整渲染，再写stdout；预留上界
为2048+96×range数，最大198656字节，输出前检查实际长度及ASCII。无路径或私密数据。
验证错误不输出成功回执；stdout失败非零退出且可能留部分JSON以及完整新目标。

## 必须完成的验收

- 独立编码精确包字节，覆盖空包、genesis到新段、旧尾增长、旧尾不变而轮转、多新段、
  新目录完整字节等于later；不读取later即可verify/restore，重新打开目标正常继续提交。
- 拒绝版本/pin/长度/count/范围次序/实际尾偏移/零长度/缺口/重叠/溢出/截断/尾随及payload
  损坏；两端独立有效的分叉/回退和错误网络不能通过创建，错误base不能验证/恢复。
- 合成物理测试覆盖跨64 KiB边界、short read/Interrupted/短写/零进度/异常返回/中途错误；
  不把合成frame的物理通过当作State或授权证据。
- 保留并复用既有真实两笔付款、正常1 MiB轮转及恢复后再次花费fixture，使随后花费真正
  来自增量恢复结果；保留旧归档、只读计划、余额/费用、双花和错误后不变断言。
- 改坏新增付款的binding signature并重算普通frame摘要和later完整布局pin，构造字节一致
  的包，让包与base组合重放明确到达Authorization拒绝；无效实例的proof执行不夸大。
- 真正CLI子进程覆盖三命令、完整JSON、两pin/选项/路径、既有目标与源内目标拒绝、只读
  stdout实际失败及可写正对照；失败回执后的完整目标能另行显式验证。
- 覆盖原保留句柄/锁、多只读实例、Unix命名替换及链接、Windows句柄存续rename拒绝；
  私有cfg(test)注入部分写、sync前、durable后确认丢失、最终源/包/目标变化。保留故障
  留下的内容，不称真实掉电/磁盘满、全容量或任意敌对主机保证。
- 按准确候选运行Ubuntu/Windows全部原默认/funded Rust cohort、fmt/strict Clippy、
  Go test/vet/支持平台race/fuzz、增长、资源和四节点回归，不放宽预算或减少原断言。
- 准确base/head/tree经非作者完整代码审核，阻断关闭；文档与证据后续提交独立审核、
  运行源码逐字节继承，原始失败、审核范围和实际合入均保留。
