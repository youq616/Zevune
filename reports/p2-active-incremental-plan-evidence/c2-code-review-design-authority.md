# P2 活动归档追加计划 C2：独立代码与测试审核

**结论：PASS_CODE，准确绑定 C2；无开放的实质代码阻断。**

`stage_accepted=false`，`native_acceptance=false`。这是静态代码和测试合同审核，不能单独
批准合入或把阶段标为完成。C2 的准确原生工作流、完整日志和实际测试结果仍需另行验收。
本报告不把先前设计 PASS、CLI 预检、作者自查或上一阶段 CI 作为当前代码通过的替代证据。

## 审核身份与原件

- 审核者：独立任务 `/root/p2_incremental_design_review`。
- 独立性：未编写、修改、格式化设计或本候选代码/测试。此前承担同设计的非作者审核和
  有界 CLI 预检；本次另行读取完整候选及调用链，没有把预检直接升级为最终结论。
- 阶段基线：`0927af157a3cc35abde14b036bc50a99a793a32b`。
- 基线 tree：`e04479cf7723588885573be2112635efa30e27cc`。
- 初始完整阅读的 C1：`99ec771c57207167f473d23ffd07b54f15a36abc`。
- C1 tree：`510693b0fd8ec085ab06de4140d6f7fd80f48c7e`；唯一父提交为阶段基线。
- 最终审核 C2：`2020c7314a996769b33706754405c0976ce7c50a`。
- C2 tree：`a25d4752d49f366f9aff047116eeffd9b1f6ae1d`；唯一父提交为 C1。
- PR：<https://github.com/youq616/Zevune/pull/15>。
- C2 PR 合成提交：`2d208360ab665fbe82b57d205cf07e789f06164b`，有序父提交为
  `[0927af157a3cc35abde14b036bc50a99a793a32b, 2020c7314a996769b33706754405c0976ce7c50a]`，
  tree 与 C2 相同。这是 PR 测试合成身份，不是实际合入收据。

本地 Git commit/tree/父关系独立核对。2026-09-17 14:10:56 UTC 又直接通过 GitHub plugin
读取 C2 Git commit、PR #15、C2 合成提交和 C1 合成提交；远端 source、base、tree、父顺序
均吻合，PR 当时为 open、merged=false。没有仅相信作者提供的身份摘要。

全部 11 个阶段改动文件的原件内容均已读取。最初完整读取 C1，之后完整读回 C1→C2 的
四文件格式差异，并逐字节将全部 11 个最终文件绑定 C2。最终原件共 **173,722 B**。
对照阶段基线，4 个既有文件变化、7 个新文件；另 **739 个既有条目的 mode/type/blob
完全一致**，没有删除。工作流、依赖、真正授权/状态执行、旧报告及项目状态文件都在该
不变集合中。设计仍是 8,604 B，SHA-256
`0234062797e5436cbccb307db50655b2b7a50f48046ccb91824e9dabc2e93193`。

除这 11 份完整原件外，已阅读 AGENTS、阶段规则、既有 ACTIVE_ARCHIVE_V1，以及真实
PoolStore 活动打开/完整重放、State 执行与授权调用、Record/Replay、AuthorizationVerifier、
namespace retained-name 绑定及旧 stdout 实现。未宣称对整个仓库或上游密码库做全面审计。

## 发现及处理

**CI-C1-FMT-01，Low，C1 原生格式检查阻断 C1 验收；C2 源码修订已核对。**

原生 job `105234456854` 使用 Rust 1.98.1，在 checkout
`066f033f2ca441bdd8533c8e1e4bfe2d3faa84a5` 上执行 `cargo fmt --all -- --check`，
输出 4 个文件的 10 处格式差异并 exit 1。本审核完整读取原始日志并核对其原件
**21,827 B**、SHA-256 `eb63703046d7a4c8acb37bf584a2e355145159650d3bc917f573bcf720e2d05b`。
GitHub 独立查询确认该合成提交 tree 为 C1 tree，父顺序为 `[stage base,C1]`。

具体文件是 `pool/active/incremental.rs`、`pool/active_flow_tests.rs`、
`pool/recovery/active/incremental/tests.rs`、`tests/active_incremental_cli.rs`。
逐处人工审查确认改动只涉及排版和 CLI 测试中 4 处可选尾逗号。另独立提取原生日志中
10 个 before/after hunk，按唯一上下文应用到各 C1 原件，重建所得 **4 份文件与 C2
原始字节完全一致**；C1→C2 没有其他文件变化。没有添加 lint allow、删断言、调超时或
改变执行顺序。C1 不能因为修订产生而被倒写成验收通过；C2 的原生确认由新 CI 负责。

