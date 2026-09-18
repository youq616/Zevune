# P2 active incremental package — C1 独立代码审核原件

## 结论与身份

结论：**PASS_CODE（仅本报告范围内的静态功能、状态和存储安全审核）；NATIVE_FMT_FAILED / TESTS_PENDING；C1 阶段验收 BLOCKED，不得据此合入。**

审核者是独立代理任务 `/root/p2_package_design_review`。本人没有编写、修改或格式化本候选的生产代码、测试或设计文档；此前承担的是同一阶段的非作者设计审核。本报告来自本人亲读原始代码、测试、调用方、Git 对象、GitHub 插件返回的提交信息和原生失败日志，不以作者摘要或另一审核者的结论代替。没有把设计 PASS、旧候选 PASS、CI 状态图标或作者自查算作当前提交审核通过。

| 身份 | 固定值 |
| --- | --- |
| Repository / PR | https://github.com/youq616/Zevune/pull/17 |
| 实际 base commit | `2cc87a2207d502ac5cfe00ea52e525c1516917e5` |
| base tree | `b5841120084a72c5948b0a2754f712e5f67ad602` |
| C1 head commit | `61c691270b91aece076177cb757e51e0e63fe310` |
| C1 tree | `56dad7fdaad64b2b29ddac6b9585b8695aa465d7` |
| C1 直接 parent | 上述 base commit |
| 已独立核对的 CI checkout | `bd710cf4c985012ca23e86c333567ce116de72bb`，parents 为上述 base、C1，tree 与 C1 完全相同 |
| 设计原文 SHA-256 | `b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41`，13,361 bytes |

GitHub 插件分别读取了 base 与 C1 的 git commit 对象和 PR #17；本地 Git 对象也独立核对了 parent/tree。正式审核开始时，本地工作树 clean 且 HEAD 为 C1。作者后来开始修复格式并发布 C2；本 C1 原件的所有最终字节、范围和判断只绑定不可变的 `git show C1:<path>`，没有掺入工作树上的 C2 字节。本报告不对 C2 自动授予任何通过结论。

## 实际读取范围

完整阶段差异为 12 paths，5 modified、7 added、0 deleted，增加 4,230 行、删除 37 行；12 个最终文件合计 262,548 bytes。base 有 886 个 Git tree entries，C1 有 893 个；其余 881 项按 path/mode/type/blob 完全相同。相同文件数量是范围核对，不能解释为已经逐个审核了全部 881 项。

完整阅读的阶段文件如下。已有文件先完整阅读基线内容，再完整阅读最终 base→C1 差异；新文件完整阅读最终内容。高层 package tests 曾在作者自查期间变动，正式 C1 后再次按 1–300、301–600、601–853 行完整读完最终 853 行，结论以该版本为准。

| C1 path | Bytes | SHA-256 |
| --- | ---: | --- |
| docs/ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md | 13361 | b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41 |
| integration/orchard/src/bin/zevune-pool-recovery.rs | 16512 | a7f251856937ae0096e4f777181fed91c7ab2daa5da181bed84957247603f31c |
| integration/orchard/src/pool/active.rs | 29857 | 621257f7690ec6d467a19616dde11553fcd6dec150e13d9bc7bc4f12c5016151 |
| integration/orchard/src/pool/active/package.rs | 27158 | 3bd76e74f276d895c13d7c50d7398ceb2afbb7c8b4d7fe5b24baf9565b41d361 |
| integration/orchard/src/pool/active/package/tests.rs | 22487 | b81fb39e0be2e4f021b68ff3bf40135007cc528b69f64cc2d6cd414c075190fa |
| integration/orchard/src/pool/active_flow_tests.rs | 46198 | 4030794c09a066ac7cce9970af81883810240cc11423f6c844bc5c5884eeab4d |
| integration/orchard/src/pool/recovery/active.rs | 10574 | aeba87d0648cf043bcb22554a71b30509f4fa19ac99863738ed729b870c280eb |
| integration/orchard/src/pool/recovery/active/incremental.rs | 7548 | 50d291f6613450faec4441d769758728423ae12aa7912d6f2d04cfbe010beedc |
| integration/orchard/src/pool/recovery/active/package.rs | 14687 | 87869f9261a8043f2e4ae33f7158bed328c1c63c2238f8c97d4f6d2faed40b9c |
| integration/orchard/src/pool/recovery/active/package/tests.rs | 34919 | 936c8092f1d798e4c9be87315475808a1051b957da608ca6fbab1439ac57e5e8 |
| integration/orchard/src/recovery_package_output.rs | 2720 | 7c2a82ac2238ccce46d4656ef884aee75e6ae9104943496336aa78c2bce52aab |
| integration/orchard/tests/active_incremental_package_cli.rs | 36527 | 914165fb58851df2da8435742848e0be6a865a8b5d67bed99768d267ff9143ce |

