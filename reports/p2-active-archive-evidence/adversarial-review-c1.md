Zevune P2 活动账本归档：C1 独立对抗审查原文

结论：**CHANGES REQUESTED（冻结验收测试存在一项缺口）**。在本次检查的数据完整性、来源绑定、只创建新目标、句柄生命周期及故障路径中，没有找到可复现的“损坏归档被接受”或“已有源被覆盖”的运行缺陷；但 C1 没有覆盖冻结设计明确要求的活动归档段交换负例，不能据 C1 现有测试宣称全部冻结验收项已经完成。此结论不是原生 CI、部署或整个 P2 阶段的批准。

审核任务：`/root/p2_archive_adversarial_review`。本人没有编写、格式化或修改候选设计、运行代码及测试，也没有以其他审核者的结论代替本次判断。审核日期：2026-09-17 UTC。

准确身份：

| 项目 | 值 |
|---|---|
| 仓库 | `youq616/Zevune` |
| PR | <https://github.com/youq616/Zevune/pull/13> |
| 基线及 C1 第一父提交 | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| 本次候选 C1 | `c5f60ac440ac39032f8f8efefc2fbfbf6e299a90` |
| C1 tree | `10fb6d729c610aa1c935c96891c99e05f81d7dd1` |
| 冻结设计 | `docs/ACTIVE_ARCHIVE_V1.zh-CN.md` |
| 冻结设计 SHA-256 | `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee` |

初始工作区 HEAD 为准确 C1 且无工作区差异；作者随后准备下一候选。本报告的结论与文件清单固定到上述 C1 git 对象，后续提交不得自动继承本报告。审核期间只进行了代码、git 对象及官方文档读取，以及独立 Python 摘要复算；唯一新写入的文件是本报告和配套审核 JSON，位于候选仓库之外。

**阻断项 AR-C1-01，优先级 P2：活动归档缺少段顺序交换的独立负例。**

冻结设计“冻结验收要求”第 4 项明确列出交换段的拒绝行为。C1 的 `pool/recovery/active/tests.rs` 对同一逻辑流做提前轮换和跨帧拆分，CLI 测试做缺段、额外文件、截断、尾字节等；`active_flow_tests.rs` 已有两段真实增长、精确备份恢复和重算校验和后的无效签名拒绝。这些用例没有交换两个已存在段的内容。对准确 C1 的源码检索中，唯一 `swapped` 用例是旧 `pool/recovery/segments/tests.rs::missing_extra_swapped_truncated_or_changed_segments_are_rejected`，它测试的是旧 ZVPSEG01，不能代替新 ZVARCP01 / ActiveSegmentsV1 路径。

这是一项冻结测试合同缺口，而不是声称运行代码已经接受交换后的目录。静态实现中，规范 layout hash 将段序号、长度和原始字节一起绑定；即使攻击者重算 layout pin，完整重放仍应检查记录的前序 AppHash、高度和真实授权。补充测试的目的，是实际执行这两层拒绝行为并避免日后误删检查。

建议复用 `real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` 中已经真实产生的两个段，无需额外构造证明、降低段容量或使用合成记录。在副本中交换 `00000000.journal` 和 `00000001.journal` 的全部原始字节，保留合法头与段名称：先用原独立 pin 断言拒绝；再重算规范布局摘要、形成结构合法的新 pin，断言 `ActiveArchive::open` 明确返回 `PoolError::Corrupt`，从第一条记录的前序状态不匹配处拒绝。补充相同文件集合及逐字节不变断言，并保留正常原目录可验证的正对照。完成后需对新准确提交复审，并由原生 CI 实际执行新增断言。

本次独立检查及依据：

1. **codec 和资源边界。** `from_bytes` 先判断准确 128 字节与 magic，长度短路避免短输入切片越界；之后才读取字段。三个摘要非零、1000000 记录、1 GiB 逻辑字节、2048 段、头长上界及 32 字节对齐、零高度与零段的关系均有检查。减法和记录字节乘法使用 checked 运算，未发现整数截断放大输入容量。布局摘要的段序号和长度转换依赖私有 ActiveJournal 已执行的固定段数及 1 MiB 单段上界。新 codec 单元用例覆盖所有 128 个前缀截断、尾字节、互斥旧格式、边界和溢出值。这些是源码覆盖判断，不是测试运行结果。

