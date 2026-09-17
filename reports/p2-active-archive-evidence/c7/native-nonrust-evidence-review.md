Zevune C7：非 Rust 原生证据独立审核

结论：**PASS_NATIVE_NONRUST_EVIDENCE，仅限本报告的 17 个非 Rust 检查范围。** 原生日志、步骤状态、准确 checkout、平台跳过项和资源原件相互一致，未发现本范围内的验收阻断。混合 job 中的 Rust 测试数量、proof/CLI 单项完成由另一独立子审认证；本报告不替代完整 23-job 汇总，也不表示阶段接受、合并、发行或安全审计完成。

审核者 `/root/p2_archive_adversarial_review`，2026-09-17 UTC。本次接受 `/root/p2_archive_native_audit` 的有界证据审核任务，逐日志装载完整原件、核对 API metadata 与末尾完成步骤，按行扫描错误/跳过/测试结果，读取实际命令、输出和对应源码。本人没有写候选代码、修改工作流、执行二进制、触发或轮询 CI。既有 C1/C3/C4/C5/C6/C7 静态原件全部保持冻结。辅助任务 `/root/p2_archive_adversarial_review/nonrust_scenario_contract` 只读核对场景与平台条件；本人另读关键付款/重启/资源完成源码，独立核对原日志和所有 ZIP 字节，不以主审 working 摘要或辅助结论替代原件。

