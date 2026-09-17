# C7 准确源码测试预期独立审核

**静态审核未发现新的挂载或断言阻断；C7 仍待准确候选的原生验证，不能继承 C6 的测试通过。** 本次静态检查确认移除了同一 library crate 的重复 fixture 模块声明，没有放宽 Clippy 或删除真实测试。是否实际通过严格 Clippy 必须另由 C7 原件确认。

source `de474720431daf33afd4a7ebc32de2d230344a5a`，tree `e4dd17dfb1efd0e3ca20441168b62b72b6fc3108`，parent `88146d54f2eaac39958ceaaea9e13f71832d536e`，base `6913d4ab2fda6956db37e0ceb49790a4518c2762`，PR #13。独立审核者 `/root/p2_archive_native_audit/source_expectations` 未编写候选代码，使用准确 `git show`、完整 diff、blob/测试主体字节比较及 commit 内 grep；未读工作树、运行 Rust、触发或轮询 CI。C4/C5/C6 历史原文未改。

## fixture 导入路径与 cfg

准确 C6→C7 只改三个文件，合计 +5 / −5：

| 文件与准确行 | C7 内容 | 静态结论 |
|---|---|---|
| `src/pool_tests.rs:7–8` | 保留唯一 `#[path = "../tests/support/fixtures.rs"]` 声明，visibility 从 `pub(super)` 改 `pub(crate)` | 该文件由 `pool.rs:781` 的 `#[cfg(test)] mod tests` 挂载，只在库测试编译中存在 |
| `src/pool.rs:785–786` | `#[cfg(test)] pub(crate) use tests::fixtures;` | 只对同 crate 测试代码重导出；移除此块后整份 pool.rs 与 C6 字节相同，无生产 API 或 replay 变动 |
| `src/wire/fixed_key_tests.rs:3` | `use crate::{pool::fixtures, CIRCUIT, NETWORK};` | 使用既有模块，删除了原来的第二个 `#[path] mod fixtures` 声明；wire 私有测试模块仍只由 `wire.rs:20 #[cfg(test)]` 挂载 |

对准确提交 `integration/orchard/src` 的完整搜索仅找到 **一个**指向 `support/fixtures.rs` 的 path 声明，即 `pool_tests.rs:7`。integration harness 各自的支持模块属于不同 crate，不把它们误当这个 library 的重复声明。本次没有 `allow`、warning suppression、feature 弱化或生产公开接口扩展。

## 保留的真实断言与运行边界

新增完整全名仍是：

`wire::fixed_key_tests::concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold`

现在位于 `fixed_key_tests.rs:9 #[test]` / 10 行函数；从 `#[test]` 到 EOF 的**完整主体与 C6 字节完全相同**，所有断言、线程、真实 proof 和错误路径均保留。fixture 源文件也完全相同，pool_tests.rs 除一处 visibility 外完全相同。新用例没有 OS / feature gate、ignore 或提前返回，default 与 local-funding-lab 两平台都应运行。

实际源码仍只构建一次真实 fixture（20 行调用 `fixtures::prove`，21 行固定 CIRCUIT ProvingKey）；真实 helper 保留 `create_proof` 和签名。先检查固定 key 版本 / 地址与各实例空 cache，首实例验证不温热其他实例；四个 worker 在 64 行分别新建 verifier，从自己的空 cache 完成真实验证，并在 74 行对可解码 proof 字节及 binding-signature 字节翻转要求 Authorization，失败不得写成功 cache，随后有效字节仍可验证；既有第二实例与末次新建实例继续证明 cache 隔离。

**四线程只检查已经初始化的固定 key 的并发使用，不覆盖冷 OnceLock 首次初始化竞争，也不增加测试函数数。** wire runtime 文件完全未改：私有 `OnceLock<VerifyingKey>` 仍只构建 `FixedPostNu6_2` 的公共 key，每个 verifier 新建独立空 cache；canonical decode、cache、spend 签名、binding 签名、真实 proof、最后 remember 的顺序保留。

生产 pool replay 前缀完全未改；每次 replay 仍新建 verifier。ActiveArchive 复制的源、目标、末次源三次完整 replay 和导出 replay 都未改。原 archive 18/17 用例、四个 funded active_flow（真实付款跨段、10001、交换两个已有段后原 pin/repin 拒绝、重算 pin 坏签名 Authorization、恢复续付）及 CLI 7 原文均保持。CLI 两次真实 payment-proof 构建、第七项 stdout 四 mode、File 探针、exit 1、可写正对照与后验 verify 均未减少。

## 计数与完整目标预期

| C7 静态预期 | Ubuntu | Windows |
|---|---:|---:|
| 原 archive 新增库用例 | 18 | 17 |
| 固定 public key 新库用例 | 1 | 1 |
| 累计新增库用例 | 19 | 18 |
| default 完整 lib | 140 | 133 |
| default 全目标 passed / 结果数 | 154 / 18 | 147 / 18 |
| funded 完整 lib | 159 | 152 |
| funded active CLI | 7 | 7 |
| funded interfaces passed / 结果数 | 56 / 20 | 56 / 20 |

这三处导入改动没有增减任何测试或 Cargo target。配套 JSON 保留全部 27 个跨平台新增函数、四个既有 flow 的准确全名、feature、平台、验收点；更新了 wire 测试行号和 pool 挂载因新增三行导致的位移。默认 active CLI 仍预期 0，不能计 funded 7；worker 线程、嵌套进程、proof 构建与重复 replay 不重复计数。

自动 metadata 调度器、调度器测试、manifest/lock、全部 workflow 和预算均与 C6 字节一致：一完整 lib；funded interfaces 5 bin + 14 integration，再独立 doc，无测试名字过滤。Orchard 仍精确 `=0.15.5` 与原 checksum，Rust 1.98.1 及 Halo2 等锁定版本不变。

C6 的 Ubuntu default 确实完成 18 结果 / 154 passed，但随后的 duplicate_mod / exit 101 使 C6 不接受；该事实仅保存在历史记录，本 C7 静态审核不转用其结果。C7 尚未收到运行原件和 synthetic 身份，保持待验，不声称编译、fmt、严格 Clippy、双平台或全矩阵通过。
