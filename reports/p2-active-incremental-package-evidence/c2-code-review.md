# P2 active incremental package — C2 独立代码复核原件

**结论：PASS_CODE（本报告范围内的静态功能/安全判断）；FMT_PASS、DEFAULT_TESTS_PASS、CLIPPY_FAILED；C2 阶段验收 BLOCKED。**

审核者为独立非作者代理 `/root/p2_package_design_review`。本人没有修改候选代码、测试、设计或格式；本次亲读 C1→C2 完整差异、原始 formatter 输出、Clippy 失败上下文、原始 CI 日志并独立核对 GitHub 提交对象。已发布 C3 的本地工作字节不属于本报告。本报告不是原生全阶段验收，也不会把 C1 的 PASS 自动转给 C2。

## 固定身份与范围

| 项目 | 值 |
| --- | --- |
| PR | https://github.com/youq616/Zevune/pull/17 |
| stage base | `2cc87a2207d502ac5cfe00ea52e525c1516917e5` |
| base tree | `b5841120084a72c5948b0a2754f712e5f67ad602` |
| C2 head | `f51c8db240933256870ff03c07bc68915b4ac4a1` |
| C2 tree | `7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400` |
| direct parent / C1 | `61c691270b91aece076177cb757e51e0e63fe310` |
| C1 tree | `56dad7fdaad64b2b29ddac6b9585b8695aa465d7` |
| CI synthetic checkout | `aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f` |
| synthetic parents / tree | [stage base, C2]；tree 与 C2 相同 |

C2 与 synthetic 的 GitHub git commit 对象由本人通过插件分别读取，并与本地不可变 Git 对象核对。所有文件身份均由 `git show C2:<path>` 重新计算，不使用正在变化的工作树或作者 manifest 充当文件本体。

stage base→C2 仍为同一 12 paths，5 modified、7 added、0 deleted；最终文件合计 262,487 bytes。base 886 entries、C2 893 entries，其中 881 个条目 path/mode/type/blob 完全相同。C1→C2 仅 7 paths 有变化，+74/-75 行，其余 886 个 C1 tree entries 逐项相同。完整 12 个最终文件的 SHA-256、bytes、Git blob、行数和阅读范围在配套 scope JSON 中列出。

## 重新核对格式修复

本人完整亲读 `git diff --unified=7 C1 C2`，并独立从已保存的 C1 Ubuntu fmt 失败原始日志解析全部 30 个 old/new hunks。将这些片段各恰好一次应用于不可变 C1 文件的内存副本后，所得 7 个完整文件与 C2 **逐字节相同**。这既不依赖作者 repairs 清单的结论，也没有在 repo 内执行改写。作者的 `c1-rustfmt-repairs.json` 只作为额外比对对象，其前后 hashes 与独立结果一致。

| C1→C2 文件 | 原 fmt hunks | C2 bytes | C2 SHA-256 |
| --- | ---: | ---: | --- |
| integration/orchard/src/pool/active.rs | 1 | 29831 | a01d97908ca9b02008d098f047450da126cf9796dcf0ccc201f96409a9d4540a |
| integration/orchard/src/pool/active/package.rs | 3 | 27208 | b1bf8a85f6dbe78fa63968f844a00b722d92e268344255deb9e78e1a01a691a0 |
| integration/orchard/src/pool/active/package/tests.rs | 7 | 22676 | da17e4fd21608870c05f88d528e01c6a2ad79e27287ff69af40c5d92b4319910 |
| integration/orchard/src/pool/active_flow_tests.rs | 1 | 46190 | ec841665b8b4ffeee0c6cf059658ca02b4b7525b7012776e2b270c54b075fd22 |
| integration/orchard/src/pool/recovery/active/package.rs | 4 | 14622 | 4bee4fbaeb96e1ceb394c28031c9fe6215f40f434c79170a8d84dfa9736a02ce |
| integration/orchard/src/pool/recovery/active/package/tests.rs | 11 | 34856 | 76295a59daaffedb52d936c61db43e569c941e3e3c8b000db0e78095d791e5fd |
| integration/orchard/tests/active_incremental_package_cli.rs | 3 | 36389 | dce6b087fe2a9381db7d3a10c918f64ee36fde4014d0f2cbbc47d5bdd23dcb87 |

变化是 formatter 规定的换行、缩进、尾逗号和单表达式 closure 的 block 排版。closure 新增大括号后仍原样返回同一个 read_at 结果；checked arithmetic、比较条件、方法调用顺序、pin bytes 和所有测试输入/断言不变。不能笼统称其只有空白字节变化，但它没有改变这里的执行语义。没有新增 allow lint、删除测试、改变 feature gate、改变真实 verifier、提升上限、修改依赖、workflow 或预算。

先前 C1 完整亲读范围与原始判断来自同一独立任务的 `c1-code-review.md` 和 scope：12 个阶段文件；12 个相关完整原始来源；两个明确只有 1–230 行的部分来源。此次在重新验证逐字节相同的来源和完整 delta 后继承的是阅读事实与相关推理，不是旧候选结论。高层测试的 C1 最终 853 行已经全读，C2 的完整排版差异也全读，最终是 849 行。另针对 Clippy 重新完整读了 C2 物理测试全部 631 行，并读了 C2 physical package.rs 的 625–784 行，包括 JoinedReader 完整定义与 read 实现。

确认 C2 仍要求不可变外部双 pins、base 与 joined 各自 fresh 全回放、全字节布局与 metadata 在成功前后核对；严格 ranges 仍绑定真实 base tail。恢复仍保留原创建文件句柄，保持失败目标、不覆盖既有对象。新 CLI 的实际回放数仍是 pack-active-incremental 6、verify-active-incremental 3、restore-active-incremental 8。完整 delta 没有触及这些边界，也没有弱化既有真实付款集成路径。