同一独立任务中还完整亲读了以下相关原始文件，并核对其 C1 blob 与已读内容一致：`AGENTS.md`、`docs/STAGE_REVIEW.zh-CN.md`、`integration/orchard/src/pool.rs`、`pool/active/incremental.rs`、`pool/recovery/segments/namespace.rs`、`pool/replay.rs`、`wire.rs`、`wire/cache.rs`、`recovery_incremental_output.rs`、`tests/active_incremental_cli.rs`、`pool/recovery/active/incremental/tests.rs`、`pool/testnet.rs`。省略前缀的路径位于 `integration/orchard/src/`，但以 `tests/` 开头的路径位于 `integration/orchard/`。各路径和完整 SHA/blob 在 scope JSON 中逐一列出。

明确部分阅读边界：`integration/orchard/src/pool/recovery.rs` 与 `pool/recovery/segments.rs` 各只读 1–230 行；未把这两个完整文件算入完整亲读范围。物理实现实际调用的严格 regular-file / hard-link / identity 检查来自已经完整读过的 `pool/active.rs`，不是从部分读到的另一个同名 helper 推断。

此前设计审核原件保持不变：`design-review.md` 14,950 bytes / SHA-256 `6c6df5d0599526f877be2b9b3eb91b1728f4dc5c7ebb4c1e002a3ff82b55b512`；`design-review-scope.json` 4,612 bytes / SHA-256 `ca79e53087baaa2526c4c65a3dffe25eb3385c971742e064ebb864ee52bb65ff`。该 PASS_DESIGN 只适用于固定设计字节。

## 认证与全量回放

从公有 API、私有 parser、物理 joined reader 到原始 Replay/State/AuthorizationVerifier 逐层追踪，未发现包内数据被提升为外部信任权威。两个 ZVARCP01 pins 都由调用者输入，parser 将包内捕获的两个 128-byte 编码与其逐字节核对；读取 payload、layout hash 或已有 Archive 对象不能替代这些独立 pins。包对象字段私有，计划构造器仅在父模块范围使用；未新增跳过验证的生产入口。

`ActiveIncrementalPackage::open` 只通过私有 `open_unverified` 建立有界物理对象，然后必须执行 `verify`。每次 `verify` 检查 base 身份和真实 physical ranges、包元数据/文件身份，先执行 base 的完整回放，再校验 base 与 joined 全字节布局，读取 joined genesis/header/profile 并创建全新的隔离 State 和 `AuthorizationVerifier`，通过原始 Replay 遍历全部 genesis→later 记录。Replay 每帧还经过原始物理分段约束，再检查完整 EOF、height、app hash、genesis 等固定结果；成功前重新检查 base 全字节、完整 package payload、捕获元数据、文件及父目录身份。

