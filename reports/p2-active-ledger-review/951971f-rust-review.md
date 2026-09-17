# PR #9 独立 Rust、活动存储与增长场景审核原始记录

记录时间：2026-09-17 02:14:59 UTC。

审核者任务：/root/p2_design_review。

本文件由该独立审核任务直接撰写，汇总本任务已经返回的设计审核、实现审核和精确提交复审结果。审核者未编写候选运行代码或测试，未编辑仓库中的候选文件；本文件是审核原始产物，不是主代理代写的验收摘要。

## 结论与精确对象

本范围代码审核结论：**PASS，适用于下列精确源码提交。** 未发现本范围尚未关闭的代码逻辑阻断。此结论不表示完整阶段已验收，不表示 CI 已通过，也不表示 PR 已合并。

| 项目 | 身份 |
|---|---|
| 仓库 | youq616/Zevune |
| PR | https://github.com/youq616/Zevune/pull/9 |
| 阶段基线 | 2b889d52c2e6c765f03ea683f42b8467d66e47f5 |
| 最终已审源码提交 | 951971f46e964d259275653063c2dc9c2dcfd104 |
| 最终已审源码树 | 386d33907d86ac7b9ac4bfd6481c2298dd95686d |
| 最终提交的直接父提交 | a11370b2f151bfef47fa85e9082723e2d9381bd5 |
| 冻结设计文件 | docs/ACTIVE_LEDGER_V1.zh-CN.md |
| 冻结设计 SHA-256 | 7aa8d718ee9a86226d84ef57a060f937b35091a6f8c5e65011508c07e4e564ce |
| 冻结设计 Git blob | 157635809279daeb57dbb5ce138c9a1a1a1da7e5 |

审核者实际从 origin 获取有关提交并核验 parent/tree；没有仅依据主代理提供的提交名称作判定。对初次冻结实现，还核验了暂存树、工作树与目标提交一致。各次差异检查通过。

## 实际审核范围

已读取根 AGENTS.md、docs/STAGE_REVIEW.zh-CN.md 和冻结设计，并以原有调用方及测试契约核对下列实现：

- integration/orchard/src/pool.rs：固定容量 profile、genesis/state 绑定、prepare/commit 预算、真实执行、持久化后的状态发布、活动容量查询。
- integration/orchard/src/pool/active.rs 及其 tests.rs：目录和文件身份、稳定根锁、连续段名、完整物理帧、规范轮换、各文件实际 EOF、总容量、失败与重开行为。
- integration/orchard/src/pool/replay.rs、pool/selection.rs：共享重放的 profile 上界、错误后不可继续、选择预算和独立提交验证。
- integration/orchard/src/pool/testnet.rs：01/02/03 清单解码、固定公开测试发行、非零 nonce、03 签名域和状态身份。
- integration/orchard/src/wallet_history.rs：持锁逻辑流、每帧物理检查、完整重放完成后才返回认证历史。
- integration/orchard/src/pool/recovery.rs、pool/recovery/segments.rs 和 namespace.rs：旧 receipt 提前拒绝活动格式、健康 store 不被该拒绝破坏、共享名称绑定代码的可见性和新增方法。
- integration/orchard/src/bin/zevune-pool-worker.rs：IPC3/IPC4 区分、请求编号和摘要绑定、op6 固定尺寸与错误规则、存储不确定性终止进程。
- integration/orchard/src/bin/zevune-funded-scenario.rs：显式生成新 03 清单，真实钱包付款、恢复和完整历史路径。
- integration/orchard/src/pool/active_flow_tests.rs：域隔离、真实付款、默认段大小轮换、高度边界、旧模式拒绝、完整 PoolStore 故障原子性。
- integration/cometbft/poolapp/active_growth_e2e_test.go：实际 worker 的逐块提交、9999/10001 付款、钱包恢复、防双花检查、100000 块物理计数及重开后继续。
- scripts/zevune_wallet.py 和 scripts/tests/test_wallet_network.py：03 清单前置识别、LAB2 付款格式、完整清单 pin 与域隔离。
- integration/orchard/tests/genesis_domain.rs：最终测试修复及同文件原有真实签名、跨域与旧格式回归。
- .github/workflows/active-ledger.yml：准确源码、格式失败传播、固定工具链、原生增长任务和实际测试选择。

