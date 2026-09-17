预审完成。当前草稿整体范围准确，**有两处应在正式验收报告中调整的证据表述**；本次未发现需要修改 C3 运行代码的问题。此结论仅是文档草稿预审，不能替代准确文档候选复审、原生 CI 或阶段接受。

已核对本地工作树干净，候选为 `9e46e03165250c6c51fa7031526d8de1bbdf27d6`，tree 为 `072da4de0b426e619c80b504dedf019a0808201b`。未修改任何文件。

1. **中等：状态表需要区分原始 JSON 数字、运行中断言和由选择策略推导的说明。**

   草稿第 33–43 行把 commitments、nullifiers、钱包记录和余额放在同一张表中，最后一列统称“最终候选实测核对”。这容易使最终填表后的读者以为所有数字都能从资源 JSON 独立取回。

   实际源码与历史原件的字段合同是：

   | 信息 | 实际证据 |
   |---|---|
   | 高度、已提交笔数、commitments、nullifiers、fees、账本逻辑字节、段数、尾段字节 | `events[].state` 等公开字段直接保存；最终状态还保存于 `result` |
   | 钱包记录数、钱包文件字节 | `events[].wallets[].records_used/file_bytes` 直接保存；最终值保存于 `result.wallet_records/wallet_bytes` |
   | A/B balance、available、pending 标记 | Rust `status()` 在运行中计算并断言，通过私有 IPC 返回，Go `walletStatus()` 再核对；**不保存为资源 JSON 数值字段** |
   | “第 33 笔预留整张 18000 note” | 与现有 largest-first 选择规则、固定交替付款及 Rust available 断言一致；**不是原始 JSON 中单独采集的 note 观测值** |
   | 当前 owned-note 数、真实花费输入数 | 本报告没有原始数值采集；actions/nullifiers 不能替代 |

   最小改法：将最后一列改成“原始字段核对及运行断言”，并在表下明确一句：

   > commitments、nullifiers、费用、钱包记录与文件字节可从原始 JSON 逐项核对。余额、可用额及 pending 状态由准确候选的 Rust／Go 运行断言验证，未作为数值字段保存于公开 JSON；18000 单位整张 note 的说明来自固定负载和现有选择策略，不作为独立 note 数量测量。

   `proposed-status-updates.json` 的 `/payment_resource_final_state_scope` 可以保留余额目标，但建议加上 `balances_asserted_in_native_Rust_Go_not_raw_JSON_numeric_fields` 或在对应说明中作同样限定，避免机器状态文件丢失这一证据区别。无需改代码、扩大 JSON 或增加钱包生产查询。

2. **低：第 108 行“启动目标60秒”应明确为 worker 启动。**

   当前源码的 worker 启动目标是 60 秒；场景 `scenario_start` 通过 `scenarioExchange(nil)` 等待 ready，适用 90 秒场景响应上限。泛称“启动目标60秒”可能被解释为场景启动也有独立 60 秒门槛。

   建议改为：

   > worker 启动60秒、worker 请求60秒、场景 ready／单响应90秒、资源 ACK15秒……

   `proposed-status-updates.json` 的超时字段已经明确写 `worker_start60s`，这一项无需改。

其余已核对项未发现草稿与源码、原始记录之间的矛盾：

- 草稿保留 C3 的准确 head/tree、直接父提交与 PR 合成提交区别，没有把 C1 或 C2 原生结果算作 C3 成功；现有 `PENDING` 是正确占位，不构成缺陷。
- C1 两份原始审核分别为 `CHANGES_REQUESTED` 与 `REQUEST_CHANGES`。C3 两路原文均为限定代码／证据合同范围的 PASS，原阻断关闭；草稿没有将其升格为原生资源验收或外部安全审计。
- 181 项操作／362 条进度以及 32 笔后的关闭、物理检查、worker 重开、钱包恢复、再准备第 33 笔、恢复 outbox 的完整顺序，与 Go 实际调用及 C3 校验一致。
- C1 Windows 原始日志确实为 `Ran 39 tests`、1 error、1 skip；错误来自不存在的 `os.killpg` 模拟属性。自进程、子进程实际 OS 采样测试当时通过，Linux proc 专属测试跳过。C3 仅修正该纯测试 fixture，未改变清理预算或增加 skip。
- 原始证据表中目前填有字节和 SHA-256 的 **11 个文件全部存在，字节数和摘要全部匹配**。C1 原始 JSON 没有被改写为 C3 结果。
- 两代 worker 和单一 scenario 身份分开统计，scenario 包含两钱包及独立账本／prover／缓存／历史／Argon2；未把它当成单钱包内存，也未把 OS 生命周期高水位说成阶段峰值或硬分配限制。
- 33 个真实付款块与此前 99998 空块加 2 个真实付款块的 100000 块增长验收分别保留；没有把本阶段扩展成 TPS、容量边界、冷磁盘、全新钱包进程、多机验收或 P2 整体完成。
- README、交付计划和状态文件的增量建议都保留旧阶段准确身份、旧证据与未完成范围。纯文档后续需核对运行源码、测试、依赖、工作流逐字节未变，这一继承要求写得正确。

正式复审应以最终文档候选的准确 base/head/tree 为对象，重新核对实测表、原件链接、全部最终 CI 计数和实际合入证据；本次不提前给文档候选或整个阶段 PASS。
