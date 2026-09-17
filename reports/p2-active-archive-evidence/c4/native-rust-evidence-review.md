# C4 原生 Rust 证据独立审核

**结论：NOT_ACCEPTED。** 本报告只审核首轮 12 个独立 Rust job 执行（8 个 default、2 个 funded-library、2 个 funded-interfaces）：7 个 job success，5 个 cancelled。已完成的单测和目标结果可以按实际边界保留；它们不能补成取消 job 的完整通过。尤其 Windows funded-library 没有完整库结果或 cohort 完成标记，C4 不满足整阶段验收。全矩阵 23 个 job 的总体状态由主审核另记，本报告不把其中 18 个 success 写成矩阵全部通过。

准确 source `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`，tree `3c44977028b58ddd387f52946632af594208edfb`，parent `7045af4ae254f0a5a5e4810f17004c91e649e474`，base `6913d4ab2fda6956db37e0ceb49790a4518c2762`，PR #13，原生日志 checkout synthetic `fb5ec39a59cb87aec0662c7706dce1f9e85e1962`。独立审核者 `/root/p2_archive_native_audit/source_expectations` 未编写候选源码；仅用 `git show` 读取准确提交、直接读取原始日志和原生 metadata，没有本地运行测试、触发 CI、轮询 GitHub 或读取正在修改的工作树。

## 首轮执行边界

表中“结果 / passed”只统计已经出现 `test result: ok` 的完整 Rust 目标结果；doc 也占一个结果。新增列为准确全名的实际 `... ok` 数量，重复 job 不增加唯一测试数。所有已完成结果的 failed、ignored、measured、filtered 均为 0。

| 范围 | 平台 | 原件 job | 整 job | 完整结果 / passed | lib passed / 耗时 | 新增实际 ok | 边界 |
|---|---|---|---|---|---|---|---|
| crypto/default | Ubuntu | [105145581709](job-105145581709.log) | success | 18 / 153 | 139 / 755.47 s | 18 | 完整；fmt、Clippy、drift 成功 |
| crypto/default | Windows | [105145581342](job-105145581342.log) | cancelled | 4 / 135 | 132 / 1234.98 s | 17 | authorization_cache 开始无 ok；Clippy、drift 跳过 |
| wallet/default | Ubuntu | [105156827116](job-105156827116.log) | success | 18 / 153 | 139 / 891.01 s | 18 | 完整；同一次执行映射新 ID；fmt、Clippy、drift 成功 |
| wallet/default | Windows | [105145580574](job-105145580574.log) | cancelled | 18 / 146 | 132 / 1122.67 s | 17 | 测试完整；Clippy Finished 后该 step 取消；drift 跳过 |
| bridge/default | Ubuntu | [105145581152](job-105145581152.log) | cancelled | 18 / 153 | 139 / 973.64 s | 18 | Rust 与 Clippy/build 完整；后续 Go race 取消；drift 跳过 |
| bridge/default | Windows | [105145580578](job-105145580578.log) | success | 18 / 146 | 132 / 740.25 s | 17 | 完整；fmt、Clippy/build、drift 成功；平台 Go race/fuzz 跳过 |
| integrated/default | Ubuntu | [105160667067](job-105160667067.log) | success | 18 / 153 | 139 / 889.29 s | 18 | 完整；同一次执行映射新 ID；Clippy/build、drift 成功 |
| integrated/default | Windows | [105145580979](job-105145580979.log) | cancelled | 12 / 138 | 132 / 1122.59 s | 17 | pool_network 开始无 ok；Clippy/build、后续 Go、drift 未执行 |
| funded/library | Ubuntu | [105145581282](job-105145581282.log) | success | 1 / 158 | 158 / 1289.4 s | 18 | 全 lib 完成标记；此 job 没有 Clippy 步骤 |
| funded/library | Windows | [105145581227](job-105145581227.log) | cancelled | 0 / 无完整结果；126 个具名 ok | 计划 151，未完成 | 17 | full_journal… 开始无 ok；无 lib 结果或 cohort 完成标记 |
| funded/interfaces | Ubuntu | [105145581497](job-105145581497.log) | success | 20 / 56 | — | 7 | CLI 7 / 134.32 s；全部 cohort、Clippy/build、drift 成功 |
| funded/interfaces | Windows | [105145581188](job-105145581188.log) | success | 20 / 56 | — | 7 | CLI 7 / 245.54 s；全部 cohort、Clippy/build、drift 成功 |

default 的完整执行是 17 个 harness 加 doc，共 18 结果：Ubuntu 139 个库测试、总 153；Windows 132 个库测试、总 146。所有 default 的 `active_recovery_cli` 目标均为 0 测试，不能计作 CLI 7 通过。双 funded-interfaces 各自执行 5 个 bin、14 个 integration 目标，再单独执行 doc，共 20 结果、56 passed，并有 `FUNDED_COHORT_COMPLETE interfaces`。Ubuntu funded-library 单一完整 `--lib` 命令无名字过滤，158 passed / 1289.40 s，并有 library 完成标记。Windows 的计划是 151，不是实际 151 passed。