`wire.rs` 的授权路径仍进行规范解码、真实签名与 binding signature 检查以及 Orchard proof verification。固定 verification key 的共享不等于授权缓存复用：本调用创建 fresh verifier/cache，不借用运行 pool 的旧成功缓存。原始 State 仍对 domain、expiry、anchors、spent nullifiers、outputs、fees 和容量逐次检查；即便单次回放内部 exact-byte cache 命中，也不产生重复花费权限。Replay 错误会使隔离状态不可恢复使用，失败路径没有向现有 pool 发布 State、pending commit 或钱包 reservation 的入口。

pack 使用原有完整 prefix 比较和两个合法 archive 的 incremental plan。restore 在新目标目录创建前再验证输入，重建后用原始创建句柄构成的 ActiveArchive 做完整回放，再对 package 做一次完整验证，并检查目标实际字节和父目录。不存在仅验证追加交易而假定 base 状态可信的恢复捷径，也不存在从 package 导入 State snapshot 的路径。

## 二进制与范围严格性

已逐条核对：magic ZVAIPK01，268-byte 固定头，12-byte 大端 u32 range descriptors，最多 2,048 个 descriptors；元数据最多 24,844 bytes。payload 长度必须等于 later logical length 减去 base logical length，整包长度精确相符且检查 EOF。logical archive 仍受原来的 1 GiB、1,000,000 records、2,048 segments、每个完整 segment 1 MiB 上限约束；没有通过 package 引入更宽协议/磁盘限额。

实际 ranges 不只对 pins 的抽象数值自洽：checked_plan 核对 base journal 的实际 byte length、segment count 和真实 tail length。旧 segment 只能追加最后一个，offset 必须等于实际 tail；新 segment 从下一 index 连续开始且 offset 为 0；严格升序、不重复、不跳号、不允许空 range，checked arithmetic 处理长度和 index 的边界。恢复物理视图同时检查生成 segment 的最小有效长度、最大长度、aggregate payload 终点和完整 later length。

joined reader 通过保留的 base genesis/base segments 和 package 内有界 spans 顺序供给原始 replay，跨 piece 不把 range 末尾伪装成整文件 EOF。只对真正完整源文件做 EOF 检查，包按整体精确长度检查；读取失败后 reader 保持失败，不能通过下一次 read 恢复。提取的 `validate_physical_frame` 保留旧 active reader 的 canonical no-split / no-early-rotation 规则，并在 joined replay 的每条真实 frame 上应用。

layout hash 仍按原有 ZVARLY01 定义覆盖 genesis、segment count、每段 index/length 和全部原始字节。metadata check 覆盖捕获的完整头和表，不能通过改 range table 后仅复用同一 payload hash 绕过。该 hash 是外部 pin 约束的一部分，不被描述为证明授权或隐私。

## 文件句柄、目标创建和失败语义

物理 package 代码实际复用了 `pool/active.rs` 严格文件函数：Unix 拒绝非 regular、symlink 和 nlink != 1，并检查 retained inode 与名字；Windows 持有的文件/目录句柄按原有策略阻止相应重命名删除。读取 package 保留共享锁；创建 package 保留最初独占写句柄；restore 的 genesis 与 segment 均保留最初创建句柄，直到完成同步、命名空间/字节检查和目标 replay，不提前关闭后用路径重新打开来冒充同一目标。

NewTarget 在创建前保留父目录身份、验证 canonical containment 和目标不存在，并在关键节点重新核对。已有 file/directory、源目录内的目标、package 自身、缺失父目录以及源目录别名会拒绝；同一父目录中的无关 sibling 不会使合法目标无条件失败。目标只用 create_new 创建；Unix 新目录/文件权限按 0700/0600，文件 sync、目录及父目录 sync 依既有平台路径执行。

流式 helpers 检查显式 offset 和总长；short reads/writes 和 Interrupted 重试，不跳字节；read/write 返回越界数量、write 0、offset overflow、提前 EOF 会失败。64 KiB 分块不会提升最大包长度或一次性装载整个 payload。成功前重读全部相关字节；cfg(test) 的 late mutations 只用于测试，没有运行时生产开关。

