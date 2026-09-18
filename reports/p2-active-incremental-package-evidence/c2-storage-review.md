# C2 持久增量包：准确候选独立存储与对抗复审

审核任务：`/root/p2_package_storage_review`。日期：2026-09-18 UTC。
本任务未编写本阶段设计、生产源码、测试、CLI、工作流或 C2 格式修复。此文件是针对 C2 新写的完整审核原件；原 C1 报告和失败日志保持不变。

**结论：PASS_CODE（静态存储/语义），BLOCKED_NATIVE_CLIPPY。** 对精确 C2 的生产语义、存储边界、真实调用方和测试逻辑未发现阻断；独立取得并完整阅读的 C2 原生日志确认默认库171项及新包physical7/API10项通过，但 strict Clippy 因测试中的 `drop(reader)` 触发 `drop_non_drop` 并以101退出。该候选未通过原生门禁，不能接受或合入。任何修复必须形成新的准确候选并独立复审，后续原生矩阵仍待完整审核。

## 1. 独立绑定的 base、candidate 与 synthetic

- 仓库及 PR：[youq616/Zevune #17](https://github.com/youq616/Zevune/pull/17)。本次独立读取为 open、merged=false，head=C2、base=main。
- stage base：`2cc87a2207d502ac5cfe00ea52e525c1516917e5`。
- base tree：`b5841120084a72c5948b0a2754f712e5f67ad602`。
- 上一个候选 C1：`61c691270b91aece076177cb757e51e0e63fe310`，tree `56dad7fdaad64b2b29ddac6b9585b8695aa465d7`。
- [准确 C2](https://github.com/youq616/Zevune/commit/f51c8db240933256870ff03c07bc68915b4ac4a1)：`f51c8db240933256870ff03c07bc68915b4ac4a1`。
- C2 tree：`7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400`；其唯一 parent 为 C1。
- PR synthetic：`aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f`。
- synthetic parents 按序为 `[2cc87a2207d502ac5cfe00ea52e525c1516917e5, f51c8db240933256870ff03c07bc68915b4ac4a1]`，tree 与 C2 精确一致。

上述 PR/commit/synthetic 通过本任务直接调用 GitHub connector 取得，另与本地 Git 对象比对；没有只使用作者给出的 IDs。核对时本地 HEAD=C2、tree=C2 tree、工作区 clean。使用 `git show <fixed commit>:<path>` 和固定 commit diff，避免正在变化的 branch 名或缓存摘要替代准确源码。

相对 stage base，C2 仍精确 12 个路径、7 新增和5修改；这 12 个最终完整文件共 262487 字节。基线 886 个 entries、C2 893 个 entries，其他 881 个 mode/type/blob 完全相同。相对 C1 仅 7 个文件变化，其他 886 个 entries 完全相同；没有工作流、依赖、预算、额外功能或旧证据变化。

## 2. 完整阅读与独立 C2 字节重建

本任务已完整阅读 AGENTS、STAGE_REVIEW、精确冻结设计、原追加计划设计，以及 ActiveJournal、ActiveArchive、两层 incremental、namespace、Replay 及相关真实验证器/调用方。C1 阶段完整阅读了全部新源码、两组包测试、1127 行完整真实 flow、361 行 CLI 入口、完整 renderer 与1024行新 CLI 测试；最终高层测试853行在作者冻结后重新从头读到尾。原生产文件以已读完整基线加全部精确候选 diff 覆盖，完整阅读范围及未读边界在保留的 C1 原件中逐项列明。

本次针对 C2：

1. 独立读取完整 `git diff C1 C2`，7文件、74行新增/75行删除，逐项检查所有表达式及上下文。
2. 不只比对作者 `c1-rustfmt-repairs.json`：使用本任务直接取得并完整阅读的 C1 wallet Ubuntu 原生日志 `105656510131`，独立解析其 30 个 formatter hunks。
3. 从本地固定 C1 Git blobs 出发，验证每段原生 before/context 唯一命中，收窄真实差异以避免相邻 context 重叠，再从后向前仅在审核者内存中重建各文件。
4. 独立重建出的 7 个完整文件与固定 C2 blobs **逐字节相同**；C1→C2 变更路径集合恰好等于这 7 个原生日志路径，没有其它隐藏变化。
5. 再次逐一核对全部12个C2文件的 `git show`、本地冻结字节、SHA-256、mode/type，以及直接按完整内容重算的 Git blob SHA；未变化5个文件与已完整读过的 C1 字节相同。

这次复审没有运行或替作者调用 formatter，也没有修改仓库。重建只验证修复符合已亲读的原生输出，不能代替新 C2 formatter 的实际执行。完整 diff 中除换行/缩进/宏参数收拢外，`visit_span` 的 closure 由单表达式变成 `{ read_at(...) }` 尾表达式块，参数、捕获、返回 Result、偏移更新和错误处理均相同；未引入分号、短路、分支或忽略错误。所有检查条件、测试值/断言、NO-FUNDS gate 和 test cfg 保持。

| C2 路径 | 字节数 | SHA-256 |
|---|---:|---|
| `docs/ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md` | 13361 | `b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41` |
| `integration/orchard/src/bin/zevune-pool-recovery.rs` | 16512 | `a7f251856937ae0096e4f777181fed91c7ab2daa5da181bed84957247603f31c` |
| `integration/orchard/src/pool/active.rs` | 29831 | `a01d97908ca9b02008d098f047450da126cf9796dcf0ccc201f96409a9d4540a` |
| `integration/orchard/src/pool/active/package.rs` | 27208 | `b1bf8a85f6dbe78fa63968f844a00b722d92e268344255deb9e78e1a01a691a0` |
| `integration/orchard/src/pool/active/package/tests.rs` | 22676 | `da17e4fd21608870c05f88d528e01c6a2ad79e27287ff69af40c5d92b4319910` |
| `integration/orchard/src/pool/active_flow_tests.rs` | 46190 | `ec841665b8b4ffeee0c6cf059658ca02b4b7525b7012776e2b270c54b075fd22` |
| `integration/orchard/src/pool/recovery/active.rs` | 10574 | `aeba87d0648cf043bcb22554a71b30509f4fa19ac99863738ed729b870c280eb` |
| `integration/orchard/src/pool/recovery/active/incremental.rs` | 7548 | `50d291f6613450faec4441d769758728423ae12aa7912d6f2d04cfbe010beedc` |
| `integration/orchard/src/pool/recovery/active/package.rs` | 14622 | `4bee4fbaeb96e1ceb394c28031c9fe6215f40f434c79170a8d84dfa9736a02ce` |
| `integration/orchard/src/pool/recovery/active/package/tests.rs` | 34856 | `76295a59daaffedb52d936c61db43e569c941e3e3c8b000db0e78095d791e5fd` |
| `integration/orchard/src/recovery_package_output.rs` | 2720 | `7c2a82ac2238ccce46d4656ef884aee75e6ae9104943496336aa78c2bce52aab` |
| `integration/orchard/tests/active_incremental_package_cli.rs` | 36389 | `dce6b087fe2a9381db7d3a10c918f64ee36fde4014d0f2cbbc47d5bdd23dcb87` |

## 3. 对 C2 存储与验证合同的判定

以下是基于完整源码阅读、全部 C2 修复上下文及逐字节身份复核得出的本候选判断，不是把 C1 PASS 或另一审核者结论自动转用。

**双独立 pin 与严格范围。** 包内两 pin 只是待比对的输入，公开 open 只有在 base 与组合历史完整 replay 后才发布对象。固定头/N/范围表/精确 delta 文件长度都在相应分配前有界检查。高层 `checked_plan` 和私有 `JoinedJournal::new` 都绑定旧尾 offset 与实际 retained base tail，新的段索引连续、offset=0，拒绝零长、重复/反序/缺口、溢出、短尾或额外数据。没有从不可验证的范围表构造可写状态或可变计划的公开 API。

**原始句柄与 EOF。** 包打开保留只读 shared lock，创建保留原 RW 创建句柄及 exclusive lock，父目录从准备到末检保留身份。读取使用显式偏移和64 KiB有界缓冲。短读/短写/Interrupted 都正确累计，零进度、异常数量和偏移溢出失败关闭。base每个完整物理文件确认真实EOF，包range中途不做整文件EOF，整个包末尾另外验证EOF。失败的 joined reader 不可恢复继续，所有者/借用关系不会释放原始锁再重开。

**布局和真实帧。** ZVARLY01 覆盖完整 genesis、实际段数量、index/length 和全部复用/新增物理 bytes，metadata 每次逐字节与捕获值比较。高层再次检查独立 base 全布局与 later 全布局。当前活动文件和组合视图共同调用同一私有 `validate_physical_frame`，逐个 Replay 实际 start/end 拒绝拆帧和过早轮转；range 边界不是记录边界。C2 仅重排 shared helper 的 checked_add 表达式，接受条件未变。

**新验证器与隔离状态。** verify先完整base.verify，独立解析base物理genesis，再解析组合逻辑头并比对 length/initial/domain，从该实际头建立隔离State，绑定genesis，并使用新 AuthorizationVerifier 全量 Replay。每个真实frame执行授权/状态及物理判定；完整EOF、最终height/app_hash/genesis匹配后，还重检全部base/package bytes/metadata/名称。没有导入旧缓存、信任checksum、跳过证明、部分State外泄或将计划作为未来支出权限。

**create_new 恢复。** pack先检查新目标和两个源，再现算完整双归档计划，按原later句柄流式写精确追加bytes、同步并完整验证包，最终复查两个源及整个包。restore在任何目录产生前完整验证，按真实物理布局create_new每个目标文件，保持genesis排他锁及所有创建句柄、逐文件和目录同步，再直接以这些句柄验证实体目标；重新完整验证输入后，末次检查整个目标和parent。没有在现有 PoolStore 中追加、覆盖或修复已提交历史。

**链接与父目录。** 包明确复用 active 层的严格 regular/check_file，包含Unix nlink==1，弥补旧 namespace helper 不含该条件的差异；Windows retained-name/reparse约束及Unix inode/device检查保留。canonical父路径禁止源内输出，parent身份检查不要求目录空白，合法兄弟恢复目录可以存在。所有既有目标都被create_new拒绝，失败不自动清理或截断。

**失败和耐久性表述。** cfg(test) 的部分metadata/payload/genesis/段写入、sync前与durable后确认丢失、末次源/包/目标变动都经过实际路径，失败保留新内容和可复核错误现场。完整留下的输出只可另行显式验证；错误本身不保证目标不存在。测试的包位翻转^1与尾段^0x80分别匹配实际helper。真实磁盘满/掉电、Windows可移植目录掉电持久化和任意恶意瞬时改写原子快照没有由此获得保证。

## 4. 真实调用方和测试含义

真实 funded flow 的所有旧断言保留。第一笔真实付款在正常1MiB轮转后，经旧归档恢复、真正增量包pack/open/restore，新恢复路径直接成为普通genesis.open_pool使用的路径；之后第二笔真实付款从该路径的真实钱包历史继续，到10001后又通过新包恢复再提交10002。没有旁路构造State或仅物理复制却声称恢复后花费。

坏新增binding signature用例重算普通frame摘要及later完整物理pin，保留真实base前缀，直接用真实base+包进入公开open并要求Authorization拒绝。它不提前打开无效later归档，所以拒绝点属于新的组合授权路径。由于binding签名检查可先于proof失败，不宣称该无效实例已执行完proof。

新的early rotation和split frame测试先通过私有metadata及完整重新计算layout检查，再由组合Replay的frame gate拒绝；恢复在创建前失败。反序descriptor用例同时反序payload、保留合法索引，针对实际次序规则。私有physical多新段场景从不进入State/PoolStore，只计物理transport覆盖，不能作为真实授权证据。

三CLI模式由固定参数白名单、显式NO-FUNDS和双pin解码进入原API，旧命令仍使用原入口。renderer整行有界生成ASCII固定JSON，经原安全File-backed stdout真实写入。新CLI测试核对独立编码原始包及全部字段顺序、无later时verify/restore和后续提交、双pin/选项/路径拒绝、全目录树不变、writer与共享reader跨进程锁、只读stdout实际写探针及可写正对照；丢回执后的完整目标可另行真实CLI验证，重用相同目标拒绝。

新增源码定义计数仍为physical8、API11、CLI8，共27定义；平台条件下预期Unix25、Windows24，其中CLI仅在funded feature启用后实际执行。默认0-test CLI harness不能算CLI覆盖。格式修复没有修改测试值、断言、feature gate或增加证明生成。上述定义计数是静态源码覆盖含义。第5节单个C2 Ubuntu默认job中实际观察到新physical7/API10项通过；新CLI harness为0项，不能算CLI执行覆盖。

成功路径代码中的完整replay次数继续为pack方法4、package verify/open各2、restore方法5；CLI为6/3/8。该特性减少重复备份bytes，未减少真实重放要求；这些次数是审阅调用关系，不是新增性能或整个进程峰值测量。

## 5. C1 格式失败、C2 原生 Clippy 阻断与剩余范围

C1-FMT-1的原始失败仍保留：job105656510131完整日志40556B，SHA-256 `247217a4771742d0e14f66222cc6e9657d1969e290c3052272a44c9e5a927080`，保留UTF-8 BOM/原换行；Rust1.98.1的fmt输出7文件/30hunks并exit1，该所读job没有运行Rust测试。C1静态报告明确BLOCKED_NATIVE_FMT，不得以后修改成曾经原生成功。

C2修复范围已在**源码字节层**独立确认精确符合全部30个原生formatter输出；没有语义或测试变化，未发现新静态存储问题。随后本任务直接通过GitHub connector独立获取并完整阅读job105658335135的823行原件，与root保存版本逐字节相同：67053B，SHA-256 `b8b147786cfb42b849192b6a7dc2596a1147db766b55962331d12538a406bddb`。原件保留UTF-8 BOM及换行，非仅接纳root摘要。

该job名为tests (ubuntu-latest)，Ubuntu24.04.5，Rust1.98.1 (48a229cea 2026-09-01)，实际checkout为上述C2同tree synthetic `aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f`。`cargo fmt --all -- --check`、locked metadata及tracked clean检查在bash -e下完成并进入下一步；`cargo test --locked --release -- --nocapture --test-threads=1`的默认库171 passed、0 failed，逐条包含新physical7/API10项。默认包CLI harness为0 tests；其余该job中的worker/integration测试和doc harness随后完成，无失败。该日志不包含funded模式包CLI或真实增量付款flow的执行，不能用默认结果冒充。

**C2-CLIPPY-1（原生验收阻断）：** 下一步 `cargo clippy --locked --release --all-targets -- -D warnings` 在 `src/pool/active/package/tests.rs:354:9` 报 `drop(reader)` 的 `clippy::drop_non_drop`，明确类型为 `JoinedReader<'_, '_>`，最终exit101。静态生产安全PASS不能豁免此要求；需最小修复并重新发布准确候选，不能加入allow或删除断言以掩盖。这里记录已观察到的失败，不预先认可后续修复或重跑。

本报告只独立审阅上述一个C2原生job，未核对所有runs/jobs。故当前结论为PASS_CODE / BLOCKED_NATIVE_CLIPPY，其余原生结果待审，不是PASS_NATIVE或阶段接受。后续准确候选的Ubuntu/Windows默认/funded Rust、fmt/strict Clippy、Go test/vet、支持平台race/fuzz、100000块增长、32+1付款资源和四节点回归仍需真实结果与独立原生审核关闭。

本地没有cargo/rustc/rustfmt/go，本次未运行编译、Clippy或产品测试；`git diff --check base C2`及`git diff --check C1 C2`成功仅表示diff空白检查。本任务未执行真实磁盘满、突然断电、Windows实机文件系统、完整1GiB/1000000记录/2048段压力或长期多机实验，不宣称资源峰值已测覆盖新包CLI。

没有新增协议密码学、生产状态导入、wallet/signer recovery或实值转移。P2继续开发，NO-FUNDS、production_storage_ready=false、audited=false、real_funds_allowed=false边界保持。本审核不等于外部专业安全审计或部署许可。

## 6. 原件与可复核材料

以下材料都由本任务直接保存到 `/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package/`，未改动仓库源码：

- `c2-storage-review-scope.json`：12506B；SHA-256 `71becfd1ab44d0a1d0ebfab743fe94f6915c3118ff007675e715f91d101e56be`。包含准确Git/API身份、12最终文件mode/type/blob/bytes/hash、每文件实际阅读方式、完整delta及未测边界。
- `c2-storage-native-fmt-reconstruction.json`：3046B；SHA-256 `53bbd1984a05838b5ebdc7f28b64b47f420fb6b25e8beddbd3d984c0b8bf0197`。记录独立读取原生日志、从C1 Git字节重建C2的7文件/30hunks结果；不是作者repairs摘要复制。
- `c2-storage-pr-api.json`：3937B；SHA-256 `03f29678bbd6998a8f5edf2099e657f12760baf5ad0da6f4886005892281f278`。这是connector structured PR对象的明确格式化JSON。
- `c2-storage-head-api.json`：1121B；SHA-256 `d960e3f97a6e326bf987cc1c9bd6a364557d0e27e188be33587e18de116793e6`。
- `c2-storage-synthetic-api.json`：2569B；SHA-256 `431ccbe2245ef1540ec001f3b311b7201b74bf6c7d5a7d237b001b52b813cce7`。
- 两个Git API文件保留connector decoded content的精确UTF-8字节，非原始HTTP字节；base另与此前独立取得的base API及本地固定对象交叉绑定。
- `c2-storage-clippy-job-105658335135.log`：67053B；SHA-256 `b8b147786cfb42b849192b6a7dc2596a1147db766b55962331d12538a406bddb`。由本任务直接获取、完整阅读，保存connector原始decoded文本的精确UTF-8字节。
- 原`c1-storage-review.md`：19216B；SHA-256 `a4dcbdd4286f13cc929c35821b12ff016607de23984a23f69f77a6138771a106`。
- 原`c1-storage-review-scope.json`：9047B；SHA-256 `88d691f2d92b91da7f20884c6144355f8ffc9396ec15d8405dd068e4fa747001`。
- 原`design-storage-review.md`：14683B；SHA-256 `acb078f95d2d73dcac85060b382b698443d5690af5073f0f0005a5b7dbe00f26`。

最终判断针对本报告明确绑定的C2当前字节形成；原C1及设计原件各自保留原作用域。后续原生通过应以另一个可追溯原件追加，不在此报告内事后抹去BLOCKED_NATIVE_CLIPPY或改写原失败历史。
