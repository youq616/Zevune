# P2 活动归档的追加关系核验与增量计划

设计日期：2026-09-17。基线 commit `0927af157a3cc35abde14b036bc50a99a793a32b`，
tree `e04479cf7723588885573be2112635efa30e27cc`。
状态：实现前设计候选；设计审核不等于实现或原生验收。

## 本阶段交付

在既有只读 `ActiveArchive` 上比较两份分别由独立可信 ZVARCP01 pin 认证的活动归档，
验证后者是否为前者的精确物理追加，并返回有界的字节追加计划。提供实际命令行入口。
同一高度、同一完整内容返回空计划；回退、同高分叉、不同网络及更高高度但改写历史均拒绝。

计划仅描述公开账本字节，不创建、修改或删除任何归档文件，不写增量包，不导入状态，
不作为以后免于验证的能力凭证。`incremental_backup_implemented` 和
`snapshot_state_import_implemented` 继续为 false。后续持久增量格式和恢复需单独设计验收。
既有 ActiveArchive 复制和三个完整 replay、旧格式/命令、容量、证明、缓存和工作流保持。

## 信任与前缀规则

调用者必须分别持有 base 与 later 的独立可信 pin。两份归档都完整通过既有真实授权、
状态、帧边界、轮换规则、物理 EOF、布局摘要及 namespace 验证；不能只比较高度或 AppHash。
两个未认证 pin 不能互相证明来源；合法旧 pin 也不证明最新高度或共识 finality。

1. 两端只支持 LAB2/ZVTGEN03/ActiveSegmentsV1。创世身份和物理头长度相同，
   原 genesis 文件全部字节必须相等。不同创世拒绝为 Genesis。
2. later 高度不得低于 base；同高只有完全相同 pin/内容允许。增长时逻辑长度必须增加，
   段数不能减少。不兼容的合法历史是 Stale，不把分叉笼统称为磁盘损坏。
3. 对 base 的所有段逐字节比较：除最后一段外，同索引 later 段长度和全部内容必须相同；
   base 最后一段允许 later 同索引段更长，但 base 捕获的全部字节必须是它的精确前缀。
   不能将同一逻辑流重新切段当作可增量衔接，不允许替换旧记录或跳过验证。
4. 新数据只能是旧尾段捕获长度之后的后缀，以及其后连续的新段。base 无段时，
   genesis 被复用，later 所有段均为新段。末段没有增长但发生轮换时，只列新增段。
5. 任何解析、I/O、字节或身份错误均返回失败；没有部分计划或部分认证状态对外发布。

## 接口及读取顺序

新增公开 `pool::recovery::active::incremental` 模块中的不可变类型
`ActiveIncrementalPlan`、`ActiveAppendRange`，字段私有，仅提供只读 getter。
新增 `ActiveArchive::incremental_plan(&mut self, later: &mut ActiveArchive)`，
`self` 为 base；返回 `Result<ActiveIncrementalPlan, PoolError>`。

计划包含 `base_checkpoint()`、`checkpoint()`（later）、`reused_bytes()`、
`appended_bytes()`、`unchanged_segment_count()`、`new_segment_count()`、`ranges()`。
每个范围包含 `segment_index()`、`offset()`、`length()`，均为 u32。
范围按 segment_index 严格递增，没有零长度或重复；offset 非零仅可发生于旧尾段。
所有 range 长度之和必须精确等于 later.length − base.length；reused_bytes = base.length，
包含 genesis 和尾段已存在的前缀。新段数量为两端段数之差。
unchanged_segment_count 只计整个长度及字节均不变的既有 journal 段，不包含 genesis。
同内容空计划：reused_bytes = base.length，appended_bytes = 0，ranges 为空，所有旧段不变。

调用顺序：

1. 核对 pin 结构和高度/创世关系；分别调用两端现有 verify，每次创建独立空授权缓存，
   进行完整真实 replay。打开归档时的历史成功不替代本次调用的验证。
2. 在原只读且持续持锁的句柄上检查 namespace，比较 genesis、不可变旧段和旧尾段前缀，
   根据两端捕获的真实段长度构建计划。不得通过用户路径重新打开数据文件。
3. 再次核对两端完整布局字节摘要和 namespace，并校验全部计划计数/加法边界，
   全部成功才返回计划。末次摘要覆盖重放后的全部字节，不只覆盖计划所列的新字节。