失败不自动删除、覆盖、重试修复或解锁再重开输入。部分创建以及已完整写完但同步结果/最终核对失败的目标按设计保留；调用者能在释放句柄后明确验证完整失败目标，不能把错误返回改报成功。stdout failure 同样可能留下已完成目标；这属于明确接口语义，不是事务回滚承诺。没有真实断电或任意并发恶意磁盘变动的实验性保证。

## 成本、CLI 和旧路径兼容

从 CLI 路由、各 API 的真实调用顺序和 renderer 逐次计数，完整回放数为：

| 操作 | CLI 输入打开成本 | 方法内部完整回放 | 合计 |
| --- | ---: | ---: | ---: |
| pack-active-incremental | base.open 1 + later.open 1 | incremental_plan 2 + package.verify 2 | 6 |
| verify-active-incremental | base.open 1 | package.open 内 verify 2 | 3 |
| restore-active-incremental | base.open 1 + package.open 内 verify 2 | restore: 输入 verify 2 + target verify 1 + 输入再 verify 2 | 8 |

每次 package.verify 的两个回放分别是 base 全回放与 fresh joined 全回放。额外 layout/identity 字节扫描不冒充回放，也没有漏掉返回前的再验证。当前实现选择这个保守成本，未添加跳过 proof 的性能开关。

新命令采用明确选项白名单，重复、缺失、未知参数以及 pins 编码问题在对应输入访问前拒绝；both pins 的解析不依赖包内“自带 pin”。旧命令路径和旧 JSON renderer 继续存在。新 renderer 限定 operation/flag、输出有限长 ASCII JSON、完整 write_all 到真实 stdout；数组长度受 ranges 上限约束。没有把 package/recovered journal 标为钱包备份、私密快照、finality 或外部安全审计结果。

旧 active frame predicate 的抽取未改变既有分段语义；高层 incremental 仅提取受限的 pin/plan 复用入口，没有开放 worker 或授权缓存。完整 diff 未修改依赖、密码学实现、协议上限、workflow 或资源预算。

## 测试源码的实际覆盖与限制

这里只评价测试定义、输入和断言的可达性，**不授予执行通过信用**。三个新测试文件分别有 8、11、8 个 #[test] 定义；平台条件使 physical/high 在每个目标平台分别有 7/10 个，CLI Linux 有 8 个、Windows 有 7 个。CLI 全文件受 `local-funding-lab` feature gate 控制，默认无该 feature 的运行出现 0 tests 不能算覆盖。

物理测试把纯 transport fixture 明确留在物理层，独立组装 header/table/payload 和复制后全字节预期。覆盖空包/genesis、超过 64 KiB 的旧 tail、完整 tail 加新 segments、短 I/O/Interrupted/越界、strict offsets/ends/caps、metadata/payload/EOF changes、失败 reader 不恢复、部分写与 durable-but-failed acknowledgement、原创建句柄锁、父目录身份和两平台各自命名语义。没有把这些合成字节当作合法付款 State。

高层最终 853 行测试覆盖公有 open 必经 verify、独立编码包、later 目录删掉后 restore 并继续普通提交、pins/范围/长度/EOF 压力、合法但相互分叉 archives、rollback/network/wrong base、已有与嵌套目标、最终字节篡改及完整失败输出保留。repinned early rotation / split frames 先证明私有 parser 和完整 bytes hash 可过，再证明 joined replay 拒绝，避免所有坏例只在早期 pin mismatch 处失败。最终新增严格乱序控制使用有效的两个 indices 加对应 payload，确认不是借助越界 index 提前拒绝。

Late fault 测试明确对真实持有的原创建句柄注入变动，特别是 Windows 不能外部写入锁定文件时没有把外部写失败当作业务拒绝。verify 成功后再变更 base tail、package metadata、payload，下一次仍失败；pack 在最终 base/later/package 变动、restore 在目标 namespace/bytes 变动时不能报告成功。测试故障 hooks 受 cfg(test) 限制。

