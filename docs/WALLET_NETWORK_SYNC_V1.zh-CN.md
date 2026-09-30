# P4：已认证网络同步到钱包的直接接线

状态：运行时实现候选，未验收。明确堆叠于 PR41 `1582306f1466ef8a6141bbb032784efb4d81232b` / tree `a35a50830b5187230b6e62158da57a2a775498b6`；PR41 自身原生 CI 尚待取得。main `0e5fd16abfebec3cc5a3db6bb99d1e4e7335c2f6` 不变。不改 PR40/PR41 分支，不合并、不部署，不接受真实资金。

## 唯一闭环

在已有 `scripts/zevune_wallet.py` 增加显式 `sync-network` 命令：独立固定网络配置/创世及网络程序/worker/钱包程序摘要 → 实际原 `zevune-network sync` → 原固定验证者票权及签名头、区块连接、全部交易真实重执行、下一签名头 AppHash 对比、原同步提交 → 严格读取该次本机进程结果 → PR41 原 opcode11 精确高度/AppHash 重扫 → 已有加密钱包同步保存。

不增加第二种网络验证器或任意远端余额API。`sync-network` 没有接收“已认证tip/hash/JSON回执”的输入入口；钱包期望状态仅来自本次实际调用已固定网络程序的成功结果。配置文件的独立摘要认证验证者集合；Python 对配置中 asset_genesis_sha256 与钱包独立创世pin的匹配只是跨后端身份预检查，完整配置与签名/授权仍由原 Go/Rust 实现验证。子进程来源摘要不是代码签名；可信本机、程序和独立pin仍为前提。

本阶段只接通同步/收款状态更新，不准备/导出/签名/广播付款，不自动重试任何步骤。原 prepare、pending、submit 与持久格式/锁/容量/超时不变；完整在线付款仍未交付。只支持已有 LAB2 的02/03网络，不把旧LAB1无域付款当作新增私密网络。

## 参数、所有权与失败

必须显式提供 --no-real-funds、钱包路径及独立祖先receipt、参考账本路径、钱包创世与其pin、网络config与其pin、网络可执行文件及pin、原worker及pin、钱包后端及pin、endpoint。参考账本首次创建需要单独 --create-reference；已有目标不覆写。同步limit默认128且只能1..128，不通过循环规避单次界限；部分追赶明确显示未追上观测tip。

endpoint/SOCKS策略完全复用原网络命令：未指定proxy只能规范数字回环；显式proxy只能本机数字127.0.0.1与规范onion v3、强制认证隔离；显式空proxy失败，禁止DNS/环境代理/直连/no-auth降级。私密通道不可用则整个操作失败，钱包不解锁。此阶段不启动Tor或创建onion服务。

所有公开语法、独立pin及程序/配置身份检查先于网络调用和私密输入。网络过程不获得钱包路径、receipt、口令或私密见证。只有网络成功且输出字段/类型/界限均匹配后，才通过原隐藏输入获取密码，构造原opcode11私有stdin帧。检查网络结果中固定scope、原height/root/app_hash/new_blocks/observed_signed_tip/caught_up_to_observed_tip/base_checkpoint_matched/real_funds_allowed，拒绝重复键、非整数/布尔混淆和多余字段；不能用原status或未约束重扫作降级。

Go同步返回后原worker已关闭，钱包重新取得原PoolStore锁并完整重放。其间参考文件被更换、回滚或增长时，PR41的准确状态检查在钱包打开/解锁前拒绝；同一真实池锁保持到钱包保存完成。这不是跨Go/Rust进程的连续锁或跨文件原子事务。配置/创世及后端普通替换在前后复查；不声称抵御恶意内核、同权并发内存修改或SHA碰撞。

网络执行仍是原5分钟预算，不重试；新父端不转发子进程stderr，也不执行shell。公共网络stdout可用独占临时文件接收，成功后仅有界读取4KiB并严格解码；临时内容不含钱包秘密，不发布回执文件。该读取界限不是文件系统配额，受信任原网络程序固定只输出有界SyncResult/固定失败。异常/取消/超时必须终止并等待直接子进程，无后台管道读写任务。钱包调用保留原300秒预算与stdin-only秘密传输，错误不打印请求/密码/路径/节点消息。

网络后期失败可能保留此前已认证的参考账本前缀，不能回滚已同步数据；钱包尚未调用时保持原字节。钱包调用失败/确认丢失可能已持久化更新，不重试、删除、重签或清预留；仍按原独立祖先receipt对账。再次调用网络同步必须重新取得签名证据，不能复用旧进程回执授权。

## 验收边界

