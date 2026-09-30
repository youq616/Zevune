# P4：直接提交同一笔已保存付款

设计检查点，尚未实现或验收。基线PR45 `e7911b9368d742a04aa64f58ba2c80706b422f11` / tree `979e72b11847d06bf55fc55f7ca8e7599459fb1a`，保留PR43/44固定格式修复；PR41 `4eca2a5d0b208266cf7bdd2e4181d9a3e9b970c1`端口候选未自动成为本祖先，各自原生门槛独立。现有分支中未发现同一提交接线模块；仅在dev/p4-pending-network-submit推进，不覆盖已冻结父候选。

## 真实缺口和调用链

原P4普通用户仍需把已准备/恢复的交易文件交给另一个网络命令。本阶段在原控制台添加显式 `submit-pending-network`，无需caller交易路径、height或AppHash。只提交已保存的一笔pending，不创建/签发新交易，不变更钱包或清预留，也不自动确认。本模块不是完整普通付款状态机或P4结项。

1. 复用 `_verified_network_reference` 实际原Go sync、独立配置/创世/程序固定、票权签名、全账本重执行及后置状态校验。本次必须caught-up；部分追赶/伪节点/配置或程序变化在秘密之前拒绝，不导入caller回执。
2. 本次请求仅使用私有随机临时目录中固定新文件名，经原输出树检查保证不落在钱包/账本/配置输入内。只记录原已签公开交易字节，无口令/密钥落盘。Unix目录限制权限；Windows依赖可信父目录ACL和可信本机，不声称防同账户恶意进程。输出不是掉电持久记录；异常进程退出可能留下临时导出，不影响原加密outbox。临时文件的尽力清理不能重签、清wallet或改变提交结果语义。
3. 明示网络身份及“只提交已有付款、mempool不是确认”，用户输入SUBMIT后才获取隐藏口令。原opcode13持锁完整重放并匹配本次checkpoint、只读恢复原pending。确认该次返回的identity/checkpoint/receipt/txid/broadcast:false，并有界读取导出、要求实际SHA256等于该txid。没有调用4/5/11/12。
4. 原Go `submit` 增加可选 `--tx-sha256`。只在submit允许该flag；显式空值或非规范摘要拒绝，原无flag调用不变。对真实transactionFile读取后的同一raw在任何worker启动、RPC或广播前核对摘要；不根据输入选择验证器，也不把摘要当授权。控制台新路径必需传该摘要及原 `--expected-height/--expected-app-hash`。Go仍先同锁匹配本地起点，再重新同步、原真实Check、一次BroadcastTxSync。恢复到提交之间没有连续锁；参考变化由原精确起点拒绝，交易内容变换由新摘要拒绝，最新许可仍由原Check决定。

## 结果、重复执行及失败

每次显式命令最多一次恢复调用和一次Go提交调用。保留原300s子进程上限及回收；没有异常自动重试、再签、重新恢复或直连降级。新界面只有精确校验过的 `accepted_to_mempool_not_confirmed` 才报告接受，返回confirmed:false、wallet_unchanged:true、retry_authorized:false。Go输出必须txid匹配、base_checkpoint_matched:true、reference_height不低于已验证起点且不越原profile高度上限。

一旦开始Go提交调用，非零退出、断链、超时、stdout/stderr异常、身份变化或输出发布失败都保守报告“结果未知，保留pending并独立对账”，不解释为未发送、全局拒绝、可再付款或确认。mempool拒绝也不能证明全网未纳入。本阶段不增加跨重启持久提交标志；新的人工SUBMIT仍可能再次发送同一字节，因此不宣称跨进程exactly-once、自动撤销或自动重试授权。共识原重复花费规则不变。后续确认必须从认证链/精确交易证据取得，不能把pending消失单独当付款确认。

公开网络命令不接收wallet路径/祖先receipt/口令/私密付款意图，只接公开参考、route和本次临时签名字节路径及其摘要。原onion v3/强认证SOCKS/no DNS/no环境代理/no直连回退、Orchard/CometBFT、旧opcode、格式、锁、容量和费用规则不变。新flag只增加内容绑定，不改Go Submit状态语义。

## 必须取得的验收

Python真实拒绝/超时子进程及隔离UI测试：部分/伪节点前拒绝、参数重复/外加caller payload/checkpoint拒绝、确认取消、错误恢复回执/内容hash拒绝、仅13一次、仅submit一次、原route/pins及起点/交易摘要准确传递、结果类型/false确认/txid/高度拒绝、所有错误不重试。UI成功隔离不是密码学证据。

Go测试使用真实临时文件验证规范hash、空flag、内容变化、symlink/oversize原限制及同raw绑定；原submit无flag兼容，错hash前于worker/RPC。两平台原生必须用真实钱包/worker/Go命令与四个本机无价值验证者，双profile验证准备→恢复→提交同一字节、钱包完整bytes/receipt/pending不变、一次mempool接受绝非confirmed。上游真实收到广播后取消响应的未知场景计数一次；无自动再次调用、原outbox保留。重启后原认证sync/原付款及错误后置状态回归仍执行，保留此前prepare/recovery零广播用例；不修改原30m/15m/300s预算或skip Windows。

设计先独立非作者审查，代码另按完整新SHA复审和准确双平台CI。所有试验仅临时合成无价值网络；禁止真实资金、真实钱包/验证者私钥上传、合并/ready/部署。源码、Linux tmpfs ENOSPC或代理审查均不替代真实四机器、30天、物理掉电与专业外审。