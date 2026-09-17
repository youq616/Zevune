# 固定公共验证密钥复用：独立设计审核原件

审核者：`/root/p2_archive_review`。日期：2026-09-17 UTC。本代理未编写或修改候选设计、实现、测试及工作流。

## 准确对象与结论

**PASS_DESIGN_ONLY：通过本次准确设计，未发现需要先修改设计的阻断问题。** 这允许按已审核合同实现，不代表 C5 代码、原生矩阵、性能或阶段验收通过。

对象为 `docs/FIXED_VERIFYING_KEY.zh-CN.md`，63 行、4682 B，SHA-256 `363e6a9576b12e5f2eb39487b00486cef92e9a49bc5728d47bf266b23a14f5a5`。我完整读取原文，并在出具记录时重新核对其字节与摘要。

依附 C4 source `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`，tree `3c44977028b58ddd387f52946632af594208edfb`；阶段 base `6913d4ab2fda6956db37e0ceb49790a4518c2762`。开始审查时实际状态只有该设计 untracked，tracked/index diff 为空；此轮读取 wire/cache/pool 原路径时仍为 C4 原实现。

**结束时工作树已变化，不能说仍只有设计文件。** 作者收到另一路设计审核后开始实现：`docs/AUTHORIZATION_CACHE.zh-CN.md`、`integration/orchard/src/wire.rs`、`integration/orchard/tests/authorization_cache.rs` 修改，新增 `integration/orchard/src/wire/fixed_key_tests.rs`；设计本身摘要仍不变，HEAD/tree 仍为上述 C4。本原件不审查这些未冻结实现，不给尚未收到的 C5 冒填 source/tree。候选实现应另行准确冻结并独审。

## 实际审查范围

完整审查新设计，并对照 `AGENTS.md`、`STAGE_REVIEW.zh-CN.md`、`AUTHORIZATION_CACHE.zh-CN.md`、冻结活动归档合同的新验证器/完整重放条款。源码复核涵盖 wire 完整规范解码和授权顺序、cache 私有容器、固定 CIRCUIT 与签名摘要、pool 每次状态检查及 fresh verifier 重放、active 复制三次验证，以及旧真实授权缓存回归。核对锁定 Orchard 0.15.5、halo2_proofs 0.3.5 与 Rust 1.98.1。

我独立查阅 Rust OnceLock 和上游 Orchard VerifyingKey API。另委派只读辅助 `/root/p2_archive_review/ci_cancel_timing` 专查现有测试与设计隔离要求；该代理未编写文件、未执行测试，反馈未发现设计 blocker。我已读取其完整反馈，其结论不能替代本代理自己的源码与合同核对。

## 设计判断

1. **固定公开材料与授权结果分开。** 原 `AuthorizationVerifier::new()` 每次构建同一 CIRCUIT 的 VerifyingKey，同时新建 VerifiedCache。设计只将前者变为模块私有 OnceLock 中的只读静态引用，后者仍逐实例独立且为空。CIRCUIT 保持 FixedPostNu6_2，不来自交易、检查点、profile、文件或网络；不增加外部密钥、其他电路、共享整个验证器或全局授权缓存入口。

2. **接受条件不变。** 规范解码、实例自身精确字节查找、全部花费签名、绑定签名、真实 proof、成功后 remember 的顺序保持。新实例首次遇到交易仍须执行完整密码学检查。域、过期、高度、历史根、双花、重复输出、费用及提交规则仍由账本逐次检查，公共密钥不是花费许可。

3. **归档真实性要求保持。** PoolStore 重放仍新建验证器并绑定独立 genesis，完整遍历、检查 frame/EOF/namespace；copy_new 的源前验、目标验、末次源验三次完整重放以及最终目标字节检查不删除。共享固定公共材料不使任何旧验证成功结果成为新归档的授权依据。