纯解析/参数测试覆盖独立pin、网络/钱包创世不同、缺失/重复/多余字段、假成功/假caught-up、边界、原操作兼容、失败不得进入私密输入或钱包。真实子进程失败测试只使用拒绝/超时程序，不提供接受型生产后端。

新增双平台原生闭环使用真实原网络命令和真实Rust钱包/worker、临时无价值创世与四本机节点，覆盖网络同步→准确重扫、真实付款后的收款余额和pending对账、退出重开再次同步，以及恶意/错误节点响应导致钱包不变。测试可替换交互式密码输入，不能替换签名验证、PoolStore或WalletStore。原私密SOCKS夹具、错误后置状态与原付款/重启回归保留各自工作流；必要的新原生步骤不提高既有30m/15m预算，也不替代旧回归。

设计复审只覆盖设计；实现另需准确SHA的独立非作者复审及实际原生CI。四本机节点/协议代理夹具不是四真实机器或Tor证据；不承诺全网最新状态、eclipse/长程攻击防护、动态验证者、流量隐私或最终项目验收。PROJECT_COMPLETION中完整P4/P5以及四真实机器/30天/专业外审门槛不改。

## 实现候选及可执行验收

设计候选 `495c4efee09dd022297e329351f55dffec1a177a` 的独立审查 `4144528327` 指出严格字段集合使用了错误的简写。`b55594dbd13106cdfa026e828b566e1dc3a05c34` 只将其改为原 `caught_up_to_observed_tip` 并请求新设计复审；独立非作者评论 `5911461086` 对该修订设计明确返回未发现重大问题。该回复只覆盖设计，不批准本运行时。实现及测试使用原完整字段名，并明确拒绝 `caught_up` 别名；不修改上游输出或放宽缺失/多余字段检查。准确设计与代码复审结果分别绑定 PR42 对应提交，不以本文件宣称未取得的审批。

新增逻辑留在原 Python 控制台，使用标准库，不扩展已有离线工具包的依赖或原生操作编号。使用参数形状如下，大写占位项来自可信本机及独立来源，密码仍在网络验证成功后隐藏输入；这不是直接可执行的示例部署：

```text
python scripts/zevune_wallet.py --no-real-funds --backend WALLET_BINARY --backend-sha256 WALLET_BINARY_PIN --pin WALLET_ANCESTOR_RECEIPT sync-network WALLET_PATH --journal REFERENCE_PATH --genesis PUBLIC_GENESIS --genesis-sha256 GENESIS_PIN --config PUBLIC_NETWORK_CONFIG --config-sha256 CONFIG_PIN --network-backend NETWORK_BINARY --network-backend-sha256 NETWORK_BINARY_PIN --worker POOL_WORKER --worker-sha256 WORKER_PIN --endpoint EXPLICIT_ENDPOINT --limit 128
```

首次参考账本额外使用 `--create-reference`；onion endpoint 必须同时显式给出 `--socks-proxy 127.0.0.1:PORT`，不可省略或传空。所有路径要求绝对路径；固定配置、创世和程序不得通过符号链接/重解析点别名输入。成功结果分别嵌套该次网络重执行结果和原 checkpoint 钱包结果，明确 `broadcast:false`、`latest_verified:false`、`retry_authorized:false`、`real_funds_allowed:false`。部分追赶可更新已认证前缀的钱包，但不得显示已同步全网最新。

`TestRealWalletNetworkSynchronization` 额外要求 `operator_e2e && wallet_network_e2e`，避免自动挤入原接近时间预算的 operator 全量用例。新 `wallet-network-sync` 双平台任务保留30分钟job/15分钟测试上限，并追加执行原错误后置状态拒绝测试；原operator和funded回归没有删改。新增测试逐个新建02/03部署，Python测试进程内保存随机测试口令；Go只交换公开配置、阶段和交易。初始limit1的真实部分追赶、真实7单位付款、广播前原pending字节一致、收款余额、全节点重启、无签名恶意provider和锁交接期间旧参考账本替换均有断言。该测试只替换隐藏密码UI，不替换任何网络或钱包验证器。

03 fixture由真实钱包命令产生的公开有效note分配创建全新manifest，新的profile在任何网络/参考账本创建之前选择；旧seed journal和donor钱包只留在测试目录而不参与新网络运行。公开账本替换和恢复只发生在临时故障测试，绝不是产品回滚入口。测试脚本不上传钱包或私钥，也不转发任意异常文本。

当前本地仅有Python编译/单元及真实拒绝/超时子进程证据，Go新测试只做gofmt语法检查；无完整Go1.27.1/原生Rust或Windows本地执行。新增原生用例和工作流存在不代表运行通过。完整源码、必要CI、复审、父PR41门槛分别记录；项目整体仍未验收。
