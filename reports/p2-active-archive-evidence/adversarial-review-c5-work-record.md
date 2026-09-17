Zevune C5 独立复审工作记录：未形成最终批准

状态：**REVIEW INTERRUPTED / C5 未接受**。本记录保留已经进行的只读检查和新原生格式失败，不是 C5 正式 PASS，也不批准任何后续候选。

审核任务 `/root/p2_archive_adversarial_review`，2026-09-17 UTC。准确阶段 base `6913d4ab2fda6956db37e0ceb49790a4518c2762`，C5 source `99ef9e8217182c9a6f4f1e9349613c1917ddec50`，tree `598f55a8d850095500329989b2ea1fa5855d5db9`，parent C4 `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`。

已经逐行读取全部 C4..C5 五文件差异、完整新增真实固定 key 隔离测试、fixture、VerifiedCache、相关 State/Replay/PoolStore 及 WalletProver 路径。私有 OnceLock 只缓存固定 CIRCUIT 的 VerifyingKey；每个 new 仍独立构建空 VerifiedCache。verify 顺序保持，proof 参数从已拥有 key 的借用改为静态只读借用。新增测试用一份真实非零付款证明，观察 A、提前存在的 B、四个并发新实例及最后新实例的实际缓存隔离，并对可规范解码的 proof/binding 签名变更明确要求 Authorization。此处是截至暂停时的静态观察，不是编译或运行成功。

父任务通知 C5 原生 source job `105166096614` 失败后，本人读取本地完整日志并复算摘要：`c5/job-105166096614.log`，20672 字节，SHA-256 `994c43ca2a98a46957c99dfe1dd755de2762fcd82a6acae006544894b5d64042`。日志实际 checkout 为 `44d9b13d1a1eed74158899717304aa42c1b5e30d`，说明为 C5 合入上述 base。2026-09-17 10:25:48 UTC 唯一格式 diff 位于 `integration/orchard/src/wire/fixed_key_tests.rs:32`，要求将 `assert_eq!(first.key.circuit_version(), OrchardCircuitVersion::FixedPostNu6_2);` 展开为四行，步骤退出 1。

本轮尚未出具 C5 正式全阶段结论，且已知必需格式 gate 失败，因此暂停最终 C5 批准。父任务将仅应用该原生格式诊断另冻 C6；须拿到 C6 准确 source/tree 后再次核对差异和完整阶段，后续结论不能自动继承 C5 的原生结果。

本人未修改候选、测试、设计、工作流或任何既有审核原件，本地未运行 Rust/Cargo/Go。本工作记录是新文件，C4 静态审核及 C5 设计审核原件继续保持原样；C5 设计 PASS 不等于 C5 实现接受。
