# C6 原生 Clippy 阻断：独立审核补充原件

审核者 `/root/p2_archive_review`，2026-09-17 UTC。本补充保留此前 C6 审核原件，不修改候选文件。C6 source `88146d54f2eaac39958ceaaea9e13f71832d536e`，tree `cbddd8e982eb9013d10010354e477b264e33841b`，stage base `6913d4ab2fda6956db37e0ceb49790a4518c2762`。

**后验结论：C6 存在必需原生门槛阻断，阶段不接受。** 原 `PASS_CODE_REVIEW` 是当时的静态结论，不能覆盖本次 Clippy 失败；我承认静态检查遗漏了新测试在同一 crate 中重复加载既有 fixture 文件的问题。

实际重新读取并核对的 Ubuntu integrated 原日志为 `c6/job-105167396538.log`，job 105167396538，68156 B，SHA-256 `a0368cb426a63c9ed4763cd88429f5744b0d0404b30c50e419f0e86903b40e40`。日志 checkout 行明确 merge C6 source into 本阶段 base。该日志有 18 组完整成功结果，合计 154 passed、0 failed、0 ignored；library 为 140 passed，66.85s；新 `concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold` 明确为 ok。这些已执行成功必须如实保留，但不能使随后失败的整个 job 获得通过，也不能代表其他平台或全部矩阵已通过。

2026-09-17 10:33:51 UTC 的 Clippy 明确指出 `src/../tests/support/fixtures.rs` 被作为模块加载多次，`clippy::duplicate_mod` 受 `-D warnings` 提升为错误；随后 lib test 编译失败，命令于 10:33:52 UTC exit 101。真实路径是既有 `src/pool_tests.rs` 的 `#[path = "../tests/support/fixtures.rs"]` 与新增 `src/wire/fixed_key_tests.rs` 的 `#[path = "../../tests/support/fixtures.rs"]` 指向同一文件。我此前核对了真实证明 helper、路径及 crate alias，却未检查同一编译单元的重复 mod 约束，属于审核漏检。测试通过、运行耗时下降或源码语义观察不能免除该必需门槛。

**拟议测试范围修法可行，但尚非 C7 批准。** 已只读核对现有模块结构与 Rust 可见性合同：pool 的 tests 本身在 cfg(test) 下；将其中 fixtures 可见性改为 pub(crate)，由 pool 在 cfg(test) 下仅 `pub(crate) use tests::fixtures` 重导出，再由 wire 私有测试 use 引用现有模块，可以保留唯一文件加载点。无需公开整个 tests，也不暴露生产 helper；pub(crate) 限制在当前 crate，cfg(test) 排除非测试构建。既有 integration tests 是独立测试 crate，它们各自的 fixture 加载与本次同 crate 重复不同。实际 C7 还须核对 guard、导入解析、fmt/Clippy、原 helper 字节、真实 proof 及所有断言和预算保持，不能添加 allow 来掩盖失败。[Rust Reference：可见性与重导出](https://doc.rust-lang.org/reference/visibility-and-privacy.html)

原件现仍为：`code-review-c6.md` 17003 B，SHA-256 `055968cb720dc117c6e4f451d2910973d3d92b6af596aee88cda6a8184a05aa2`；`code-review-c6-observation.json` 11322 B，SHA-256 `c19ef9435e847e06917e1289fbeb23e2b63df34d07b4cfac3b4f0a93d6a37cf6`。本补充未覆盖它们，没有出具 C7 source/tree 或通过结论，也未运行本地编译、Clippy、测试或 CI。准确 C7 需新的独立全阶段审核和自己的完整原生矩阵，不能继承 C6 的部分成功。
