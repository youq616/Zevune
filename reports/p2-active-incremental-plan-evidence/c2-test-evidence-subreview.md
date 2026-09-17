# C2 增量计划测试证据附属静态审核

审核者：独立子任务 `/root/p2_incremental_design_review/c1_test_evidence`。
主审核者：`/root/p2_incremental_design_review`。本子任务未编写、修改或格式化候选源码和测试。
冻结前原件身份核对时间：2026-09-17 14:12:30 UTC。

**结论：在本附属静态范围内未发现新增实质问题；不是原生测试通过或阶段验收结论。**
`native_tests_run_by_this_reviewer=false`，`stage_accepted=false`。

- Stage base：`0927af157a3cc35abde14b036bc50a99a793a32b`，tree `e04479cf7723588885573be2112635efa30e27cc`。
- 首次完整读取的 C1：`99ec771c57207167f473d23ffd07b54f15a36abc`，tree `510693b0fd8ec085ab06de4140d6f7fd80f48c7e`，唯一父提交为 stage base。
- 本报告最终绑定 C2：`2020c7314a996769b33706754405c0976ce7c50a`，tree `a25d4752d49f366f9aff047116eeffd9b1f6ae1d`，唯一父提交为 C1。
- 上述提交、tree 和父关系由本子任务读取本地 Git 对象独立核对；本报告没有独立核对 GitHub PR synthetic merge 或实际工作流身份。

完整读取了冻结设计、AGENTS.md、阶段审核规则，以及四个测试文件的全部内容。C1→C2 的四文件、十处 diff hunk 也全部读取：`pool/active/incremental.rs`、`pool/active_flow_tests.rs`、`pool/recovery/active/incremental/tests.rs` 仅改变空白；CLI 测试改变空白并增加四个可选尾逗号，没有改变字符串、断言或调用顺序。去除空白与闭合括号前可选尾逗号后的机械比较四文件均一致；这只是支持手工逐处检查的补充，不是 Rust AST 等价证明。其余候选文件在 C1→C2 完全未变。

为确认测试到达的真实边界，另读取了两层 incremental 实现、ActiveArchive 的 open/verify/check_bytes、ActiveJournal 的创建/只读打开/文件共享/布局校验/显式偏移读取、namespace 绑定、pool replay/Record 编解码/实际状态执行、wire 编解码与 AuthorizationVerifier，以及 CLI 参数分派、JSON 渲染和安全 stdout 写入。没有修改仓库文件，没有运行编译、测试、格式化、Clippy 或 CI，没有创建提交或推送。环境中 `cargo`、`rustc`、`rustfmt` 均不可用；实际执行的 `git diff --check base C1` 和 `git diff --check base C2` 均退出 0，它们不替代 rustfmt。

主审核者在本任务进行中告知 C1 原生 rustfmt 失败，随后作者冻结 C2 格式修订。本子任务没有独立审核那份原生日志，不将该通知或 C2 的格式 diff 作为 C2 原生通过证据。C2 仍需主审核与实际原生回归。

## 测试合同核对

1. **物理范围与真实授权证据分开。** `pool/active/incremental/tests.rs` 的五项测试明确使用合成帧，只调用 ActiveJournal，不送入 State/PoolStore 验证。它们覆盖不同短读、Interrupted 重试、零读/超量读/权限错误/偏移溢出、空归档、旧尾段增长、原尾段不变而增加新段、跨 64 KiB 的旧字节比较、封存段最后一字节及旧尾段最后一字节、物理 EOF 和捕获长度。1 MiB 填满的合成例子用正常物理 append，但不能计为真实付款或授权成功。回调主动返回 Storage 的案例覆盖错误传播，未实际诱发分配器 OOM。

2. **公开 API 的分叉双方确实独立有效。** 归档 fixture 用同一 DOMAIN 和正常 prepare/commit 生成空块，修改合法 block_id 形成分叉。测试先分别 open、verify，再断言同高分叉、更高分叉和回退为 Stale。更高分叉额外确认长度增长与段数关系，并直接要求 retained-byte `visit_append_ranges` 返回 Stale，避免只以旧 hash 或锁失败冒充物理前缀拒绝。错误网络使用另一正常创世，两端先独立 verify，再要求 Genesis。错误 AppHash、布局摘要、旧 pin、旧平面日志分别有拒绝路径和原件字节检查。

