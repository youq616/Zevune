# C7 原生 Rust 完整范围独立审核

**结论：PASS_FOR_COMPLETE_EXACT_C7_NATIVE_RUST_SCOPE。** 已直接独立审核准确 C7 的全部 12 个 Rust job：8 个 default、双平台 funded-library、双平台 funded-interfaces。12 个 job 原生结论全部 success，目标与结果完整，所有 Rust 结果的 failed、ignored、measured、filtered 均为 0。该结论只接受本报告负责的完整 Rust 范围；整阶段仍由主审核及非 Rust 审核收尾，不能把它写成我已独立审完全部 23 个矩阵 job。

准确 source `de474720431daf33afd4a7ebc32de2d230344a5a`，tree `e4dd17dfb1efd0e3ca20441168b62b72b6fc3108`，parent `88146d54f2eaac39958ceaaea9e13f71832d536e`，base `6913d4ab2fda6956db37e0ceb49790a4518c2762`，PR #13；所有原件 checkout `00d4442b12cb72344ffa5bea101eb7142ab03270`。[官方身份原件](source-identity.json)的 source/tree、synthetic/tree 以及 synthetic 的 base/source 两父提交一致；每份 raw fetch/checkout、原生 check-run head/base/PR 也逐份核对。静态记录中待补的 synthetic 身份由本记录补齐，未后改静态原文。

独立审核者 `/root/p2_archive_native_audit/source_expectations` 未编写候选源码。审核直接读取全部原件及 metadata，逐份验证长度与 SHA，按 FIFO 关联 Cargo harness/result，再将每个新增精确全名逐一对应到实际 `ok`。没有本地执行 Rust、触发 CI 或轮询 GitHub；C4/C5/C6 的失败、取消、重跑和局部成功没有转作 C7 证据。

## 每个 job 的完整实际结果

表内“结果 / passed”按本 job 的完整 Rust 结果记账，含独立 doc 结果；重复 workflow 的同名测试不增加唯一覆盖数。全部 job 均完成本身 fmt、锁定依赖检查和末尾 drift。库 cohort 的 workflow 本身没有 Clippy，不能从相邻接口 job 借一个 Clippy 完成给它；其余 10 个 job 的严格 Clippy 均实际完成。

| 范围 | 平台 | job 原件 | 完整结果 / passed | lib 或 CLI / 耗时 | 新增实际 ok | 严格 Clippy |
|---|---|---|---|---|---|---|
| crypto/default | Ubuntu | [105169883708](job-105169883708.log) | 18 / 154 | 140 / 66.79 s | 19 | 11.33 s |
| crypto/default | Windows | [105169884041](job-105169884041.log) | 18 / 147 | 133 / 84.79 s | 18 | 21.25 s |
| wallet/default | Ubuntu | [105169883281](job-105169883281.log) | 18 / 154 | 140 / 40.64 s | 19 | 7.67 s |
| wallet/default | Windows | [105169883394](job-105169883394.log) | 18 / 147 | 133 / 76.23 s | 18 | 18.63 s |
| bridge/default | Ubuntu | [105169884058](job-105169884058.log) | 18 / 154 | 140 / 67.08 s | 19 | 11.68 s |
| bridge/default | Windows | [105169884404](job-105169884404.log) | 18 / 147 | 133 / 88.63 s | 18 | 21.71 s |
| integrated/default | Ubuntu | [105169884577](job-105169884577.log) | 18 / 154 | 140 / 67.43 s | 19 | 12.11 s |
| integrated/default | Windows | [105169884951](job-105169884951.log) | 18 / 147 | 133 / 51.24 s | 18 | 13.29 s |
| funded/library | Ubuntu | [105169883800](job-105169883800.log) | 1 / 159 | 159 / 206.84 s | 19 | 此 job 不设 Clippy |
| funded/library | Windows | [105169883974](job-105169883974.log) | 1 / 152 | 152 / 413.20 s | 18 | 此 job 不设 Clippy |
| funded/interfaces | Ubuntu | [105169883929](job-105169883929.log) | 20 / 56 | CLI 7 / 68.27 s | 7 | 14.88 s |
| funded/interfaces | Windows | [105169883969](job-105169883969.log) | 20 / 56 | CLI 7 / 124.60 s | 7 | 39.09 s |

八个 default 各有 17 harness + doc，共 18 结果：Ubuntu lib 140 / 总 154，Windows lib 133 / 总 147。所有 default 的 active CLI 目标都是 **0 测试**，不计 funded CLI 7，也不宣称 feature 门控的四个 active_flow 在 default 执行。同一平台四份 default 的完整库名称集合完全相同；Ubuntu-only 11 项、Windows-only 4 项，净差 7 来自已审 cfg，不是忽略的测试。

