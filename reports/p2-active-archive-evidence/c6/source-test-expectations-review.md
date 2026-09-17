# C6 准确源码测试预期独立审核

**C5→C6 为单处格式修改；静态用例预期保持不变。C6 尚待准确候选的原生证据，不宣称格式、编译或测试通过。** C5 原始记录继续保留 NOT_ACCEPTED_NATIVE_FORMAT_FAILED，未修改历史原文。

source `88146d54f2eaac39958ceaaea9e13f71832d536e`，tree `cbddd8e982eb9013d10010354e477b264e33841b`，parent `99ef9e8217182c9a6f4f1e9349613c1917ddec50`，base `6913d4ab2fda6956db37e0ceb49790a4518c2762`，PR #13。独立审核者 `/root/p2_archive_native_audit/source_expectations` 未参与源码编写，使用 `git show` 和准确 commit diff，未读取工作树、运行测试、触发或轮询 CI。

准确差异只有 `integration/orchard/src/wire/fixed_key_tests.rs`，+4 / −1：固定电路版本的单行 `assert_eq!` 展开为原生 rustfmt 要求的多行形式。旧 blob `8db6997`、新 blob `af0f6b2` 的非空白字符序列完全相同，测试函数名、所有属性、唯一真实 fixture 调用均一致；其他全部已审源码、依赖锁、workflow 与原预算逐 blob 比较一致。这只能确认改动对应已知格式 hunk，不能替代 C6 自身原生 rustfmt 结果。

新增测试全名仍为：

`wire::fixed_key_tests::concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold`

`src/lib.rs:12` 挂载 wire，`wire.rs:20` 仅 `#[cfg(test)]` 挂载私有测试模块，`fixed_key_tests.rs:12/13` 声明唯一测试。没有 feature、平台 cfg、ignore 或提前返回；default 和 local-funding-lab 的 Ubuntu/Windows 都应实际执行。支持 fixture 仍为原有真实 `create_proof` 与签名路径，一次 fixture 构建；四个线程不是四个测试。

固定 key getter 仍为私有 `OnceLock<VerifyingKey>`，只构建固定 `CIRCUIT = FixedPostNu6_2`。每个 verifier 仍拥有新建的空 `VerifiedCache`；只有不可变公共 key 共享，授权成功字节、账本、交易与秘密不共享。canonical decode、实例 cache、全部 spend 签名、binding 签名、真实 proof、成功记入的执行顺序与 C5 一致。测试保持正确版本 / 指针同一、cache 隔离、真实首次验证、可解码 proof 和 binding-signature 翻转都返回 Authorization 且不缓存、后续独立实例仍冷的断言。

**测试在固定 key 已初始化后检查四线程并发使用，不覆盖冷 OnceLock 首次初始化竞争。** 具体 Send/Sync 与所有 Rust 类型要求仍待准确锁版本的原生编译。Orchard `=0.15.5` 及 checksum、Rust 1.98.1、Halo2 等依赖均原样保留，未从上游在线文档推断本候选编译通过。

| 静态预期 | Ubuntu | Windows |
|---|---:|---:|
| 原 archive 新增库用例 | 18 | 17 |
| 固定公共 key 新库用例 | 1 | 1 |
| 累计新增库用例 | 19 | 18 |
| default 完整 lib | 140 | 133 |
| default 全目标 passed / 结果数 | 154 / 18 | 147 / 18 |
| funded 完整 lib | 159 | 152 |
| funded active CLI | 7 | 7 |
| funded interfaces passed / 结果数 | 56 / 20 | 56 / 20 |

原有四个 funded active_flow 及真实付款跨物理段、10001、原 pin/repin 交换两个已有物理段后 Corrupt、坏签名重算 checksum/pin 后 Authorization、完整复制后续付路径均未删改。复制仍执行源、目标、末次源三次完整 replay，每次新 verifier 与空 cache；原 archive 18/17 与 CLI 7 原文也未改变。CLI 的两个真实 payment-proof 构建和第七项 stdout 四 mode、File 探针、exit 1、可写对照与后验 verify 保留；新的 wire fixture 在库中另有一次真实 proof，不能把它混成 CLI 新用例。

metadata 自动枚举仍为一个 lib、5 个 bin、14 个 integration；funded interfaces 为 19 个目标加独立 doc，library 为不带名字过滤的完整 `--lib`。新增私有测试不增加 Cargo target。默认 active CLI 的 0 测试不能当作 7 通过；平台排除、并发 worker、嵌套进程探针与三次 replay 不加到唯一测试数。

配套 JSON 保留全部 27 个跨平台新增函数全名、四个既有 flow、精确平台 / feature / 验收点、C6 blob hash，以及 C5 原生格式失败作为明确标注的历史。后续只能用准确 C6 source/tree/synthetic 关联的完整原件验证这些预期，不能借用旧候选通过。C6 原生 synthetic 身份当前尚未提供，本静态记录不猜测它。
