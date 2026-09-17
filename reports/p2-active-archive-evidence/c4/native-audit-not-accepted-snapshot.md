# C4 原生 CI 冻结审核：NOT_ACCEPTED

准确 C4 首轮 10 个 PR workflows / 23 个逻辑 job 的原件已齐：18 success、5 cancelled；对应完整原始日志 23 份、1,322,058 B。完整日志表示保存到了原生 runner 清理末尾，不表示被取消任务的测试已经全部完成。C4 不满足整阶段验收，按根代理决定冻结为 NOT_ACCEPTED；后续重跑只保留历史观察，任何结果均不转移为 C5 的验收信用。

source `50ef0d9a5f7c7fdcf64118bd1e0f307457d37736`；tree `3c44977028b58ddd387f52946632af594208edfb`；base `6913d4ab2fda6956db37e0ceb49790a4518c2762`；PR13 synthetic `fb5ec39a59cb87aec0662c7706dce1f9e85e1962`。GitHub Git 对象验证 synthetic 双亲为 base、source，tree 与 source 相同；每份完整日志 checkout 均为该 synthetic。10 份 workflow 与 base 逐份同哈希，预算、依赖与矩阵均未修改。

## 首轮全矩阵

| run | workflow / job | 原始 job → 同执行日志别名 | 结论 | 完整原件 B |
|---|---|---|---|---:|
| 35204106289 | local-network-operator / operator (windows-latest) | 105145580393 | success | 95708 |
| 35204106289 | local-network-operator / operator (ubuntu-latest) | 105145580920 | success | 97642 |
| 35204106325 | funded-wallet-consensus / funded (windows-latest) | 105145581188 | success | 92447 |
| 35204106325 | funded-wallet-consensus / funded-library (windows-latest) | 105145581227 | cancelled | 47407 |
| 35204106325 | funded-wallet-consensus / funded-library (ubuntu-latest) | 105145581282 | success | 51715 |
| 35204106325 | funded-wallet-consensus / funded (ubuntu-latest) | 105145581497 | success | 90632 |
| 35204106263 | payment-resource-baseline / resources (windows-latest) | 105145580546 | success | 56168 |
| 35204106263 | payment-resource-baseline / resources (ubuntu-latest) | 105145580729 | success | 54922 |
| 35204106273 | orchard-bridge / boundary (windows-latest) | 105145580578 | success | 72484 |
| 35204106273 | orchard-bridge / boundary (ubuntu-latest) | 105145581152 | cancelled | 71552 |
| 35204106260 | wallet-laboratory / wallet (windows-latest) | 105145580574 | cancelled | 59588 |
| 35204106260 | wallet-laboratory / wallet (ubuntu-latest) | 105145580801 → 105156827116 | success | 60575 |
| 35204106310 | scaffold-tests / tests (ubuntu-latest) | 105145580839 | success | 21312 |
| 35204106310 | scaffold-tests / tests (windows-latest) | 105145581297 | success | 19225 |
| 35204106458 | orchard-cryptography-laboratory / tests (windows-latest) | 105145581342 | cancelled | 46528 |
| 35204106458 | orchard-cryptography-laboratory / tests (ubuntu-latest) | 105145581709 | success | 60609 |
| 35204106299 | orchard-consensus-integration / integrated (windows-latest) | 105145580979 | cancelled | 59816 |
| 35204106299 | orchard-consensus-integration / integrated (ubuntu-latest) | 105145581494 → 105160667067 | success | 76793 |
| 35204106416 | consensus-laboratory / integration (windows-latest) | 105145581373 | success | 43146 |
| 35204106416 | consensus-laboratory / integration (ubuntu-latest) | 105145581455 | success | 42437 |
| 35204106593 | active-ledger-growth / source | 105145581774 | success | 22948 |
| 35204106593 | active-ledger-growth / growth (ubuntu-latest) | 105151667262 | success | 38700 |
| 35204106593 | active-ledger-growth / growth (windows-latest) | 105151667332 | success | 39704 |

所有原件 SHA、原生起止、逐 step 结论及跳过步骤见配套 JSON 和各 job metadata。Ubuntu wallet 原 105145580801→105156827116、Ubuntu integrated 原105145581494→105160667067 是已成功执行被后续 attempt API 映射到新 ID；同时 crypto Ubuntu 和 bridge Windows 也有映射。四组新旧日志直接比较均逐字节相同，见 log-aliases.json；每组只保存一份完整原件，不加执行数。

## 五次取消的完成边界