本次静态范围未发现新的 Critical/High/Medium/Low 实质缺陷，也未发现需要改变冻结设计
或削弱验证才能继续的阻断。以下检查结论给出判断依据，资源和测试限制单独保留。

## 代码安全不变量

### 完整重放、可信 pin 与结果隔离

`pool/recovery/active/incremental.rs` 的公开方法先检查两枚 pin 的结构、创世/头长、
高度、逻辑长度及段数关系。不同创世为 Genesis；倒退、同高不同 pin、增长但长度未增
或段数减少为 Stale。任何早期拒绝都没有发布计划，也没有新文件写入。

关系检查通过后明确执行 `self.verify()` 和 `later.verify()`；没有依赖 open 时的历史
成功，也没有同路径或同 pin 的免验证分支。现有 verify 在真实 replay 前后核对完整布局，
replay 对物理 genesis 单独解析并检查 EOF，然后重建未发布状态、逐条执行真实授权和
状态规则，检查记录基准/结果 AppHash 和物理帧/规范轮换。每次 replay 创建新的独立授权
缓存；C2 未改变固定公共验证密钥或缓存实现。

方法的最后还对两端调用完整 `check_bytes`，再调用私有 `ActiveIncrementalPlan::checked`，
全部成功才构造并返回公共计划。任何失败只丢弃局部 Vec 和未发布重放状态；没有修改 live
PoolStore、PreparedBlock、钱包预留或签名状态的路径。

公开计划和范围的字段私有，只有只读 getter；没有外来反序列化、可写 File、可导入状态、
执行计划或跳过未来验证的入口。两个独立可信 pin 是调用者前提；此关系不证明来源、
最新高度或共识 finality。

### 逐字节物理前缀与严格范围

`pool/active/incremental.rs` 的 `visit_append_ranges` 只在原保留句柄上读取。
先检查两端 namespace，比较完整 genesis，再逐一比较全部旧 journal 段。
旧非尾段必须同长度；旧尾段可以增长，但其全部捕获字节必须与 later 同索引的前缀
逐字节相等。分叉的有效历史返回 Stale，不被默认为普通磁盘损坏。

比较覆盖每个 chunk，而不只是文件头、记录摘要或末段；base 每个文件的捕获长度和真实
EOF 都确认。later 同索引文件在自己的完整捕获长度处检查 EOF，不会在 base 旧尾长度
处错误要求 EOF，因此合法追加不会因此被误拒绝。later 全部新字节又由真实 replay 和
末次全布局摘要覆盖，不能只验证旧前缀后发布未经授权的新数据。

所有旧段比较成功后，回调只产生旧尾段非空后缀，以及随后连续新段的完整范围。没有
重分片、零长范围、旧段改写或跳过段的成功路径。低层回调可能在后续错误前累积局部
工作，但唯一生产调用方把它保存在方法内的私有 Vec；错误通过 `?` 丢弃，部分结果不会
成为公共计划。

最终 checked 构造器再要求索引严格递增、范围非空、不超段长、非零 offset 仅属于旧尾段，
新段从 base.segment_count 连续到 later.segment_count−1；检查
`unchanged_segment_count + ranges.len() == later.segment_count`，并要求全部范围长度
之和加 base.length 精确等于 later.length。这样复用字节正确包含 genesis 和旧尾前缀，
不变段数不包含 genesis，新段数也不与范围数混淆。base 无段和同内容空计划均符合这些
等式，不依赖特殊成功 JSON 分支。

### 读取、平台与失败窗口

`fill_at` 将两侧分别填满同样的固定长度缓冲；每次合法 short read 可有不同返回长度，
会按实际读取字节推进偏移，Interrupted 重试当前偏移，提前 0 字节为 Corrupt，其他 I/O
错误为 Storage；注入返回超过请求长度也被拒绝。偏移加法与显式转换经过 checked 验证。
比较使用两个 64 KiB 缓冲，不依赖 clone 句柄共享游标。Windows 仍通过显式 seek_read
偏移读取；调用顺序没有并发改变共享游标的分支。

现有只读归档的 genesis 共享锁、Unix inode/link 检查、Windows 不共享 DELETE 的保留
名称与 reparse 拒绝完整继承。新模块未新增通过路径重开数据文件或提前解锁的路径。
多个只读实例可以共存，合作 writer 在归档存活期间不能获得 genesis 独占锁。

两次完整重放后、最终摘要前的故障分支仅在 cfg(test) 中存在，生产编译不包含文件修改。
它们模拟并保留外部目录项/字节变化，旧 copy_new 故障编号 1–6 和三次完整 replay
没有改变。设计明确不提供任意恶意瞬时修改再还原下的原子快照；可信父目录、操作系统
和文件系统仍是前提，最终读取到返回之间不能被描述为不存在任何外部修改窗口。

### 有界计数、内存与输出