还顺带检查了 Go profile、op6 容量解析、ABCI InitChain 的 AppVersion 绑定和 FinalizeBlock 的编码调用，以核对 Rust 交界。这不代替另一独立任务 ci_code_review 对 Go/network 全范围的审核。

## 设计审核与关闭的阻断

初次冻结设计 SHA-256 为 0d9cba29e938cb2901e6f630600eff0b271bc67956da5ebbeaaac4f959a04774。本任务对该版本给出暂不通过，要求先关闭两项 P2 设计缺口，之后才开始实现。

1. **物理段边界和规范轮换。** 单纯把文件拼接成逻辑流，可能重新拼接被拆开的合法帧，也可能接受提前轮换形成的不同段数。修订设计要求每个物理段在完整帧末尾结束，并检查下一完整帧确实无法容纳才允许结束非末段；重开及历史重放均需核验。最终实现由 validate_frame 在每个完整重放块后、钱包 visitor 之前执行检查。
2. **活动容量查询的完整协议。** 新增 IPC4 op6，固定 161 字节响应，原 Summary 后追加大端 u64 逻辑字节、u32 段数、u32 尾段字节。普通拒绝尾部为零；旧 profile 拒绝该操作；Go 根据已 pin 清单推导真实头长度并检查关系；存储异常为 fatal。避免把目录 Stat.Size 误当账本字节。

本任务重新读取并核验修订后的设计 SHA-256 7aa8d718ee9a86226d84ef57a060f937b35091a6f8c5e65011508c07e4e564ce 和 blob 157635809279daeb57dbb5ce138c9a1a1a1da7e5，对该精确设计给出 PASS。该设计批准只允许进入实现，不替代代码和测试验收。

## 实现预审发现及后续补强

