Zevune P2 活动账本归档：C3 独立对抗复审原文

结论：**PASS（准确 C3 的代码与测试设计独立复审）**。C1 的唯一阻断项 AR-C1-01 已由 C3 补充的真实段交换回归在源码层关闭。本次完整范围复核未发现其他应阻止该代码候选合入的数据完整性、来源绑定、覆盖已有文件、平台句柄或故障处理问题。原生 CI 是另一个必需的验收门槛，本报告不证明 CI 通过，也不批准部署、资金使用或将整个 P2 标为完成。

审核任务：`/root/p2_archive_adversarial_review`；审核日期 2026-09-17 UTC。我没有编写、修改或格式化候选设计、源码及测试，没有读取其他审核者的结论作为判断依据。这里只读取准确 git 对象与官方合同，并执行独立 Python 摘要复算及静态检查。

| 身份 | 精确值 |
|---|---|
| 仓库及 PR | [youq616/Zevune PR #13](https://github.com/youq616/Zevune/pull/13) |
| 阶段基线 | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| C1 | `c5f60ac440ac39032f8f8efefc2fbfbf6e299a90` |
| C2 / C3 第一父提交 | `7477d9e0656ed751f525a4b6fe9f6649b995ede6` |
| 本次准确候选 C3 | `7045af4ae254f0a5a5e4810f17004c91e649e474` |
| C3 tree | `4017bee976c18767ed568d7ec8a33f6d668b8c22` |
| 冻结设计 SHA-256 | `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee` |

C1 原审查继续保留为 REQUEST_CHANGES，不能重写成 C1 曾经通过：`adversarial-review-c1.md` 为 12848 字节，SHA-256 `1b2f12b42dffb0a5bd5bea9c7f48945062534d46580c43ea194b9d6766b9b915`；其 JSON 为 13376 字节，SHA-256 `3a89c3f602133431e12f4094cc0101859439198ed85000c5189c5dcf9f72dd47`。本复审另存新文件，范围固定到 C3，后续修改不自动继承结论。

**AR-C1-01 关闭依据。** 冻结设计第 4 项要求交换活动段后的拒绝行为，C1 未覆盖这一具体路径。C3 在既有 `real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` 中增加 44 行，不增加另一组证明生成或修改容量。执行至 10001 后，测试已有通过真实提交及同步产生的两段，原第一段为空块历史，第二段从首次真实付款的高度开始。新代码只在新测试目录里交换这两个段的完整原字节；头、文件名集合和各记录的 checksum 均保留。

拒绝证据在源码中具有明确分层：

- 使用原 pin 打开交换目录，要求 `PoolError::Corrupt`；原源与交换目录逐字节不变。
- `repin_layout` 重新构造规范摘要并调用公开 `from_bytes`，使新 pin 通过结构边界；另经 `ActiveJournal::open_readonly` 与实际生产 `layout_hash` 比较，确认新 pin 的 layout 字段确实匹配，随后释放这组检查句柄。
- 测试解码交换后第一条真实记录，断言其高度是原首次真实付款高度，且 `base_hash` 不等于独立 genesis 的初始 AppHash。随后用新 pin 再打开，明确要求 `PoolError::Corrupt`。这与 Replay 在真实执行前比较前序 AppHash 的拒绝点一致，不能由旧摘要不匹配或仍持有检查句柄解释。
- 再次断言原源和交换目录字节不变，然后继续原来的正常 10001 归档/恢复、普通 open、重复花费拒绝及提交 10002 正对照。新增断言没有 ignored/cfg 隐藏，也没有把原付费交易换成空块。

这足以关闭“测试源码缺失”的问题；是否实际执行成功，要由准确 C3 的 funded library 原生完整日志确定。本报告没有把源码中的断言等同于运行通过。

**C1 到 C3 的差异复核。** 我检查了全部改动。C2 是 rustfmt 排版，包括两处单表达式 match 分支的冗余花括号折叠，未发现返回值或控制流差异。C3 除上述 44 行测试外，只把新 pin 头长对齐条件改为 `!(header - MIN_HEADER).is_multiple_of(32)`。前面的范围条件仍以短路方式保证减法不下溢，除数固定非零 32，接受集合与原 `% 32 != 0` 相同。Rust 官方将该 u64 API 列为自 1.87.0 起稳定，符合仓库固定 1.98.1；没有改变协议、容量、codec 或依赖。[Rust u64::is_multiple_of](https://doc.rust-lang.org/std/primitive.u64.html#method.is_multiple_of)

完整范围复审确认：

1. **先约束 pin，再读取候选。** 新格式准确 128 字节、magic ZVARCP01；三个非零摘要、最大高度、逻辑容量、段数、头长、对齐及零高度关系检查齐全。输入短于固定长度时先拒绝，不先切片。记录字节下界和上界使用 checked 运算，私有物理段上界约束后再进行固定宽度摘要编码。旧 120 字节 ZVPRCP01 及 ZVPSEG01 没有被新 API 接受或重解释。

2. **物理头和独立身份。** 从保留 genesis 句柄内按捕获长度解析 03 头，要求准确头长和物理 EOF，再比较逻辑解析头。构建真实 State 后，必须与正常 opener 的独立预期头摘要、已拥有 store 的 genesis 或独立归档 pin.genesis 相等。没有仅依赖第一次打开时的比较；同 inode、同长度但实际头改变的用例使用原拥有句柄，测到的是身份拒绝而不是 Windows 锁失败。

3. **完整重放不被摘要替代。** 普通活动 open、检查点导出和归档 verify 都使用共享 `replay_active_handles`。每次构造新 AuthorizationVerifier，所有记录由 Replay 逐条执行真实域、到期、锚、花费、承诺、签名和证明规则；每条记录还验证完整物理帧边界及规范轮换。隔离 State 仅在最后真实 EOF、finish 和名称检查后可发布；归档始终不向外暴露可写 State/PoolStore。

4. **全部已提交状态与 pin 一致。** 检查点导出比较整个 committed Summary、genesis 和容量，并在重放前后计算原始字节/布局摘要。PreparedBlock 不进入 pin，不被消费或改写。不支持的 legacy 先拒绝且不 poison；真实历史/存储错误使活动 store 不可用。归档每次 verify 都从头检查 bytes、重放、tip，再检查 bytes 与 namespace，不把过去成功的 verifier 缓存当作授权。

5. **布局向量与真实拒绝层。** 独立 Python 重算仍得到 76 字节 genesis SHA-256 `07782393f4021cabba3a8a09f0d2747e6ae4404457475c6e9df85100f734bc1e`、92 字节规范布局 SHA-256 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`。单元负例对错误头、跨帧、提前轮换、错误后状态、尾字节重新计算摘要后再拒绝。真实付款签名负例重算 record checksum 和完整新 layout pin，并明确要求 Authorization。因此不存在仅靠不匹配的旧 hash 来声称验证了真实密码学的测试替代。

6. **源只读与平台锁。** 活动归档源以只读句柄及 genesis 共享锁持有，普通 writer 仍使用独占锁。共享读者可共存，合作 writer 被排斥；完整 reader 克隆不重复加锁。双进程测试实际启动当前测试可执行文件，指定 exact 测试名，并检查 `1 passed`，防止零测试进程误判成功。对锁释放的正对照位于最后归档 drop 之后。Rust 合同说明共享锁与独占锁关系、克隆句柄及重复加锁限制；候选按该合同保留拥有关系。[Rust File](https://doc.rust-lang.org/std/fs/struct.File.html)

7. **名称保留与 Windows 正对照。** Unix 目录和每个文件比较 dev/inode，拒绝 symlink、多硬链接、未知名称、缺号及非普通文件。Windows 保持既有无 DELETE 共享句柄，文件和目录保留 OPEN_REPARSE_POINT，目录另加 BACKUP_SEMANTICS；没有拿相同时间戳或长度当 Windows identity。Windows 用例先证实文件可写，再断言实际 rename/delete 在两个读者及剩一个读者期间失败，最后所有 drop 后完成相同 rename/delete；readonly 用例在归档锁取得前确认实际写打开 error 5。这些测试没有用一般权限错误取代锁保护的正对照。平台合同支持对应实现，但仍要求 Windows runner 实测。[Rust Windows OpenOptionsExt](https://doc.rust-lang.org/std/os/windows/fs/trait.OpenOptionsExt.html)、[Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[Microsoft LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)

8. **不覆盖源或已有目标。** 在创建任何目标之前先检查源路径绑定、绝对路径、canonical 父目录与源内别名、目标不存在及完整源验证。底层只有非递归新目录和 create_new 新文件，Unix 使用 0700/0600；没有删除、覆盖、truncate、修复或自动重试。归档源句柄不能写入。非法源在全验阶段失败，不能留下新目标；创建之后的失败可以留下新目标，但不冒充“目标不存在”。

9. **目标原句柄完整验真。** 目标 genesis 在首次写入前取得独占锁；64 KiB 缓冲复制每个文件准确原字节，并检查捕获长度之后的真实 EOF。全部文件 sync_all，Unix 再同步目标目录和父目录。目标的第一次全验直接使用这些原创建且持续持锁的句柄，不通过 unlock/drop/reopen 改变所认证对象。全验目标之后再次全验源，再做目标最后 bytes/namespace 检查才返回原 pin。

10. **游标与错误后不可续读。** 摘要和复制使用显式偏移；物理头克隆 rewind；逻辑 ActiveReader 自己维护每个文件偏移；普通 append 明确 seek 到捕获尾部。因此顺序执行不依赖 Windows 克隆游标的偶然值。短读持续进行，Interrupted 重试，其他读取错误失败关闭；真实 EOF 不能被逻辑长度代替。ActiveReader 一旦失败，后续 read 仍错误；Replay 错误会消费隔离 State，不能跳过损坏记录继续认证。

11. **部分复制、同步及回执失败。** cfg(test) 私有故障 1/2 留部分头/段，3 留完整但未完成最后文件同步的过程可见字节，4 位于同步之后且没有成功确认。3/4 的完整目标允许以后显式验证，测试明确不把这视为真实断电保证。5/6 确实在目标全验后/源最后全验后加入未知目录项，触发末次源或目标检查，不能返回成功；它们故意改变目录集合，只保证原文件字节不变。真实 CLI stdout 只读句柄使回执失败非零，完整目标保留并可以随后显式 verify。

12. **真实恢复、旧路径及挂载。** 两段真实增长 fixture 先在真实付款导致段轮换后备份/恢复，再继续第二跳至 10001，另做 10001 恢复及 10002 提交。新 CLI 集成 fixture 使用两笔真实非零支付，接收者从实际恢复历史首次扫描后花费，检查重复花费与所有余额。四个 active 命令共用新 API，旧命令的参数/JSON 语义保留；false 的 finality、validator_ready、real_funds_allowed 明确。新模块和 namespace 子模块确实挂载，新 CLI integration target 被现有 funded cargo metadata 全目标计划选中；没有修改 runner、工作流、锁定依赖、Go 接口或旧 32+1 资源测试来绕过回归。

本次源码清单仍为新核心测试 12 个、namespace 测试源码 7 个（平台 cfg 不同）、新 funded CLI 测试 7 个；C3 在已有增长测试中增加断言，没有新增测试名。配套 JSON 保存准确 C3 各读取文件的长度和 SHA-256、检查结论及 AR-C1-01 的关闭记录。实际平台测试数量应由 native auditor 根据准确 C3 日志确定。

本地没有 Rust/Cargo/Go，未编译、运行 cargo fmt/Clippy 或执行 Rust/Go/native Windows 测试，也未读取或认证 CI 结果。额外 `git diff --check base..C3` 只报告冻结设计文件结尾空白行；这是非运行的文档尾空白提示，不改变设计合同或上述结论，我保留了该已冻结设计的原字节。不能把这一静态检查说成所有源码工具门槛通过。

仍需保持的边界：独立 pin 不证明来源、最新高度或 finality；归档不是钱包、验证者签名状态、共识数据库/WAL 恢复，不是增量、快照或剪枝。可信父目录、操作系统和文件系统仍是前提，未证明任意恶意瞬时替换、映射视图绕过或真实断电/磁盘满条件。源和目标可能各保留最多 2048 段句柄，reader 还会克隆，没有新的全容量句柄/内存或归档性能测量；不能复用旧 32+1 指标宣称新归档成本。这是独立编码代理审查，不能称为外部机构安全审计。

在上述范围内，本审核对准确 C3 无未关闭阻断项；阶段合入仍须准确候选的原生 CI 全部满足既定要求，并保留最终证据。