3. **追加期望没有取自生产范围生成器。** 空块公开 API 用高度差 × 150 独立计算后缀与段数，拼接测试内的字节映射并要求与完整 later 映射相等。增长测试的辅助函数按实际文件边界指定范围，检查所有计数、长度总和、完全不变段数，重建后要求与 later 每个文件的字节相同，再把测试重建目录交给真正 ActiveArchive 完整验证。测试重建是测试代码行为，不表示产品已经提供增量写入或恢复接口。

4. **真实付款和 1 MiB 轮换由原有 funded 状态流承担。** `active_flow_tests.rs` 在原四项测试中向前两项增加检查，没有删去原断言；base→C1 为纯增加 138 行，C2 只再格式化一项新增断言。实际轮换流程通过正常 prepare/commit 写入 6,963 个空块，在第 6,964 块放入真实 A→B 付款；断言旧段还能容纳空块但不能容纳该付款，从而要求按原 1 MiB 容量轮换。新增计划检查旧段保持完整不变、仅新增第 1 段。经过真实 copy_new 备份和恢复后，B→C 付款在 10,001 高度提交；计划比较恢复前的已付款源与恢复后继续生长的目录。再次恢复后第 10,002 块为空块，也有尾部 150 字节范围核验。此流程不是 10,002 笔付款，不是缩小容量的轮换，也不是全容量资源实验。

5. **重算摘要后的坏签名不是普通 hash 拒绝。** 原状态流保留真实付款，改变绑定签名的末字节，重算记录 SHA-256 和整个 ZVARCP01 物理 pin，并要求 PoolStore/ActiveArchive 打开返回 Authorization。新增 and_then 两种角色链明确在 open 失败，因此 incremental_plan 的闭包不执行；源码注释准确说明这一点。CLI 真付款案例在真实备份和恢复后由首次扫描恢复历史的 Bob 产生第二笔付款；伪造只改变新增第二条记录的绑定签名，旧 base 前缀保持原字节，记录 checksum 和完整 pin 重新计算。有效控制先后成功，伪造打开要求 Authorization，真实 CLI 要求失败且所有文件保留伪造前后规定的字节。静态追踪表明签名编码用 `Signature::from` 保留这 64 字节，改动不触及长度、记录状态字段、证明、签名域或交易政策字段；随后真实 verifier 检查绑定签名。需要保留的证据边界是：测试断言记录 PoolError::Authorization，未增加 verifier 内部调用计数；不能把坏归档打开失败表述为 incremental_plan 方法已执行，也不能把坏签名失败表述为该坏实例完成了证明验证。

6. **每次调用重检与末次检查有独立触发。** 公开 API 先成功规划，再分别改变 base/later 的 namespace、同长度字节、截断或追加，要求下一次调用拒绝；同长度替换来自另一份先独立验证成功的合法历史。私有 cfg(test) fault 7–10 在双方 replay 和完整前缀比较后再改变任一端目录项或末字节，要求末次完整检查失败，并明确把测试施加的变化保留下来。测试不是声称目录在注入前后不变。全部生产成功路径由两次 open 加方法内两次 verify 构成四次完整 replay；已成功调用不能绕过下一次方法里的重新验证。

7. **Windows 共享与写入假设符合既有句柄契约。** 普通 fixture 的独占 PoolStore 在目录字节读取前已 drop。共享 archive 允许独立读取 genesis，segment 文件没有独占锁；Windows retain_name 保留 READ/WRITE sharing，故对 segment 的同长度覆盖、截断、追加可作为真实外部变化注入，不依赖已被禁止的 DELETE sharing。合作 writer 用 genesis 独占锁，测试确认任一共享 archive 未 drop 前仍 Locked，全部原路径读者 drop 后能重新打开 writer。Unix 专属测试覆盖 inode 替换、硬链接和缺失/软链接；Windows 专属测试要求两端 rename 返回 OS 错误 5 或 32，drop 后 rename 成功。Windows 不执行 Unix 专属身份案例。这里仅核对源码与平台分支，没有在本任务实际运行任一系统测试。

