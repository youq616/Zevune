# P2 active incremental package — C3 独立代码复核原件

**结论：PASS_CODE；NATIVE_PENDING。** 本结论只覆盖准确 C3 候选的静态功能、认证与存储安全审核，不是阶段验收或合入确认。审核者为独立非作者代理 `/root/p2_package_design_review`；本人没有编写或修改此候选的生产代码、测试、设计、格式修复或 Clippy 修复。

## 准确候选

| 身份 | 值 |
| --- | --- |
| PR | https://github.com/youq616/Zevune/pull/17 |
| stage base / tree | `2cc87a2207d502ac5cfe00ea52e525c1516917e5` / `b5841120084a72c5948b0a2754f712e5f67ad602` |
| C3 head / tree | `cb0804e7c921a456cbbafab313b3a4a4501b8f5e` / `21de343c12bc27cb1022ffd7ebd451abe0e61f29` |
| direct parent C2 / tree | `f51c8db240933256870ff03c07bc68915b4ac4a1` / `7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400` |
| synthetic commit | `3dfa8d77921693b9e99af5b94af198498b9422e9`，parents=[base,C3]，tree 与 C3 相同 |

本人通过 GitHub 插件分别读取 C3、synthetic 的 git commit 对象与 PR #17，核对以上身份及 PR open/unmerged；本地观察到 clean C3 HEAD，并从不可变 Git 对象重新计算最终内容。stage base→C3 仍为 12 paths（5 modified、7 added），共 262,465 bytes；其余 881 个 base entries 的 path/mode/type/blob 相同。所有 12 个最终路径的大小、SHA-256 和 blob 在 scope JSON 中逐一列出，未将相同 entry 数量称为全仓库逐行阅读。

## 完整 delta 与实际阅读

C2→C3 恰好一个文件删除一行、0 行增加、减少 22 bytes：

```diff
         assert_eq!(logical(&restored_again, &genesis_again), expected);
-        drop(reader);
         drop(joined);
         drop(package);
         let reopened = RetainedPackage::open(&package_path).unwrap();
```

文件为 `integration/orchard/src/pool/active/package/tests.rs`，C3 最终 22,654 bytes，SHA-256 `7bdcac72ffcb39dd8d7ca8393d1e77dd127fd381391d055a7e87d8a52f62d828`，Git blob `ef24f03957081cdd2eb6ec73a2a0a85695331e1e`。本人检查 C2 原件只有一个精确的 8-space `drop(reader);\n`，在内存仅删除这行后完整字节等于 C3；其余 **892 个 C2 entries** 完全相同，包含所有生产代码、其他测试、设计、依赖、workflow 和预算。Git diff --check C2 C3 exit 0。

此次完整亲读了带 50 行上下文的全部 delta，另亲读 C3 tests.rs 210–360 行，包含受影响测试完整函数；核对 C3 physical package.rs 360–398、694–707 行的 JoinedJournal/JoinedReader 定义。此前同一任务的完整 C1 stage/caller 阅读、完整 C1→C2 差异与 C2 物理测试 631 行全读，有不可变原件记录。此次借助准确 blob 比较继承的是已读字节与推理范围，重新审阅新 delta 后才作 C3 判断，没有自动继承旧 PASS。C1 中两个只读 1–230 行的来源仍只算部分覆盖。

## 修复判断

C2 原生 Clippy 在无 Drop 的 JoinedReader 上报告 drop_non_drop。该 reader 只有对 JoinedJournal 的借用和普通标量，不持有独占文件句柄或析构器；C3 测试在前面已经读至 EOF 并断言后续 read 返回 0，此后没有 reader 使用。删除这行使借用在最后使用后自然结束，不移除任何读取、EOF、全字节/布局、锁或重开断言。

测试仍先确认持有 restored 原创建句柄时 ActiveJournal::open 返回 Locked，再实际 drop restored 与 restored_genesis，随后成功重开并校验全部 logical bytes；最后 drop joined（拥有 segment Vec 的视图）及拥有文件/目录句柄的 package，然后独立打开 package 再核对全字节。没有通过提前释放真正句柄、增加 allow lint、修改 feature gate 或减少断言来掩盖错误。

因此 C2-CLIPPY 的具体源码触发点已在 C3 最小修复；原生 Clippy 是否实际通过仍须 C3 运行证据。全部生产字节与已审 C2 相同，外部双 pins、fresh base+joined 全回放、真实 Orchard 授权、真实 tail/range 约束、原创建句柄、最终全字节复查、失败目标保留及 CLI 6/3/8 回放成本保持已审实现。未发现新的静态阻断或需要额外改动的非阻断问题。

## 未执行边界与审核信用

本地没有 Rust/Go toolchain，未执行 native compile/test/fmt/Clippy 或 Go commands；本 C3 原件没有读取 C3 原生作业日志，不把 C2 的默认 171 项成功或 C2 的失败结论改写成 C3 结果。尤其 C2 默认命令中的新 CLI 是 0 tests，不能替代 feature-gated CLI、两笔真实付款 active flow 或 Windows 的 C3 验收。

本报告为 **准确 C3 的 PASS_CODE + NATIVE_PENDING**。阶段仍需准确 C3 tree 的相关 CI、必要真实密码学/恢复证据和独立结果共同闭合，不能仅凭此文标记完成。真实断电、磁盘控制器、任意时刻 kill、网络文件系统和外部安全审计仍未执行；NO-FUNDS 与公开 metadata 边界保持原设计范围。

## 不可变证据链

| 原件 | Bytes | SHA-256 |
| --- | ---: | --- |
| c1-code-review.md | 22123 | daa1339e96987cffe248778fe321c81886fe7fb4b9d75a23a6a7bc6955e63d9f |
| c1-code-review-scope.json | 19869 | 3a6f765a9fc6691656c219c182816ec694f3d9bb1df8997be0bbfbd2c677147a |
| c2-code-review.md | 10141 | 6d6555493d5268cb34911fb74ac98e1bda5b7f5263adbb8c9399956ae0f948a3 |
| c2-code-review-scope.json | 13671 | d65c390068ce1e8e9e7bb995b7c7d1c8e405b08ad7c537041adbd3baeb9e207e |
| c3-code-review-scope.json | 8902 | a8c2ed477498752f7b2d53a6f651ff8dce27f7d1855592728a032c02b6ff779c |
| c3-code-review-delta.patch | 4401 | 051dc574f0ecda0882797577baf0181273b5f0a47210d8bab1b8aa463adb9ba8 |
| c3-code-review-remote.json | 23687 | a7cb3d18d244ef883a4f32b9c001fec29dc9ad4c3adc267fe6499d75c8099750 |

原件目录 `/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package/`。scope 保存最终 12 paths、entry 对比、准确单行 delta 和阅读边界；remote carrier 保留 GitHub 连接器 decoded content，不是 HTTP 抓包。先前 C1/C2 及设计原件保持不变，本次未修改 repo 文件。