## 源码挂载与实际执行映射

[源码静态原文](source-test-expectations-review.md)和[精确测试清单](source-test-expectations.json)保持不变；本报告配套 JSON 保存每个新增全名、平台、feature、冻结验收点、原始 ok 行号/时间及每个目标结果。新库测试通过 `pool::recovery::active::tests` 与 `namespace_tests` 正常挂载：Ubuntu 18、Windows 17，在每份相关库执行原件均逐项看到一次实际 ok，包括尚未跑完整库的 Windows funded-library。19 个跨平台库函数定义中的 cfg 差异是编译平台选择，不是运行时 ignored；完整库平台差异为 11 个 Unix-only 对 4 个 Windows-only，净差 7。

两份 funded-interfaces 均逐项显示全部 7 个 `active_recovery_cli` 用例 ok。首个用例实际执行包含两个真实 payment-proof 构建的付款、备份、恢复后扫描及接收方续付路径；这是一个用例里的两个构建，不额外加测试数。第七个 stdout 用例完整结束，因此准确 C4 中无条件执行的 checkpoint / verify / backup / restore 四个 mode，readonly File 写失败探针、每个 mode 精确 exit 1、可写 File 的成功 JSON 对照、源与 sink 不变、完整 backup/restore 字节及随后分别实际 verify 的断言均得到执行。这四个 mode 仍是一个测试；`File.flush` 不等于 fsync，Windows NULL handle 分支没有专门运行 fixture。

两份 funded-library 原件均实际显示四个既有 `pool::active_flow_tests` 名称 ok。增长用例 Ubuntu raw 433 行 / 09:40:06.0922117Z、Windows raw 418 行 / 09:44:01.8853079Z 对应准确 source 中真实付款触发两物理段、10001 付款、备份恢复及继续 10002 的完整路径。其中 C3 加入且 C4 未改变的 44 行交换回归无额外 cfg、skip 或提前返回：交换两个已有物理段后，原 pin 与重新计算完整 pin 都断言 Corrupt，源/测试副本字节与命名空间保持；重算后的物理布局摘要先匹配，再由链顺序/base-hash 校验拒绝。此项不冒充 Authorization 覆盖。另一个已通过的 active_profile_domain… 用例调用真实坏 binding signature 回归，重算记录 checksum 与 pin 后，普通 open 和 ActiveArchive 均明确断言 Authorization 拒绝及字节不变。Windows 这些单项确已通过，仍不能推导整个 funded-library 完成。

调度器原生 JSON 计划和实际执行逐目标对应 `cargo metadata --locked --features local-funding-lab` 生成的目标集合；不是固定 allowlist。库命令为 `cargo test --locked --release --features local-funding-lab --lib -- --test-threads=1`，interfaces 的 19 个目标无名字过滤，doc 另跑。两库 job 的 scheduler Python 13 项均实际 OK，只是既有调度器检查，不再加到新增测试数。库 job 自身没有 Clippy，相关静态检查不能从其他 job 借来填充。

## 五次取消的准确边界

- **Windows wallet**：step 5 已完成完整 default，18 结果 / 146 passed；Clippy 在 09:50:13.5240250Z 输出 Finished 25.02 s，09:50:13.5931481Z 出现取消。原生 step 6 结论仍为 cancelled，最终 drift skipped，整 job 不接受。
- **Windows crypto**：库 132 / 1234.98 s 已完成，随后仅得到 4 个完整结果 / 135 passed。`authorization_cache` 的 `real_authorization_reuse_rejects_changed_bytes_and_restarts_cold` raw 536 行只开始，未见 ok 或结果；537 行 10:00:41.6806876Z 取消。不能记为完整 146；Clippy、drift skipped。
- **Ubuntu bridge**：全部 Rust 18 结果 / 153 passed、Clippy 11.38 s 和 worker build 0.08 s 均已完成；取消发生在后续 Go Boundary race checks step 11，raw 906 行 10:03:31.6388747Z。不把 Rust 测试记为失败，也不把整 job 记为通过；fuzz、最终 drift skipped。
- **Windows integrated**：库 132 / 1122.59 s 完成，仅 12 个完整结果 / 138 passed。`pool_network` 的 `zero_value_real_proof_for_consensus` raw 703 行只有开始；704 行 10:02:35.1993741Z 取消。step 7 中 Clippy/build 只是命令头出现，未完成执行；后续 Go 与 drift skipped。
- **Windows funded-library**：151 个计划测试中有 126 个具名 ok，包括新增 17 与四个 active_flow，但零完整 lib 结果。`wallet::vault::store::compact_tests::full_journal_compacts_exact_real_outbox_and_continues_after_confirmation` raw 528 行只有开始，529 行 10:07:35.2105691Z 取消；无 `FUNDED_COHORT_COMPLETE library`，step 6 cancelled、drift skipped。126 个单项证据不能写成 151 passed。