**P2：Windows 测试跨进程读取被排他锁定的 genesis。** 初版增长测试在 Rust worker 持有 genesis.try_lock() 时，使用 Go os.ReadFile 读取同一文件内容。Windows 的排他锁会拒绝另一进程读取锁区。审核依据为 [Rust File::try_lock 文档](https://doc.rust-lang.org/std/fs/struct.File.html#method.try_lock) 和 [Microsoft LockFileEx 文档](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)。

修复已独立复核：持锁阶段只检查 genesis 元数据与段字节；两个完整 header/物理历史扫描均移至 Client.Close 等待 worker 退出后，关闭前保存 Summary/capacity，第二次完整扫描还比较不可变 header 摘要。生产根锁没有放宽。此阻断在初次正式冻结实现前已关闭。

审核还要求补强两类证据，最终已读到相应测试：

- 旧默认 PoolStore 正常执行 10000 次 prepare/commit/write/sync 后，prepare 和 selection 拒绝 10001；通过持锁原句柄核对字节不变，并在关闭、重开后再次检查。
- 已有满段之后，下一段的四类发布故障保留全部已提交前缀字节，保留失败尾段，并区分空/部分段拒绝和完整帧可重放。另有完整 PoolStore 层 fault1/2/3/4 检查：公开接口变为 Unavailable，私有 committed state、逻辑长度、容量没有发布部分结果，禁止继续准备、选择或提交。

这些测试在代码层面使用真实持久化路径；本审核者未在本地执行 Rust 原生测试，不能把已读取测试说成已运行通过。

## 精确提交复审链

| 候选提交 | 源码树 | 本任务结论及差异 |
|---|---|---|
| 514c8632027de6f14173c7a51c6117d6a9a7fe73 | dc03b1ee32b2c0daca95a3bbb0d7294e6156adb8 | 初次精确实现代码审核 PASS；上述预审问题和测试补强已关闭。CI 当时尚未通过。 |
| a11370b2f151bfef47fa85e9082723e2d9381bd5 | 7ed4b1a6ecd461c10ac469f4facdba718f671fed | 增量复审 PASS。逐项读取 6 个 Rust、4 个 Go 文件的格式差异及 1 个工作流调整。运行条件、常量、状态转换和测试断言语义未改变。 |
| 951971f46e964d259275653063c2dc9c2dcfd104 | 386d33907d86ac7b9ac4bfd6481c2298dd95686d | 增量复审 PASS。只修改 genesis_domain.rs 的 13 行新增、4 行删除；正确扩展 03 测试且未降低边界。 |

a11370b 的工作流调整使 gofmt -d 非零时仍执行 Rust 格式诊断，最终继续严格失败。本任务提取该提交中的准确脚本，以模拟子进程结果实际执行 5 种组合，确认 Go 差异或任一非零结果都失败，且出现 Go 差异后仍调用 Rust 检查。这是工作流控制逻辑测试，不是实际运行原生 formatter，也不是密码学或状态验证的替代。

951971f 修复了旧测试把已支持的 ZVTGEN03 当成未知版本的断言：未知列表改为 00/04/99；02/03 均检查零 nonce；01/02/03 均检查每一截断位置和尾字节，并增加合法解码的原字节、摘要一致性。没有删除测试、增加 skip、过滤测试名称或放宽长度边界。同文件真实授权和跨域测试保持不变。

通过 Git 对象身份核验，951971f 相对 a11370b 的下列内容逐字节一致：

| 路径 | 未改变的 Git 对象 |
|---|---|
| integration/orchard/src | 013fe0d6ebcf1da5f643d1a360101002041bcd0d |
| internal | 6b6568334a76cebeb1d8f1b2062465f26e22d969 |
| integration/cometbft | 87f0df0885f69f7c747c42cef582678b6b516cbc |
| scripts | 7a3632b382b620edb9e7fd3c3dad2e502faefdc0 |
| .github/workflows | 63fbe0a3c0dc3c2ce017ad1e220d12e0038b6b90 |
| docs/ACTIVE_LEDGER_V1.zh-CN.md | 157635809279daeb57dbb5ce138c9a1a1a1da7e5 |

## 实现判断及实际限制

代码路径表明：03 的完整 manifest hash 隔离付款签名域，03 账本头进入 State.genesis 和应用摘要；旧格式仍维持原有高度、字节和恢复接口契约。预算计入 150 字节完整空帧及每笔 4 字节长度字段，最终提交重复真实授权与状态执行。跨段重放要求完整物理帧、规范轮换、各文件实际 EOF，任何失败后丢弃未发布重建状态。

增长测试逐块调用实际 worker 的 Finalize/Commit，没有直接赋值高度、预制日志或接受替身。9999 和 10001 的付款来自真实钱包，包含找零、费用、恢复与收款后再次花费；重复支付检查在有效期内进行。物理扫描核对实际记录数、段边界、付款原字节和最终摘要。这些是对测试代码真实性与覆盖范围的判断，不是声明该测试已执行成功。

本审核者本地没有 Go/Rust 原生运行结果。主代理报告的 Python 82 项和远端编译/测试信息不计作本任务独立执行的结果。CI 属于独立验收条件：本记录不宣称其已通过，也不替主代理宣称合并或完成。未来运行源码或测试改变后，须对新的准确提交复审。

必须保持明确的范围：100000 块是正常本地 worker 提交计数，约 15 MB，不能当作四节点共识 100000 高度、超过 64 MiB 或突破承诺集合上限的证据。四节点活动网络付款与重启需使用另一真实场景验证。完整钱包历史、状态集合和摘要扫描仍有增长成本；全部段句柄还会消耗主机文件描述符。故障注入验证代码对应行为，不证明实际断电零丢失。项目仍是 NO-FUNDS 本地实验，历史技术文档缺口保持记录。

本记录是独立编码代理审核，不是外部专业机构的协议、密码学或安全审计。最终阶段验收仍要求最终准确源码 CI、Go/network 独立审核、阻断反馈关闭和限制如实披露同时成立。