双 funded-library 各执行一个完整、无名字过滤的 `cargo test --locked --release --features local-funding-lab --lib -- --test-threads=1`，Ubuntu **159 / 206.84 s**、Windows **152 / 413.20 s**。每个平台包含自己的全部 default 库名称并增加同样 19 项 feature 测试。两库均有完整 library 结果和随后 `FUNDED_COHORT_COMPLETE library`；Windows 原件 raw 555 / 11:02:25.2500932Z 是完整 152 结果，557 / 11:02:25.2604125Z 是完成标记。

双 funded-interfaces 的原生 metadata 计划与实际目标逐一一致：5 bin + 14 integration，再单独 doc，各 **20 结果、56 passed**。运行来自 metadata 自动枚举，无名称过滤，所有目标结果之后才出现 interfaces 完成标记；没有把支持 fixture 文件误计为 integration 目标。两库中用于核对分组调度器的 Python **13 项均 OK**，这些既有检查不额外计入新增 Rust 功能测试。

## 新增用例与真实断言

[静态精确清单](source-test-expectations.json)与[源码审核原文](source-test-expectations-review.md)保持原 SHA。配套正式 JSON 保存 27 个跨平台新增函数的全名、平台、feature、冻结验收点，以及每份原件每个新增 `ok` 的行号与 UTC 时间。27 个定义为 20 个库函数（其中既有本阶段 archive 19 + fixed-key 1）和 7 个 CLI；实际每个相关库执行为 Ubuntu **19**、Windows **18**，其中 archive 分别 **18/17**。两个接口执行各自都有全部 **7** 个新 CLI 名称。线程、mode、proof 构建、重复 replay 或跨 workflow 重跑不能另加为唯一测试。

**固定公共 key 与独立 cache。** 十份 library 执行（八 default、双 funded-library）均实际 `ok` 于 `wire::fixed_key_tests::concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold`。准确 C7 的完整测试主体及真实 fixture 与此前已审版本字节相同，只将重复 `mod` 改成使用现有 cfg(test) 模块；两平台默认和 funded 严格 Clippy 现在实际成功，无 duplicate_mod。一次真实证明及签名 fixture、固定 `FixedPostNu6_2` key 版本/地址、初始独立空 cache、一个实例成功不温热另一个、四个并发 verifier 的独立真实验证、可解码 proof 和 binding-signature 改动被 Authorization 拒绝且不缓存、后续新实例仍冷等断言得到本轮执行映射。四线程使用的是**已初始化**的公共 key，不能宣称冷 OnceLock 初始化竞争覆盖。

**完整 replay 与真实活动归档流程。** 原归档测试全部逐名执行，准确源码保留每次新 verifier/空 cache、检查点导出 replay，以及复制中的源、目标、末次源三次完整 replay。两库四个 active_flow 均完整 `ok`；关键结果如下：

| 精确用例 | Ubuntu 原件 / 实际 ok | Windows 原件 / 实际 ok |
|---|---|---|
| `pool::active_flow_tests::real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` | 105169883800，raw 433，10:42:14.0613255Z | 105169883974，raw 418，10:57:34.0107922Z |
| `pool::active_flow_tests::active_profile_domain_rejections_preserve_bytes_reservations_and_legacy_contract` | 105169883800，raw 430，10:41:53.2648959Z | 105169883974，raw 415，10:55:43.6343255Z |

增长用例包含真实付款触发默认物理段轮转、10001 真实续付、完整备份/恢复及继续至 10002。原样保留的 44 行无条件回归交换两个已存在的物理段，原 pin 与重算完整 pin 均要求 Corrupt，源与 fixture 字节/命名空间不变；重算后的物理布局摘要先匹配，再被链顺序/base-hash 校验拒绝。这不冒充 Authorization 覆盖。另一个真实坏 binding signature 用例重算 record checksum 与完整 pin 后，普通 open 与 ActiveArchive 均明确要求 Authorization 拒绝且字节不变。以上是完整成功用例中的实际断言路径，不是额外测试。

**CLI 7 与 stdout 回归。** 双平台 CLI 完整结果分别 **7 / 68.27 s** 与 **7 / 124.60 s**；真实付款/恢复/接收方续付用例中的两次 genuine payment-proof 构建保留且本轮成功。第七项 `active_cli_stdout_failure_is_nonzero_and_complete_target_remains_verifiable` 在 Ubuntu raw **802 / 10:45:34.3895759Z**、Windows raw **788 / 10:53:58.3992659Z** 都完整 `ok`。准确 C7 主体无条件执行 checkpoint、verify、backup、restore 四个 mode：真实 readonly File 写失败探针、每个 mode 精确 exit 1、可写 File 成功 JSON 对照、源与 sink 不变、完整 backup/restore 目标字节及随后分别真实 verify 均映射到这些成功结果。四个 mode 仍只是一项测试。`File.flush` 不等于 fsync，Windows NULL-handle 分支没有专门运行 fixture。