CLI 测试用真实 subprocess 和文件 stdout，检验精确 JSON 与独立二进制预期、无 later 目录恢复、后续提交、选项与 pins、lock、target、corruption、平台 alias 等。stdout 错误用只读真实文件并先验证其写入确实失败，也保留可写控制例；失败后的完整目标仍可明确打开验证，重复操作拒绝覆盖。新 CLI 例主要使用空 commits，本报告不把它们包装成新 CLI 真付款证明。

既有 `active_flow_tests.rs` 的本阶段 diff 增加 161 行，没有删除原断言或额外构造 WalletProver。两笔真实 Orchard 付款、默认 1 MiB 旋转和原有 full archive/incremental plan 检查保留。新 helper 的独立 wire 预期、pack/open/restore、全字节一致性进入原真实流程：第一笔后恢复出的 pool 实际承接第二笔付款，第二次增量恢复后继续高度 10002 的提交，并保留余额、费用、双花、reservation/recovery 检查。

针对新第二笔付款的 binding signature 篡改，测试保留原合法 base prefix，重算 frame SHA 和 later layout pin，再独立构造包，直接在 combined replay 中期望 Authorization 拒绝；没有先打开一个坏 later Archive 让测试在前置入口失败。坏 binding signature 本身在 proof verification 前拒绝，不能声称此坏例执行了坏 proof 验证；合法付款的真实 proof 回放由既有真实 verifier 路径承担，最终仍需原生执行证据。

## 已发现问题

### C1-FMT — 必需格式检查失败，阶段阻断

严重性：低层面的代码格式缺陷；按照项目验收规则是明确阻断条件。没有把“只涉及格式”解释为可忽略失败。

