Zevune P2：C6 原生 Clippy 阻断及静态报告适用范围补记

结论：**REQUEST_CHANGES；C6 未接受。** 必需原生检查发现同一 fixture 文件在 library test 中被作为两个模块加载，Clippy 在 `-D warnings` 下退出 101。此前 C6 静态原文没有识别这个阻断，不能用其中的 PASS_STATIC 或已通过的个别测试替代完整原生门槛。本补记保留历史，既不修改原报告，也不批准后续候选。

审核任务 `/root/p2_archive_adversarial_review`，2026-09-17 UTC。本人未编写或修改候选源码、测试、格式、设计或工作流。本次只读核对精确 git 对象、原生日志与原报告，新增此补记。

| 身份 | 精确值 |
|---|---|
| 阶段 base | `6913d4ab2fda6956db37e0ceb49790a4518c2762` |
| C6 source | `88146d54f2eaac39958ceaaea9e13f71832d536e` |
| C6 tree | `cbddd8e982eb9013d10010354e477b264e33841b` |
| 第一父提交 C5 | `99ef9e8217182c9a6f4f1e9349613c1917ddec50` |
| PR | [youq616/Zevune #13](https://github.com/youq616/Zevune/pull/13) |
| 原生 Ubuntu integrated job | `105167396538` |
| 日志实际 synthetic checkout | `4bfe426af700303719bbc58344408e070af90467` |
| 日志说明 | Merge 上述 C6 source into 上述 stage base |
| 原日志 | `c6/job-105167396538.log` |
| 原日志 bytes / SHA-256 | `68156` / `a0368cb426a63c9ed4763cd88429f5744b0d0404b30c50e419f0e86903b40e40` |
| 原静态报告 | `adversarial-review-c6.md` |
| 原报告 bytes / SHA-256 | `15160` / `1db32733360b82162e50279c7dad06c05cd262897c7143503a893484bcc201c7` |

**AR-C6-03，P2，阶段验收阻断：重复模块加载。** C6 的 `integration/orchard/src/pool_tests.rs:7` 通过 `#[path = "../tests/support/fixtures.rs"]` 声明 fixture 模块；新增 `integration/orchard/src/wire/fixed_key_tests.rs:9` 又通过 `#[path = "../../tests/support/fixtures.rs"]` 声明同一实际文件。两项均进入同一个 library test 编译单元。原生 Clippy 明确诊断 `file is loaded as a module multiple times`，并建议保留一处 mod、其余改为 use。10:33:51 UTC 日志说明 `clippy::duplicate-mod` 由 `-D warnings` 提升为错误，10:33:52 报 lib test 编译失败、exit 101。此项是实际必需 lint gate 失败；日志没有显示密码学错误被接受，也不能将其推断为已证实的密码学漏洞。

在失败前，10:32:56 UTC 日志确有 `concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold ... ok`，随后库测试计数为 140 passed、0 failed、0 ignored、0 filtered out，66.85 秒。这些是准确 C6 的部分运行观察。该 DEFAULT 运行中的 active_recovery_cli 目标为 0 tests，不能据此声称 funded CLI 的七个测试、stdout 故障或全部双平台矩阵通过。Clippy 失败后的候选总体仍不满足验收；旧 C4/C5 成功或取消同样不能补足。

修复要求：在 library test 中保留现有 fixture 模块的单一定义，以受 cfg(test) 限定且足够的 crate 可见性供另一测试模块导入。保留 fixture 实现和整份真实授权断言，不增加 lint allow，不把测试辅助函数暴露为生产 API；冻结新候选后重新独立审核并运行其完整必需矩阵。这里描述修复边界，不认证后续实现或原生结果。

**对原报告完成状态的更正。** 原 C6 Markdown 在本次原生诊断到达前写出，表示静态源码判断；JSON 固定身份步骤尚未完成时，共享工作区已因后续修复切换候选，末次 HEAD 断言失败。因此没有创建 `adversarial-review-c6.json`，也没有完成 C6 报告成对交付。原文“仅新建本审核及 JSON”“审核起止工作区干净”及“配套 JSON 保存”不能据此解释为已经产出 JSON 或完成 C6 收尾身份核验；可证实的是开头核对 C6 身份并读取其准确 git 对象。原文称“独立 Python 再次重算”亦过强：该轮最终脚本在身份保护处中断，未再次执行该向量计算，向量依据来自此前实际已执行的独立核算。后续候选须重新执行并单独记录，不能补造 C6 检查。原 Markdown 原字节保持，以上更正在本补记中明确保留。

既有 AR-C1-01 段交换和 AR-C3-02 stdout 修复的源码观察不因该 lint 反例自动变成运行失败，但也不构成当前候选接受。本人未运行本地 Rust/Go、Windows、fmt 或 Clippy；本结论中的 native 事实仅来自上述具备长度、摘要和准确 checkout 的日志。C6 明确保留为未接受历史，新候选必须有自己的精确 source/tree、独立审查原件与原生证据。
