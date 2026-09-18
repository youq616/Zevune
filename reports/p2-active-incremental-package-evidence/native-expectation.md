# P2 持久增量包：独立原生 CI 审核前置期望

审核任务：`/root/p2_package_native_audit`。日期：2026-09-18 UTC。
审核者未编写本阶段 repository 源码、tests、workflow 或设计，只写本审核材料。
仓库：`youq616/Zevune`。基线提交 `2cc87a2207d502ac5cfe00ea52e525c1516917e5`，
基线 tree `b5841120084a72c5948b0a2754f712e5f67ad602`。
本次读取时，HEAD 和 tree 与上述值一致；唯一工作区新增文件为设计文档。

**状态：EXPECTATION_ONLY / NATIVE_PENDING。** 本材料不是测试执行、代码或设计批准。
当前尚无本轮冻结 candidate commit、PR、synthetic checkout 或真实 run/job 结果。
不得将旧阶段的通过或本材料中的预计数字计为本阶段新覆盖。候选冻结后必须重新核对实际
base/head/tree、变更路径、源码测试清单和未变化预算，逐一审查本轮真实结果。

## 审核输入与读取范围

完整读取了 AGENTS、STAGE_REVIEW、当前设计、全部 12 个 workflow YAML、funded target
分组脚本及其单测、Cargo manifest 和固定工具链文件。完整读取了上阶段 reviewer-only
`native_audit_rust_helpers.py` 与更早 `native_log_summary.py`；只借鉴日志解析方法，不继承
旧 candidate 的执行信用，也不把派生汇总作为原始证据。

只读定位并读取本轮相关测试入口和 feature gate、现有 CLI 独立物理预期辅助函数、资源采集
固定常量/顺序/结果校验/成功与清理 gate，以及完整 100000 块增长主测试和完整 32+1 付款
资源主测试。尚未声明完整阅读这些大文件的所有辅助函数或后续候选源码。

- `AGENTS.md`：3240 字节；SHA-256 `bc5a7f3ba26bb99da6264427effd12b7df03a6f48c4c1a21281ade0b4c0b5f96`。
- `docs/STAGE_REVIEW.zh-CN.md`：2139 字节；SHA-256 `738d92594cb0851975bd05b5746edba9cd10512ea049cbdb02e1be8e2020bb46`。
- `docs/ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md`：13361 字节；SHA-256 `b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41`。
- `scripts/run_funded_rust.py`：5739 字节；SHA-256 `d7020b399362a56cbad7578255e9973a9c5be5592dcc2410624f46a0f639c97f`。
- `scripts/tests/test_funded_rust.py`：7405 字节；SHA-256 `2123f0561a7a5eff67dc2b9aa17f1741106158eb309872d15deb9eda811d51b9`。
- `integration/orchard/Cargo.toml`：841 字节；SHA-256 `45d275f12a798c684bcf6b2e86034aff964414fbd32156b8601c4031d7487c7c`。
- `integration/orchard/rust-toolchain.toml`：86 字节；SHA-256 `887f9be066a15585a2c583578e84b0fcb541126d81546276bad3d2ff00d61167`。

## PR workflow 与 job 清单

本轮设计要求修改 `integration/orchard/**`，这会满足下列 6 个带路径过滤的 PR workflow，
以及 4 个没有 PR 路径过滤的 workflow。默认所有矩阵均保留 Ubuntu 与 Windows。

