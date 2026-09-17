# C2 格式跟进的静态测试预期核对

任务：`/root/p2_archive_native_audit/source_expectations`。未编写候选。

- base：`6913d4ab2fda6956db37e0ceb49790a4518c2762`
- parent/C1：`c5f60ac440ac39032f8f8efefc2fbfbf6e299a90`
- C2 source：`7477d9e0656ed751f525a4b6fe9f6649b995ede6`
- C2 tree：`8e6544a6de9a8337926f70f8a89aa36e59ab7e39`
- PR：[#13](https://github.com/youq616/Zevune/pull/13)

本记录仅完成**格式修正的准确源码比较**，不是 C2 原生测试或阶段验收。C1 两份原文保持不变。读取均来自 `git show` 的准确提交，没有读取工作树、执行编译/测试或轮询CI。

完整 C1→C2 diff 已逐项阅读，共7文件，与 `c1/rustfmt-applied.json` 登记的30个原生fmt修正hunk所属文件一致。变更为换行/缩进、可选末尾逗号，以及两处单表达式match arm花括号展开；未改变调用、断言、常量或条件。另逐文件核对quoted string literals相同；这项辅助检查不是Rust解析器或编译级语义证明。

测试名与cfg属性清单一致，所有准确C2行号和文件哈希已重算。调度器、Cargo、funded workflow、父级模块挂载文件和冻结设计逐字节未变。因此预期仍是新增库 Ubuntu18／Windows17，funded CLI各7项；目标预期仍为1lib＋5bin＋14integration，interfaces19目标另doc。全部只是源码预期，未计任何实际PASS。

父任务告知独立对抗审核发现冻结验收点4缺少“两份已存在物理段互换”的明确测试，正在C3补充原pin与重算pin均Corrupt且字节不变的断言。本任务没有把格式修正视为该遗漏的修复，也没有验收C2；须收到准确C3后核对新增逻辑。

C1详细覆盖说明仍见 `../c1/source-test-expectations-review.md`。C2 JSON为`source-test-expectations.json`，36344字节，SHA-256 `e879bccc57a00815b6819244a1118f6b563f8f15eaaf9bf696f04055db3d48ca`。两代记录都不替代完整非作者代码审核与原生日志验收。