准确 workflow 原预算为 crypto/wallet/integrated 25 分钟、bridge 20 分钟、funded-library 30 分钟；上述 job API 总时长分别为 25:12、25:05、25:13、20:08、30:12（按名称对应）。这些时长与预算相近，但现有日志/metadata 没有证明具体取消原因，本报告不强断超时根因，也未发现可据此改写成编译、断言或 lint 失败的原始证据。

## 时间、身份与原件完整性

下面均为 2026-09-17 UTC 的原生 API job 起止。配套 JSON 另保留 raw 首末时间、metadata 观察时间、完整 SHA、关键行及步骤结论。

| job | 原件字节数 | SHA-256 | API 起止 UTC |
|---|---:|---|---|
| 105145581709 | 60,609 | `16e226b3be73f69e20cf29ca7645dac28efc4bdf256d990787f37bc71784cac9` | 09:16:50–09:31:59 |
| 105145581342 | 46,528 | `7d42e4434fb160cf4bf921e2d6fd8cfe419f761d2624cbb8f5912724ad54be63` | 09:35:33–10:00:45 |
| 105156827116 | 60,575 | `1fee6f71c95264c6d612e6d7a3451c413fc0120e3fb8e3037f5122b32d6a5328` | 09:34:29–09:52:28 |
| 105145580574 | 59,588 | `a790c404ae69d567175690cb37ec23864a6499da4afb8f60005e051981522515` | 09:25:12–09:50:17 |
| 105145581152 | 71,552 | `0bcd032629d75209a336a7f4892943b3a6677bf92156922a9a795613478cdd6a` | 09:43:25–10:03:33 |
| 105145580578 | 72,484 | `8ddc22d56c7dcce56d68b9be41ba44b8213fdf2a82213a76493c1a8d3b06ac24` | 09:17:00–09:34:37 |
| 105160667067 | 76,793 | `1bc967de3ff01aecd4f09e285b08e21b9e54a647d01b00057abef8c38f4cef8d` | 09:42:58–10:04:38 |
| 105145580979 | 59,816 | `531b5b631e40bb5d4bc08fb3e31fb7db43374cdb5e6ca65b343f7123ca8c1751` | 09:37:27–10:02:40 |
| 105145581282 | 51,715 | `29cdda30e026940b011f8837c858ccf83dab740c90bf36bb6adc0d105daa2f5c` | 09:36:44–09:59:37 |
| 105145581227 | 47,407 | `c9192a16f3b570e4781033a647a8c628c49138476f76ea473f668c65a22665c6` | 09:37:27–10:07:39 |
| 105145581497 | 90,632 | `a8610101678173c1b848bdf960c4dbb7e1f029ba5e1e40a9a66cbcdd15f32748` | 09:45:24–09:55:05 |
| 105145581188 | 92,447 | `0603f502e2e1b4ae1aeab8dae3091102724ea508aca31eb714f5d4c8f119ed5d` | 09:33:50–09:53:56 |

Ubuntu wallet 原始 job `105145580801` 在 attempt 2 列表映射为 `105156827116`，两份官方观察起止均 09:34:29–09:52:28；attempt 2 run 在 09:52:57 才启动，不能称 Ubuntu 又运行了一次。Ubuntu integrated 原始 `105145581494` 映射为 `105160667067`，两份原生观察仍为 09:42:58–10:04:38；同样是原执行带入新 attempt。映射文件及 SHA 已纳入 JSON，每组只计一次执行。

原始 stdout/stderr 存在交错：如 Ubuntu crypto 在 default_worker_policy 结果前已打印下一 genesis_domain harness，funded Ubuntu 在 operator_cli 结果前已打印 payment_preflight。审核按 FIFO 对应 announcement/result，并核对具名测试与目标，避免给下一目标错计结果。Windows integrated 一度出现的本地半副本属于复制诊断；本次只读取恢复后 59,816 B、SHA `531b5b631e40bb5d4bc08fb3e31fb7db43374cdb5e6ca65b343f7123ca8c1751` 的完整原件，不将 local-incomplete 文件当 CI，也不新增一次失败。

四项后续重跑 `105156825897`、`105159915319`、`105160660583`、`105160666174` 的冻结时状态以 [retry-observation-at-freeze.json](retry-observation-at-freeze.json) 为准；本报告未审核其后续日志，不声称它们仍全部 pending，也不使用晚到结果改写首轮结论。依冻结决定，Windows funded-library 不再启动 C4 重跑。C4 的全阶段接受状态固定为 **NOT_ACCEPTED**；本报告保留可复核的局部成功和完整取消历史。
