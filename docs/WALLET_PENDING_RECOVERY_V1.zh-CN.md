# P4：认证参考状态下恢复同一笔已保存付款

状态：新恢复边界设计检查点，尚未实现或验收。基线PR44 `202db3436baca4a7d2d8a0a2b90973134d116c91` / tree `684da4052a5e8e0aab58e5d45f3a99fdb30e15b9`，继承PR43 `698a0`、共同PR41 `c53517`及PR42旧祖先`8d177`；基线已有PR42新`de9766dc4da50f838549ec74e784f00944cc3755`的完全相同expiry修复blob，不为冗余祖先制造空提交。所有父候选原生门槛仍保留；本分支不改父分支，不合并/ready/部署。

## 已有能力与确切缺口

原opcode5可以从本地历史sync后导出pending，但会更新钱包，并且没有将该次网络验证状态和持锁导出绑定。原opcode12保存成功、输出失败或退出后，需要恢复同一笔签名字节；不能让用户重签，也不能先调用11/5清除或更新原pending后才发现参考不匹配。此模块提供不改变钱包的准确状态约束恢复，不另造签名器、备份格式或诊断产品。

新增WalletStore私有子模块中的 `pending_payment_from_history`：持原排他锁，validate_storage；检查已有pending和outbox以及原decode的签名域；由zeroizing snapshot/restore构造临时钱包，原Wallet::sync验证真实history并要求原pending_id仍然保留。若已过期、已消费、历史回退、错误域、缺outbox或不可用实例，拒绝且不清除/发布临时状态。返回原已认证outbox精确bytes与txid。不得调用room/persist、WalletProver或build，满256记录仍能恢复；成功及拒绝均不更新扫描缓存、receipt、钱包文件、预留或pool。已不再pending的处理应另行显式对账，不凭本恢复失败声称已确认。

原wallet-local新增opcode13（0..12不变），精确7字段：wallet/journal/genesis/genesis_sha256/output/expected_height/expected_app_hash，独立祖先wallet receipt必须合法非零。先公开语法及create-only输出检查，再原固定genesis、PR41 open_checked同锁完整pool重放/精确状态；pool→wallet打开、只读恢复、原create-only export。两个Store持有到导出结束。输出竞争或写入失败可以留下新目标，钱包和原outbox仍不变，不删除/重签/重试。

成功响应固定 `checkpoint_pending_exported_not_broadcast`，包括身份、height/app_hash、txid、原当前receipt、checkpoint_matched:true、wallet_unchanged:true、broadcast:false，不含余额/付款明文/confirmed。receipt可等于输入或晚于合法祖先，不能换钱包或同代不同digest。恢复字节不等于当前网络愿意接受，未知广播状态未改变。

## 普通用户入口

既有Python控制台增加 `pending-at-checkpoint` 和 `recover-pending-network`。前者仅约束调用者独立取得的checkpoint，不将hash当认证；后者严格复用PR44 `_verified_network_reference` 本次真实Go sync→票权签名/完整重执行→精确tip-1，只在caught_up_to_observed_tip时继续。拒绝caller expected-tip输入、部分追赶、伪节点、错误identity、非法输出路径，不循环同步。

输出路径安全策略复用原 `_prepare_network_output`；公开pin/路径/config/genesis/程序校验在秘密前，RECOVER显式确认后隐藏输入密码；只调用13一次，不调用11/12/5/4，不广播。网络子进程没有wallet路径/receipt/密码/输出路径。交接时参考增长或替换仍由Rust原open_checked拒绝，程序及公开输入前后复核。无跨进程连续锁承诺、无全网最新/finality声明。原300s、30m/15m、格式/锁/容量/费用不改。

## 必须取得的验收

库/命令真实双profile测试：从原真实付款保存后重开（balance仍NotSynced），恢复精确同bytes/txid，旧/错域/已消费/已过期/无pending/缺outbox拒绝；恢复前后receipt/pending/NotSynced与完整wallet/pool文件不变，所有第二句柄字节读取先drop相应Store。满记录恢复不增加记录；实际export竞争/写入错误保留两个原Store及outbox，不提供接受型假后端。

真实钱包二进制opcode13用例证明框架/输出/恢复精确bytes，零新签名路径；原动态funded-wallet调度发现新target，不替换旧付款或故障回归。既有网络prepare原生场景补充：真实准备后进程退出，新的认证sync→13恢复同pending到新文件；原准备文件/钱包receipt和完整字节均不变，第二次恢复显式执行也不重签，RPC代理计数零广播，重启后仍同bytes。测试只有临时无价值身份和本机进程，不上传私钥或真实钱包。

Python隔离UI/解析与失败进程回归不能替代上述Rust/Go原生。准确实现SHA独立非作者复审及Linux/Windows必要CI另外取得；父候选审查不外推。P4在线广播/确认完整状态机、P5及原P1—P8仍未完成；真实Tor/四真实机器/30天/专业外审不由此代替。