| 身份 | 准确值 |
|---|---|
| PR | [youq616/Zevune #13](https://github.com/youq616/Zevune/pull/13) |
| Stage base | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| Source | `de474720431daf33afd4a7ebc32de2d230344a5a` |
| Tree | `e4dd17dfb1efd0e3ca20441168b62b72b6fc3108` |
| 实际 PR checkout | `00d4442b12cb72344ffa5bea101eb7142ab03270` |

`source-identity.json` 的 source/tree 和 synthetic 两父提交经独立核对；synthetic 的 tree 与 C7 source tree 相同。以下每份日志均出现准确 source 合入准确 base 的 checkout，API check-run head 为 C7、状态 completed/success，日志长度与 SHA-256 等于原子发布记录，末尾 Complete job 成功。完整日志及 metadata 的逐件摘要在配套 JSON 中。123 项非 Rust 源码、工作流和依赖与 C4 的连续性也独立用准确 git blob/长度/摘要复核；**源码相同不继承任何旧运行结果。**

本范围为 11 个完整的非 Rust 主 job，加 6 个混合 job 的 Go/Python 部分。表中的通过数量按日志实际类型区分；没有把包成功、seed harness、子案例、helper、编译检查或 Rust 结果混算成独立场景。

| 范围 | Ubuntu job | Windows job | 本次实际证据 |
|---|---|---|---|
| Scaffold | 105169884469 | 105169884871 | 各 7 个实际测试包、2 个无测试 command 包；fmt/vet 成功；Ubuntu 另有 7 包 race 与两次 bounded fuzz |
| Consensus laboratory | 105169883820 | 105169883452 | 各 59 个顶层 Test 结果、4 个 Fuzz seed harness、43 个子案例；全套 test/vet/build；Ubuntu adapter race |
| Orchard bridge，Go 部分 | 105169884058 | 105169884404 | root 7 包回归/vet、真实 Go→Rust authorization 单项 2.14 / 3.01 秒；Ubuntu boundary race、两个 10 秒 fuzz |
| Orchard integrated，Go 部分 | 105169884577 | 105169884951 | root 回归、CometBFT 回归/vet、pool_e2e 6 个顶层结果；Ubuntu 真实 adapter/IPC race 与 10 秒 fuzz |
| Funded interfaces，Go/Python 部分 | 105169883929 | 105169883969 | Python 135 项：132 成功+3 平台 skip / 134 成功+1 平台 skip；真正 Python→Rust interop；funded 四节点主场景 56.35 / 83.96 秒 |
| Operator | 105169884503 | 105169884063 | 各 51 个顶层 Test、4 个 seed harness、47 个子案例；Python 同为 135 项及对应平台 skips；实际 bundle 构建/使用；Ubuntu race 与三次 3 秒 fuzz |
| Active growth | 105173493571 | 105173493547 | 精确增长测试各 1 项，74.62 / 478.15 秒；100000 次真实本地 worker 提交及恢复后空块 100001 |
| Payment resources | 105169883621 | 105169883365 | Python 53 项：50 成功+3 skip / 52 成功+1 skip；真正 32+1 付款场景 155.66 / 223.44 秒及完整资源原件 |
| Active source | 105169883377 | 不适用 | 原工作流固定 Ubuntu；source formats、双 Go module compile-only 与锁/源码无漂移检查成功，不计实际 Go tests |

**实际 fuzz 与平台 skip。** Ubuntu scaffold FuzzDecodeBinary/FuzzJournalBlockDecode 各 3 秒，两 worker，最终分别 7690 / 151359 次执行；bridge FuzzDecodeEnvelope/FuzzReadFrame 各 10 秒，497102 / 388902 次；integrated FuzzPoolFrame 10 秒，385029 次；operator FuzzCanonicalPublicConfiguration/FuzzNumericLoopbackEndpoint/FuzzTestGenesisFrame 各 3 秒，9394 / 11094 / 49666 次。计数是本次观察，不是安全覆盖率或性能承诺。consensus/operator 普通 go test 下的 Fuzz*/seed# 是 seed 回归，与这些持续 fuzz campaign 分开。

Windows 按原 workflow 明确跳过 scaffold race+两 fuzz、consensus adapter race、bridge race+两 fuzz、integrated adapter/IPC race+fuzz、operator 整段 race+三 fuzz；没有把它们写成 Windows 通过。Python 在 Linux 跳过三个 Windows 文件共享案例，在 Windows 跳过一个 Linux proc descriptor 案例；Windows 的三个实际共享/替换案例全部输出 ok。没有未解释的运行 skip。日志中 actions 的 Node.js 20→24 弃用提醒不是测试失败；没有 error、FAIL、panic、race 报告或非零 exit 标记。

**真实场景范围。** `TestNodeProcessHelper`、`TestPoolNodeHelper` 等顶层 PASS 包含没有子进程环境时直接 return 的 helper，不能额外计真实网络场景；源检查与 funded 前置 `-run '^$'` 仅编译，也不计测试。非 verbose root Go 日志只足以证明包级成功，本报告不虚构其函数级通过数量。

funded 的 `poolapp/funded_e2e_test.go:255` 与 operator 的 `labnet/operator_e2e_test.go:253` 都在全四节点重启前完成 A→B→C，随后检查恢复/余额/重复付款拒绝。**operator 全套中全网重启后的新付款依据是另一项** `TestActiveFundedFourNodePaymentRestart`，在 active_funded_e2e_test.go:188–227 顺序执行 A→B、全四节点停止/重启、B→C；该项 Ubuntu 74.50 秒、Windows 77.93 秒，均实际 PASS。不能把它归给 `TestRealOperatorNonzeroPaymentsAndRestart`，后者分别 92.09 / 109.24 秒。QuorumSignedWrongPostState、reference pin、真实 journal copy/adversarial replay、offline storage/lock 等 operator 案例亦在原件中完成。

**100000 增长。** 两平台 `ACTIVE_GROWTH_RESULT` 均明确记录 100000 committed、99998 empty、2 paid、15018544 logical bytes、15 segments、每段上限 1048576。Ubuntu growth/replay 为 64090 / 2428 ms，Windows 为 464635 / 3257 ms。源码在 9999 和 10001 高度付款，恢复后 100001 使用 nil tx，增加一个空记录。精确 15 段/15018544 字节来自本次日志；源码通过真实 frame 大小累计、全状态及容量/物理记录比较，要求 repeated rotations，并未硬编码这两个结果。这里是本地 worker 提交，非四节点 100000 共识高度，也不证明超过 64 MiB、全 commitment 容量或 100000 笔付款；耗时包括耐久写入和边界 proof/钱包检查，不能换算付款吞吐。

**资源原件独立验证。** 以下完整小 ZIP 是保留的原件。本人重新计算整体 digest，核对 API size/digest、对应 job upload log、两名成员和已解包 JSON 的逐字节一致性；再独立核对 source/tree/synthetic、每个事件、进程身份、计数和完成结果。

| 原件 | Ubuntu | Windows |
|---|---|---|
| Artifact ID | 10493495324 | 10494490178 |
| ZIP bytes | 9297 | 9470 |
| ZIP SHA-256 | `f5022d99ae137c45cfa31ca4c769eb642304706f4a46fc4370d708fd65b22d9d` | `8e298238be965a850136001b11926fd84296420cd4148a5ecf5452defa0b1865` |
| resource JSON bytes | 130208 | 131259 |
| resource JSON SHA-256 | `3f2877bfe4e9c6c9b2befd5eb6d432cd85272aa26f71eb20600f6f345580dcc2` | `568f47a6765a61fe09e526c59240a62931afb62bedf66cf121a0b4949b212baa` |

每平台恰有 9 个按序 events/完整 memory checkpoints、18 个 OS samples、362 个连续 progress 条目、181 个 completed operations。started/completed 成对匹配名称/付款索引；result.timings.operations 与完成条目逐字数据一致，33 次 prepare/candidate/worker_commit/scenario_apply 各覆盖索引 1..33。阶段依次为 genesis、payment_8/16/24/32、worker_reopened_32、wallet_recovered_32、pending_restored_33、complete_33。sample 与各 event 的 role/generation/PID 一致，同代 creation identity 不变，只有 worker 两代加 scenario 一代三个身份；未把 PID 数字单独当身份。

最终两平台都为 33 付款块、每笔两 action、68 commitments、66 nullifiers、33000 fees、308756 logical bytes、1 段、308616 tail bytes，钱包记录 [52,51]、文件 bytes [1713368,1680420]。14 个 checks 全部为 true，Go exit 0、status passed、failures 空、无未完成操作、commit_outcome_uncertain=false。源码仅在第 33 笔真正提交、第二次磁盘逐帧检查、第二代 worker 关闭和 scenario 结束后写完整 result；第 32 笔后的 worker/wallet 恢复与第 33 笔精确 outbox/reservation 及错误 commit tag 保留 pending 的检查均在完成条件之前。

| 资源观察 | Ubuntu | Windows |
|---|---:|---:|
| Worker OS lifetime peak，bytes | 11509760 | 13135872 |
| Scenario OS lifetime peak，bytes | 176611328 | 117686272 |
| Go result total，ms | 155659 | 223185 |
| Supervised process，ms | 155727 | 225250 |
| Supervisor，ms | 155819 | 226031 |

这些是 Linux RSS/HWM 与 Windows working set/lifetime peak，不是 private heap、整机内存、阶段峰值或跨平台可比加速比。scenario 包含 proof、授权缓存、历史、双钱包和 Argon2；不含 Python supervisor/Go coordinator。预算是每进程 1 GiB 的测量检查，非内存强制隔离。cleanup 明确 registered children exit=true、registered processes=3，precheckpoint child-tree cleanup=false，保留后者限制。setup JSON 的 not_started 只是开始观察，最终完成依据是完整日志与 resource result。`result_sha256` 是原报告保存的原始 result.json digest；独立原始 result.json 不在 ZIP 中，因此只保留该 reported 值，不伪称从嵌套重序列化内容重算它。

**Operator bundle 的有界字节核验。** 两个完整大 ZIP 均在本地只读重新打开，未执行解包二进制。API、原 upload log、原 manifest、全部五个 payload 的长度/摘要一致，无重复、路径穿越、额外成员；两个文本文件又与 C7 git blobs 逐字节一致。

| Bundle | Artifact | ZIP bytes / SHA-256 | 原 manifest bytes / SHA-256 |
|---|---|---|---|
| Linux | 10493857439 | 22851758 / `6f36e3dd04c364eb502fb1882ce11c61262f73b15f514ec5cf23026fae4ff841` | 1288 / `3c128c636a5d8c1219a0d2349fc788a7fc9b2e491821844b98e43c54dca2878c` |
| Windows | 10494057037 | 22388948 / `36e519c629f07ae46c911d8e686c9189092599a711c9117ca1b317790e707855` | 1302 / `500c9e8b8ae8a531b305fbd25c33d63c55901b724f78cd8b5a9766a461212d72` |

每 ZIP 恰为 manifest 加五个清单文件，包含三个平台可执行文件、operator 文档和 wallet Python。manifest 的 source_commit 是准确 synthetic、source_tree 是准确 C7 tree，build_source 为 isolated_exact_git_blobs，real_funds/public_network/network_anonymity 三项严格 false。ZIP 没有 notice/license inventory，不虚构已包含或已完成发行审计。大 binary ZIP 按主审约定只作本地验证，证据 Git 保存原 API metadata、原 manifest 和成员核验表；这与两个实际完整归档的小 resource ZIP 不同。没有发布或运行这些 bundle。

**适用限制与交付。** 本次完整 17-scope 记录、每项步骤/日志摘要/计数/skip/fuzz、资源和 bundle 自主核验结果、原件索引在 `native-nonrust-evidence-review.json`；可追溯工作记录为 `nonrust-independent-review-working.json`。最终本地 metadata 已有 23 个 success，但本人的通过结论只覆盖上述 17 个非 Rust 范围，Rust 12 个 job 的重叠/补充审查及整阶段接受由主审另行汇总。没有借 C4/C5/C6 通过或取消补 C7；没有在本地缺少 Rust/Go 的情况下声称重跑。NO-FUNDS、可信 OS/文件系统、单机固定验证者实验、未测真实断电/磁盘满/全容量/生产吞吐和外部安全审计等边界继续有效。