独立证据来自 [wallet-laboratory Ubuntu job 105656510131](https://github.com/youq616/Zevune/actions/runs/35362376487/job/105656510131)，run 35362376487 / attempt 1，head C1。GitHub 原始 job metadata 显示精确 source/lock 检查失败，后续 genuine wallet payments、strict static checks 和 no-drift 步骤均 skipped。本人完整读取保存的 525 行 Ubuntu 日志；某次工具输出中间截断的片段后来单独读取补齐。日志 checkout 为本报告身份表中的 synthetic commit，其 tree 与 C1 一致，已通过 GitHub git commit 对象独立核对。

在 Ubuntu 24.04.5，固定 Rust toolchain 1.98.1 安装后，`cargo fmt --all -- --check` 报 7 个文件、30 处 diff，退出 1。日志执行组虽然还显示 cargo metadata 和 git diff 命令文本，但 shell 使用 -e/pipefail，不能据此声称这些后续命令已经执行。日志未单独查询 rustfmt component 的版本号；1.98.1 是安装 toolchain / rustc 版本标记。

| C1 file | rustfmt 报告的 C1 行号 | hunks |
| --- | --- | ---: |
| pool/active/package/tests.rs | 170, 283, 294, 330, 518, 564, 571 | 7 |
| pool/active/package.rs | 3, 116, 578 | 3 |
| pool/active.rs | 214 | 1 |
| pool/active_flow_tests.rs | 289 | 1 |
| pool/recovery/active/package/tests.rs | 212, 244, 369, 378, 430, 460, 474, 506, 600, 776, 804 | 11 |
| pool/recovery/active/package.rs | 92, 154, 187, 371 | 4 |
| integration/orchard/tests/active_incremental_package_cli.rs | 34, 418, 439 | 3 |

表中省略的 `pool/` 前缀均位于 `integration/orchard/src/`。复现命令是在固定 C1 tree 的 `integration/orchard` 目录运行 `cargo fmt --all -- --check`，使用项目固定工具链。修复建议是逐项应用实际 formatter 输出，发布新 commit，重新核对完整 delta 与最终 tree，并在新 tree 跑完 required regression；不能编辑旧审核原件冒充 C1 已通过。

本次完整读过的是 Ubuntu job 原始日志。读取的同一 run jobs 元数据同时列出 Windows job 105656510465 failure 和后续步骤 skipped；未完整读取 Windows 原始日志，因此不额外宣称已经审核其具体失败栈或其他 workflow 的全部根因。

### 其他静态发现

在上述完整阶段范围和已追踪真实调用方中，本人的静态审阅未发现功能/授权/状态/存储安全阻断缺陷。本段是范围内审核判断，不承诺不存在未发现问题，也不预判尚未执行的编译、Clippy 或测试会通过。后续候选的 native 结果和追加发现另建审核原件。公开元数据、全回放开销、失败可能保留完整目标、平台边界和非钱包备份性质已经在固定设计及实现接口中明确，不另列为本候选缺陷。

## 验证信用与未执行边界

实际完成的本地验证：不可变 Git 身份/parent/tree/diff/path-mode-blob 核对、逐文件 bytes/SHA-256、全部阶段差异及所列调用方/测试源码阅读、`git diff --check base C1` exit 0、独立 GitHub 发布身份核对、一个真实失败 fmt job 的完整日志及其 run jobs 元数据读取。git diff --check 通过只说明 Git 空白错误检查通过，不能替代 cargo fmt。

本地没有 Rust/Go toolchain，未运行 cargo build/test/clippy/fmt、go test/vet/race/fuzz；没有把 Python/Git 静态检查当作 native compile 或执行成功。已见 C1 fmt 失败使所读 wallet job 的真实付款、密码学、状态恢复及静态检查步骤未执行。没有审计所有其他 workflows 的完整日志，也没有给未读日志或未执行测试授予信用。

未执行真实断电、磁盘控制器故障、网络文件系统语义、进程任意时刻 kill、真实 Windows 文件系统本地试验或独立外部密码学安全审计。平台 gated tests 和 cfg(test) 故障注入的静态存在，不证明以上实际环境全部覆盖。项目仍是 NO-FUNDS 开发范围，本结果不代表部署许可、真实资金安全或 finality。

因此，本审核关闭的是 **C1 静态代码审阅**；C1 的必需 native 检查已经发现失败，阶段验收保持 BLOCKED。修改后的 C2 必须取得自己的精确提交审核，并具备真实通过的相关 CI、必要密码学/恢复证据、所有阻断问题关闭以及明确未测边界，才可讨论阶段合入。

## 审核原始证据

这些文件由本独立任务写入 scratch，未修改 repo 工作文件。JSON carrier 保存连接器返回的原始 decoded content 字符串，不宣称是 HTTP 网络抓包；日志由该字符串 UTF-8 编码精确保存，保留 BOM 和换行。

| 文件 | Bytes | SHA-256 |
| --- | ---: | --- |
| c1-code-review-scope.json | 19869 | 3a6f765a9fc6691656c219c182816ec694f3d9bb1df8997be0bbfbd2c677147a |
| c1-code-review-remote.json | 23521 | 712d374add954c95f47685d4e07f9cce56848fe6f092f28b8d67d8e3c79645b3 |
| c1-code-review-fmt-carrier.json | 44403 | 541cda1d8b0f5e0842d44e0940dcd710405d364fd040800565b7ec590f326253 |
| c1-code-review-fmt-job-105656510131.log | 40556 | 247217a4771742d0e14f66222cc6e9657d1969e290c3052272a44c9e5a927080 |
| c1-code-review-fmt-run-jobs.json | 5750 | 40e965cc139854d00944a7ee2b1400eb5175b484fb6006f3ec41ffeed95c6e98 |

原件目录：`/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package/`。scope JSON 包含全部 12 个最终 path 的 git blob、大小、SHA、相关完整/部分阅读边界、27 个测试定义名称及 execution_credit=0、完整 tree 范围核对和 30 个 fmt locations。本 Markdown 与该 JSON 配套使用；新的候选结论另建文件，不覆盖此 C1 原件。
