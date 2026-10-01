# P4：检查点约束的签名前准备

状态：设计检查点，未实现/验收。独立分支 dev/p4-checkpoint-payment-prepare，明确堆叠于 PR41 28d53da9c225a74da98eff4b88dfd2438ac82fab/tree ab68b01f46b0d9101306c192dd1a59f996dbd892。不依赖 PR42 的运行时候选，不改 PR40/41/42。禁止合并、部署及真实资金。

## 原需求与这一阶段的缺口

原 P4 要求签名前拒绝错误网络/费用/状态且不让普通用户手工搬运交易。PR41只将独立检查点绑定到扫描；PR42将原网络完整验证接到这个扫描。现有 opcode4 prepare 则另开参考账本、先保存扫描再准备，没有将本次签名绑定到调用者刚验证的精确参考状态。本阶段将这个真正的签名前运行时入口补齐，不是另外造验证报告或桌面模块；统一在线签名→提交编排仍须后续接线。

检查点仍必须由原 Go 验证者票权/签名头/完整重执行链独立获得。高度/hash相等不是认证、最新性或最终性证明。本接口不得接收远端余额、备用验证器或改变原 Orchard 规则。可信本机、独立程序/创世pin和独立钱包祖先receipt仍是前提。

## 唯一操作及锁所有权

原 ZVWCLI01 私有帧新增 opcode12，原0..11保持。必须有合法钱包receipt，精确11字段：wallet/journal/genesis/genesis_sha256/recipient/amount/fee/expiry/output/expected_height/expected_app_hash。形状、数量、16KiB总帧、字段4KiB、数字/地址/域规则保持；缺失receipt、零hash及未知/尾随字段拒绝。

处理顺序：公开语法、输出create-only前提、固定完整创世、收款域/金额费用边界检查 → 复用PR41 open_checked取得持锁的真实PoolStore并完整重放/精确状态匹配 → 从同一句柄取WalletHistory → 打开原WalletStore并持其排他锁 → 临时重扫与付款预检查 → 原真实WalletProver构造证明/签名并本地验证 → 单次原加密journal持久化checkpoint+预留+完整签名outbox → 原create-only交易导出 → 固定成功回执。两个锁保持至准备和导出返回；不跨进程假装连续锁，池只读不提交。

输出已存在、错误检查点、错误域、无效意图在钱包更新之前拒绝。网络失败和参考文件变化由前级/检查点处理；本阶段不联网、不广播、不自动重试、不清预留。输出失败可能已经有加密pending及部分新输出，保留它们，不删除/重新签名；未知持久化结果沿用原 fail-closed unhealthy 状态，不能返回交易。

## 原钱包内部的原子准备

在原 WalletStore 中新增只用于显式付款的新方法，使用现有 zeroizing snapshot/restore 模式把重扫和 build_payment 放在临时钱包上；不复用扫描后自报余额，不构造接受型历史。原持久钱包如果已有pending/outbox，直接 Pending，必须先由独立同步对账，不能在一次新prepare中顺便清旧pending再签另一笔。

检查现有room/validate_storage → 取得临时钱包、真实history.sync → 新路径确定性费用上限与原check_payment_to（地址域/金额/expiry/余额/容量/花费限制） → 仅成功后构造原WalletProver → 在同一共享Rust准备方法内再次核对费用上限、临时wallet.build_payment重新检查并验证真实证明 → 提交前再次费用/room/validate_storage → 发布临时wallet和签名outbox并调用原persist一次。没有可复用的preflight令牌。任何历史/策略/证明拒绝在发布之前保持磁盘、receipt和pending；持久化I/O故障仍可能部分写入且标不可用，不声称跨文件事务。

新路径固定费用策略：`1 <= fee <= min(100, max(1, amount / 100))`，除法为无符号整数向下取整。即通常最多金额1%，不足100测试单位时允许最小1单位；绝对上限100测试单位。amount=1/fee=99999、amount=100/fee=2、amount=200/fee=3及任何fee>100拒绝，amount=1/fee=1、amount=200/fee=2允许进入其余原检查。此为无价值实验中减少误填的保守本地钱包策略，不是市场费率估计、共识规则或主网经济参数；不读取节点建议费，不提供高费绕过开关。Python提前提示/拒绝，Rust公开能力层再次检查（不能只依赖UI），最终build前和persist前重复同一确定性检查。旧opcode4/底层原API与历史交易验证不改，也不宣称旧入口已具备该新保护。未来统一在线付款必须使用本检查路径。

不改 journal格式、最大256条、原sync、prepare_payment_to、backup或opcode4的兼容行为；新路径将扫描与新付款保存为一个原格式快照，因此最多消耗一条，但不是扩容或迁移。原锁/同步写入及每次构造真实proof保持。调用者必须持锁提供已经完整验证的WalletHistory；该库方法自身不认证共识来源。

## 命令与验收

既有Python控制台新增prepare-at-checkpoint，复用原程序pin、隐藏口令、交互式收款地址/金额/费用/expiry及显式PREPARE确认。checkpoint/receipt/创世和已存在输出等公开错误先于口令/后端；返回严格检查确切height/hash、txid/receipt、域和checkpoint_matched，仍明确not_broadcast，不回退opcode4或11。

实际Rust回归必须包括两storage profile真实付款/原验证器接受、同一池锁保持、准确/旧/错检查点、既有pending原字节不变、域/过期/不足金额及异常fee拒绝且无prover初始化/无wallet变化、费用阈值逐边界、满容量拒绝、持久化故障不泄露签名交易与已有故障恢复回归。实际wallet-local子进程以opcode12验证形状、精确状态、create-only导出及重开pending，原0..11回归保留。Python新增解析/参数/响应/费用/无重试与旧操作兼容测试；仅UI/拒绝测试可隔离，不用接受型假后端代替证明。

独立初稿审查4145307847指出原check_payment_to没有异常费用策略；本修订明确补齐范围，不能把原正整数/余额检查称为高费保护。需对此新设计SHA复审，随后新实现另需准确SHA非作者复审和现有双平台Rust原生CI。原30m/15m、请求300秒和所有存储/证明预算不提高。本地没有Cargo时不声称Rust执行通过。P4完整在线付款、P5、四真实机器、30天和专业外审仍未完成。