## 独立原生证据与阻断发现 C2-CLIPPY

本人通过 GitHub 插件独立重新取回 [Ubuntu job 105658335135](https://github.com/youq616/Zevune/actions/runs/35362925520/job/105658335135) 的完整 decoded log，67,053 bytes / SHA-256 `b8b147786cfb42b849192b6a7dc2596a1147db766b55962331d12538a406bddb`，与作者归档逐字节相同；分块读完全部 823 行，工具曾截断的中段另行读取补齐。准确身份为 orchard-cryptography-laboratory **PR run 35362925520** 的 tests (ubuntu-latest)，head C2、checkout 为身份表中同 tree 的 synthetic。又独立读取该 run 的 jobs 元数据确认步骤结果。

在固定 Rust toolchain 1.98.1 / Ubuntu 24.04.5：

- committed formatting / dependency lock / 初始 tracked source 检查步骤成功，C1-FMT 在 C2 此作业中已实际关闭。
- `cargo test --locked --release -- --nocapture --test-threads=1` 完成；库 171 passed、0 failed，其中新的 physical package 7 项与 high package 10 项逐项通过，原始 default crypto/worker/integration tests 的非空组也完成。
- 新 `active_incremental_package_cli` 测试 binary 在此无 feature 的命令中是 **0 tests**。该结果不能算新 CLI 测试通过，也不能算本阶段受 local-funding-lab 约束的两笔真实付款 active flow 验收完成。
- `cargo clippy --locked --release --all-targets -- -D warnings` 在 `src/pool/active/package/tests.rs:354:9` 的 `drop(reader)` 处失败：`clippy::drop_non_drop`，exit 101。随后最终 no tracked source/dependency drift 步骤 skipped，不能替其写 PASS。

**C2-CLIPPY 严重性为测试静态规范缺陷，验收性质为阻断。** JoinedReader 只有借用的 JoinedJournal 引用和普通标量，没有拥有文件锁、没有 Drop impl。该测试已在前面读至 EOF，再额外断言下一次 read 为 0；drop(reader) 所在位置之后没有使用 reader。当前调用仅为结束无析构借用而写，Clippy 在 strict -D warnings 下拒绝。本人区分 reader 的借用、joined 所有的 segment Vec，以及 package/restored 拥有的文件/目录句柄，不建议添加 allow 或删除锁/字节断言。

最小修复建议是删除此无意义调用，依 Rust 的非词法借用结束 reader 的最后使用；保留实际 owning 对象的 drop、目标重新打开以及全字节断言。该行在 C1 已存在，并非 C2 formatter 引入的业务退化；C1 所读作业在 fmt 即停止，未执行到该 lint。本 C2 原件准确保留已确认的失败，后续 C3 必须单独审阅和重跑。

本次读取的其他 run jobs 元数据仅用于定位目标：push run 35362921040 的两个 jobs 不是本完整日志对应的 jobs。carrier 如实保留这次查询，但不将其日志/测试算入本人完整审计信用。正确 PR run 的 metadata 另存 `c2-code-review-exact-run-jobs.json`。没有把 Windows 的 in-progress 或 metadata 成功当作已完整审核 Windows 原生行为。

## 限制和结论

在 C1 完整阅读基础上，经本次全部 delta 与最终 12-path 身份重新核对，本人没有发现格式修复改变功能/授权/存储语义，静态功能/安全结论为 **PASS_CODE**。这不掩盖已经确认的 C2-CLIPPY：**C2 不能合入，阶段仍 BLOCKED**。默认作业中的局部测试成功也不等于相关 feature、两个平台、全部 required workflows 和必要真实付款/恢复证据已验收。

本地仍无 Rust/Go toolchain，没有运行 cargo/go native commands。上列成功/失败是本人读过原始日志的远端执行证据；Git 和 formatter-output 内存重建是本地静态核对。没有完整审计其他 CI 作业；未执行真实断电、磁盘控制器故障、任意时刻 kill、网络文件系统或外部安全审计。NO-FUNDS、公开 metadata、保守全回放成本和失败目标保留边界保持 C1 设计所述范围。

## 原件与配套证据

| 文件 | Bytes | SHA-256 |
| --- | ---: | --- |
| c1-code-review.md | 22123 | daa1339e96987cffe248778fe321c81886fe7fb4b9d75a23a6a7bc6955e63d9f |
| c1-code-review-scope.json | 19869 | 3a6f765a9fc6691656c219c182816ec694f3d9bb1df8997be0bbfbd2c677147a |
| c2-code-review-scope.json | 13671 | d65c390068ce1e8e9e7bb995b7c7d1c8e405b08ad7c537041adbd3baeb9e207e |
| c2-code-review-delta.patch | 27143 | dbf700903764c82dc672a92be0aaffbc58858bfc46c3cbf4f7a5d93418956292 |
| c2-code-review-format-check.json | 11831 | 78bda947c50e9ad2415c320139df2004e8adc6427197d9832e91d8ed1b5c5b59 |
| c2-code-review-remote.json | 78351 | 00811cf4c255bdcb0795ff56e676931d7c9b70b44722a68d2dd95f162cd5fafc |
| c2-code-review-exact-run-jobs.json | 5406 | 8ed02160d24fdba0736c88166d401e088f4d416847ec953cec7d6fc607a6af86 |
| c2-code-review-job-105658335135.log | 67053 | b8b147786cfb42b849192b6a7dc2596a1147db766b55962331d12538a406bddb |

以上原件位于 `/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package/`，只写入 reviewer scratch；未修改 repo 文件。GitHub carrier 保留连接器的原始 decoded content 字符串，不称为网络抓包。C1 原件保持不变，C2 原件同样不得改写成后续候选 PASS。