两枚 pin 保留原 1,000,000 高度、1 GiB 逻辑总长、2,048 段及 1 MiB 单段上限。
范围最多 later 段数，使用 `try_reserve_exact` 且每次 push 前检查容量；范围各值为 u32，
总长和加法为有界 u64，没有因平台 usize 截断接受非法输入。新模块未引入随高度增长的
额外索引或历史记录数组。

两个归档各自已有的全部段句柄、顺序 replay 的临时 reader 克隆和完整状态仍有实际成本。
一次对已打开归档的 `incremental_plan` 新执行两次完整 replay；正常 CLI 的两次 open
各 replay 一次，随后方法再两次，所以首次 CLI 完整路径为四次。不能把新计划对象很小
解释为整个操作资源廉价，或把重用公共验证密钥说成重用授权缓存。

`recovery_incremental_output.rs` 在任何输出前限制 ranges.len()≤2,048，以 checked
运算预留 `2,048 + 96 × ranges.len()` 字节，完整构建后检查 ASCII 和实际长度。
独立保守计算即使用 u64/u32 最大值，固定部分仅 1,124 B，每范围加分隔逗号最多 69 B；
2,048 项完整输出上界 142,435 B，小于预留上界 198,656 B。该计算只是输出预算分析，
不是 2,048 段或 1 GiB 实际测试。两枚临时 hex 字符串也固定为各 256 字符。

## CLI 合同与兼容

新命令使用独立分派，参数必须恰为 `--base`、`--base-checkpoint`、`--source`、
`--checkpoint`，并显式确认 NO-FUNDS。缺失、重复、未知、output、两个相对目录、旧 pin、
错误长度/大小写/hex 都在现有有界参数框架内拒绝。两枚 pin 的全部 hex 和结构解析均在
打开任一目录之前执行；BTreeMap 索引发生在键集合验证之后。

旧命令成功输出与主体保持原字节；相对基线仅加入模块、帮助行、命令分派和 base 路径
检查，没有把 active 或 legacy 接口变成另一种恢复工具。帮助仍说明只读计划不写增量
备份，错误输出复用通用消息，不包含用户路径或外部字符串。

成功 JSON 的 format 首字段、operation、两个 pin、各计数、ranges 及七个布尔字段顺序
符合冻结设计，空计划沿用同一 schema。成功只声明 replay 与物理前缀已验证；
`incremental_backup_written`、`snapshot_imported`、`finality_verified`、`validator_ready`、
`real_funds_allowed` 均为 false。

完整渲染后通过未修改的安全 `write_active_receipt` 写出，保留 StdoutLock，复制拥有的
FD/handle 交给 File，Windows NULL 句柄拒绝，write_all/flush 错误返回非零。没有退回旧
stdout 缓冲适配器。操作系统部分写出仍可能留下部分 JSON；本报告不声称所有失败零输出、
flush 即 fsync 或下游已经持久接收。

## 测试可信度核对

新增定义有 **5 个低层测试 + 10 个公开 API 测试 + 7 个 funded CLI 测试 = 22 个跨平台
源代码定义**。API 的 10 个中，7 通用、2 Unix、1 Windows，因此新增 library 应在 Ubuntu
编译 14 项、Windows 编译 13 项；funded CLI 两平台各 7 项，默认 feature 下该文件 0 项。
原 active_flow 保留原 4 项 funded 测试，只向其中 2 项增加检查，不能记成新增 4 项。
这些是源码定义和 cfg 核对结果，不是实际执行或通过计数。

- 物理测试覆盖独立 short read/Interrupted、提前 EOF、I/O 错误、返回量/偏移边界、空段
  集合、尾增长、真实物理 1 MiB 分段、跨 64 KiB 的全部旧字节、EOF/长度及回调错误传播。
  其帧是明确标识的合成字节，没有送入 State/PoolStore，不能作为真实授权证据。回调返回
  Storage 不是实际 allocator OOM。
- API 测试使用正常 prepare/commit 的空块生成真实历史。相同网络的同高/更高分叉先
  分别 open 和 verify；更高分叉还确认增长元数据通过，并直接要求物理比较 Stale。
  不是只用坏摘要或锁失败代替分叉拒绝。成功后两端的目录项、同长内容、截断、追加和
  另一份已有效重放历史的同长替换都会在再次调用时检查。
- cfg(test) 7–10 在双方 replay 和完整前缀比较之后分别改变两端 namespace 或末字节。
  断言要求最后完整检查拒绝，并逐文件核对准确保留的外部变化；没有伪称注入前后目录
  和文件完全不变。Unix 覆盖替换/硬链接/缺失/软链接；Windows 覆盖两端 rename 被 OS
  拒绝、drop 后可 rename。Windows 拒绝层是 retained-name 的 OS 保护，非修改后的 hash。
