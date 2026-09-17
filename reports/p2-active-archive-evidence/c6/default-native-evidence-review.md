# C6 Ubuntu default 原生执行独立审核

**C6 NOT_ACCEPTED：完整默认 Rust 测试实际通过，随后严格 Clippy 发生真实 `duplicate_mod` 错误，整 job failure。** 这不是取消，也不是“测试未执行”。本报告只覆盖已提供的一个 Rust 执行原件，不代表双平台、funded 或全矩阵通过，不使用旧候选结果补足范围。

准确 source `88146d54f2eaac39958ceaaea9e13f71832d536e`，tree `cbddd8e982eb9013d10010354e477b264e33841b`，base `6913d4ab2fda6956db37e0ceb49790a4518c2762`，PR #13；原始 checkout synthetic `4bfe426af700303719bbc58344408e070af90467`。raw 91/118/121 行分别给出完整 fetch、source/base merge 描述和完整 checkout SHA；原生 metadata 的 head/base/PR 与该身份一致。静态记录中此前待提供的 synthetic 身份由本新记录补齐，原静态文件保持不变。

独立审核者 `/root/p2_archive_native_audit/source_expectations` 直接读取原始日志、metadata 和准确 C6 静态映射，未修改源码或历史原文、未运行测试、未触发/轮询 CI。按 FIFO 匹配 Cargo harness 与完成结果，逐项核对新增精确全名的唯一实际 ok。

- 原件：[job-105167396538.log](job-105167396538.log)，**68,156 B**，SHA-256 `a0368cb426a63c9ed4763cd88429f5744b0d0404b30c50e419f0e86903b40e40`。
- 原生 metadata：[job-105167396538-metadata.json](job-105167396538-metadata.json)，SHA-256 `d03f9521d7177e9ba2f551b0b73308e178aa691a0c7e5b7c721f5d8f05b00297`；观察时间 **2026-09-17T10:35:38.100Z**。
- job：`integrated (ubuntu-latest)`，API 起止 **2026-09-17 10:29:29–10:33:54 UTC**，conclusion `failure`。raw 首末时间 **10:29:31.5809196–10:33:52.5932578 UTC**。
- Rust：`1.98.1 (48a229cea 2026-09-01)`；实际命令 `cargo test --locked --release -- --test-threads=1`，无名字过滤、无 local-funding-lab feature。

## 实际完成的默认目标

全部 **17 个 harness 加 doc，共 18 个完整结果、154 passed**；每个结果 failed、ignored、measured、filtered 都是 0。lib 为 **140 passed / 66.85 s**，raw 644 行 / **10:32:56.4453608Z**；最后 doc 结果 raw 760 行 / **10:33:41.0614827Z**。源码预期的全部默认目标均出现并完成，没有丢失或拿下一目标的结果冒充上一目标。

| 目标 | passed | 秒 | 原件结果行 |
|---|---:|---:|---:|
| `lib` | 140 | 66.85 | 644 |
| `zevune-orchard-worker` | 0 | 0.00 | 650 |
| `zevune-pool-worker` | 3 | 0.00 | 659 |
| `active_recovery_cli` | 0 | 0.00 | 665 |
| `authorization_cache` | 1 | 8.02 | 672 |
| `bridge` | 1 | 10.17 | 679 |
| `cache_state_guards` | 0 | 0.00 | 685 |
| `default_worker_policy` | 1 | 0.00 | 692 |
| `genesis_domain` | 0 | 0.00 | 698 |
| `genesis_manifest_bounds` | 0 | 0.00 | 704 |
| `operator_cli` | 0 | 0.00 | 710 |
| `payment_preflight` | 0 | 0.00 | 716 |
| `pool_network` | 1 | 8.05 | 723 |
| `real_bundle` | 4 | 18.24 | 733 |
| `recipient_domain` | 3 | 0.06 | 742 |
| `recovery_cli` | 0 | 0.00 | 748 |
| `test_genesis` | 0 | 0.00 | 754 |
| `doc` | 0 | 0.00 | 760 |

`active_recovery_cli` 在 default 实际是 **0 测试**，不能计作 funded CLI 7 通过。四个 `pool::active_flow_tests` 由 feature 门控，此份日志没有执行，不能据本次报告宣称真实 funded 10001/交换段流程通过。此处的 default `authorization_cache` integration 则实际 1 passed / 8.02 s，保留既有真实授权回归的准确范围。

## 新增 19 项与真实缓存隔离用例

[静态清单](source-test-expectations.json) 的 Ubuntu 新增 19 个完整测试名逐个出现且恰好一次 `... ok`，包含原 archive 18 项及新增 wire 1 项。archive 名称统一前缀为 `pool::recovery::active::tests::`，以下后缀与原件行组成完整映射：