4. **同步和失败边界合理。** 标准 OnceLock 可在静态对象中并发初始化；get_or_init 正常完成只初始化一次；初始化 panic 向调用者传播且单元仍未初始化。重入初始化是错误，设计明确禁止。后续若上层捕获 panic，只能重做同一固定构建，不得返回备用成功结果；没有新加接受路径。[Rust OnceLock 官方文档](https://doc.rust-lang.org/std/sync/struct.OnceLock.html)

5. **固定版本和资源限制明确。** 上游 API 提供显式版本 build、circuit_version 以及 Send/Sync。实际读取的是 latest URL，页面标为 0.15.5；没有把未成功读取的版本专属 URL 或上游实现源码算成核验依据。实际锁定依赖能否在所有 feature/platform 编译须由新候选原生矩阵确认。密钥保留至进程退出，未来换版本重新审核，没有多版本运行时切换承诺。[Orchard VerifyingKey API](https://docs.rs/orchard/latest/orchard/circuit/struct.VerifyingKey.html)

6. **性能动机保持证据边界。** 重复构建固定密钥有源码证据；日志耗时与它相关，未做性能采样将全部耗时归因于它。全部测试、真实证明、重放、并行配置和原预算保持，不能预先保证解决每个取消。旧 C4 成功片段不能成为 C5 的通过信用。

## 实现回归要求

以下要求落实已通过设计，不表示已执行，也不要求伪接受器或新生产诊断接口。

| 边界 | 有意义的结果 | 不充分证据 |
| --- | --- | --- |
| 固定版本 | 多实例取得同一只读 key，circuit_version 等于 CIRCUIT，构造来源只有固定常量 | 仅 ptr_eq，不核对版本与构建来源 |
| 缓存隔离 | A 真正 verify 有效 fixture 前无条目、后有条目；提前创建 B 以及随后新建 C 均仍无条目，各自 verify 后才独立记入 | 手工 remember；只断言对象不同；只检查新实例 verify(raw) 成功 |
| 实际并发 | 并发创建/使用实例、保持独立空缓存，真正 verify，join 并检查全部线程结果；共享 key 而不共享成功条目 | 仅并发读指针、忽略线程 panic、没有 join、只测单实例 warm hit |
| 坏签名和坏 proof | 真实 fixture 对应字节改变后仍可规范 decode，明确 Authorization 拒绝，坏字节不缓存，有效原字节仍成功 | 只有截断/长度拒绝或 is_err，不能辨别结构错误与密码学拒绝 |
| 初始化失败 | 实现保持直接固定构建，无 catch 后成功、备用 verifier、重入或可变替换 | 用另一个 OnceLock 的标准示例冒充上游构建 panic 已测 |
| 归档与状态 | 旧测试/断言、真实付款、重算 pin 后坏授权、三次重放和失败不变性全部保留 | 少做调用、删测试、放宽预算、引用旧候选成功/取消 |

现有 authorization_cache 集成测试末尾只断言新实例 verify(raw) 成功，即使误共享成功缓存也可能通过；cache.rs 原并发测试的合成 remember 只证明容器。新增回归需要通过真实生产 verify 得到成功条目，然后在私有测试内用 contains 观察各实例，不能导出生产写入接口或 fake remember。

指针相等有助于证明复用，但不能单独证明授权安全。若 fixture 或其他测试已先初始化全局 key，普通并发测试只覆盖并发使用，不能声称冷首次初始化竞争已覆盖。设计已经明确这个边界；独立新进程冷启动竞争不是当前设计通过的附加先决条件。上游构建 panic 若未实际注入，也必须按未测报告；本设计不需要为了测试标准库而增加生产可注入 initializer。

旧测试“new fixed key”注释以及 AUTHORIZATION_CACHE 文档“自行构建固定密钥”的生命周期文字应同步澄清；所有旧断言保留。这属于实现文档验收，不是当前设计级 blocker。

## 未执行与结论限制

本轮未编写候选文件、安装工具链、运行原生测试、重触发 CI 或测量性能；未运行 C5 fmt/Clippy、真实证明、Windows/Ubuntu 矩阵，未测冷进程首次初始化竞争、构建 panic、峰值内存或进程终止。没有外部安全审计或真实资金结论。

下一步冻结实现准确 source/tree，对全阶段 base..新候选及直接调用方/回归重新独审，并取得同一候选完整原生矩阵。原 C4 静态 PASS 仅保留其原范围；C4 取消、部分成功及 race 勘误都不补足新候选验收。本次零设计阻断不覆盖尚未审查的实现缺陷。