| Workflow name | jobs | runner / 原 timeout-minutes | 主要原生入口 |
|---|---:|---|---|
| `scaffold-tests` | 2 | tests / Ubuntu、Windows，15 | root Go test、vet；Linux race 与两 decoder fuzz |
| `consensus-laboratory` | 2 | integration / Ubuntu、Windows，18 | CometBFT 全模块 test、vet、四独立进程；Linux adapter race |
| `orchard-bridge` | 2 | boundary / Ubuntu、Windows，20 | 默认完整 Rust test + strict Clippy；实际 Go→Rust proof；Linux bridge race/fuzz |
| `orchard-consensus-integration` | 2 | integrated / Ubuntu、Windows，25 | 默认完整 Rust test + strict Clippy；四进程 pool consensus/restart；Linux race/fuzz |
| `orchard-cryptography-laboratory` | 2 | tests / Ubuntu、Windows，25 | 默认完整 Rust test + strict Clippy |
| `wallet-laboratory` | 2 | wallet / Ubuntu、Windows，25 | 默认完整 Rust test + strict Clippy |
| `funded-wallet-consensus` | 4 | funded-library 与 funded / 各 Ubuntu、Windows，30 | funded library 与 interfaces 两不相交完整 target cohorts；真实四节点付款/钱包恢复 |
| `active-ledger-growth` | 3 | source / Ubuntu，15；growth / Ubuntu、Windows，40 | source fmt/Go compile gate；100000 实际 worker commits、正常段轮转、完整重启 |
| `payment-resource-baseline` | 2 | resources / Ubuntu、Windows，40 | 固定 32+1 真实付款、完整恢复、OS resident/lifetime peak 预算 |
| `local-network-operator` | 2 | operator / Ubuntu、Windows，30 | isolated Git object bundle；实际 operator 与真实付款；Linux race/fuzz |
| **合计** | **23** | **10 个 PR workflows** | **全部准确候选、完整终态** |

`development-source` 是本开发分支的 push-only / workflow_dispatch workflow，不属于上述
23 个 PR jobs。它在本轮源码 push 时应产出精确 source archive，可作为额外来源证据，
不能用该 push run 替代某个 PR run。`crate-notice-inventory` 只匹配它自身 3 个 notices
相关路径；本轮不修改它们则不触发，不能声称它已经为候选执行。实际差异若改变这些前提，
清单需明确补充；不允许静默缩小预期。

## Rust 与 CLI 结果要求

- 固定 Rust 为 1.98.1；Cargo.lock 和 source 都不得被 CI 重写。`cargo fmt --all -- --check`、
  `cargo metadata --locked`、默认与 funded 的 `cargo clippy --locked --release --all-targets -- -D warnings`
  要在对应 job/step 实际成功；funded Clippy 另外保留 `--features local-funding-lab`。
- 四个默认 Rust workflows、各两个平台，合计 8 个默认 Rust test jobs。它们不启用
  `local-funding-lab`。`active_flow_tests` 受 test+funded gate，现有 `active_incremental_cli`
  顶部受 funded gate；默认 cohort 中可能出现其 0-test harness，不能算为 CLI 或真实
  funded 恢复通过。新 package 纯物理/空历史 tests 的实际 feature gate 要从候选核对。
- funded-library 的两个 jobs 各运行一个完整 `--lib` invocation。funded interfaces 的两个
  jobs 通过实际 Cargo metadata 列出并运行所有 bin/test targets，再运行 `--doc`。
  检查 metadata target union 完整且与 library 不相交，且每个执行命令没有 test 名称过滤、
  `--skip`、`--ignored`、`--no-run`。两种 cohort 都需实际 `FUNDED_COHORT_COMPLETE` 标记。
- 应有 12 个包含原生 Rust tests 的 jobs；确切 harness 数、test 数及新增 unique 名称仅在
  当前源码与真实完整日志可核对后记录。重复平台和多个 workflow 的同名通过是重复执行，
  不得累加成独立用例数。Unix/Windows 条件编译差异需要与当前源码对应。
- 必须看到新 pack / verify / restore 的真正子进程测试和精确 JSON / 参数 / pin / path /
  stdout failure 断言通过；恢复后的第二笔真实付款必须使用 incremental restored directory。
  保留原先两笔真实付款/正常 1 MiB rollover/余额费用/双花拒绝/错误后不变断言，不能把
  合成文件物理检查、改坏 checksum 后早拒绝、0-test harness 或 proof-free fixture 当作真实
  combined replay 的授权拒绝证据。源码审核须确认 forged later pin + rehashed bad binding
  signature 用例实际到达 Authorization，native 日志负责确认该精确用例确实执行成功。
- 库/CLI 针对新格式、独立 pins、严格范围、全部 payload、read/write 边界、故障保留、
  held handles/locks 与平台特定路径规则的覆盖清单，要从最终候选编译 gates 和执行名称
  映射，不能提前捏造测试数量或完成率。设计列出的 pack 4、verify 2、restore 5 次 replay
  （CLI 6/3/8）是成功路径语义，不是可以从 cargo 总耗时推导的性能实测。

## Go、预算和平台条件

