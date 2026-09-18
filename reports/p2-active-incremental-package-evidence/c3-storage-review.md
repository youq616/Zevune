# C3 持久增量包：独立存储与对抗代码复审

审核者：`/root/p2_package_storage_review`，2026-09-18 UTC。本任务未编写设计、生产代码、测试或C1/C2/C3修复；本报告是新的准确候选审核原件，原设计/C1/C2原件保留。

**结论：PASS_CODE，NATIVE_PENDING。** C3完整单行修复正确消除了已知Clippy报错的源码原因，没有削弱测试、改变资源释放或影响生产代码。准确C3尚需原生CI与独立原生结果审核；本报告没有给出PASS_NATIVE，也不能单独据此接受或合入阶段。

## 准确身份与完整变化

仓库：[youq616/Zevune，PR #17](https://github.com/youq616/Zevune/pull/17)。本人直接通过GitHub connector取得PR、C3 Git commit与synthetic commit，与本地固定Git对象交叉核对，未依赖作者给出的摘要。核对时PR open、merged=false，HEAD准确为C3且工作区clean。

| 身份 | commit | tree |
|---|---|---|
| stage base | `2cc87a2207d502ac5cfe00ea52e525c1516917e5` | `b5841120084a72c5948b0a2754f712e5f67ad602` |
| C2 | `f51c8db240933256870ff03c07bc68915b4ac4a1` | `7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400` |
| C3 | `cb0804e7c921a456cbbafab313b3a4a4501b8f5e` | `21de343c12bc27cb1022ffd7ebd451abe0e61f29` |
| PR synthetic | `3dfa8d77921693b9e99af5b94af198498b9422e9` | `21de343c12bc27cb1022ffd7ebd451abe0e61f29` |

C3的唯一parent为C2；synthetic的parents按序为`[stage base, C3]`，同tree得到独立确认。相对stage base仍12路径、7新增/5修改，完整最终文件共262465B。逐项重算12文件的SHA-256和Git blob SHA，并与本地冻结字节比较全部一致；完整tree比对确认其他881个mode/type/blob与base相同。

C2→C3全部变化仅为 `integration/orchard/src/pool/active/package/tests.rs` 删除一行 `        drop(reader);`（含换行22B）；0新增、1删除，无其它文件、mode、依赖或workflow变化，其他892个entries与C2相同。从C2完整blob仅删除这一个唯一匹配行即可逐字节重建C3完整blob。最终该测试文件22654B、630行，Git blob `ef24f03957081cdd2eb6ec73a2a0a85695331e1e`，SHA-256 `7bdcac72ffcb39dd8d7ca8393d1e77dd127fd381391d055a7e87d8a52f62d828`。全部12路径的准确mode/type/blob/hash及阅读方法见本报告scope JSON。

## 阅读、存储与测试判断

原始阅读依据是本人已完成的完整设计/C1审核及C2准确复审：AGENTS、STAGE_REVIEW、冻结设计、旧增量设计；ActiveJournal/ActiveArchive/两层incremental/namespace/Replay与真实Authorization调用；全部新包生产代码、physical/API测试、完整真实active flow、CLI入口/renderer/CLI测试。C1最终853行API测试在作者冻结后完整重读；C2完整7文件/30个formatter变化则由本人亲读的C1原生日志从C1字节独立重建并与C2逐字节核对。这是本人亲读范围的连续性，不能以另一审核者PASS替代；各原件记载的未读或未测边界仍适用。

本次另外完整阅读C2→C3 diff及其40行上下文、准确C3中整个 `transport_view_and_original_creation_handles_preserve_exact_physical_layouts` 测试、`JoinedJournal::reader`、`JoinedReader`完整字段/read_next/Read实现，以及相关拥有资源的类型字段和释放次序。该reader只含`&JoinedJournal`与偏移/状态标量，没有拥有File、目录锁或Drop；最后一次使用是完整读完后再次读取0字节的EOF断言。删除显式drop让借用在最后使用后自然结束，不释放或延后任何资源操作。

EOF和逐字节断言、逐帧物理检查、源/目标完整layout比较、实际恢复目标锁冲突以及包/目标create_new拒绝都保留。目标实际拥有者的`drop(restored)`、`drop(restored_genesis)`后重新打开及字节检查仍在；随后`drop(joined)`、`drop(package)`、重新打开包并比对全部编码bytes仍在。没有加入allow、删除断言、改变feature gate或绕过Windows名称/锁语义。

准确C3的其余11文件与C2完全相同；结合上述重新审核，严格实际旧尾offset、连续新段、完整layout与真实frame/canonical rollover、原始句柄/父目录身份/nlink/EOF、完整重放和新验证器、create_new故障保留等既有结论仍成立。真实付款恢复后继续花费、重算pin后Authorization拒绝、物理重算pin后非法分段拒绝的代码未变。未发现新的静态存储/对抗阻断。私有physical合成多段测试仍仅是transport覆盖，未提升为真实State证据。

## 原生状态与可复核原件

C1已知fmt失败、C2已知Clippy失败分别在原报告中保持。本人直接取得且完整读过C2 job105658335135：同tree synthetic、fmt完成、默认库171项（包括新physical7/API10）通过，包CLI为0项；随后strict Clippy在测试354行`drop(reader)`触发`drop_non_drop`、exit101。C3在源码层消除此原因，只能说明修复合理，不能把C2已通过的部分测试转记成C3已执行或预先证明新Clippy通过。

本次未读取任何C3原生job日志，本地没有cargo/rustc/rustfmt/go。base→C3及C2→C3的`git diff --check`通过只代表空白检查。完整Ubuntu/Windows默认与funded、strict Clippy、Go/race/fuzz、增长/付款资源/四节点原门禁仍需准确C3原生结果闭环；未执行真实磁盘满/断电、全容量或长期多机实验，Windows目录掉电持久化及新增包CLI资源峰值边界未被扩展。NO-FUNDS及production_storage_ready/audited/real_funds_allowed=false保持。

以下原件位于 `/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package/`：

- `c3-storage-review-scope.json`：12512B，SHA-256 `19f5009df5f59e7afb9443bee8339853c022533243ed599814b1ca6a8cd6f3c7`，含全部最终文件身份、实际阅读/未执行边界及引用原件hash。
- `c3-storage-exact-delta.diff`：3699B，SHA-256 `6f4d8ecc6a51ec41ccd52d630802b97bbc9b7cc1d8dbac7f56b618aba4652d6a`，完整准确单行diff与上下文。
- `c3-storage-pr-api.json`：4392B，SHA-256 `efa096b087dcd16bccbc958a03565c7377897f9df41aa113e7cea8443236acae`；connector structured PR对象明确格式化的JSON。
- `c3-storage-head-api.json`：1107B，SHA-256 `123351237ebeb00fac37094dfa4e287a3e3c260a442af73f2c40390fba5778dc`；`c3-storage-synthetic-api.json`：2569B，SHA-256 `f5be2bc990b98765ae74ad3bbf0eb183fac2d8f45b529f0ac2854d0ee1f6d7f4`。两者保留connector decoded content精确UTF-8字节，非原始HTTP字节。
- 亲读依据 `c2-storage-review.md`：17494B，SHA-256 `9f8921dae6ba7eca1bdbd2da0ab759c8c41cec895aa6074ce203926fdc5bb1b9`；`c1-storage-review.md`：19216B，SHA-256 `a4dcbdd4286f13cc929c35821b12ff016607de23984a23f69f77a6138771a106`；`design-storage-review.md`：14683B，SHA-256 `acb078f95d2d73dcac85060b382b698443d5690af5073f0f0005a5b7dbe00f26`。

本PASS_CODE只针对表中准确C3，未改写C2的BLOCKED_NATIVE_CLIPPY历史；原生通过或进一步变更须另有可追溯原件。
