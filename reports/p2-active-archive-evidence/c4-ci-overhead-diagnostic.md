# C4 原生 CI 开销：有界只读诊断

记录：2026-09-17 10:12 UTC。诊断任务 `/root/p2_archive_review`；日志／准确 base 对照由只读子任务 `/root/p2_archive_review/ci_cancel_timing` 协助。未修改源码、测试、设计、工作流或既有审核原件，未执行测试、安装工具链或重跑 CI。本文件仅供后续选择，不加入 C4 的代码 PASS 或原生通过结论。

对象保持 source `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736` / tree `3c44977028b58ddd387f52946632af594208edfb`，base `6913d4ab2fda6956db37e0ceb49790a4518c2762`。最后本地检查 HEAD/tree 正确、工作树干净。

**判断：新增 core／namespace 测试确实给已有默认库测试增加了数分钟耗时，其中存在可避免的重复初始化。最明确的源码来源是每次 fresh AuthorizationVerifier 都重新 build 同一个固定电路的 VerifyingKey，连只含空块的归档／名称测试也支付该成本。日志与调用数量高度相关，但没有 profiler，不能把区间每一秒都归因于 key build。** 当前四个首次 attempt 均完成整个库测试后才取消；取消不是已有断言失败的证据，也不能把未完成步骤计为通过。

## 原生观察与准确边界

四个 workflow 文件在 base 与 C4 字节相同：wallet/crypto/integrated 为 25 分钟，bridge 为 20 分钟，RAYON_NUM_THREADS=2、CARGO_BUILD_JOBS=2、test-threads=1 均未改。

| 首次 attempt | 原生结果与时间 | 最后实际执行位置 |
|---|---|---|
| Windows wallet 105145580574 | 09:25:12–09:50:17，25m05s；132 库测试 passed，1122.67s | 完整 cargo test 完成后，Clippy 开始于 09:49:47；09:50:13 出现 Finished release，随后取消；步骤被记录 cancelled，最终 drift skipped，不能自行升格该 gate。 |
| Windows crypto 105145581342 | 09:35:33–10:00:45，25m12s；132 库测试 passed，1234.98s | 10:00:39 开始旧 authorization_cache 集成目标；10:00:41 取消，测试未得 ok；static/drift skipped。 |
| Ubuntu bridge 105145581152 | 09:43:25–10:03:33，20m08s；139 库测试 passed，973.64s | Rust、Clippy/build、Go regression 和真实 Go→Rust proof 完成；10:03:19 开始 race，10:03:31 取消，race 无成功结果，fuzz/drift skipped。 |
| Windows integrated 105145580979 | 09:37:27–10:02:40，25m13s；132 库测试 passed，1122.59s | 10:02:32 开始旧 zero_value_real_proof_for_consensus，10:02:35 取消；root Go／four-process consensus 等后续步骤未执行。 |

原日志只明确写 `The operation was canceled.`。时间与预算吻合，支持“预算余量被挤压”的判断；没有读取到明确 timeout 根因句，不能把这种推断写成平台已确认的取消原因。未观察到这些取消点的断言、编译或 lint 失败，不等于未完成目标已成功。

Windows integrated 的本地最初稿为 45002 字节、SHA256 `f4c4769ded27fdf5e82047e8e013cb0d31ffbf0f7827aedf8d7044a67ff47934`，止于半行，不能当成完整日志。子任务通过 GitHub plugin 另取完整日志后，我在 10:10:52 UTC 再检查时本地该路径已经由原生证据流程更新为完整 59816 字节；我亲自读取其中 132 passed、取消及 cleanup。本诊断没有写入／覆盖该日志。

本次最终读取的四个本地原件位于 `c4/`：

| 日志 | 字节数 | SHA256 |
|---|---:|---|
| job-105145580574.log | 59588 | a790c404ae69d567175690cb37ec23864a6499da4afb8f60005e051981522515 |
| job-105145581342.log | 46528 | 7d42e4434fb160cf4bf921e2d6fd8cfe419f761d2624cbb8f5912724ad54be63 |
| job-105145581152.log | 71552 | 0bcd032629d75209a336a7f4892943b3a6677bf92156922a9a795613478cdd6a |
| job-105145580979.log | 59816 | 531b5b631e40bb5d4bc08fb3e31fb7db43374cdb5e6ca65b343f7123ca8c1751 |

