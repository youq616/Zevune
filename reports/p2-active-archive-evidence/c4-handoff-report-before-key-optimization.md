# P2 活动账本归档与完整恢复：阶段验收记录

状态：**交接草稿，阶段尚未接受。** 当前冻结候选为 C4，两路非作者独立代码与测试设计复审已通过，未关闭源码阻断为 0；完整原生 CI、实际合入和最终文档复审仍待完成。C3 的两份初始静态 PASS 保留为历史，后续原生反例与独立补充已确认 AR-C3-02 并拒绝 C3；不能据旧 PASS 接受 C4。

本阶段限定于既有 LAB2 / ZVTGEN03 / ActiveSegmentsV1 活动账本的检查点绑定完整公开字节副本。它沿用原目录布局，连接 `zevune-pool-recovery` 的四个显式活动命令；P2 整体继续开发。

## 1. 准确身份与验收状态

| 项目 | 记录 |
|---|---|
| 仓库 / 开发入口 | `youq616/Zevune` / `dev/m12-genesis-domain` |
| 实际阶段基线 | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| 基线 tree | `5e039b41e00f7a0a2e78937c796a40fbe68bfb0c` |
| 冻结设计 | [ACTIVE_ARCHIVE_V1.zh-CN.md](../docs/ACTIVE_ARCHIVE_V1.zh-CN.md)，13188 B；SHA-256 `de6d9639d724b777a8d4a937fa5e21b1b70880585ec8d0c0bf9336bff87a9cee` |
| 当前冻结候选 C4 head / tree | `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736` / `3c44977028b58ddd387f52946632af594208edfb` |
| C4 唯一父提交 | `7045af4ae254f0a5a5e4810f17004c91e649e474`（C3） |
| PR / base | [PR #13](https://github.com/youq616/Zevune/pull/13) / `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| C4 PR synthetic checkout | `fb5ec39a59cb87aec0662c7706dce1f9e85e1962`；parents 按顺序为阶段 base、C4，tree 与 C4 相同，已由 root/API 核对并保存于 [C4 清单](p2-active-archive-evidence/candidate-c4.json)；runner 实际检出仍由本轮原生日志逐一核对 |
| 本阶段接受条件及实际结论 | PENDING_STAGE_ACCEPTANCE |
| 运行代码实际合入提交、父提交及 tree | PENDING_RUNTIME_MERGE |

基线 tree 不包含本次新增设计及实现；不能拿它代替候选 tree。PR 的测试 checkout、候选源码和实际 merge 提交分别记录，只有实际核对后才可称树相同。后续仅归档文档的提交须另行核对运行代码、测试、依赖和工作流字节，并接受独立文档审核。

## 2. 冻结交付合同

以下为[准确冻结设计](../docs/ACTIVE_ARCHIVE_V1.zh-CN.md)的合同摘要；最终实现覆盖情况以第 4、5 节的准确源码和证据为准。

- **保持完整物理布局。** 归档目录直接保存原 `genesis` 和从 `00000000.journal` 开始的连续完整记录段，每个文件的长度、段顺序及字节保持相等。没有 MANIFEST、包装目录、重新分片、状态快照或外来索引。
- **新增独立 pin。** `ZVARCP01` 固定 128 B，CLI 使用准确 256 个小写十六进制字符；绑定 genesis 摘要、高度、AppHash、逻辑总字节、物理头长、段数及 `ZVARLY01` 规范布局摘要。逻辑字节包括 genesis 和所有段。严格长度、checked 运算及容量关系在文件读取和不可信分配之前检查；结构合法仍需真实重放。
- **独立可信来源。** pin 必须通过独立可信渠道保留。与不可信归档一起收到的未认证 pin 不证明来源；旧合法 pin 只能认证旧历史，不证明最新状态。布局 SHA-256 是完整性绑定，不是签名、隐私证明或共识最终性。
- **完整重新验证。** 活动 store 的检查点导出、每次归档验证和目标验证均以新 `AuthorizationVerifier` 完整重放真实授权与状态。先在保留的 genesis 物理文件中解析 03 头并确认准确 EOF，再读取段；逐记录检查物理边界和规范轮换。导出时比较完整已提交 Summary；归档验证时将重放所得 genesis、高度和 AppHash 与独立 pin 比较，同时核对容量、物理布局及摘要。真实 EOF、前后字节及 namespace 检查完成后才返回结果。
- **保留原句柄。** 归档源持有只读文件句柄及 genesis 共享锁；普通活动 writer 仍持独占锁，多个归档读者可以共存。目标通过 create-new 的原创建句柄写入、持锁和完整重放，不先释放句柄再从路径打开验证。克隆句柄可能共享游标，读取明确定位且串行执行，不重复对已持锁句柄加锁。
- **只创建新目标。** 所有路径绝对；目标父目录已存在。创建前拒绝已有目标、源内目标和父路径别名指向源内的目标，并完整验证源。按 64 KiB 有界缓冲准确复制，文件 `sync_all`；Unix 另同步目标目录和父目录。成功前再完整验证源并核对目标最终字节及 namespace。
- **保留错误结果。** 创建后失败可留下部分或完整新目标，不自动删除、覆盖、截断、重建或重试。完整副本即使成功回复丢失，仍可按原 pin 另行显式验证。错误返回不证明目标不存在或没有完整副本。

新 API 为 `PoolStore::active_recovery_checkpoint`、私有字段的 `ActiveRecoveryCheckpoint` 和只读 `ActiveArchive::open / checkpoint / verify / copy_new`。`backup-active` 与 `restore-active` 共用 `copy_new`；归档对象不提供可写 PoolStore、状态导入或节点启用能力。

| 新 CLI 命令 | 独立输入和动作 |
|---|---|
| `checkpoint-active` | 通过独立 03 清单及其摘要打开原 store，绑定可信高度和 AppHash，再导出新 pin；沿用普通 store 的读写访问及独占锁要求，但不改账本字节 |
| `backup-active` | 按独立 pin 验证只读源，精确复制到不存在的新归档目录 |
| `verify-active` | 按独立 pin 对只读归档重新完整验证 |
| `restore-active` | 使用同一复制算法，恢复到不存在的新活动目录；目标此时没有作为节点启动 |

四命令均要求 `--no-real-funds`，拒绝缺失、重复或未知参数、错误 profile、相对路径和非规范数值/hex。活动成功 JSON 明示 `replay_verified:true`、`finality_verified:false`、`validator_ready:false`、`real_funds_allowed:false`，以及操作、pin、格式、profile、height、AppHash、bytes 和 segment_count。stdout 写入失败返回非零；错误文本不泄漏用户路径或私密内容。

旧 `ZVPRCP01` 120 B 检查点、`ZVPSEG01` 分段备份、派生索引和旧命令保持原含义，仍拒绝活动 profile；新活动接口拒绝 legacy。请求不支持的 profile 先拒绝，不使健康 store 失效；真实存储、身份或历史错误仍按既有规则失败关闭。旧 Go 网络 `CopyStorageAtCheckpoint` 对活动 profile 的拒绝保持。本阶段不改变签名域、交易与日志编码、IPC、容量、依赖或既有五文件交付包。

## 3. 已收到的设计审核

独立设计审核任务 `/root/p2_archive_review` 于 **2026-09-17 08:03:18 UTC** 对上表准确设计给出 **PASS，仅限实现前设计**。原文为 [design-review.md](p2-active-archive-evidence/design-review.md)，8774 B，SHA-256 `a87eebfc684c85c372ac3b4b941b1a7c915a043b669a7c4885fcd4a84953512c`。该任务没有编写设计、实现、测试或工作流，并核对了现有存储、重放、恢复、CLI 及测试调用方。

设计审核没有运行编译或测试，也没有可供审核的实现 head/tree；其 PASS 不表示后续实现、原生 CI、阶段合入、生产可用性或外部安全审计通过。准确实现的独立复审另见第 4 节，不由设计 PASS 代替。

独立 Python 布局向量记录于 [layout-vector.json](p2-active-archive-evidence/layout-vector.json)，880 B，SHA-256 `28741db9bdbfddaf07f0355752f932449c327685ec6f12ca0a4aa66728fe7ed5`。其中固定空活动头为 76 B、无段，规范布局输入 92 B，预期布局摘要为 `325fba79e5d367646d57a58c594264ae5b0d216af5ce1858e88b0f26a6a882ed`。这是独立固定输入向量，不含付款，也不是候选 Rust codec 已执行通过或真实授权的证明。

## 4. 当前准确候选的实现与独立代码审核

完整阶段仍为十个变更文件：以 [C3 十文件清单](p2-active-archive-evidence/candidate-c3.json)为基础，覆盖 [C4 清单](p2-active-archive-evidence/candidate-c4.json)所列两个实际修改文件；其余八文件与 C3 字节相同。本草稿逐一读取准确 C4 Git blob，核对上述合成清单的长度与 SHA-256。下面描述源码变更，不代表编译或执行通过：

| 文件范围（均在 `integration/orchard/`，设计除外） | C4 源码职责 |
|---|---|
| `docs/ACTIVE_ARCHIVE_V1.zh-CN.md` | 已冻结并独立审核的设计原件，字节保持 |
| `src/pool.rs`、`src/pool/active.rs` | 普通活动打开与归档共用的真实重放、只读保留句柄、物理头边界、布局摘要和原句柄复制 |
| `src/pool/recovery.rs`、`src/pool/recovery/active.rs` | 挂载新 API、新 pin codec、检查点导出、只读归档及 create-new 完整恢复 |
| `src/bin/zevune-pool-recovery.rs` | 四个显式活动命令、严格参数、独立检查点；C4 通过 owned OS 输出副本与直接 File 写入传播活动回执错误 |
| `src/pool/recovery/active/tests.rs`、`src/pool/recovery/active/namespace_tests.rs` | 新 pin、布局、完整复制、锁与 namespace、失败注入测试 |
| `src/pool/active_flow_tests.rs`、`tests/active_recovery_cli.rs` | 既有真实付款增长 fixture 的归档增量、C3 真实两段交换断言；C4 保留同名第七项 CLI 测试并加强四命令回执故障与可写文件正对照 |

相对阶段基线没有 Go 代码、Cargo/Go 依赖、工作流或测试调度器改动。C1/C2/C3 的候选、原初审核与后续失败不改写。AR-C1-01 的两段交换断言由 C3 引入、C4 保留；C4 的输出路径和断言已按当前准确提交独立复审，AR-C1-01 与 AR-C3-02 均在源码／测试设计层面关闭；实际原生执行仍待准确 C4 证据。

C4 两份正式独立复审原件已收到并全文核对，其适用身份为第 1 节准确 base、C4 head/tree 和 C3 父提交；均重新审核完整阶段变更与相关调用方，没有继承 C3 的初始静态 PASS。C3 在实际原生运行中新增 AR-C3-02，独立审核补充已明确不接受 C3；原件及完整观察边界保留在第 6 节。

| 独立任务及原文 | 结论与覆盖范围 | 原件身份 |
|---|---|---|
| `/root/p2_archive_review`；[code-review-c4.md](p2-active-archive-evidence/code-review-c4.md)，2026-09-17，本地身份观察 09:21:46 UTC 后另核对 GitHub synthetic | `PASS_CODE_REVIEW`；完整 base..C4、调用方、真实重放、布局／pin、平台句柄、CLI 和测试设计；AR-C1-01 与 AR-C3-02 在源码层关闭，未关闭代码审核阻断 0 | 16663 B；SHA-256 `a4bab8b1ae3fe05c185a82b4256bda8420ba5cbcf37c5c7304cbfceb708512e2` |
| `/root/p2_archive_adversarial_review`；[adversarial-review-c4.md](p2-active-archive-evidence/adversarial-review-c4.md)，2026-09-17 UTC | `PASS`，限定准确 C4 的独立代码与测试设计；完整阶段和对抗路径复核、AR-C1-01 保持源码关闭、AR-C3-02 源码修正通过，未关闭源码阻断 0 | 15431 B；SHA-256 `5d736cf901527a97cf27725212088432f6a1b943a9caccd02e1b94521e34b844` |

两位审核者均未编写、修改或格式化候选设计、源码、测试、工作流或依赖。主审核的[身份与字节观察](p2-active-archive-evidence/code-review-c4-observation.json)为 8674 B，SHA-256 `9608eadbabc493e66e88090c2a576f0fa8cd69a9b7c11cb8ddec9575f1cbce9a`；对抗审核的[完整结构化原件](p2-active-archive-evidence/adversarial-review-c4.json)为 28068 B，SHA-256 `c39f3f128b121b6903fe9fd8603c699084f8361814fb3c49e5b528cb05fc584c`。

**synthetic 核对来源分别记录。** 主审核者本地没有 synthetic 对象，首次 `git rev-parse synthetic^{tree}` 退出 128，随后通过 GitHub plugin 的只读 Git commit API 独立核对同 tree 及 `[base, C4]` parents；[API 原响应](p2-active-archive-evidence/code-review-c4-synthetic-github.json)为 2570 B，SHA-256 `0668331800cdd71258d9c091b4ef8cb94e6992996e7a43505340c7f1681ada36`。对抗审核者独立核对的是本地 source/tree/parent，其 synthetic 仅引用父任务提供值，本地无对象，未独立核验 synthetic 或 CI checkout。不能把两份报告合并描述为两者均独立核实合成提交；runner 实际检出仍须本轮完整原生日志证明。

两路实际执行限于 Git 身份／文件字节／差异检查、官方合同与历史日志阅读、独立 Python 布局摘要复算及静态审查，没有编译或运行 Rust/Go、fmt/Clippy、原生 Windows 测试，也没有认证 C4 CI。完整 `git diff --check base..C4` 退出 2，唯一诊断仍为冻结设计第 185 行 EOF 空行；主审核另记录排除冻结设计的源码／测试范围退出 0，设计原字节保持。

**代码关闭不等于原生验收关闭。** AR-C1-01 仍须准确 C4 funded-library 中的真实段交换完整用例通过；AR-C3-02 仍须准确 C4 双平台 CLI 第七项实际走完四命令、完整副本字节和显式 verify 后验断言，并完成原 interfaces cohort。两份代码 PASS 不替代完整必需原生门槛、阶段接受或最终文档独审，也不是外部机构安全审计。后续源码或测试改变须再次固定准确提交复审。

C4 相对 C3 只修改 `zevune-pool-recovery.rs` 和 `active_recovery_cli.rs`，合计 **+90 / -22 行**。活动回执新增 `write_active_receipt`：保留 `StdoutLock`，以安全 OS fd/handle API 复制为 owned 对象，再转成 `File` 直接 `write_all` / `flush`；复制或实际写入错误返回原非零失败路径，Windows 显式拒绝 NULL stdout handle。函数不关闭原 stdout、不重新打开路径、不重试账本复制，也不删除已完成的新目标；旧命令输出路径不变。此路径已通过上述源码／测试设计复审，双平台实际执行仍待本轮原生证据。

同名第七项 CLI 测试保留真实只读输出句柄，并加强为四命令逐一要求精确 exit 1、继承前先用该 `File` 直接写探针确认失败、可写文件输出精确 JSON 的正对照，以及 backup/restore 后完整字节与显式 `verify-active`。仍是 7 个顶层 CLI 测试，真实付款测试仍为两笔，不因扩展断言增加证明或计作更多独立测试通过。

回执 `File::flush` 不表示文件 fsync、磁盘持久化或下游已经消费回执；这里认证的是直接 File 写入的 OS 错误传播，不与账本复制的 `sync_all` 混同。Windows NULL guard 是已复审的源码防护，未设置专门 detached-console NULL fixture；现有只读／可写文件与捕获管道用例不能算该 NULL 分支或所有控制台输出环境的原生执行覆盖。

最终文档归档提交的准确身份、运行／测试／依赖／工作流字节等价核对、非作者独立审核原文和实际合入结果另记于 PENDING_HANDOFF_REVIEW_AND_MERGE_RECORD。

## 5. 准确候选的原生证据

PENDING_NATIVE_CI_EVIDENCE

以下映射来自准确 C4 的测试源码，**尚未据 C4 完整原生日志登记执行通过**。模块缩写仅方便定位：`R = pool::recovery::active::tests`，`N = R::namespace_tests`，`F = pool::active_flow_tests`，`P = pool::active::tests`；`CLI` 是 `tests/active_recovery_cli.rs` 的 funded integration target。所有函数名均为源码中的准确名称。

| 验收范围 | C4 函数／实际断言位置 | 证据边界；本轮执行状态 |
|---|---|---|
| pin codec 与独立向量 | `R::checkpoint_codec_has_exact_length_distinct_magic_and_bounded_arithmetic`；`R::exported_genesis_checkpoint_matches_independent_fixed_layout_vector` | 128 B、全部前缀截断/尾字节、格式互斥、边界与独立固定 hash；待原生日志 |
| 零高度、精确复制及继续提交 | `R::genesis_and_committed_archive_copies_preserve_every_file_and_continue_normally`；`CLI::active_cli_genesis_without_segments_is_an_explicit_checkpoint` | 原文件集合和每个文件字节相等，普通活动 open 后继续；待原生日志 |
| committed state、PreparedBlock 与不支持 profile | `R::checkpoint_export_preserves_prepared_work_and_never_certifies_uncommitted_bytes`；`R::incompatible_checkpoint_profiles_reject_without_poisoning_healthy_stores`；`R::checkpoint_export_replays_same_length_replacement_and_never_publishes_its_state` | 导出比较完整 committed Summary；不支持 profile 不 poison，真实历史错误不发布替代状态；待原生日志 |
| 保留句柄重放的独立 genesis | `R::retained_replay_binds_the_independently_expected_genesis_after_a_same_length_change` | 通过原持锁句柄改同长头，要求 `Genesis`，避免另一个句柄的 Windows 锁失败掩盖检查；待原生日志 |
| 物理头与域边界 | `R::repinned_headers_are_bounded_inside_the_physical_genesis_file` | 重算 pin 后分别要求准确 `Bounds`、`Corrupt`、`Genesis` 或 `Domain`；不能从段续读伪造头，含错 profile/network、零域和非法曲线点；待原生日志 |
| 真实帧、规范轮换及后状态 | `R::repinned_layout_still_requires_complete_frames_canonical_rotation_and_real_state` | 提前轮换、跨帧拆段、checksum、重算 checksum 后错后状态、尾字节均以实际 layout hash 相符为前提再拒绝；错误高度/AppHash 要求 `Stale`；待原生日志 |
| 正常多段恢复与两跳付款 | `F::real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` | 原 fixture 正常提交跨 1 MiB：6963 次空提交后，第一笔真实付款在 6964 高度触发第二段并归档恢复；恢复目录继续到 10001、完成第二跳真实付款，再对 10001 归档恢复并继续 10002。只有两笔真实付款，其余空块不计作付款；待原生日志 |
| **C3 引入、C4 保留：交换两个已存在的真实物理段** | 同一 `F::real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` 的新增 44 行，位于 10001 高度持久文件观察后 | 互换两段全部原字节，原 pin 与重算 pin 均断言 `Corrupt`；先核对生产布局摘要等于新 pin，再解码首记录并断言其前序 AppHash 不是 genesis。源与错误副本分别保持原文件集合及字节；待 C4 原生日志；C1/C2 没有该断言，C3 静态关闭记录不替代本轮执行 |
| 真实签名而非旧摘要拒绝 | `F::active_profile_domain_rejections_preserve_bytes_reservations_and_legacy_contract` 调用 `assert_noncanonical_layouts_reject` | 改真实 binding signature，重算 record checksum 与完整 layout pin；普通 open 和 ActiveArchive 均明确要求 `Authorization`，保留正常对照。CLI 的旧 pin 损坏用例不计这项授权证据；待原生日志 |
| create-new、源预验及既有目标 | `R::creating_a_target_is_exclusive_and_source_validation_precedes_creation`；`CLI::active_cli_locked_sources_and_existing_or_nested_targets_are_refused` | 目标原创建句柄持锁验证；已有/源内目标拒绝，坏源不创建目标；待原生日志 |
| 真实进程锁、只读源和失败后句柄释放 | `N::active_archive_locks_coordinate_real_processes`；`N::readonly_source_files_copy_into_a_normally_writable_active_directory`；`N::failed_open_releases_all_acquired_file_and_directory_handles`；`N::unknown_entry_after_open_prevents_verification_and_creates_no_target` | writer 与多读者、drop 后正对照、精确子进程测试选择及失败释放；子进程的重复单项结果不另加到库总数；待原生日志 |
| Unix 名称与父别名 | `N::persistent_entry_replacements_symlinks_and_hardlinks_are_not_certified`；`N::parent_aliases_and_replaced_directories_cannot_redirect_a_retained_archive` | 两项 `cfg(unix)`，链接、持久文件/目录替换及别名；不得计为 Windows 执行，待 Ubuntu 原生日志 |
| Windows 实际 rename/delete | `N::windows_files_and_directory_cannot_be_renamed_or_deleted_until_last_reader_drops` | 一项 `cfg(windows)`；两读者、剩一读者时均拒绝，最后 drop 后正对照；不得用 Ubuntu 替代，待 Windows 原生日志 |
| 部分写入与确认丢失 | `R::partial_copies_and_lost_acknowledgements_preserve_targets_without_retry_or_repair` | fault 1/2 留部分 genesis/首段；3 为写完但未完成最后同步，4 位于同步后；源字节与目标保留，3/4 完整副本可显式后验验证，均非真实断电；待原生日志 |
| 末次源／目标检查 | `R::final_source_and_target_namespace_changes_cannot_return_success` | fault 5/6 故意加入未知源或目标目录项，要求末次核验不能成功；原账本文件字节保持，但被注入的目录项集合已变。不能称整个目录不变；待原生日志 |
| CLI 真实付款、严格参数和 legacy | `CLI::active_cli_real_payment_backup_restore_and_receiver_spend`；`CLI::active_cli_bad_options_and_exact_tip_fail_without_changes`；`CLI::active_cli_keeps_legacy_profiles_pins_commands_and_json_separate` | 实际可执行文件，Bob 首次扫描恢复目录后再花费，重复付款拒绝；新旧命令/profile/pin/JSON 分离；待原生日志 |
| CLI 损坏源 | `CLI::active_cli_corrupt_missing_extra_and_split_files_fail_before_copy_creation` | 坏头/段、缺段/额外文件、截断/追加、提前轮换均保留原 pin；只获得 CLI 拒绝覆盖，不单独证明授权层拒绝；待 C4 原生日志 |
| **C4：四命令回执错误传播** | 同名 `CLI::active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable`；生产 `write_active_receipt` | 先检验可写文件收到精确成功 JSON；再对 checkpoint/verify/backup/restore 四命令逐项先用真实只读 File 写探针确认 OS 拒写，继承同一句柄后要求精确 exit 1。检查 sink 与原源字节，backup/restore 的完整新副本分别显式 verify，最后保留已有目标拒绝；待 C4 原生日志，C3 此用例的后验断言未执行 |
| **既有物理层空段/EOF 回归** | `P::unknown_missing_empty_and_truncated_segments_fail_closed_without_repair`；`P::captured_reader_requires_each_real_eof_and_poisoned_readers_cannot_resume` | 原有 `pool/active/tests.rs` 未由本阶段新增；空段拒绝在既有 `ActiveJournal` 物理层测试，不能冒称新增归档专用空段用例。仍须本轮原生日志确认 |
| 全部既有原生回归 | 默认及 funded 完整 library/interfaces、格式/Clippy/锁定构建、全部 Go test/vet、支持平台的 race/fuzz、100000 块增长、32＋1 资源、四节点 | 同一准确候选逐项确认，待完整 CI 汇总；旧阶段的成功不是本轮执行结果 |

静态清单为新核心库 12 个函数和 namespace 7 个函数；其中 namespace 的 4 项双平台、2 项 Unix、1 项 Windows，故新增库的源码执行预期是 Ubuntu 18／Windows 17。新 funded CLI target 为 7 项，默认未启用 feature 的零用例不算 7 项通过；既有 active-flow 的 4 项保留并扩展，C3 的 44 行和 C4 对原第七项 CLI 的增强均没有新增顶层测试函数；两笔真实付款/证明负载不变。默认与 funded 的重复运行、锁测试子进程和不同 workflow 的重复执行不能相加成新增覆盖。以上均为源码预期，不是已验收的实际测试计数。

CI 汇总需列实际观察时间、run/job/step 数、完整日志来源与 hash、候选和 checkout tree、工具链、Rust/Python/Go 实际结果及平台跳过原因。仅编译、过滤为零测试、条件跳过及重复执行不得合并成新增测试通过数。原代码候选、重复 push、合并和文档触发的运行分别记录；不能把一个事件已成功的状态套到另一个事件。

本阶段没有新增活动归档专用资源测量。上述增长/资源基线回归即使本轮重跑，也分别保持原固定负载的解释；前阶段 32＋1 的进程内存和耗时不能填作本阶段归档操作的资源数据。不能据 1 GiB 逻辑容量推断实际归档峰值内存、文件描述符预算、复制速度或机器容量。

## 6. 历史失败、修复和未知项

四个候选的准确身份和文件清单分别保留在 [C1](p2-active-archive-evidence/candidate-c1.json)、[C2](p2-active-archive-evidence/candidate-c2.json)、[C3](p2-active-archive-evidence/candidate-c3.json)、[C4 两文件增量](p2-active-archive-evidence/candidate-c4.json)，共同 PR 为 [#13](https://github.com/youq616/Zevune/pull/13)，共同阶段基线为 `6913d4ab2fda6956db37e0ceb49790a4518c2762`。

| 候选 | source / tree | 对上一个候选的变化和接受状态 |
|---|---|---|
| C1 | `c5f60ac440ac39032f8f8efefc2fbfbf6e299a90` / `10fb6d729c610aa1c935c96891c99e05f81d7dd1` | 初始实现；格式门槛失败，并存在 AR-C1-01 测试覆盖阻断；不接受 |
| C2 | `7477d9e0656ed751f525a4b6fe9f6649b995ede6` / `8e6544a6de9a8337926f70f8a89aa36e59ab7e39` | 父为 C1；修复 7 文件的 30 个 rustfmt hunk，未补交换测试；随后 Clippy 门槛失败；不接受 |
| C3 | `7045af4ae254f0a5a5e4810f17004c91e649e474` / `4017bee976c18767ed568d7ec8a33f6d668b8c22` | 父为 C2；补 44 行交换断言及单行 lint；初始静态 PASS 后由原生反例和两路补充确认 AR-C3-02；不接受 |
| C4 | `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736` / `3c44977028b58ddd387f52946632af594208edfb` | 父为 C3；仅活动回执生产路径和同名 CLI 测试 +90/-22；两路源码／测试设计复审 PASS，完整原生 CI 与阶段接受待定 |

**C1 原生格式门槛。** 非作者 `/root/p2_archive_native_audit` 的[原生拒绝记录](p2-active-archive-evidence/c1/native-audit-rejected.md)为 `REJECTED_NATIVE_FORMAT_GATE`。2026-09-17 08:22:35 UTC 的 job 观察及五份完整日志确认 `cargo fmt --check` 在 7 个变更 Rust 文件输出 30 个差异 hunk，退出 1。已保存的失败任务为 `105129273810`、`105129276084`、`105129274242`、`105129274366`、`105129274663`，合计 237377 B；不是 C1 全部矩阵日志。其 PR synthetic checkout 为 `604e1d5ebd44093d9e1337de61e3e47297dd4223`，由该审核核对 parents 为基线和 C1、tree 等于 C1。失败步骤之后的 Rust 测试、Clippy 和真实资源场景没有因此取得通过证据；失败前已执行的 Python 项也不能替代归档测试。其他 job 和独立 push 观察保留各自时间与未知终态，没有将它们一律写成失败或成功。

**C1 两路审核及补充。** `/root/p2_archive_review` 于 08:23:10 UTC 的[主审核原文](p2-active-archive-evidence/code-review-c1.md)起初给出静态 `PASS_CODE_REVIEW`，明确没有执行 CI、编译或测试。另一非作者任务 `/root/p2_archive_adversarial_review` 的[对抗审核](p2-active-archive-evidence/adversarial-review-c1.md)随后给出 `CHANGES REQUESTED`，发现 **AR-C1-01，P2／Medium 验收覆盖阻断**：未交换两个已存在的活动段，并分别以原 pin、重算 pin 检查拒绝。旧 ZVPSEG01 的交换用例不能代替新 ActiveArchive。该发现是冻结测试合同缺口，不是已证明运行代码接受损坏归档的漏洞。

主审核者于 08:26:49 UTC 的[补充原文](p2-active-archive-evidence/code-review-c1-addendum.md)确认格式失败和上述缺口，明确 C1 不满足合入条件、C2 未获得正式 PASS。初始 PASS 原件不改写、不隐藏；其“工作树干净”只对应 `2026-09-17T08:23:10.328331+00:00` 的观察，不能套到作者后来开始暂存格式修订的时点。该审核还记录完整 diff 的唯一 whitespace 诊断为冻结设计第 185 行 EOF 空行，退出 2；排除冻结设计后的源码／测试 diff 检查退出 0。不能把完整范围描述成毫无 whitespace 诊断，冻结设计字节保持。

**C2 原生 Clippy 门槛。** [原始日志](p2-active-archive-evidence/c2/job-105130677319.log)记录 run [35199527967](https://github.com/youq616/Zevune/actions/runs/35199527967)、Ubuntu job [105130677319](https://github.com/youq616/Zevune/actions/runs/35199527967/job/105130677319)，实际 checkout 为 `bc2e180ec53be25ee36b80931adbd5e8dbe1d9a3`。`Verify exact source and unchanged locks` 步骤依次运行 fmt、metadata 和 Clippy；fmt 已完成，08:26:20 UTC 在 `src/pool/recovery/active.rs:88` 出现 `clippy::manual_is_multiple_of`，由 `-D warnings` 升为错误，08:26:21 退出 **101**。诊断为 `(header - MIN_HEADER) % 32 != 0`，建议 `!(header - MIN_HEADER).is_multiple_of(32)`。失败前日志另有 Python `Ran 135 tests`、`OK (skipped=3)`，不作为归档 Rust 或 C3 测试的通过结果。本候选完整矩阵未获接受、也未全量归档。

**C3 的 AR-C1-01 源码修正及初始静态复审。** C2→C3 精确 diff 只有两个文件：`active_flow_tests.rs` 增加 44 行；新 pin codec 的余数检查改一行，没有关闭 lint 或改边界。44 行直接复用既有增长 fixture 在 **10001** 高度的两个真实段，互换完整段字节和各自完整记录 checksum。原 pin 要求 `Corrupt`；重新按规范布局生成的 pin 先与生产 `layout_hash` 比较相符，再解码交换后的第一条记录，确认其高度是原第一笔付款高度、前序 AppHash 不是 genesis，最后仍要求 `Corrupt`。两次拒绝都核对原源和错误副本的文件集合及字节不变；随后原正常目录继续归档恢复作为正对照。没有新增证明、改变 1 MiB 容量、降低授权或调整工作流。两路 C3 初始静态复审据此确认 AR-C1-01 在源码与测试设计层面关闭；这项历史判断不等于 C3 整体接受，也不为 C4 提供原生执行信用。


C3 的两份初始静态 PASS 原件保留如下，准确适用对象为上表 C3，不适用于第 1 节的新 C4：

| 独立任务及原文 | 实际结论与范围 | 原件身份 |
|---|---|---|
| `/root/p2_archive_review`；[code-review-c3.md](p2-active-archive-evidence/code-review-c3.md)，2026-09-17 08:32:06 UTC | `PASS_CODE_REVIEW`；重新核对完整阶段 diff、调用方、恢复流程、平台句柄和测试设计；AR-C1-01 在源码层关闭，代码审核未关闭阻断 0 | 14909 B；SHA-256 `7c864c3e9288c4dbae9149fc9bddec3de9113926a014ff6c092c2d5db12b05cf` |
| `/root/p2_archive_adversarial_review`；[adversarial-review-c3.md](p2-active-archive-evidence/adversarial-review-c3.md)，2026-09-17 UTC | `PASS`，限定准确 C3 的代码与测试设计；独立重新核对全部变更和对抗路径，确认 AR-C1-01 关闭，未发现其他代码候选阻断 | 12629 B；SHA-256 `127d9ef1b798aeb008542e58af6241a8efe24799cba59ef2014bc4ec7c7f0f2b` |

两份原文均明确未执行 Rust/Go 编译、测试、fmt、Clippy 或原生 Windows 运行，也未认证 CI。原初静态检查的完整 `git diff --check base..C3` 退出 2，仅有冻结设计第 185 行 EOF 空行；排除冻结设计的源码／测试范围退出 0，不能把完整范围写成毫无诊断。**下述真实运行反例纠正了两份原初静态审核对 stdout 错误传播路径的肯定，原件不改写，C3 仍不可合入。**

**C3 原生回执回归失败。** 非作者 `/root/p2_archive_native_audit` 的[拒绝 Markdown](p2-active-archive-evidence/c3/native-audit-rejected.md)及[定量 JSON](p2-active-archive-evidence/c3/native-audit-rejected.json)，记录时间为 `2026-09-17T09:10:54.690169+00:00`，结论 `REJECTED_NATIVE_CLI_REGRESSION`。准确 PR synthetic checkout 为 `11402e8d8db1e2ae9b6d8615ea9f6362e8676606`。Ubuntu funded interfaces [run 35199878279 / job 105131817273](https://github.com/youq616/Zevune/actions/runs/35199878279/job/105131817273) 的 fmt、锁文件和 funded Clippy 步骤已成功；失败发生在 `Complete binary, integration and documentation tests`。

[原始日志](p2-active-archive-evidence/c3/job-105131817273.log)在 **09:07:51 UTC** 记录同名第七项 CLI 测试失败，check-run 于 **09:07:53 UTC** 完成。新 `active_recovery_cli` target 为 **6 passed / 1 failed / 0 ignored / 0 filtered，137.53 s**；其中低高度真实两笔付款与恢复测试属于六个实际 `ok`。失败点是 `tests/active_recovery_cli.rs:106:5` 的 `!output.status.success()`：真实只读 stdout fixture 的子进程却返回成功。该 cargo 调用总共取得 6 个 harness 结果、20 pass 和 1 fail，含五个 bin target 与该失败 CLI target；它没有 `FUNDED_COHORT_COMPLETE interfaces`，后续计划的 integration/doc、独立 bins build、互操作和该 job 四节点步骤不能记为通过。driver 显示 `FUNDED_COHORT_NOT_COMPLETED: CalledProcessError`，job step 退出 1。

**失败断言的执行边界。** `failure()` 在第一条状态断言即 panic，连该 helper 后续 stdout/stderr 检查也未执行，更未达到 sink 文件、原源/目标字节、目标后验 `verify-active`、已有目标拒绝及最终字节断言。不能把 C3 这次失败称为“完整目标保留已验证”，也不能据此日志断言目标必定完整或不存在。日志没有 stdout OS errno 或底层写错误，直接证据是这次 fixture 调用成功退出；根因分析与原生直接观察分开记录。

**AR-C3-02 的独立后验纠正。** `/root/p2_archive_adversarial_review` 于 09:12 UTC 的[补充](p2-active-archive-evidence/adversarial-review-c3-addendum.md)为 `REQUEST_CHANGES`，主审核者的[补充](p2-active-archive-evidence/code-review-c3-addendum.md)亦确认 C3 不可接受并承认初次静态漏检。二者将问题记为 **AR-C3-02／P2（Medium）：活动 CLI 回执错误传播缺陷**，不是账本复制损坏、密码学拒绝或目标删除。原 AR-C1-01 的源码关闭记录保持；新的输出缺陷必须修生产路径，不能把非零测试放宽为成功。

两份补充把失败与 Rust 官方 `StdoutRaw → handle_ebadf` 的源码行为相对照：标准 stdout 抽象会将匹配 EBADF 转为成功，Unix 只读 fd 的写错误因此可能在到达调用方 `map_err` 前被消化，stdio 的 flush 不补回该错误。仅对 stdout lock 的 `write_all + flush` 使用错误传播不足以满足冻结合同。这是结合准确 C3 控制流、实际反例和[官方 stdio 源码](https://doc.rust-lang.org/src/std/io/stdio.rs.html)／[Unix stdio 源码](https://doc.rust-lang.org/src/std/sys/stdio/unix.rs.html)的因果分析，不是日志中直接打印的 errno，也未声称逐字节鉴定 CI 的 libstd 二进制。

**C3 保存范围。** 本轮失败观察保存 7 份完整 PR 原件，**6 份成功、1 份失败，共 412261 B**，精确清单见拒绝 JSON；不声称 C3 全部 23 个预期 job 已完成或均失败。已取得的默认库成功包括 Ubuntu orchard-bridge：库 139／默认全部 153；Windows wallet：库 132／默认全部 146，均 0 failed/ignored/filtered。新增默认库的 18／17 项已逐名确认，默认 CLI 的 cfg 排除零用例不能算 funded 七项通过。这些历史成功不能替代 C4 本轮验收。09:08:27 的独立快照有 21 个实例化 PR jobs，7 success、1 failure、5 in_progress、8 queued；其中第七个 success 只有完成元数据、未另取完整日志，另两个 growth jobs 未在该快照取得完成证据。queued 的工作流列表与实际矩阵日志分别保留，不推断其机制或所有成员未运行。独立 push Windows bridge job `105131805112` 的 cancelled 只保留其 08:29:49–08:50:01 UTC 元数据，不推断取消原因或计入必需 PR 结果。

**C4 修正范围与待验收。** 按当前准确 C4 diff，生产回执改为持锁的安全 owned fd/handle 副本转 `File` 直接写，Windows NULL 明确拒绝，原 stdout 不被关闭。原只读 sink 用例保留并增强为四活动模式、精确 exit 1、OS 写探针、可写文件正对照及 backup/restore 副本后验检查。两文件 +90/-22，不改存储、真实付款／证明数、冻结设计、工作流、依赖或旧命令路径。两路准确 C4 原件已确认 AR-C3-02 在源码／测试设计层面关闭；实际执行成功和阶段接受仍待完整原生证据，不能继承 C3 的静态 PASS 或部分历史成功。

**C4 同提交的 Windows wallet 取消与一次单任务重跑。** 以下为固定在 2026-09-17 09:53:54 UTC 左右保存的历史观察，不是完整 C4 当前结果汇总。源码仍为第 1 节准确 C4，tree、工作流、25 分钟限时、依赖和全部测试未修改；两份 C4 源码审核仍适用于相同候选，原生验收继续待定。

[wallet run 35204106260](https://github.com/youq616/Zevune/actions/runs/35204106260) 的 Windows attempt 1 [job 105145580574](https://github.com/youq616/Zevune/actions/runs/35204106260/job/105145580574)，元数据起止为 **09:25:12–09:50:17 UTC，25 分 05 秒**，最终 `cancelled`。[完整日志](p2-active-archive-evidence/c4/job-105145580574.log)实际检出 C4 synthetic `fb5ec39a59cb87aec0662c7706dce1f9e85e1962`，包含 **18 个默认 harness 结果、146 pass、0 fail/ignored/filtered**；其中库为 **132 pass，1122.67 s**。这是该次默认测试步骤已成功的证据，不能扩为完整 job 成功，也不能计为默认 cfg 排除的 funded CLI 七项通过。

[具体 job 元数据](p2-active-archive-evidence/c4/job-105145580574-metadata.json)及 [09:51:51.685Z 的 run/jobs 观察](p2-active-archive-evidence/c4/wallet-cancel-run-jobs-observation.json)明确将 `Strict static checks` 记为 `cancelled`，最后 `Assert no tracked source or dependency drift` 为 `skipped`。日志 **09:50:13.5240250Z** 有 Clippy `Finished release ... in 25.02s`，约 **69 ms** 后的 **09:50:13.5931481Z** 记录 `The operation was canceled.`；不能把这行 Finished 改写为整个静态检查步骤通过，也不能为跳过的最终源码漂移检查补计通过。

耗时与既有 25 分钟 job 限时相符，只能作为推断。审核者未通过可用接口取得取消 annotations，日志也没有明确给出 timeout 原因；**取消原因未独立确认**，不能断言是 timeout、测试失败或 Clippy 失败。完整观察、尝试读取 annotations 的结果及因果边界见 [wallet-cancel-observation.json](p2-active-archive-evidence/c4/wallet-cancel-observation.json)。本次原日志为 **59588 B**，SHA-256 `a790c404ae69d567175690cb37ec23864a6499da4afb8f60005e051981522515`，UTF-8 BOM 和 742 组 CRLF 均保留。

root 于 **09:52:57 UTC** 仅对取消的 Windows job 发起一次原候选、原限时和原测试集重跑；[请求与工具回执](p2-active-archive-evidence/c4/wallet-rerun-request.json)的 `success:true` 只证明请求成功，不能证明新执行成功。attempt 1 的取消及全部原件保留，不以重跑覆盖历史。

| 固定观察中的任务身份 | 原始时间与状态 | 计数／解释边界 |
|---|---|---|
| Windows attempt 2，新 job `105156825897` | 09:53:00 UTC 开始；09:53:54.037Z 观察为 `in_progress`，conclusion 为 null | 一次单任务重跑的实际新执行；本段不填写后来的终态，须由最终准确原生日志独立验收 |
| Ubuntu attempt 1，job `105145580801` | 09:34:29–09:52:28 UTC，success | 同 run 原先已经完成的 Ubuntu 执行 |
| latest/attempt 2 映射中的 Ubuntu 新 ID `105156827116` | 同为 09:34:29–09:52:28 UTC，success；并非在重跑请求后重新开始 | 记录为已有成功执行在 latest attempt 中的映射，不额外计一次 Ubuntu 重跑或新增成功测试 |

上述对应关系分别保存于 [attempt 1 jobs](p2-active-archive-evidence/c4/wallet-rerun-initial-attempt1jobs.json)、[latest jobs](p2-active-archive-evidence/c4/wallet-rerun-initial-latestjobs.json)和 [run attempt 2](p2-active-archive-evidence/c4/wallet-rerun-initial-run.json)。只有取得并审核后续完整执行的必要步骤，才能关闭 Windows wallet 的同一验收门槛；本段不提供其他任务的动态计数，也不改变第 5 节待填的最终 C4 原生验收结论。

**C4 Windows crypto 取消与一次同源单任务重跑请求。** [cryptography run 35204106458 / attempt 1 job 105145581342](https://github.com/youq616/Zevune/actions/runs/35204106458/job/105145581342) 的[元数据](p2-active-archive-evidence/c4/job-105145581342-metadata.json)及 [10:03:02.560Z 的 attempt 1 jobs 观察](p2-active-archive-evidence/c4/crypto-attempt1-jobs-observation.json)记录起止 **09:35:33–10:00:45 UTC，25 分 12 秒**，结论 `cancelled`。[完整日志](p2-active-archive-evidence/c4/job-105145581342.log)为 **46528 B**，SHA-256 `7d42e4434fb160cf4bf921e2d6fd8cfe419f761d2624cbb8f5912724ad54be63`，实际 checkout 仍是同一 C4 synthetic。取消前仅有 **4 个完成的 harness 结果、135 pass、0 fail/ignored/filtered**：默认库 132 项／1234.98 s、Orchard worker 0、pool worker 3、默认 cfg 排除的 active CLI 0。随后 `authorization_cache::real_authorization_reuse_rejects_changed_bytes_and_restarts_cold` 已开始，但没有 `ok` 或该 target 的结果；**10:00:41.6806876Z** 日志记录取消，不能计作该用例或其余默认套件通过。

第 5 个完整测试步骤 `Real proofs, pool replay, durable worker codec and zero-value fixture` 的元数据是 `cancelled`；之后 Clippy 所在 `Static checks` 与最终 source-drift 检查均为 `skipped`。这与 wallet 那次默认全套测试已结束的观察不同，不能把两者的完成范围混用。耗时虽与原 25 分钟限时相符，日志没有明确 timeout 原因、annotations 未取得；[独立取消观察](p2-active-archive-evidence/c4/crypto-cancel-observation.json)将原因保留为未独立确认，不能据此断言测试断言、编译或 lint 失败，也不能为未完成项目补计通过。

root 于 **10:03:27 UTC** 仅对该取消 job 发起一次重跑，准确 C4 source/tree、全部测试、工作流、依赖和原 25 分钟预算均不变。[请求回执](p2-active-archive-evidence/c4/crypto-rerun-request.json)的 `success:true` 仅表示请求被接受，不是后续执行成功。原 attempt 1 的日志和取消记录保留；后续 attempt/job 映射与执行终态须由其原件及最终完整 CI 汇总核对，本固定历史段不写动态进度或阶段接受结论。

**C4 bridge／integrated 的另两次首次取消与单任务重跑请求。** 下表仅保留 attempt 1 的固定日志、元数据及请求回执；每项均在相同 C4 source/tree、相同测试／依赖／工作流和原限时下重跑一次。取消耗时接近各自限时，但原因未独立确认，不能直接称 timeout、断言或编译失败。请求成功不代表重跑执行成功，后续终态仍由最终完整原生汇总认证。

| 首次任务与原限时 | 已完成与未完成的准确边界 | 完整原件及一次重跑请求 |
|---|---|---|
| Ubuntu orchard-bridge：[run 35204106273 / job 105145581152](https://github.com/youq616/Zevune/actions/runs/35204106273/job/105145581152)；09:43:25–10:03:33 UTC，**20 分 08 秒**；原限时 20 分钟 | 默认完整 **18 个结果／153 pass**，新增活动库 18 项；Clippy＋worker build、Go test/vet 和互操作步骤均为 success。race 日志有 `ok ... 1.326s`，但第 11 步 `Boundary race checks` 元数据为 **cancelled**，不能改记整个步骤通过；fuzz 和最终 drift **skipped**。 | [日志](p2-active-archive-evidence/c4/job-105145581152.log)：71552 B，SHA-256 `0bcd032629d75209a336a7f4892943b3a6677bf92156922a9a795613478cdd6a`；[job 元数据](p2-active-archive-evidence/c4/job-105145581152-metadata.json)／[attempt 1 观察](p2-active-archive-evidence/c4/bridge-attempt1-observation.json)。[10:05:59 UTC 请求回执](p2-active-archive-evidence/c4/bridge-rerun-request.json)仅确认单任务重跑请求成功。 |
| Windows orchard-consensus-integration：[run 35204106299 / job 105145580979](https://github.com/youq616/Zevune/actions/runs/35204106299/job/105145580979)；09:37:27–10:02:40 UTC，**25 分 13 秒**；原限时 25 分钟 | 仅完成 **12 个结果／138 pass**；库 **132 pass／1122.59 s**，新增活动库 17 项。`pool_network` 的 `zero_value_real_proof_for_consensus` 已开始但无 `ok` 或结果，随后取消，第 7 个 Rust 测试步骤为 **cancelled**；余下 Rust、Clippy/build、Go、四节点及最终 drift 均不授信。 | [日志](p2-active-archive-evidence/c4/job-105145580979.log)：59816 B，SHA-256 `531b5b631e40bb5d4bc08fb3e31fb7db43374cdb5e6ca65b343f7123ca8c1751`；[job 元数据](p2-active-archive-evidence/c4/job-105145580979-metadata.json)／[attempt 1 观察](p2-active-archive-evidence/c4/integrated-attempt1-observation.json)。[10:06:00 UTC 请求回执](p2-active-archive-evidence/c4/integrated-rerun-request.json)仅确认单任务重跑请求成功。 |

原件 SHA-256 供归档核对（换行/BOM 保持，不覆盖原文）：

| 原件 | 字节 | SHA-256 |
|---|---:|---|
| `code-review-c1.md` | 13228 | `7571183736041b27d855d98d250d6fba3d85eb2845b83e68dd1b769cd586f571` |
| `adversarial-review-c1.md` | 12848 | `1b2f12b42dffb0a5bd5bea9c7f48945062534d46580c43ea194b9d6766b9b915` |
| `code-review-c1-addendum.md` | 3452 | `e906768fd9bbf0b1d5b2598ed586b65285edb71144691b5f82f8f49e2124bacb` |
| `c1/native-audit-rejected.md` | 3447 | `df6370b998deb899748c40b3588b3bed5c9441ec356c0d5c7aadc16916b34aa0` |
| `c2/job-105130677319.log` | 63569 | `67fa4d451492b8958ee1750e81c6a2fd261dea5cdf326048fc87de5ba916375c` |
| `c3/job-105131817273.log` | 76073 | `64c3e286d1f0ba3ed339d3047793b2e6190ea056a0c2b1f9bc037b06d6ff53bb` |
| `c3/native-audit-rejected.md` | 5122 | `628b2669f5777228eec8bc74fc670ca1ed2e95b3350da90ddcdd9d8d06f4af7c` |
| `c3/native-audit-rejected.json` | 13476 | `63619e31ccd880e874245c4284f5885b0469f2e7a9a046331b58f2e06c2c5a79` |
| `adversarial-review-c3-addendum.md` | 7094 | `abf56bdc75c9f1db074f1b04085330a8a9746fe409a3585f49ea385e441b5437` |
| `code-review-c3-addendum.md` | 3426 | `5646a417ae749eb6542102eed70d30a9331e85b925b19f30d44e6caceb51e0cf` |


这里只收录本阶段实际观察到的候选、运行、失败/取消/未执行状态和原始证据，不预先声称没有失败。每次修复均保留原失败、实际拒绝层、源码变化及新候选复验；没有日志的错误号、故障层、测试计数和终态保持未知。

前阶段活动账本与付款资源的报告及原件保持原文：[活动账本验收](p2-active-ledger-validation.md)、[付款资源验收](p2-payment-resource-validation.md)、[其历史失败索引](p2-payment-resource-diagnostic-history.json)。不复制前阶段整套证据，不将其中“该阶段未测活动归档”的历史范围改写为本轮已测，也不将其数据用作本轮验收结果。

## 7. 未覆盖范围与交接

本阶段只复制完整公开活动账本，不包含钱包、密码、密钥、CometBFT 数据库/WAL 或最后签名状态；备份不是可直接启动的完整验证节点。继续使用同一验证者身份前需另行协调签名状态，不能同时启动两个相同身份的副本。没有新增 Go 网络恢复入口、状态导入、迁移、剪枝、快照或增量备份。

可信父目录、操作系统和文件系统仍是前提。Unix 绑定设备/inode 并拒绝多硬链接；Windows 持有不共享 DELETE 的句柄并拒绝 reparse point；这些约束不证明抵抗任意恶意瞬时替换后还原。Windows 目录持久化未新增承诺，私有 cfg(test) 注入及同一 OS 的重放不能替代真实断电、磁盘满或进程级崩溃的系统验收。

每个源或目标最多保留 2048 个段句柄，另有 genesis 和目录；完整重放 reader 还会克隆整套句柄。不得沿用旧备份的 64 段/66 句柄口径。完整历史重放、内存状态和句柄成本仍存在，主机资源不足必须失败关闭；本轮未测归档资源峰值、长期全容量、持续真实交易增长、多机运行或性能分布。

`P2` 保持 `in_progress`；`incremental_backup_implemented`、`snapshot_state_import_implemented`、`production_storage_ready` 和 `audited` 保持 `false`。旧 `pool_recovery_scope` 继续描述旧 API，活动归档能力通过独立状态键记录。CI 和独立编码代理审核均不等于外部协议、密码学或安全审计。

后续 P2 工作仍包括快照加增量恢复的独立合同与验证、存储容量及历史边界、真实故障恢复和持续运行。本阶段接受与否只由第 1、4、5 节的最终准确证据决定，不能据文档新增或设计 PASS 提前接受。

原始记录将集中于 `reports/p2-active-archive-evidence/`，逐份保存来源、长度和 SHA-256；汇总与 merge 证据使用 `reports/p2-active-archive-` 前缀。归档不得修改原始日志、审核文字、换行或平台 BOM；生成的汇总与原件分别标识，不创建包含自身 hash 的循环清单。