## skip、输出交错及范围限制

Rust 的全部完成结果没有 failed、ignored 或 filtered。原生 workflow 只有以下四个步骤按准确 Linux 条件在 Windows 跳过：Windows bridge 的 `Boundary race checks` / `Bounded decoder fuzz checks`（workflow 69/72 行）；Windows integrated 的 `Real adapter race checks` / `Local IPC race and bounded fuzz`（workflow 68/72 行）。分别是 14 success + 2 skipped、13 success + 2 skipped；这是平台 Go 条件，不是 Rust 用例跳过，也没有记作执行通过。其他十个 job 的原生步骤全 success。Ubuntu 对应步骤的实际非 Rust 语义由主审核负责，不能仅凭本报告的 metadata 状态完成那部分审查。

有两处实际 stderr/stdout 交错需要保留边界：Ubuntu wallet 在 raw 627 已宣布 `recipient_domain`，但 raw 630 的 4-pass 属于此前 `real_bundle`；Windows bridge 在 raw 654 已宣布 `genesis_domain`，但 raw 655 的 1-pass 属于此前 `default_worker_policy`，genesis 的 0-pass 是 raw 660。两处均直接检查原件并按 FIFO 匹配；其余目标也逐项与计划对应，不用最近一次 announcement 盲目归属结果。

本报告不把原生日志耗时当性能基准或吞吐承诺，不把 process-visible byte/fault 断言扩展为掉电可靠性，也不构成生产资金安全或外部安全审计结论。完整的非 Rust、resource/growth、四节点等阶段验收与最终发布/合并决定仍由主审核综合。

## 原件完整性与时间

以下为 2026-09-17 UTC 的原生 API 起止；正式 JSON 另保留每份 raw 首末时间、metadata 观察时间、步骤、实际测试行号和全部目标结果。完成报告前已重新核验所有 12 份原件及 metadata 的 SHA 与长度。

| job | 原件字节数 | SHA-256 | API 起止 UTC |
|---|---:|---|---|
| 105169883708 | 60,752 | `3b271c81df27ebe0cb7c998ae4cf977d9814239db193a61c513581b55dcd8368` | 10:38:53–10:43:04 |
| 105169884041 | 60,191 | `db90de7200c5bd2c6940da32b75b68a40dbfd5bd0ec00964757d9bf74c081812` | 10:46:06–10:53:18 |
| 105169883281 | 60,715 | `dc1dbab928008fd7c3fe418c31fb6ba4b12ac1065e7c13dd8d37a0602c446789` | 10:39:10–10:41:55 |
| 105169883394 | 60,147 | `89e1c39d77d65248348e8de6abc5a5c9ea76502c52c8d660625c76b2a3ef196f` | 10:43:11–10:49:32 |
| 105169884058 | 75,708 | `303fbb0f0cf5261345441a44b733bfc6e050cc638117d4a03997a8eaa6ab807f` | 10:49:26–10:54:56 |
| 105169884404 | 72,626 | `e0ea9dbf8b58c9b192a64cb2bf7c3e23ab83177ce656a118df38ccd0b24a99dd` | 10:43:25–10:51:47 |
| 105169884577 | 77,087 | `4037cc25f1944a16455b9bafb1fbbcabcd3098761fac1895683062274e22c3c6` | 10:49:34–10:57:46 |
| 105169884951 | 74,880 | `b9576db97b55bafebfc74be02fa68ef59752aae7382d2639348f2f31482d3f51` | 10:46:11–10:53:32 |
| 105169883800 | 51,857 | `d02e5a6ac4f8aeda9548c8e992886c7044902047707d2df14dc496aea3f86af9` | 10:40:42–10:45:14 |
| 105169883974 | 51,119 | `2a10eb274d26407894aad54008c75b724022e7041790d494d8ccfcd4fc1a9fb5` | 10:52:40–11:02:28 |
| 105169883929 | 90,706 | `6fdc8219fedda7cd261e1760b3c8b70281add0975045237ef93bbc51897ac18f` | 10:41:48–10:49:20 |
| 105169883969 | 92,366 | `e9c013f650b9ef7eaf12d8d18032330d96755986ad423563c7abaee695be0432` | 10:45:15–11:00:12 |

正式结论仅由这些准确 C7 原件支持：**完整 12-job Rust 范围通过，整阶段接受状态由主审核决定。** C4 的取消历史、C5 fmt 失败、C6 完整 default 后 Clippy exit 101 均继续保留，没有被本轮成功覆盖或改写。
