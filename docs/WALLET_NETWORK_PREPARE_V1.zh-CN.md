# P4：认证网络同步直接驱动受约束付款准备

状态：本文件为接线设计检查点，尚未实现/验收。新分支dev/p4-network-payment-prepare基于PR43 698a0da6d68cf106494f5019b89f30dbbf5f04c6/tree760650dc804d14d7212d6ffce36fbef332a1c624；运行时将以正常多父提交整合PR42 8d177efab1df5c2f56a24ac5914ea5f5f3e2a6c3/tree2dbfb29867ce6fd01b3c111d608a0d80cddc9415。共同PR41基线c53517de28660f8d0889b765896ddd7e3cca5168。三个原候选不改，原生门槛分别保留；组合不是已验收，不合并或部署。

## 原需求缺口和唯一操作

原P4普通用户付款不能要求手工搬运参考检查点。PR42只把认证网络同步接到opcode11扫描，PR43 opcode12只约束调用者提供的检查点。新增既有控制台prepare-network，将本次原Go完整验证结果直接接到既有opcode12；不重写两个底层模块，不新建钱包或审计包装程序。本阶段明确不自动submit或广播，完整普通付款/确认状态机仍待后续接线。

输入沿用sync-network的独立config/genesis/三个可执行文件摘要、祖先wallet receipt、显式endpoint/proxy、wallet/journal、limit及create-reference；另要求create-only output，不能传入expected-height/hash或预先生成的网络回执。新增expiry-blocks为1..100的规范整数，默认20，在本次验证高度上求和生成到期高度，拒绝越过原profile高度上限。不采用节点费率建议。

## 不变的认证和准备链

复用PR42原配置身份与程序pin检查、实际zevune-network sync一次、固定票权签名/区块/真实账本重执行/下一签名头后置状态验证、严格本机结果解析。不以Python解析器、调用者hash或远端余额建立信任。可提取原公开检查/调用逻辑为私有共享函数，原sync-network行为与拒绝边界不放宽。网络进程不能取得wallet路径/receipt/口令/收款人/金额/输出路径。

prepare-network仅在caught_up_to_observed_tip=true时继续；部分追赶保持已认证参考前缀、拒绝签名前流程，不自动循环补齐。该条件不证明全网最新、时钟新鲜度、抗eclipse或最终性。确认界面说明只追至观测tip-1。

网络验证成功后显示固定身份与验证高度，通过原交互输入收款人/金额/费用，复用PR43确定性费用策略和原域/整数检查；用户输入PREPARE后才取隐藏口令。expiry不再要求用户查高度。公开检查/输出存在性/请求形状先于口令和钱包；前后复核原程序/配置/genesis身份，确认/口令期间新出现输出时拒绝。私有付款意图仍只经原wallet-local stdin，不进入网络命令、argv、env或日志。

不用opcode11先保存扫描，不回退opcode4，也不生成新的操作码。只执行一次原opcode12，它必须重新持锁完整重放并核对本次检查点后，才打开钱包、检查pending、临时重扫、真实证明并单次原persist。Go与Rust间无连续锁；参考文件被增长/回滚/换入另一状态时原检查点守卫拒绝。两个锁、fee/余额/容量/expiry检查及原create-only导出全由PR43保持。

成功严格检查原opcode12结果的确切height/hash、身份、txid、broadcast=false和同钱包receipt前进，再输出network和wallet分项。错误结果、导出/输出/最后身份复核失败都可能已有持久pending，不重试、不删除交易或钱包文件、不清预留、不重签、不广播。新增命令不能以本次hash一致显示confirmed。

## 资源、兼容及验收

保留原0..12、sync-network、prepare-at-checkpoint、Rust/Go生产代码、依赖、格式/容量/锁/同步写入及30m/15m/300s预算。共享网络进程沿用原终止/join和脱敏输出，不新建后台任务。onion v3与本机SOCKS认证隔离、禁止DNS/环境代理/直连/no-auth降级；不启动Tor。

本地Python覆盖原入口兼容、同一实际网络结果绑定到12、无caller-tip入口、部分追赶/假响应拒绝在secret之前、错域/fee/expiry/取消、private数据隔离、输出重叠与已存在、配置/program变化、失败至多一次调用无回退/删除。隔离UI调用测试不是原生证明。

双平台原生使用真实原Go/Rust程序、合成无价值genesis和四本机节点，新增真实控制台prepare-network路径；只替换交互输入，不替换签名/验证/存储。验证两profile真实付款准备、一条wallet记录、精确pending与导出字节相等；未广播及第二次prepare不能替换pending；错提供者/部分追赶/换入旧参考拒绝且wallet字节不变；节点重启后同pending不重签。原PR42同步/收款/重启/错误后置状态及PR43库/CLI故障测试不删除。无真实钱包资金、真实网络广播、付费设施或密钥上传。

依ARCHITECTURE先独立评审这一新增接线边界，不重复父模块设计。实现后再按完整新SHA独立代码复审及原生CI；文档/代码审查不替代测试。四真实机器、30天、实际Tor与专业外审以及完整P4/P5/P1—P8仍未完成。