## 新测试的时间证据

按单线程运行中前一个旧测试完成，到新组最后一项完成的时间戳估算。包含调度、I/O、输出等，既不是 test harness 内建逐项计时，也不是 CPU profiler。

| C4 作业 | 新 active core／namespace 逐项 ok | 整组区间估算 |
|---|---:|---:|
| Windows wallet | 17 | 370.77s |
| Windows crypto | 17 | 405.64s |
| Windows integrated | 17 | 368.15s |
| Ubuntu bridge | 18 | 352.69s |
| Ubuntu crypto（已成功的同候选参考） | 18 | 273.41s |

Windows wallet／crypto 中 `genesis_and_committed_archive_copies_preserve_every_file_and_continue_normally` 分别约 87.51/97.33s，`active_archive_locks_coordinate_real_processes` 约 46.37/53.40s，partial/lost-ack 约 44.84/48.32s，final-source/target namespace 约 42.63/41.82s。它们都是空块和公开字节／文件系统语义测试，耗时并不来自这些 fixture 新建真实付款证明。

准确 base 的同 workflow 对照由子任务通过 GitHub plugin 读取：

- [base Windows integrated job 105112959141](https://github.com/youq616/Zevune/actions/runs/35194045376/job/105112959141)：success，总 24m05s，115 库测试 834.42s，四进程／restart 最后完成。C4 对应库增加 17 项后为 1122.59s，其中新组约 368.15s。base 本来距 25 分钟已很近。
- [base Ubuntu bridge job 105112959181](https://github.com/youq616/Zevune/actions/runs/35194045384/job/105112959181)：success，总 13m51s，121 库测试 567.95s，race/fuzz 完成。C4 对应库增加 18 项后为 973.64s，其中新组约 352.69s。

准确 base 的 head_sha API 返回的 8 个 runs 没有 wallet/crypto，故本诊断不杜撰这两者的同 base workflow 对照。不同 runner 的速度波动明显，旧／新完整库差值不等于新增组时间；不能从这些数字保证下一次运行何时完成。

## 源码可确认的重复工作

`wire.rs:270` 的 AuthorizationVerifier::new 每次都调用 `VerifyingKey::build(CIRCUIT)`，并新建空 VerifiedCache；`lib.rs:27` 的 CIRCUIT 固定为 FixedPostNu6_2。共享 active replay 在 `pool.rs:476` 每次新建 verifier；ActiveArchive::open 自带 verify，每次显式 verify 再重放；正常 copy_new 内部先源、再目标、最后源共三次新 replay。创建普通 store 也会初始化 verifier。

这三次生产 copy replay 和独立缓存是冻结安全合同，不应为了 CI 耗时删去。当前测试另外增加了多次没有中间状态变化的 open 后立即 verify、重复源验证，以及相同空块 fixture 重建。

两个手工核对的静态调用例子：

- `genesis_and_committed_archive_copies_preserve_every_file_and_continue_normally` 对 height0、height3 各循环一次。每轮 fixture 2 次 new，源 open 1、紧随其后 verify 2、copy 3、backup open 1、restore copy 3、backup/source 再 verify 2、普通恢复 open 1、pin export 1，合计每轮 16、两轮 32 次 key build。库日志两例约 88–97 秒。
- 实际多进程锁测试主路径及成功子进程合计约 17 次 verifier 初始化；它的日志两例约 46–53 秒。失败取锁的分支在 verifier 前返回，不计为初始化。

以上为按已读源码的成功分支静态计数，未插入计数器；每次初始化平均约几秒的对应关系支持热点推断。磁盘同步、线程调度和进程启动亦有成本，不能将这个除法当成独立 benchmark。

## 可供后续选择的具体方案

**优先保持 C4 冻结，等待已授权的每个任务一次同源重跑结果。** 本诊断既不触发额外重跑，也不把“接近完成”代替通过。若仍不能在原预算完成，应另立优化候选，保存当前取消证据并按新 source/tree 重新独审与完整回归。

**方案 A：仅整理新测试的重复准备与重复检查，保持所有独立验收情景。** 可首先把 namespace 测试同一高度的空块 fixture 通过一次正常 create/commit/export 生成不可变公开 bytes/pin，再写入每个 case 自己的新目录；保留每个 case 的实际 archive open、句柄／锁、名称攻击及原字节断言，绝不共享正在被改写的目录或 live PoolStore。Unix 六种 entry replacement/link case 可复用一个已生成 fixture，Windows／其他同高度 namespace case 也可复用只读值；生成向量、PreparedBlock、不同真实历史等专门测试仍保留自己的生产准备路径。

对无中间操作的 `ActiveArchive::open(...).verify()`，open 已完成完整验证，可逐项考虑删去紧邻的第二次同样调用。必须保留至少一个明确的重复 verify 测试、打开后改变字节／namespace 再 verify 的测试、共享读者／drop 生命周期、两种高度 backup→restore、每种故障与后验验证、真实多段与 repin 拒绝。不能机械批量删除所有 verify：有些调用证明 copy 后保留句柄仍可用，或恰好检查已发生的状态改变。

这种测试整理不改真实验证器、生产三次重放或预算，也不减少真实付款／坏签名样本。合理预期是少量至几十次初始化的成本减少，尚未测量；**不能保证仅此方案就让 Windows integrated 在 base 已达 24m05s 的预算下获得足够余量**。应先建立修改前后情景／断言映射再实施，不能把删测数量当成优化目标。

**方案 B：若需要可靠保留全部现有测试调用，单独评审“共享固定不可变验证密钥，保持每次全新验证上下文”。** 将固定 CIRCUIT 的 VerifyingKey 作为进程内一次初始化的不可变公共材料；每次 AuthorizationVerifier::new 仍产生新的 verifier 对象及独立空 VerifiedCache，全部签名、proof.verify、状态规则和三次 replay 原样执行。可考虑标准库 OnceLock 持有固定版本 VK，再由 verifier 只读引用；不要共享整个 AuthorizationVerifier 或 VerifiedCache，不接受文件／网络传入 VK，不改变电路版本，也不以现有 cache hit 认证新归档。

这是运行代码／生命周期变更，必须作为新候选先明确设计，再独审；当前不提供实现或批准。上游 Orchard 0.15.5 官方 API 将 VerifyingKey 按明确 circuit version 构建，并标明 Send/Sync；这支持进一步研究不可变材料复用，不能替代项目自身对版本绑定、失败关闭、资源生命周期和线程安全的验证。[Orchard VerifyingKey 官方 API](https://docs.rs/orchard/latest/orchard/circuit/struct.VerifyingKey.html)。构建错误／panic 不得回退为接受；若未来支持多个 circuit，必须按准确版本隔离，不能复用错误版本。

该方案能原样保留所有重复验证测试和真正重放次数，收益范围可能比 A 更大；但本诊断未实现、未测量，不承诺节约秒数。验证至少应包含：保留完整原生矩阵与原时间预算；固定电路 genuine proof 正负样本；跨新 verifier 的缓存隔离／重新授权；repin 坏签名仍 Authorization；真实归档恢复和再次花费；并发初始化只有正确固定密钥而无共享成功缓存。只允许公开计时／计数，不记录交易或秘密数据。

不建议直接提高 timeout、删去旧 cohort、减少真实付款证明、跳过完整重放／同步、把 cancelled 记成功、或通过无限重跑直到偶然成功来回避成本问题。把重复 workflow 合并或拆分新 jobs 是更大 CI 设计调整，会改变总资源和验收映射，不是本次 C4 的可直接替代品。

本诊断的可执行决定仅是保留明确证据和上述后备候选，C4 的既有静态审核结论及原生待验状态不因本文件改变。