原工作流保留 root `go test ./... -count=1` 和 `go vet ./...`，以及 integration/cometbft
的 `-mod=readonly` test/vet。Go 固定集成版本 1.27.1，scaffold 使用 stable；两种真实版本
要从 logs 记录。source gate 的 `go test ... -run '^$'` 仅编译，不能计为测试通过。

Linux 保留以下 race / fuzz 实际执行；Windows 原条件跳过须逐 step 标注，不称跨平台
race/fuzz 已完成：

- scaffold：root race；FuzzDecodeBinary、FuzzJournalBlockDecode 各 3 秒。
- consensus：`./app` race。
- orchard bridge：`./internal/orchardbridge` race；FuzzDecodeEnvelope、FuzzReadFrame 各 10 秒。
- integrated：实际 poolapp 两个 Real 测试 race；poolbridge race；FuzzPoolFrame 10 秒。
- network operator：labnet/launcher race、错误 post-state 拒绝 race；
  FuzzCanonicalPublicConfiguration、FuzzNumericLoopbackEndpoint、FuzzTestGenesisFrame 各 3 秒。

按 YAML 静态计数，Windows 固有条件跳过 step 合计 9 个（3+1+2+2+1），应逐一与实际终态
匹配，不能将任何其它意外 skipped/cancelled job 混入允许清单。所有固定 timeout、feature、
Go tags、test 选择、并发资源设置和 source checks 保持，失败不可通过增大预算获得接受。

增长测试的成功证据必须同时包含 named PASS、最终 ACTIVE_GROWTH_RESULT 和实际阶段
结果，固定 100000 块中 99998 空块、2 笔真实付款，继续到 100001；正常段容量 1048576，
当前段/总字节/高度政策不变，边界付款为 9999 与 10001。该测试为本地 worker commits，
不代表 100000 四节点共识高度；约 15 MB 不能支持 >64 MiB 或全容量结论。源码测试内
20 分钟 context，Go invocation 25 分钟，workflow 40 分钟不变。

资源测试固定 32+1 笔真实付款、2 actions/payment，最后 height33、commitments68、
nullifiers66、fees33000；9 checkpoint phases，按固定有序 operations 完成恢复后付款33。
两类测量对象为 worker（2 generations）与 scenario，每进程 OS resident / lifetime peak
预算 1073741824 字节；Go workload 1200 秒、supervisor 1230 秒、handshake15 秒、worker
start/request60 秒、scenario response90 秒不变。完整 JSON 必须 status passed、go_exit_code0、
无 unfinished operation、commit_outcome_uncertain false、所有固定 result checks true、
progress 和 event 序列完整、结果与最后事件一致、进程清理确认，并从原始每个 sample
核对预算。不得只读末尾 passed 字符串或作者聚合峰值。

## 原始证据与 artifact 收集要求

1. 精确 GitHub PR 身份：真实 base/head、候选 tree、PR synthetic checkout commit 的
   parents/tree；每次实际 checkout 要与候选代码树相等，不能只看分支名。候选更新后
   旧 commit 结果保留但不转移为新 commit 的通过。
2. 用完整 `actions/runs?head_sha=<C>&event=pull_request&per_page=100` 列表并校验总数；
   对每个实际 run 保留完整 jobs（filter=all/per_page=100，必要时完整分页）及 step metadata。
   match workflow、event、head_sha、run_attempt、status、conclusion，终态和数量都完整。
3. 每一个 job 的原始完整 log，含 checkout/setup、实际命令、完整结果、失败、post cleanup，
   不以尾部片段、actions badge 或作者 JSON 摘要代替。connector 返回的 decoded UTF-8
   content 逐字节保存并记录 SHA-256、长度、BOM/CRLF；不经 universal-newline 改写。
   API wrapper 的结构化 JSON 是 connector 规范化数据，不能称网络响应原始 bytes。
4. 每个平台的 payment resource artifact：artifact API 元数据、下载 archive 本身（哈希）、
   解出 `payment-resource-setup.json` 和 `payment-resources.json` 的完整字节。setup 的
   source_head / checkout_commit / checkout_tree 与运行元数据和原生日志交叉绑定；初始
   not_started 只表示 setup 观察，不与最终 result 混用。失败若只生成 setup，必须明确
   未完成资源 workload，不凭上传成功判断通过。完整资源 JSON 由审核者核对每条数据。