8. **真实 CLI 的 stdout、失败和字节保护有正反控制。** 子进程使用 Cargo 提供的真实 binary 路径。成功输出与独立 expected_json 的全部 ASCII 字节、字段顺序、范围顺序及唯一末尾换行完全相等；同路径、不同路径同内容和零高度空计划使用同一 schema。参数、重复/未知项、缺少 NO-FUNDS、相对路径、错误大小/大小写/非 hex/超长 pin、旧格式、错误 pin、分叉、回退、网络、两端物理损坏及缺失目录均通过真实进程拒绝，并检查通用错误不带临时根路径。正常调用前后比较整个 fixture 树的目录成员和每个文件字节。持有独占 writer 时特意不在锁内调用 tree_bytes；子进程拒绝后先 drop writer 再比较，避免 Windows 检查本身变成锁失败。stdout 追加与空计划各有可写文件正对照，逐字节读取 receipt 并检查整个目录树只出现规定变化；只读 File 在交给子进程前由 write_all 证实不能写，子进程须精确退出 1，sink 及所有账本字节不变，随后普通 pipe 输出再成功。重定向时 `Output.stdout` 为空本身不是写入证据，实际 sink 的字节不变才是此负例的关键；这些用例不覆盖任意 broken pipe、部分写出或下游持久交付。

## 定义数量和 cfg 范围

| 范围 | C2 定义数量 | 平台/feature |
|---|---:|---|
| 新增物理层 unit tests | 5 | Unix/Windows 默认及 funded library |
| 新增公开 API unit tests | 10 | 7 通用、2 `cfg(unix)`、1 `cfg(windows)` |
| 新增真实 CLI integration tests | 7 | 整文件 `cfg(feature = "local-funding-lab")` |
| 既有 active_flow tests | 4 | 父模块 `cfg(all(test, feature = "local-funding-lab"))`；本阶段新增接点位于前 2 项，没有新增 test 定义 |

新增 library 定义在 Ubuntu 为 14 项、Windows 为 13 项；另有 funded CLI 7 项，故全部新增测试的可编译定义预期为 Ubuntu 21 项、Windows 20 项。跨平台源代码有 22 个新增 test 定义。重复工作流、重复调用、注入模式和原四项 active_flow 不能再次计入“新增测试数量”。这些是源码定义计数，不是原生执行/通过数量；默认 feature 下本 CLI 文件贡献 0 项。

本范围没有实际触发 allocator 失败，没有 2,048 段满容量计划或全容量峰值实验，没有真实断电/磁盘满/并发恶意瞬时改回测试，没有 Windows 目录持久化保证，也没有外部安全审计结论。C2 原生格式、Clippy、所有默认及 funded cohort 和 Ubuntu/Windows 文件行为仍需实际结果证明。

## C2 原件身份

所有数据均从 `git show C2:path` 的原始字节计算，不使用已可能继续变化的工作树来绑定审核。

| 路径 | 字节 | SHA-256 | Git blob |
|---|---:|---|---|
| `docs/ACTIVE_INCREMENTAL_PLAN.zh-CN.md` | 8604 | `0234062797e5436cbccb307db50655b2b7a50f48046ccb91824e9dabc2e93193` | `e0d484dc7cc7a2423bd43e362584713ffd336ca7` |
| `integration/orchard/src/pool/active/incremental/tests.rs` | 8480 | `747600d6d14f3e4c758549c58516bcde07c1a403e4783202e3cf26ec34b0ecf3` | `e6e8f7e62aa22ef6206091e9d6fc1b1c7c6a8ff9` |
| `integration/orchard/src/pool/recovery/active/incremental/tests.rs` | 21240 | `4933c10a8b25c506ed9fed17ddf41e222f0a5e68d6f0b80a2390c83208f8acc1` | `33019d0c56f4f6b0dc309d95f639647bf830d852` |
| `integration/orchard/src/pool/active_flow_tests.rs` | 39770 | `a10e38aadf8bd44b2daa6aedb6287159f460929b67682a7aa498e2f29939b86a` | `7767f002c1e0945209ce6a3cc777f44c859dc5d8` |
| `integration/orchard/tests/active_incremental_cli.rs` | 26153 | `26725f2716eb7a53b65581b12117de25f649fc8b6fc3f05f633ad9dd90741ac0` | `4a9fcdcdc771cb94ba511aabe0d6ad59829745d6` |
| `integration/orchard/src/pool/active/incremental.rs` | 6689 | `3ab1d8ccd20005cb2d537a71dc3e8cc83dcb503e98979d333ca93daf68c44274` | `a04372074717df74074fed315ed5f68738edd092` |
| `integration/orchard/src/pool/recovery/active/incremental.rs` | 7162 | `052e6df1227f06cddff8f32e49daf0ed21e4fcabeafcd28d4f084f735a6b8870` | `46bc2fd5cd73cf647f485af4c647d2131aa9b2a2` |

本报告由子任务直接形成，父任务需完整阅读后将范围和限制纳入其最终审核。未收到或未核对 C2 原生结果，不能据本附属报告合入或声称阶段完成。