- 真付款 flow 保留原断言和顺序：第 6,964 块真实 A→B 付款迫使默认 1 MiB 轮换，第
  10,001 块在实际备份/恢复后执行 B→C；第 10,002 块为空块。三个新增计划接点分别
  验证全新段、恢复后旧尾后缀和后续 150 字节空帧，测试内按计划重建后逐文件相等，再
  用 later pin 完整打开并 verify。这个测试重建不是生产增量恢复功能。
- 真签名损坏案例重算记录 checksum 与完整布局 pin。flow 两种角色的 and_then 链明确
  在 `ActiveArchive::open` 返回 Authorization，所以 incremental_plan 闭包未执行。
  CLI 真付款例还专门破坏新增第二条付款记录、保留 base 前缀，重算全部普通摘要，要求
  真实打开 Authorization 和真实 CLI 失败；不把坏 hash、过期或无效布局当作签名拒绝。
  测试没有 verifier 内部计数，不能声称坏实例完成了证明验证。
- CLI 用真实二进制子进程，成功与独立组装的完整 ASCII JSON 字节和单个末尾换行比较。
  普通调用前后比较整个 fixture 目录集合和每个文件字节。追加和空计划均有实际只读
  File 写入失败探针、精确 exit 1、sink 不变、可写 stdout 文件正对照和后续 pipe 成功。
  持有独占 writer 的用例在 drop 后才读取整个树，避免 Windows 检查本身被锁挡住。

基线→C1 的 active_flow 825 条原行按顺序全保留，机械核对成立；新增 138 行，C2 只
格式化其中一条新断言。本审核没有发现删旧证明/签名/状态/容量/恢复断言、引入 mock
verifier 或通过缩小段上限制造轮换证据的情况。

## 附属独立检查与原始证据

另有非作者附属任务 `/root/p2_incremental_design_review/c1_test_evidence` 独立完整读取
四个测试文件、设计及所需真实调用，最终绑定 C2，无新增实质静态发现。主审核已完整
阅读其 12,313 B 原文，并与自己对源码的阅读交叉核对；没有委托其替主审核读取其余文件。
其“四次 replay”说明按首次 CLI 全路径理解；已打开实例的方法每次新增两次，此处已明确。

本目录的原始证据：

| 原件 | 字节 | SHA-256 |
|---|---:|---|
| `c2-test-evidence-subreview.md` | 12,313 | `f30dc7c696ca74d075375caed334081ebcf49cd9800b1f602bd92afbc45e1d3c` |
| `c2-code-review-observations.json` | 4,488 | `93907810ed59d9a4d277bd5928959837e1904dcd4e17cdbd029901daf7e3c275` |
| `c2-code-review-github-identity.json` | 20,132 | `f221402e10cd481a50a4c5ec82a30a3980ac0402062826403a92e58b1a9550bd` |
| `c1-first-format-job-105234456854.log` | 21,827 | `eb63703046d7a4c8acb37bf584a2e355145159650d3bc917f573bcf720e2d05b` |

observations JSON 含全部 11 份文件的 C2 Git blob、字节、SHA-256 和格式 hunk 重建结果。
GitHub identity JSON 保留本任务独立调用的完整原响应。代码路径、报告和原始日志均可由
父任务按准确字节归档；不能用后续较新的原件覆盖此冻结证据。

## 仍需实际验收的边界

本机 `cargo`、`rustc`、`rustfmt` 不可用，本任务没有运行 Rust/Go 编译、Clippy、单元/集成
测试、race/fuzz 或 workflow，也没有修改仓库、提交、推送或合入。实际执行的
`git diff --check base C1` 与 `git diff --check base C2` 均成功，但前者不曾代替 rustfmt，
C1 的原生失败已明确保留。C2 原生格式 source job 成功的父任务通知不扩展本报告的
原生验收范围；主矩阵和完整日志尚未由本审核认证。

未实际验证 allocator OOM、2,048 段/1 GiB 满容量计划及资源峰值、任意恶意并发修改、
全部平台 I/O 失败、broken pipe/部分写出/下游持久接收、真实断电或磁盘满、Windows
目录持久化、长期多机、验证者签名状态恢复。进程测试与只读核验不能替代这些证据。
项目仍是 NO-FUNDS；生产就绪、增量包写入、快照导入和外部安全审计不能因本报告变为已完成。

**最终保持 PASS_CODE，仅绑定 C2 `2020c7314a996769b33706754405c0976ce7c50a` / tree
`a25d4752d49f366f9aff047116eeffd9b1f6ae1d`；无开放的实质代码阻断，阶段和原生验收待完成。**
若后续原生结果给出反证或源码/测试发生变化，保留本原文，另行记录发现与新候选复核。