- Windows wallet：25:05，预算25分钟；完整 default18结果/146 passed。Clippy 打印 Finished 后 step仍 cancelled，最终 drift skipped。测试没有被记为失败，整个 gate 也没有被记为通过。
- Windows crypto：25:12，预算25分钟；仅4完整结果/135 passed（lib132完成）；authorization_cache真实授权复用用例只有开始，没有 ok/result；Clippy/drift跳过。
- Ubuntu bridge：20:08，预算20分钟；完整 Rust18结果/153 passed、Clippy/build、Go regression/vet和真实互操作完成。race包输出 ok 1.326s 后 step11仍 cancelled，后续 fuzz/drift跳过。
- Windows integrated：25:13，预算25分钟；仅12完整结果/138 passed（lib132完成）；pool_network真实零值proof用例只有开始；Clippy/build、后续Go/drift未完成。
- Windows funded-library：30:12，预算30分钟；计划151项，126具名ok（含新增17及4个active_flow）；无完整lib结果、无cohort完成标记。full_journal_compacts_exact_real_outbox_and_continues_after_confirmation只有开始。未申请此任务的第五个C4重跑。

原生仅明确报告 operation canceled。时长接近 workflow 预算是观察，不足以证明取消根因；当前原件没有将这五次取消判定为代码断言、编译或 lint 失败的依据。check-run注解端点未被连接器支持，未据此虚构原因。

## 已完成测试的实际范围

独立 Rust 正式报告 native-rust-evidence-review.md/json 覆盖首轮12次Rust执行：7整个job成功、5取消。源码挂载与逐名称原生ok核对了新增库Ubuntu18/Windows17；双funded-interfaces各20完整结果/56 passed，CLI7均实际执行。default中的CLI目标为0，不能计7。Ubuntu funded-library完整158 passed；Windows库计划151不能用126具名ok补成完成。

stdout第七项走完checkpoint/verify/backup/restore四mode、只读File写失败探针、精确exit1、可写File正对照与完整备份恢复后的verify。它仍是一个测试；File.flush不是fsync，Windows NULL guard无专用fixture。实际付款用例内包含2次真实payment proof构建；两已有物理段交换后的原pin和repin均Corrupt、字节不变的44行回归已按原生通过的真实增长测试映射；坏签名重算checksum/pin后的Authorization拒绝是另一条独立路径。

非Rust独立审核读取了11个完整非Rust jobs与4个混合job中的Go/Python范围，共15个成功范围，另保留2个取消范围。完整逐项原始审核备忘录的有效内容保存在配套JSON中；已有 nonrust-native-partial-review.md/json 保持原有4job正式范围，没有被冒充为15job的新正式子审结论。

两个资源原始ZIP和解压JSON已按API大小/digest及日志上传SHA验证；各9 checkpoints、18 OS采样、362进度、181完成操作计时、14末态检查均成功。每进程预算1GiB，Linux worker/scenario峰值11,558,912/180,563,968 B；Windows13,033,472/119,226,368 B。注册子进程正常清理不等于完整进程沙箱；fixture为32+1付款公开场景，不代表生产或满容量。

双平台增长实际提交100000块，99998空块+2真实付款，15物理段、15,018,544逻辑字节；第二笔真实付款在10001，100000后完整重开再续100001是空块。funded interfaces的B→C付款在一个validator离线时、全网重启之前；operator另有真实重启后续付，不能混用两个场景的顺序。Go -run '^$'目标只计编译，普通fuzz种子harness与限时fuzz campaign分开计。

## 晚到重跑与原件完整性

冻结初始观察10:18:10 UTC另存 retry-observation-at-freeze.json。后续10:26:08观察中，wallet retry105156825897已success（09:53:00–10:17:52），bridge retry105160660583已success（10:06:04–10:25:13）；其完整日志分别59,932 B和75,567 B。crypto105159915319与integrated105160666174仍返回in_progress，后续状态另存附录。以上不改首轮18/5或C4 NOT_ACCEPTED。当前25份不同实际执行的完整日志共1,457,557 B。

Windows integrated原件一度出现本地45002B前缀副本，原因未确认。完整59816B原件经原始tool内容及另一独立重取核对恢复；local-copy-incident.json记载全过程，local-incomplete前缀明确为按原始内容重建的诊断文件，不冒充当时改名保留的物理文件。该事件不增加CI运行或取消次数。正式日志逐份与既有原始完整内容核对或原子发布记录的长度/SHA重新核验；大原件先写.part、验证后原子发布。

早期API queued观察不推导实际执行未开始；以原生job与日志时间对齐。冻结设计EOF空行诊断仍单独保留，不声称全部源码/文档无任何whitespace诊断。审计者未修改运行代码、测试、workflow，未触发或重跑CI，未在本地执行Rust/Go测试。
