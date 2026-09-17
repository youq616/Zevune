# C5 准确源码测试预期独立审核

**静态挂载与新增断言核对完成；C5 NOT_ACCEPTED。** 已直接读取 supplied native 原件 `job-105166096614.log`：准确 C5 checkout 在新测试 `assert_eq!` 的唯一 rustfmt hunk 后 exit 1。下列计数均为静态预期，不是 C5 测试通过记录；没有将 C4 的成功、取消或重跑转作本候选证据。

source `99ef9e8217182c9a6f4f1e9349613c1917ddec50`，tree `598f55a8d850095500329989b2ea1fa5855d5db9`，parent `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`，base `6913d4ab2fda6956db37e0ceb49790a4518c2762`，PR #13；该原生失败日志 checkout `44d9b13d1a1eed74158899717304aa42c1b5e30d`。独立审核者 `/root/p2_archive_native_audit/source_expectations` 未编写候选代码，使用 `git show`、完整 C4→C5 diff 与 blob 字节比较；未读取工作树、运行 Rust、触发或轮询 CI。C4 历史原文保持不变。

## 改动与授权边界

准确 diff 仅 5 个文件：`wire.rs`、新增 `wire/fixed_key_tests.rs`、`authorization_cache.rs` 的两行注释及两份合同文档。`wire.rs:261` 私有 getter 的函数内 `OnceLock<VerifyingKey>` 只构建 `VerifyingKey::build(CIRCUIT)`；`src/lib.rs:27` 常量仍为 `FixedPostNu6_2`。没有外部 key/版本选择、可变共享状态或失败后备用接受路径。`AuthorizationVerifier::new` 同时取不可变静态 key 引用和独立 `VerifiedCache::default()`；后者仍是实例自己的空 `Mutex<VecDeque<Entry>>`。

`verify` 的完整函数体与 C4 字节相同，唯一适配是 `.verify_proof(&self.key)` 改为 `.verify_proof(self.key)`。顺序仍为规范有界解码、该实例的精确字节缓存查询、所有 spend 签名、binding 签名、上游真实 proof 验证，最后才记入成功缓存。现有 cache 实现和 `authorization_cache` integration 全部断言保留；后者去掉注释后与 C4 完全相同。

`PoolStore::replay_active_handles`（`pool.rs:452`）在每次调用的 476 行仍新建 verifier、479 行完整遍历。`ActiveArchive::copy_new` 在 `active.rs:236/251/256` 的源、目标、末次源三次 `verify` 全部保留，每次通过 206 行重新 replay；导出在 126 行另做 replay。以上生产文件均与 C4 字节一致。归档 18/17、真实 growth / 10001 / 两已有段交换 / repin Authorization 的四个 flow，以及 CLI 7 和 stdout 四 mode 的原测试文件亦全部一致。

## 新增测试与精确预期

唯一新增全名：

`wire::fixed_key_tests::concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold`

由 `src/lib.rs:12 pub mod wire` → `wire.rs:20 #[cfg(test)]` 私有模块 → `fixed_key_tests.rs:12 #[test]` 挂载。没有 feature 或 OS 门控、ignore、提前返回；default 与 local-funding-lab 双平台均应执行。复用 `tests/support/fixtures.rs` 是私有支持模块，不新增 Cargo integration 目标。

该测试只调用一次真实 `fixtures::prove`，用固定电路 ProvingKey、真实 note/witness 与 60,000 / 39,000 输出生成有效付款 fixture。支持函数 102 行实际 `create_proof`、104 行实际签名，支持文件与 C4 字节不变。测试确认正确版本与同一个 public-key 地址、初始两个实例均无条目、第一实例成功后另一个仍冷；四个并发 worker 各新建 verifier、屏障后各自从空 cache 实际验证并记入，再分别拒绝可解码的首个 proof 字节翻转及最后 binding-signature 字节翻转，精确要求 `WireError::Authorization`，失败字节不得入 cache；有效字节继续成功。末尾既有第二实例仍冷、独立验证后才入 cache，最后新建实例依然空。

**测试明确先初始化 key 再启动并发检查；不覆盖冷 OnceLock 首次初始化竞争。** 四个 worker 和两种坏字节不是额外测试。固定 public key 与授权成功缓存的生命周期分开，独立 crate-level `Verifier` 以及 proof-generation key 生命周期不在此次修改范围。

| 预期项目 | Ubuntu | Windows |
|---|---:|---:|
| 保留的新增 archive 库测试 | 18 | 17 |
| 此次新增 wire 测试 | 1 | 1 |
| 累计新增库测试 | 19 | 18 |
| default 完整 lib | 140 | 133 |
| default 全部目标 passed / 结果数 | 154 / 18 | 147 / 18 |
| funded 完整 lib | 159 | 152 |
| funded active CLI | 7 | 7 |
| funded interfaces 全部 passed / 结果数 | 56 / 20 | 56 / 20 |

所有计数都待准确候选的原生日志验证。默认 `active_recovery_cli` 仍为 0，不能计 CLI 7；平台 cfg 排除不冒充 ignored 或通过。CLI 的两次真实 proof 构建仍在原第一用例，未删减。配套 JSON 保留全部 27 个跨平台新增函数全名、feature、平台、冻结验收点与四个既有 flow 的完整映射。

## 依赖、枚举与未完成验收

`Cargo.toml` 与 `Cargo.lock` 字节不变：Orchard 精确 `=0.15.5`，lock checksum `a3cb2b35534bba3c63fbf640dc6cd9dfd1ece2fae886cdab4ab1f1e380dd6ca1`；Halo2 proofs 0.3.5、gadgets 0.5.0、Pasta curves 0.5.2、RedDSA 0.5.2、Rust 1.98.1 均未更换。静态 `OnceLock` / 只读引用的具体 Send/Sync 类型要求仍需此锁定版本的原生编译确认，文档中的上游 API 说明不等于实际编译通过。

`scripts/run_funded_rust.py`、调度器测试、所有 workflow 与原预算逐文件相同。metadata 仍自动枚举一个 lib、5 个 bin、14 个 integration；funded library 为无名字过滤的完整 `--lib`，interfaces 执行 19 个目标加独立 doc。新增私有测试自然进入 library；没有目标遗漏或通过删调用、减少 fixture、减少三次 replay、放宽预算获取通过的改动。

实际已读 fmt 原件 20,672 B，SHA-256 `994c43ca2a98a46957c99dfe1dd755de2762fcd82a6acae006544894b5d64042`；raw 245 行 / 10:25:48.9453241Z 唯一 diff 要求展开 `fixed_key_tests.rs:32` 附近的固定版本 `assert_eq!`，257 行 / 10:25:48.9889686Z exit 1。**C5 不接受**，未声称新测试已实际运行或 Clippy/双平台全套通过。任何后续格式修正必须按新的 source/tree 另立预期与原生证据；本原文不后改。
