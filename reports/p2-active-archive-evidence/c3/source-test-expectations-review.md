# C3 两段交换回归的静态测试预期核对

任务：`/root/p2_archive_native_audit/source_expectations`，未编写候选。

- base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`
- parent/C2：`7477d9e0656ed751f525a4b6fe9f6649b995ede6`
- C3 source：`7045af4ae254f0a5a5e4810f17004c91e649e474`
- C3 tree：`4017bee976c18767ed568d7ec8a33f6d668b8c22`
- PR：[#13](https://github.com/youq616/Zevune/pull/13)

**准确C3的新增断言已完成只读核对，此范围未发现静态阻断；没有宣称编译、测试、CI或阶段验收PASS。** 候选内容均来自准确 `git show` 和 C2→C3 diff，没有读取工作树或执行/触发测试。C1、C2四份原文哈希保持不变。

C3仅改变两文件：`active_flow_tests.rs` 增加44行，`recovery/active.rs` 改变一行。自动比较确认前者去掉这44行后与C2逐字节相同；后者完整文件差异只有明确的整除判断替换。没有其他目标、模块、cfg、ignore或测试函数名变化。

新增段互换位于既有 funded library 测试 `pool::active_flow_tests::real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002` 内，C3第596—639行，无额外分支/feature/跳过/早退。它在两笔真实付款及10001高度正常提交后，从已关闭writer的真实持久化目录复制byte map，将已存在的 `00000000.journal` 和 `00000001.journal` 内容互换，保留genesis和原规范名称。

- 原pin打开交换目录明确要求 `PoolError::Corrupt`，随后比较原source与交换fixture的完整文件名/字节映射均不变。
- 重算全部layout pin，断言新旧pin不同；用生产 `ActiveJournal::open_readonly` 与 `layout_hash` 证明新pin的摘要确实匹配交换后的物理字节。两个检查句柄明确drop后继续。
- 独立解码交换后第一段首个完整record，断言它是高度6964的真实第一笔付款，且base hash不等于genesis初始AppHash。随后使用重算pin打开仍明确要求 `PoolError::Corrupt`，并再次断言两份目录完整byte map不变。
- 该新pin分支覆盖的是重放链顺序错误：准确 `Replay::next_block` 在 `pool/replay.rs` 第250—252行先比较record base hash与genesis摘要并返回Corrupt。它不是授权错误用例，也不靠旧layout mismatch或文件锁失败获得信用。真实坏签名重算pin后Authorization拒绝仍由另一个既有增强用例覆盖。
- 原有效目录继续原本的10001归档/恢复、重复付款拒绝、10002提交及余额/历史/容量检查，均保留。

生产单行将 `(header - MIN_HEADER) % 32 != 0` 改为 `!(header - MIN_HEADER).is_multiple_of(32)`，对u64及固定非零除数32等价。前置范围条件短路保证执行减法时header不小于MIN_HEADER；未改变容量或错误类别。是否通过准确Rust工具链的编译及Clippy仍由原生CI验证。

测试预期保持：新增库 Ubuntu18／Windows17，funded CLI各7项；1lib、5bin、14integration targets，interfaces19目标另doc。新增44行是已有growth测试内部回归，不增加测试计数。须从**准确C3**两平台funded library日志取得该完整测试的实际 `ok` 和 cohort completion，旧提交结果不能用于证明新增断言执行。

全部准确测试名、C3行号、平台、feature、冻结验收映射、源码哈希及差异证据已写 `source-test-expectations.json`，40495字节，SHA-256 `e87424a21f9b6dbd2f73cb3a68d315dc92410dbe44317abf0012e0e5e0b039a1`。本记录不替代独立代码审核、完整原生日志验收或真实断电/外部安全审计。
