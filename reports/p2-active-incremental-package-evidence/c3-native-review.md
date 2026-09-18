**PASS_NATIVE_C3 — 准确 C3 的本阶段原生验收证据通过独立审核。**

审核日期：2026-09-18 UTC；任务 `/root/p2_package_native_audit`。本审核者没有编写本候选
实现、测试、设计、workflow，未调整验收预算。结论形成于完整10个终态PR workflows、
23个jobs的所有原始日志/API/工件到齐、逐字节完整性复核及非作者分项原文全文阅读之后。
没有发现本范围内尚未关闭的原生验收阻断；这不替代其他独立源码审核或扩大产品能力。

| 身份 | 准确值 |
|---|---|
| 仓库 / PR | `youq616/Zevune` / [#17](https://github.com/youq616/Zevune/pull/17) |
| 阶段 base | `2cc87a2207d502ac5cfe00ea52e525c1516917e5` |
| base tree | `b5841120084a72c5948b0a2754f712e5f67ad602` |
| C3 source | `cb0804e7c921a456cbbafab313b3a4a4501b8f5e` |
| C3 tree | `21de343c12bc27cb1022ffd7ebd451abe0e61f29` |
| C3 parent | `f51c8db240933256870ff03c07bc68915b4ac4a1`（C2） |
| actual PR checkout | `3dfa8d77921693b9e99af5b94af198498b9422e9` |
| checkout parents / tree | 精确为 `[base, C3]`；tree 与 C3 相同 |

审核者通过 GitHub 插件独立查询 source/synthetic commit、准确PR runs及jobs，和root
保存的完整终态原件、本地精确Git对象交叉核对。全部23份日志的实际checkout一致，
全部run/job顶层head和run head_commit tree准确绑定C3；不把会随live PR更新的嵌套
PR关联对象用作历史运行身份。base→C3只有冻结范围的12个路径；原有全部workflows、
工具链、锁依赖、调度器、Go/resource/growth实现与预算未改变。

**完整矩阵和原始证据。**

| 必需 workflow | 实际 PR run | jobs | 终态 |
|---|---|---:|---|
| payment-resource-baseline | [35363727198](https://github.com/youq616/Zevune/actions/runs/35363727198) | 2 | success |
| orchard-bridge | [35363727125](https://github.com/youq616/Zevune/actions/runs/35363727125) | 2 | success |
| consensus-laboratory | [35363727392](https://github.com/youq616/Zevune/actions/runs/35363727392) | 2 | success |
| orchard-consensus-integration | [35363727277](https://github.com/youq616/Zevune/actions/runs/35363727277) | 2 | success |
| scaffold-tests | [35363727199](https://github.com/youq616/Zevune/actions/runs/35363727199) | 2 | success |
| local-network-operator | [35363727265](https://github.com/youq616/Zevune/actions/runs/35363727265) | 2 | success |
| wallet-laboratory | [35363727131](https://github.com/youq616/Zevune/actions/runs/35363727131) | 2 | success |
| orchard-cryptography-laboratory | [35363727278](https://github.com/youq616/Zevune/actions/runs/35363727278) | 2 | success |
| active-ledger-growth | [35363727172](https://github.com/youq616/Zevune/actions/runs/35363727172) | 3 | success |
| funded-wallet-consensus | [35363727269](https://github.com/youq616/Zevune/actions/runs/35363727269) | 4 | success |

10个workflows均为pull_request、attempt1、completed/success；23个实际jobs全部success，
无cancelled、无失败、无job级skip。步骤合计**274 success /9 skipped**，9项全部是原有
Windows条件skip：scaffold3、consensus1、bridge2、integrated2、operator1；对应Linux
命令实际执行。全部要求的fmt、strictClippy、source/lock不变检查和cleanup均有自身原文。
仓库另外两个workflow是push-only source archive及本次路径不触发的notice inventory，
没有冒充本次PR测试覆盖。原始期望没有事后修改成通过结果。

`c3-native/`共**62个原件 /2,017,223 B**，目录集合、每件长度与SHA-256全部独立重算，
与冻结manifest完全一致。包含完整runs列表、10份run/10份jobs/10份artifact API、
**23份完整logs /1,417,655 B /16,675解码行**，双平台资源原ZIP及四个精确JSON成员，
双平台operator原manifest。BOM/CRLF原字节保持，解码解析副本不改写原文；API原件是
connector提供的结构化内容，不声称保留底层HTTP传输编码。operator大ZIP另在scratch
真实下载、全成员读取并验证；仓库证据保留其API、manifest和完整校验记录，不放二进制。

**Rust cohort 和全部新增具名用例。**

| 完整 cohort | 实际 jobs | 每 job harness | Ubuntu passed | Windows passed |
|---|---:|---:|---:|---:|
| default：bridge/integrated/crypto/wallet | 8 | 20 | 库171、总185 | 库163、总177 |
| funded-library | 2 | 1 | 190 | 182 |
| funded interfaces：5bins+16integration+doc | 2 | 22 | 71 | 70 |

合计**206个完整Rust harness result、1,961次重复具名通过执行**。这是各job累计，
不是1,961个唯一测试。每个harness均核对target、`running N`、具名pass数量与result，
failed/ignored/measured/filtered均0。同平台四个default jobs的完整target顺序、各target
pass数与名称集合全部相同。funded库包含对应default库全体并新增19个既有funded-only
测试；两个动态cohort保持完整target分区，未加test-name filter、skip、ignore或no-run。

新增源码定义共**27个**：物理package8、公开API11、CLI8。实际各OS适用库17个
（物理7+API10）；它们在8个default和2个funded-library jobs逐名全部通过，共170次。
两个funded interfaces再执行新CLI **Ubuntu8 /Windows7**，共15次。新增定义跨两平台
联合全部有具名覆盖，累计185次；平台差异来自源码cfg，不是忽略或漏跑。默认feature
中的新CLI目标为0项，只保留其编译/空harness事实，不把它算作实际CLI执行。

Ubuntu新CLI在[job105660992545](https://github.com/youq616/Zevune/actions/runs/35363727269/job/105660992545)
8项/211.73秒；Windows在[job105660992463](https://github.com/youq616/Zevune/actions/runs/35363727269/job/105660992463)
7项/267.15秒。两端旧active_incremental_cli各7项、active_recovery_cli各7项及其它既有
目标保留。完整interfaces计划选5个bin与16个integration target，另执行doc，最后均有
`FUNDED_COHORT_COMPLETE interfaces`；doc的0项结果不授予文档测试样例执行信用。

审核者完整读取三个新测试文件、实际active_flow修改与辅助编码/恢复函数，将静态名称
和cfg逐个映射到实际日志，未把名称相似当作相同语义。新增覆盖包括：独立格式编码和
精确物理字节；genesis/空尾/新段/相同内容空包；元数据、pin、offset、length与EOF；
短读写/Interrupted、注入失败残留、失败reader不可继续；重算pin的早轮转/跨段frame到达
真实组合replay拒绝；包/目录拥有者锁及最后drop释放；Unix链接/名称替换与Windows
保留句柄行为；真实CLI子进程三命令、独立双pin、移除later后验证/新目录恢复、普通后续
提交、已有/嵌套输出拒绝，以及只读stdout失败仍保留完整输出供显式再次验证。

新CLI fixture主要采用真实普通空块提交，物理层私有fixture只证明传输字节；这些不冒充
新增真实付款。真实付款覆盖来自修改后的既有funded library主流程：两端4个active_flow
均具名通过，库总耗时Ubuntu154.70秒/Windows436.12秒。原来两笔genuine付款生成次数
未增加，第一笔导致正常1MiB轮转后，**第二笔真实花费确实从增量恢复返回的目录继续**，
普通prepare/commit跨10000到10001，另一次包恢复后重花被拒绝并正常提交10002。旧归档、
只读计划、余额/费用/双花及源不变断言仍保留。新损坏向量只改新增第二笔binding signature，
重算普通帧摘要及later物理pin，以有效base和新包直接调用open到达Authorization拒绝，
没有先打开坏later目录遮蔽组合入口；不声称该坏签名实例必然执行了后续所有proof步骤。

**原生日志解析修正，独立于产品修复。**

Ubuntu wallet原日志105660991474中，两个0-test stdout result（589/594行）早于对应
Cargo stderr Running announcement（596/597行）。原v1解析器假定announcement已到达，
因此在读取这份真实成功日志时产生AssertionError；该观察和v1原字节均保留。它不是
产品失败，也没有因此重跑、改写或删除CI日志。

v2分别收集完整Cargo announcement与stdout harness结果，保持各流内部执行顺序，要求
总数严格相等后按ordinal配对；每个running N、具名数量、零fail/ignored/filtered和最终
cohort完整性条件不变。v1/v2在完整C1 21份+C2 23份日志上解析对象逐一相等；C3再核对
同平台四个default完整target/name集合及动态funded target并集。上述两个新CLI/恢复CLI
空目标仍为0，没有制造执行信用。`rust-parser-v2-observation.json`保存完整失败观察、
原文身份、实际行、对照结果及新旧helper哈希。此改动仅修正审核工具，候选C3源码未改。

**Go、Python、真实网络、增长和工件。**

非作者分项 `/root/p2_package_native_audit/nonrust_logs` 对所有原始API/logs、资源ZIP及
operator全部payload独立阅读全文/全字节核对，其最终原文已由本任务完整读回，结论
`PASS_NONRUST_NATIVE_C3`。使用准确C3证据，不继承任何C1/C2通过项。

- 适用Go test/vet、Linux race和8个真实bounded fuzz引擎通过；fuzz分别为scaffold
  2×3秒、bridge2×10秒、integrated1×10秒、operator3×3秒，原参数和预算保持。
  编译用 `-run '^$'` 不算测试运行。Python8次suites累计672发现/660通过/12平台skip，
  是135个既有名称的重复范围，Linux/Windows共享测试的适用端均实际执行。
- 两个平台实际Go→Rust授权、Orchard四进程集成、funded四节点非零A→B→C、钱包outbox
  恢复、节点离线及整网重启、错误post-state拒绝与operator流程完成。funded专用
  四节点test Ubuntu61.32秒/Windows91.34秒；其两次local样本为6139/6330ms和
  8824/12055ms，包含backup/rescan、signed-header及独立replay。没有把两样本叫p95、
  TPS、WAN或生产付款速度。Python互通的prepare计时范围也保持local_prepare_not_finality。
- 两平台growth实际100000 commits（99998空/2付款）、15段/15018544B、固定1MiB段限额，
  完整重放后继续100001。Ubuntu增长68105ms、重放2436ms；Windows418674ms、2743ms。
  它是local worker增长，不是100000四节点高度、100000笔付款、超过64MiB或全容量证明。
- 两平台资源32+1真实付款均有9events、362progress/181严格有序操作、18内存samples、
  14checks、最终result、具名PASS和登记子进程退出。实际setup/result原成员与原ZIP
  完全相等、ZIP匹配API；初始setup的not_started不被当作最终结果。最终height33、
  commitments68/nullifiers66/fees33000，逻辑308756B/1段。Ubuntu两worker/scenario
  生命周期峰值11522048/11685888/176529408B；Windows13053952/12783616/117739520B，
  全在固定1GiB门槛内。原Go1200/supervisor1230/handshake15/start-request60/scenario90
  秒预算不变；这些不是新package CLI所有进程峰值、每阶段独立峰值或跨平台性能比较。
- operator两原ZIP的全部5payload各自流式重算长度/SHA/CRC，manifest、builder receipt、
  artifact metadata和准确synthetic/tree一致，两文本与精确Git blobs逐字节相同。
  下载二进制没有在本地执行，也没有独立重建；完整性不等于代码签名或可复现构建证明。

**历史拒绝、冻结记录与限制。**

C1永久保持REJECTED_NATIVE_C1：17个fmt失败jobs，0 Rust执行；C2永久保持
REJECTED_NATIVE_C2：10个strictClippy失败jobs，同时保留其真实部分成功。C1→C2只是
7文件30个原生fmt hunks；C2→C3只是删一个多余 `drop(reader);`，没有allow、断言或
预算变化。C3 PASS来源于自身完整矩阵与本次独立读取，未事后改写早期结论。

| 原文 / 审计记录 | bytes | SHA-256 |
|---|---:|---|
| `c3-native-review.json` | 635231 | `8a2d69734ef03c3f0631f3a89a206d18f385933a1f06dfc8956f996b021267b3` |
| `native-expectation.md` | 15339 | `bb1d40e78a983703a41804ed51d89593a813693d06d77f25cdd6d6da5d8ddd4a` |
| `c3-native-review-structural.json` | 592246 | `cce9bfd571308764f53a3f4997c3c1516efc6f29d0cb33f188d6be425e777d15` |
| `c3-native-source-scope.json` | 13663 | `b85f100a941194dc7a85f52f10e635f87d9992fd525812f8a562e8dd393e3fe6` |
| `c3-native-original-manifest.json` | 10748 | `ce46da4d693bd973862f7401a753eeccf4af0338c03f4a775c5daf32f54e67bb` |
| `c3-native-nonrust-review.md` | 19741 | `8f15ef020c7f1bfdb6bc09a7d67a43b61e47eb2cb372d993e441d761f8416597` |
| `c3-native-nonrust-review.json` | 516810 | `19d6cdaf3d44a3972883a2261115171b70b21a154fdb9e7c83487c2e8d16b30e` |
| `c3-resource-independent-review.json` | 60951 | `2502f314c3fdf81944bf438b0e7c8925c5fb1af729daf20487e0f0bddd366460` |
| `c3-operator-independent-review.json` | 12050 | `19759c64009d7cc2d893210afd17484ba9699a38517e5435f98b284ee18b65c0` |
| `rust-parser-v2-observation.json` | 41603 | `79d3ea38ebd9137939eaf8ea46b7972aa8718a38d2fc3dd61eecfa7a2a3c7038` |
| `native_audit_rust_helpers.py` | 4101 | `a5ee1226de8ec8aba16c1d04954606927efe796a8d558ef7af04097c2beec02d` |
| `audit_native_structure.py` | 3184 | `a8a4a37698fef1c61dc13d53f599ed83ead1bb12f95124d5d42f281c0d0c2305` |
| `native_audit_rust_helpers_v2.py` | 4320 | `2fee2dff4a115049fed1023c2af12ad7435ca753c4c69171d925f45e4e3f554d` |
| `audit_native_structure_v2.py` | 3187 | `32640fb97a41fbb11fe4b50dbb32bdbb12a9bbac11efe5c86c6e70c00ec862dd` |
| `audit_complete_native.py` | 11772 | `0bfc5b670c95a60a71ebeda8ca3421367148c33fe74600cd1df3ef69f706aaae` |
| `c1-native-review.md` | 10580 | `b36c0a5ec922eb7db16b52047655ef45da73307b7df2e97d6da19dd19559c407` |
| `c1-native-review.json` | 210320 | `125829c4e8766347438b6ff49c8df1ae21c834ffb6e8439232b538fb33ff1b10` |
| `c2-native-review.md` | 10874 | `2ab31654a79d40031012d78ea97d3ba19b85fb01579180ab53fc4be4fd419334` |
| `c2-native-review.json` | 573013 | `27b8a99e5e95cd68cfc5b4361520f464abe793109879baea77837f4cba4bc308` |

本任务没有本地Rust/Go workload执行、下载binary执行、重新采集OS数据或合入操作。
结构化checker不是自动批准器；本原文及JSON的PASS_NATIVE_C3是全原件、源码测试含义
及独立分项复核后的限定结论。它支持本阶段NO-FUNDS活动账本持久增量包的原生验收，
不宣称状态快照导入、剪枝、生产存储、真实资金、最终性、专业外部安全审计，或真实
磁盘满/物理掉电、全容量、macOS、任意敌对文件系统保证。阶段发布和文档验收由root
结合独立代码审核及准确merge/evidence身份另行闭合。