2. **独立布局向量。** 我用 Python `hashlib` 独立构造 `ZVOPOL03 || SHA256(zevune-orchard-lab-1) || [7;32] || u32be(0)`。头长 76，头摘要为 `07782393f4021cabba3a8a09f0d2747e6ae4404457475c6e9df85100f734bc1e`；布局输入 `ZVARLY01 || u32be(76) || header || u32be(0)` 为 92 字节，摘要为 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`，与 C1 固定常量一致。此向量只验证编码与摘要，不证明支付授权、可信来源或共识。

3. **物理头与独立 genesis 绑定。** `ActiveJournal::read_header` 在保留的 genesis 文件内按其捕获物理长度解析，要求解析头长相等及真实 EOF，无法从首段借取伪造承诺数量所需字节。共享 `PoolStore::replay_active_handles` 再比较物理头和逻辑头，并把重新构造的 `State.genesis` 与调用者传入的独立预期摘要比较。正常 open 传入独立初始头的 SHA-256，导出传入已拥有 State.genesis，归档传入独立 pin.genesis。因此没有把第一次名称打开时读到的头当成随后重放时唯一身份依据。同长度原句柄篡改回归通过原拥有句柄写入，避免 Windows 的另一个文件句柄锁错误掩盖所测 genesis 比较。

4. **完整重放与真实授权。** 每次共享重放均构造新的 AuthorizationVerifier；`Replay::next_block` 检查前序 AppHash，在隔离的临时 State 执行实际域、到期、锚、重复花费、输出、签名及证明规则，核对记录后状态。每条完全解析记录均调用 `validate_frame`；最后需要真实 EOF、finish 和 namespace 检查才发布普通 PoolStore。归档不暴露该临时 State。`active_flow_tests.rs` 修改真实付款的绑定签名并重算 record checksum 及完整新 layout pin，要求归档明确返回 Authorization，避免把旧摘要或平台锁失败当作密码学拒绝。

5. **导出与重复验证。** 检查点导出在重放前后计算完整物理摘要，并比较全部 committed Summary、独立 genesis 与容量。新 API 首先拒绝 legacy，不让健康旧 store 因不支持格式而失效；实际导出错误使活动 store 不可用。PreparedBlock 位于调用者手中，导出不消费或重写它。`ActiveArchive::verify` 每次重新执行摘要、真实重放、pin 高度/AppHash 和末次字节检查；它不把过去一次验证或缓存结果当作再次验证成功。错误后没有返回部分认证的状态对象。

6. **源只读、合作锁和名称绑定。** 新源通过 `read(true).write(false)` 打开，并持有 genesis 的共享锁；普通 writer 保留独占锁。目录及每个文件句柄持续存在，Unix 检查设备/inode、symlink 与多硬链接，Windows 继承既有不共享 DELETE 的名称保护及 reparse 拒绝。没有发现对已持锁句柄或其克隆再次加锁，也没有先打开可写 store 再解锁重开的做法。Rust 1.98.1 官方 File 合同允许多个共享锁、排斥独占锁，并说明重复加锁和非持锁句柄读写行为有平台差别。候选按此区分原 owning handle、克隆 reader 与其他路径句柄。[Rust File 官方合同](https://doc.rust-lang.org/std/fs/struct.File.html)

7. **Windows 检查没有把普通权限失败包装为锁证据。** 原生测试要求 readonly 写入拒绝发生在任何归档锁之前，并检查 error 5；名称保留用例先确认测试文件可写，在两个归档及只剩一个归档时要求实际 rename/delete 拒绝，检查 error 5 或 32，全部 drop 后再完成同一路径 rename/delete 正对照。双进程测试通过精确测试名称与输出中的 `1 passed` 防止零测试子进程被误判成功，并覆盖共享读者、writer 排斥及 drop 释放。Microsoft 的共享锁合同允许读取共享锁区，阻止普通写入；这支持在归档共享锁期间检查源字节，但不支持在另一个句柄上读取普通 writer 的独占 genesis。上述断言仍必须在 Windows CI 中实际通过。[LockFileEx 官方合同](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)

8. **Windows 名称保护的技术依据。** `retain_name` 去掉 FILE_SHARE_DELETE，保留 READ/WRITE 共享；目录附加 BACKUP_SEMANTICS 与 OPEN_REPARSE_POINT，未丢失后者。官方 OpenOptionsExt 合同说明 share_mode 替换默认共享标志、custom_flags 后次调用覆盖前值；CreateFileW 说明删除权限也用于重命名。候选遵守这两个合同，没有把相同长度或时间戳当作 Windows 文件身份。本结论限定普通文件系统操作及可信父目录，不扩展到任意恶意瞬时替换或映射视图写入。[Rust Windows OpenOptionsExt](https://doc.rust-lang.org/std/os/windows/fs/trait.OpenOptionsExt.html)、[Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)

9. **目标创建与持续句柄。** `copy_new` 先检查源仍绑定保留句柄，再 canonicalize 源和目标父路径，拒绝源内目标及已有目标；全源 verify 在任何目标创建之前。底层使用非递归目录创建和逐文件 create_new，Unix 模式为目录 0700、文件 0600，源句柄不能写；没有删除、截断、覆盖或修复分支。64 KiB 缓冲读取每个捕获长度及真实 EOF，目标 genesis 在写入前持独占锁。所有文件 sync_all 后，Unix 再同步目录及父目录。目标完整重放直接使用创建时的原句柄，未经过 drop、unlock 或路径 reopen。目标全验后再完整验证源，并检查目标最后字节与 namespace 才返回 pin。

10. **游标与失败状态。** 摘要和复制每次按显式偏移读取；物理头克隆先 rewind，逻辑 ActiveReader 自己维护偏移，append 原路径显式 seek 到尾部。因此串行调用没有依赖 Windows 克隆共享游标的偶然位置。每个物理文件既读够捕获长度也检查实际 EOF。ActiveReader 遇到错误后保留 failed 标志；临时 Replay 的错误状态被消费，不能捕获错误后继续认证余下历史。

11. **部分写入与确认丢失。** 私有 cfg(test) 1/2 分别留下部分 genesis/首段；3 留下最后文件写完、未进行其同步的过程可见完整字节；4 位于文件和相应目录同步之后。测试允许 3/4 的完整字节随后显式验证，并明确 3 不代表持久化、4 也不代表真实断电。5 在目标全验后插入未知源目录项，6 在末次源验证后插入未知目标目录项，均通过生产末次检查拒绝。5/6 故意改变目录集合，不能报告“整个源/目标目录未变”；测试分别移除注入项后检查原文件字节，表达正确。实际 stdout 只读句柄测试还覆盖成功复制后回执失败的非零退出和完整目标保留。

12. **真实恢复路径与旧合同。** 已有真实支付增长用例在首次付款导致第二段之后从独立副本恢复，再继续接收者花费至 10001；10001 再归档、恢复后提交 10002。CLI 另有两笔真实非零支付，Bob 首次扫描恢复目录后花费，并检查重复付款拒绝、钱包余额和源/归档未变。新四命令共用 ActiveArchive 路径，成功输出保留 false 的 finality、validator_ready、real_funds_allowed，旧路径参数和旧 JSON 没有改义。公共恢复没有获得可写 PoolStore 或跳过完整重放的接口。

覆盖数量仅作源码清单：新 active recovery 核心测试 12 个、namespace 源码测试 7 个（Unix 两项、Windows 一项受 cfg 限制）、新 funded CLI 集成测试 7 个；既有 active-flow 的 4 个测试保留并扩展。`recovery::active`、`tests` 及 `namespace_tests` 的模块声明存在，新 CLI target 由现有 funded cargo metadata 全量枚举机制选择。准确平台运行数量、结果、耗时及全部旧回归是否执行，应由本候选 CI 原日志确定，不能从这些静态数量推导通过。

未执行与限制：本地没有 `rustc`、`cargo`、`go`，因此没有编译、cargo fmt/Clippy、Rust/Go 测试、实际 Windows 进程锁、四节点、100000 块或 32+1 资源运行。本报告没有读取 CI 结果，也不认证 CI 成功。最大 2048 段及复制/重放的同时句柄、全历史状态成本保持真实；没有测量新归档操作的性能、全容量耗尽、磁盘满或真实断电。完整性摘要和私下保存 pin 不建立来源认证、最新高度或 finality；本阶段不含钱包、验证者签名状态、增量、快照、剪枝或外部安全审计。

AR-C1-01 修复且新准确候选通过独立复审和全部要求的原生 CI 之前，不能合入或把本阶段标记为已验收。