| 测试后缀 | 实际 ok 行 |
|---|---:|
| `checkpoint_codec_has_exact_length_distinct_magic_and_bounded_arithmetic` | 525 |
| `checkpoint_export_preserves_prepared_work_and_never_certifies_uncommitted_bytes` | 526 |
| `checkpoint_export_replays_same_length_replacement_and_never_publishes_its_state` | 527 |
| `creating_a_target_is_exclusive_and_source_validation_precedes_creation` | 528 |
| `exported_genesis_checkpoint_matches_independent_fixed_layout_vector` | 529 |
| `final_source_and_target_namespace_changes_cannot_return_success` | 530 |
| `genesis_and_committed_archive_copies_preserve_every_file_and_continue_normally` | 531 |
| `incompatible_checkpoint_profiles_reject_without_poisoning_healthy_stores` | 532 |
| `namespace_tests::active_archive_locks_coordinate_real_processes` | 533 |
| `namespace_tests::failed_open_releases_all_acquired_file_and_directory_handles` | 534 |
| `namespace_tests::parent_aliases_and_replaced_directories_cannot_redirect_a_retained_archive` | 535 |
| `namespace_tests::persistent_entry_replacements_symlinks_and_hardlinks_are_not_certified` | 536 |
| `namespace_tests::readonly_source_files_copy_into_a_normally_writable_active_directory` | 537 |
| `namespace_tests::unknown_entry_after_open_prevents_verification_and_creates_no_target` | 538 |
| `partial_copies_and_lost_acknowledgements_preserve_targets_without_retry_or_repair` | 539 |
| `repinned_headers_are_bounded_inside_the_physical_genesis_file` | 540 |
| `repinned_layout_still_requires_complete_frames_canonical_rotation_and_real_state` | 541 |
| `retained_replay_binds_the_independently_expected_genesis_after_a_same_length_change` | 542 |

新增完整全名 `wire::fixed_key_tests::concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold` 在 raw **639 行 / 10:32:56.4450467Z** 明确 `ok`。准确 C6 源码中该用例没有 skip、ignore、feature 或 OS 隐藏分支，其完整执行包含：一次真实 proof fixture 构建及签名、固定 `FixedPostNu6_2` key 版本与相同只读地址、独立空 cache、首实例成功后其他实例仍冷、四线程分别首次真实验证、可解码 proof-byte 与 binding-signature-byte 变更返回 Authorization 且不记入成功缓存、有效字节仍可验证，以及随后独立 verifier 仍从空缓存开始。该库成功编译并执行为此次 Ubuntu / 锁定版本的共享静态 key 与线程类型提供实际编译证据。

上述四线程使用发生在 key 已初始化之后，**不覆盖冷 OnceLock 首次初始化竞争**；四个 worker、两种坏字节和多次 verify 仍只算一个测试。公开 key 的共享不等于共享授权成功缓存；此报告也不把其他平台或 feature 的编译结果从 Ubuntu default 推出。

## Clippy 失败边界

原生 step 5 `Check committed source and unchanged dependency locks` 为 success，其中 raw 236–238 行的 `cargo fmt --all -- --check`、锁定 metadata 与初始 `git diff --exit-code` 均在成功步骤内。C6 此次实际格式检查已成功，区别于 C5 的 rustfmt 失败历史。

step 7 将 test、Clippy、worker build 顺序放在同一 `bash -e -o pipefail` 脚本（raw 386–390）。完整 test 命令先成功，随后实际运行 `cargo clippy --locked --release --all-targets -- -D warnings`。raw **850 行 / 10:33:51.3461970Z** 报 `file is loaded as a module multiple times: src/../tests/support/fixtures.rs`；854 行明确 `clippy::duplicate_mod` 由 `-D warnings` 提升为错误。857 行说明 `zevune-orchard-lab (lib test)` 因此编译失败，859 行 / **10:33:52.3706599Z** 退出 **101**。这里是 Clippy 编译检查失败，不是此前已经成功的 140 项库测试失效。

因此，原生 step 7 和整个 job 为 failure；其后的独立 worker build 只有命令头，不能计作已执行成功。Go regression、四进程共识、race/fuzz 和最终 drift 步骤均 skipped。初始源码检查成功不冒充末尾 drift 完成。此份原件没有取消信息，也没有将 lint 错误降级成提示的依据。

本报告接受的局部事实是：准确 C6 Ubuntu default 完整 **18 结果 / 154 passed**，新增 **19** 全部实际 ok，且该 job 初始 fmt 成功。必须保留的阻断是：**Clippy duplicate_mod / exit 101，C6 NOT_ACCEPTED**。仅有这一份 Rust 执行被本报告审核；Windows、funded 和其他矩阵项的实际结果待各自原件，不能补写为本次通过。
