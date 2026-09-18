# P2 持久增量包 C1：非 Rust 原生证据独立分项审核

审核任务：`/root/p2_package_native_audit/nonrust_logs`，日期：2026-09-18 UTC。
父审核任务：`/root/p2_package_native_audit`。本审核者未编写本阶段仓库源码、测试、workflow 或设计，
只创建本分项审核材料与 scratch 解析辅助脚本。本文固定到 C1，不对后续候选给出结论。

**结论：C1_REJECTED_NATIVE_FMT_FAILURE_NONRUST_LIMITED_COVERAGE_ONLY。**

C1 的有限 Go/Python 检查具有本候选的真实执行证据，但完整阶段不能接受。17 个 job 均在
同一组 7 文件、30 个 rustfmt hunks 上失败；没有运行任何 Rust test harness，没有运行
100000 块增长、32+1 真实付款资源 workload，也没有构建或上传 operator bundle。
应修正格式后，以新的准确 head/tree 重新运行全部相关 CI；本文和 C1 原件必须保留，不得
事后改写为后续候选的 PASS。有限 Go/Python 通过不能替代增量包的真实授权 replay、CLI
和恢复后继续付款验收，也不能替代独立代码审核。

## 准确候选、原件和审核方式

- PR：[Zevune #17](https://github.com/youq616/Zevune/pull/17)。
- base：`2cc87a2207d502ac5cfe00ea52e525c1516917e5`。
- C1 head：`61c691270b91aece076177cb757e51e0e63fe310`。
- C1 tree：`56dad7fdaad64b2b29ddac6b9585b8695aa465d7`。
- PR synthetic checkout：`bd710cf4c985012ca23e86c333567ce116de72bb`，parents 正好为
  `[base, C1]`，tree 与 C1 相同。C1 自身的唯一 parent 为 base。

完整读取 AGENTS、STAGE_REVIEW、native-expectation，以及 12 个 workflow YAML；完整读取
资源采集与校验脚本、资源 Go 测试、100000 块增长测试、bundle builder 和 verifier。
对 C1 与 base 的 Git 对象直接比较，确认 `.github/workflows`、`scripts`、
`integration/cometbft`、`internal/poolbridge`、`go.mod`、`go.sum` 无变化，因此原始测试入口、
原有超时、固定付款数、内存预算及平台条件没有被放宽。

独立逐文件重算 `c1-native` 全部 56 个原件的长度与 SHA-256，总计 **1,367,731 字节**；
与原件清单完全一致。清单 `c1-native-original-manifest.json` 为 9,519 字节，SHA-256
`62554c4488f619e38e34e7c964b4e339774636fba5cc7f1b6d9f8ed31537d3af`。
全部 21 份完整 decoded job logs 共 **1,056,143 字节**，逐字节读取、散列、完整扫描和解析，
保留 BOM/CRLF 原样。审核中通读了实际非 Rust 命令与输出、Go 全部具名结果、Python 全部
具名结果和平台差异、失败和跳过 step、两个资源 ZIP 的完整内容；没有用末尾摘要取代原件。
派生 JSON 保存全部 job/step 终态、原件身份、各结果对应的原始 log 行号及名称。

终态 `runs.json` 和各 `run-*.json` 中，嵌套 `pull_requests[0].head.sha` 已随当前 PR 更新为
C2 `f51c8db240933256870ff03c07bc68915b4ac4a1`。这是保留在原件中的当前 PR 投影，不能
用作 C1 run 的源码身份。本审核用顶层 `run.head_sha`、`head_commit.tree_id`、
`job.head_sha`、初始 PR 对象，以及全部 21 个实际 checkout 日志共同确认 C1，未改写
嵌套字段或把 C2 的执行授予 C1。

本审核只离线解析当前候选的真实 GitHub 证据，没有本地运行 Go/Rust workload，没有
重新采集 OS 资源，也没有导入旧阶段通过结果。GitHub API JSON 是 connector 返回数据
保存的原件，不声称其为底层 HTTP 线缆字节。

## 完整终态与未执行范围

10 个预期 PR workflows 全部有 attempt 1 终态，2 成功、8 失败。22 个 API jobs 中，
4 成功、17 失败、1 skipped；steps 合计 **152 success / 17 failure / 92 skipped**。
正常预期的 23-job 矩阵没有运行完成：growth 的 `needs: source` 因 source 格式失败而
留作一个零 step、未展开平台矩阵的 `growth` job（105657416224），没有 Ubuntu 或 Windows
的 growth 运行，也没有可收集的执行日志。其余 21 个已执行 jobs 的日志齐全，不能将
没有日志的零 step 占位项称为缺失实际执行日志，更不能把它视为增长通过。

| Workflow / run | 终态 | 实际范围 |
|---|---|---|
| [scaffold-tests / 35362376522](https://github.com/youq616/Zevune/actions/runs/35362376522) | success，2 jobs | 两平台 root Go test/vet；Linux root race 和两个 bounded fuzz |
| [consensus-laboratory / 35362376433](https://github.com/youq616/Zevune/actions/runs/35362376433) | success，2 jobs | 两平台 CometBFT 模块 test/vet、四进程共识实验及 launcher build；Linux adapter race |
| [orchard-bridge / 35362376379](https://github.com/youq616/Zevune/actions/runs/35362376379) | failure，2 jobs | 格式失败；Go→Rust proof、后续 Go regression/race/fuzz 未执行 |
| [orchard-consensus-integration / 35362376563](https://github.com/youq616/Zevune/actions/runs/35362376563) | failure，2 jobs | 格式失败；Orchard 四进程共识、Go regression/race/fuzz 未执行 |
| [orchard-cryptography-laboratory / 35362376375](https://github.com/youq616/Zevune/actions/runs/35362376375) | failure，2 jobs | 格式失败；默认 Rust test 和 strict Clippy 未执行 |
| [wallet-laboratory / 35362376487](https://github.com/youq616/Zevune/actions/runs/35362376487) | failure，2 jobs | 格式失败；默认 Rust test 和 strict Clippy 未执行 |
| [funded-wallet-consensus / 35362376578](https://github.com/youq616/Zevune/actions/runs/35362376578) | failure，4 jobs | Python 单测及 interfaces 前置 Go 编译通过；funded Rust、钱包实际互通、真实四节点付款未执行 |
| [active-ledger-growth / 35362376593](https://github.com/youq616/Zevune/actions/runs/35362376593) | failure | source 格式失败，后续 Go 编译未执行；growth 零 step 依赖跳过 |
| [payment-resource-baseline / 35362376595](https://github.com/youq616/Zevune/actions/runs/35362376595) | failure，2 jobs | Python validator/OS helper tests 完成，格式失败后 workload 未执行；仅上传 setup |
| [local-network-operator / 35362376586](https://github.com/youq616/Zevune/actions/runs/35362376586) | failure，2 jobs | 同 step 内 Python 单测先完成，随后格式失败；build、operator、race/fuzz、bundle 上传未执行 |

4 个成功 jobs 中 Windows 的 4 个跳过符合既有条件：scaffold 的 race、binary fuzz、journal
fuzz，以及 consensus 的 adapter race。其余 88 个 skipped steps 位于失败 jobs，包含
后续业务步骤和 post-cache 等；这些不能被解释为完整成功矩阵中仅允许的 9 个 Windows
条件跳过。无 cancelled job 或非终态结果混入接受统计。

17 份失败日志均有 exit code 1，并各自列出这 7 个路径的 30 个格式差异：
`src/pool/active.rs`、`src/pool/active/package.rs`、`src/pool/active/package/tests.rs`、
`src/pool/active_flow_tests.rs`、`src/pool/recovery/active/package.rs`、
`src/pool/recovery/active/package/tests.rs`、`tests/active_incremental_package_cli.rs`
（以上均位于 `integration/orchard`）。这是 C1 的阶段阻断项，不能以有限非 Rust 成功消除。

## 实际 Go 覆盖

所有具备 Go setup 的实际日志均报告 Go **1.27.1**，分别为 linux/amd64 或 windows/amd64；
scaffold 的 `stable` 本次实际也解析到该版本。

- scaffold Ubuntu job [105656510648](https://github.com/youq616/Zevune/actions/runs/35362376522/job/105656510648)
  与 Windows job [105656509836](https://github.com/youq616/Zevune/actions/runs/35362376522/job/105656509836)：
  `go test ./... -count=1`、`go vet ./...` 均完成，7 个有测试的 root 包通过、2 个命令包无测试。
  Ubuntu 另有 `go test -race ./... -count=1` 完成。无测试文件的包没有计入通过用例数。
- Ubuntu 两个 fuzz 命令均为原来的 `-fuzztime=3s -parallel=2`，实际进入 fuzz engine 并 PASS：
  `FuzzDecodeBinary` 8,456 executions，新增 interesting 1、总 corpus 4；
  `FuzzJournalBlockDecode` 109,831 executions，新增 interesting 8、总 corpus 11。
  前者包含终止等待后 4 秒日志行，没有修改原定 3 秒 fuzz 参数。
- consensus Ubuntu job [105656509838](https://github.com/youq616/Zevune/actions/runs/35362376433/job/105656509838)
  与 Windows job [105656509396](https://github.com/youq616/Zevune/actions/runs/35362376433/job/105656509396)：
  `go mod download/verify`、`go mod tidy -diff`、gofmt、
  `go test -mod=readonly ./... -count=1 -timeout=8m -v`、vet、launcher build 和最终 git diff 均完成。
  每平台 5 个有测试的包、63 个顶层具名结果通过；包括嵌套测试及 fuzz seeds 时为 106 个
  named PASS。63 中 4 个为 Fuzz 函数的普通 seed 执行，不能称作 4 次 fuzz-engine 运行。
  Ubuntu 的 `-race ./app -count=1 -timeout=3m` 另行通过。两平台无具名 Go FAIL/SKIP。
- 上述 consensus 实际日志包含 `TestFourProcessConsensusAndRecovery` 和
  `TestFullRestartAdvancesBeyondDurableHeight`，四进程共同高度、签名门槛、3/4 继续、2/4
  观察窗口停滞、恢复 quorum、重启和缺失签名状态拒绝的既有测试通过。这里是基础共识实验，
  不能代替本候选未执行的 Orchard 付款共识或新的增量包恢复功能。
- funded interfaces 的 Ubuntu job 105656510698 和 Windows job 105656510724 在格式失败前，
  分别完成 root 和 integration/cometbft 两个模块的 `go test -mod=readonly ./... -run '^$'`。
  每平台 12 行有测试包的结果明确标为 `[no tests to run]`，另有 3 行 `[no test files]`。
  这些只给予编译信用，不增加本轮实际测试通过数。

## 实际 Python 覆盖

完整解析每一个具名单测输出，计数与各 suite 的 `Ran ...`、`OK`、平台 skipped 原文一致：

| 所属 jobs | Ubuntu：发现 / 通过 / 跳过 | Windows：发现 / 通过 / 跳过 |
|---|---:|---:|
| funded-library scheduler tests | 13 / 13 / 0 | 13 / 13 / 0 |
| funded interfaces 全部 scripts/tests | 135 / 132 / 3 | 135 / 134 / 1 |
| local-network-operator 全部 scripts/tests | 135 / 132 / 3 | 135 / 134 / 1 |
| payment resources 专项 validator/OS helper tests | 53 / 50 / 3 | 53 / 52 / 1 |

合计 8 次 suites：672 次发现、660 次通过、12 次平台跳过。这是重复执行数量；跨 suite
去重后为 135 个已有 Python test 身份，不能宣称新增 660 个测试。Ubuntu 每次相应 suite
跳过 3 个 Windows 文件共享测试；Windows 跳过 1 个 Linux proc descriptor 测试，平台
另一侧实际通过对应测试。Python 测试中的 OS self/child helper 采样通过，只证明采样
辅助实现该测试范围，不能冒充本轮 32+1 真实付款的内存峰值。

operator jobs 的 Python 单测位于随后 fmt 失败的同一个 step；完整日志确认 `OK` 先于
rustfmt 差异和 exit 1。因此可保留单测通过事实，但该 step/job 终态仍是 failure。

## 两个平台资源 ZIP：仅初始身份

两份 ZIP 均校验 GitHub artifact 元数据的长度及 SHA-256，并完整读取所有 ZIP entries。
每份恰好一个 `payment-resource-setup.json`，解出字节与 root 保存的 setup 原件完全一致。
无 `payment-resources.json`，无 event、progress、memory sample 或付款 workload result。

| 平台 | artifact id | ZIP bytes | ZIP SHA-256 |
|---|---:|---:|---|
| Ubuntu | 10555232590 | 459 | `ef6f1aee85055c272351ce837916405b26a8ed944944bc73c13df660f11d5d0e` |
| Windows | 10555276497 | 463 | `2f9967510ac063eb7bccdf44bafb32dee31228e65476d5213c2c1b1d63e6304a` |

两份元数据的 run id 均为 35362376595、head 均为准确 C1，artifact 名称携带准确 synthetic
checkout，`expired` 为 false。两份 setup 均为 `schema_version=1`、
`kind=workflow_setup_observation`、`observed_execution_status=not_started`，head、checkout
commit/tree 与本审核身份一致。Ubuntu setup 456 字节；Windows setup 466 字节，保留 CRLF。
setup 的初始状态和 always-upload 成功不能被提升为资源执行成功。

固定资源门槛保持 32+1 真实付款、2 actions/payment、9 checkpoints、181 operations、
362 progress records、worker 两代及 scenario 一代、每进程 1 GiB OS resident/lifetime peak，
Go workload 1200 秒、supervisor 1230 秒。C1 没有实际结果，因此没有这几个角色的本轮
资源峰值、进度完整性或预算通过结论。增长固定 100000 块、正常 1 MiB 段和 20 分钟
内部/25 分钟 Go/40 分钟 workflow 门槛同样未执行。operator workflow 的 artifact 清单为空，两个 jobs 均未上传，
没有 binary payload、manifest 或本轮 bundle integrity 可供验证。

## 交付与边界

分项派生明细：`c1-native-nonrust-review.json`，386,128 字节，SHA-256
`ebaf5a51bde46fd98309fca57a29a3f77f86a5435c6c2428a2d3e4d946520865`。
其中包括全部 56 个原件散列、22 个 job 的完整 step 终态、21 份完整日志散列与解析结果、
全部实际 Go/Python 名称和行号、两个 setup-only ZIP 的验证数据。

独立校验脚本为 scratch `audit_c1_nonrust.py`。它没有修改 repository 或 CI，没有运行
下载的程序，也不把旧阶段或 C2/C3 结果纳入 C1。没有发现已执行 Go/Python 检查的额外
失败；这项有限观察不能消除 17 个格式阻断和大量未执行路径。本文不授予整个阶段、
密码学、生产存储、最终性、真钱或外部专业安全审计的批准。