5. 每个平台的 local-network bundle 上传需实际 step 成功。为可追溯构建，应保存 artifact
   元数据并核对 BUNDLE-MANIFEST.json 的 source_commit / source_tree / 编译版本 / 清单
   哈希和 NO-FUNDS 限制。若未下载检查整个可执行 bundle，必须明确只验证上传及 manifest，
   不声称独立逐字节验证全部二进制或可复现构建。
6. 开发分支 push 的 zevune-tracked-source artifact 是额外 source review 资料：保存 artifact
   元数据、COMMIT、SOURCE-TREE、TREE、SHA256SUMS 和 archive digest。若采用它，应校验
   候选 commit 和完整 tree/blob 身份；它没有提供 PR workload 执行信用。
7. 原始 rejected candidate logs / 原文审核报告与后续候选严格区分保存。审核者原文不能
   在原位置事后改写成另一候选 PASS；后续补充结论保存为新对象。最终文档-only followup
   如运行源码 byte equality 成立，继承对应运行覆盖，另核实际触发的新 runs，不捏造一次
   新 funded/growth/resource 测量。

Rust 日志解析采用 FIFO target announcements 与 result 配对，因为 Cargo stderr 可先打印
下个 target，再交付前个 stdout result。每个 harness 校验 named pass 数与 `running N` /
`test result` 一致、失败/忽略/过滤数、重复名、未闭合 target。`--nocapture` 的度量输出可能
位于 `test ...` 与独立 `ok` 之间，不能只正则收集同行 `... ok` 导致漏计。派生解析可以帮助
导航，但最终审核需要完整原始日志、API step 终态与准确候选测试含义互相支持。

## 尚未验证的边界

本地无 Rust/Go 编译环境，未本地编译或执行本轮 native tests。本文只登记将来应核对的
真实 CI；尚无 frozen candidate，所以代码审核、设计 PASS、原生 PASS 均 pending。
即使后续上述证据通过，也不代表外部专业安全审计、真实磁盘满/突然断电、Windows 可移植
目录掉电持久化、任意敌对 OS/FS 原子快照、全 1 GiB/1000000 records/2048 segments 压力
测试、生产性能/最终性/真钱能力。旧资源 tests 不直接测量新 package CLI 全进程资源峰值。

## 已完整读取的 workflow 字节身份

后续验收比较当前候选与这些基线文件，任何修改须明确说明，不自动接受预算变化。

| YAML | bytes | SHA-256 |
|---|---:|---|
| `active-ledger.yml` | 3853 | `d6a23f40525f6dca01d3b03fd48649c180e63c65f145d67d5a12bfe7615c90c3` |
| `ci.yml` | 1207 | `429eb85ef77e55fd1a3bc664329fa92d417f33f4b2abd76141108c4f30c3219d` |
| `consensus-lab.yml` | 1444 | `354b9e9e7e2c1a3a1a63f3ccd79d495d10d9e8cb40124f6db7f2e9d899670908` |
| `crate-notices.yml` | 1016 | `0570422d6e6157a279d888a87ce34e531bcaebe2a895512b354fceb372e7ca55` |
| `development-source.yml` | 1290 | `7662eb5f641b44d1a17397a3c356ea47d39cc85c4fe882a90403e7df1013139c` |
| `funded-wallet.yml` | 5263 | `bb6d2ea2490ad878805532baf2c608bc49dd423eb0c0a5f014168f509ab22296` |
| `network-operator.yml` | 3903 | `25ffb6fe7489d14e5e3a58e0710bb67f38bb15fbfb5492874d63f72665f94696` |
| `orchard-bridge.yml` | 3198 | `bf190dd56d44b0aa1f464a0784022429fb8aa2cb0a263333e30eadfecf702398` |
| `orchard-consensus.yml` | 3290 | `642161027b9f5e0a6da8f83e3829f28a5d728314103fa909774656005563d9ca` |
| `orchard-lab.yml` | 1540 | `8d6554b2b4491c343d90f38e2f565196c78c75e69edd25eacaeb5f49ee37e0a2` |
| `payment-resources.yml` | 5225 | `d83634ff4aebac9befeec9c9dbaa554b75d8e2b3ba8368d39c3cb2fcc9a7b2eb` |
| `wallet-lab.yml` | 1483 | `32afa268bf17dc59279f100b4b7abcab3eaca803093b34dcce6967df2d8eeafb` |