两端 genesis 共享锁保持至各归档 drop，阻止合作 writer；多个只读归档可并存。
可以为同一路径打开两个独立只读实例并得到空计划，不通过字符串路径相等跳过验证。
沿用当前链接、重解析点及 retained-name 检查；可信父目录、OS 和文件系统仍是前提。
不承诺防任意恶意瞬时修改再还原，不提供并发 writer 的快照语义。

比较使用两个不超过 64 KiB 的有界缓冲，显式偏移读取并正确处理 short read/Interrupted；
不能要求一次 read 填满，也不依赖克隆句柄游标。base 每个物理文件确认捕获长度和 EOF；
later 更长尾段的全文件 EOF/完整性由其完整验证及末次全字节检查覆盖。
计划最多 2048 条；按已验证容量有界保留内存，try_reserve 失败关闭。所有长度/计数使用
checked 算术及显式转换。原有全部段句柄、重放临时 reader、完整历史状态的成本保持；
本阶段不声称优化 replay 时间、减少当前磁盘空间或测量全容量资源峰值。

## 命令行合同

```text
zevune-pool-recovery plan-active-incremental --no-real-funds --base <绝对较早归档目录> --base-checkpoint <256 lowercase hex> --source <绝对较后归档目录> --checkpoint <256 lowercase hex>
```

缺失、重复、未知参数，相对路径、旧 pin、错误 hex、未确认 NO-FUNDS 均在可行的最早阶段拒绝。
不接受 --output、自动寻找 base、自动选择最新高度或从目录自取可信 pin。
成功输出单行 ASCII JSON，格式 `zevune-active-incremental-plan-1`，固定包含 operation、
base_checkpoint、checkpoint、base_height、height、base_bytes、bytes、reused_bytes、
appended_bytes、unchanged_segment_count、new_segment_count、ranges，range 为
`{"segment_index":N,"offset":N,"length":N}`；按以上顺序输出，最后换行。
附 `replay_verified:true`、`byte_prefix_verified:true`、`incremental_backup_written:false`、
`snapshot_imported:false`、`finality_verified:false`、`validator_ready:false`、
`real_funds_allowed:false`。JSON 不含文件路径、私密数据或不受限的外部字符串。
schema 同时用于普通追加及空计划；不增加 success 限定分支。
使用既有 active 安全 stdout File 写入路径传播错误。失败时不输出成功 JSON，非零退出；
沿用 recovery 通用错误消息，不泄漏用户路径。写出失败可能产生部分 JSON，不能称完全无输出。

## 本轮验收

- 独立计算计划范围/字节总数并与真实文件后缀比较：零高度到零高度/非零，同一尾段增长，
  真实 1 MiB 轮换后增长，原尾段不变的新段，同路径/不同路径同内容空计划。
- 两端各自可验证的同高和更高分叉、回退、错误网络、旧格式、错误 pin、缺失/截断/追加/
  替换/链接/多余项拒绝，保留原文件字节。不得只用坏 hash 或锁失败冒充前缀拒绝。
- 打开之后源/目标的内容或 namespace 变化拒绝；正确计划后继续调用仍重新检查。
  合作 writer 锁及多读者行为保持；至少明确实际测试的平台。
- 真实付款、正常跨段及恢复后再花费流程中增加计划核验，保留已有所有断言，不减少
  证明、完整重放、容量或签名检查；坏签名重算普通摘要后仍到达 Authorization 拒绝。
- 真正 CLI 子进程：追加和空计划完整 JSON、参数/回退/分叉/错误 pin 拒绝、只读 stdout
  写入探针及可写正对照；调用前后目录集合与每个文件字节一致。
- Ubuntu/Windows 原生默认及 funded Rust 全部既有 cohort、格式/Clippy、既有 Go test/vet
  与支持平台 race/fuzz、增长、资源及四节点回归按准确候选完成。未运行和 skip 单列。
- 非作者针对准确 base/head/tree 审核实现与真实调用方；修复阻断后重新核对候选。
  文档跟进按仓库阶段规则核对运行树字节不变并独立审核，保留实际合入身份。

这是 P2 的增量恢复前置能力；P2 仍在开发中。持久增量包、快照导入、剪枝、迁移、磁盘满/
真实断电、Windows 目录持久化、长期多机、验证者签名状态恢复及外部审计不在本轮完成。
