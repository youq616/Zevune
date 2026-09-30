# P5 第二阶段：受限 RPC 服务网关

状态：设计检查点，尚未实现或验收。基线 main `0e5fd16abfebec3cc5a3db6bb99d1e4e7335c2f6` / tree `36034da259fb7e28b8783097a6e4bdf48f57d6f0`，已有 PR39 onion/SOCKS 客户端保持不变。使用已存在且与该基线相同的 `dev/p5-rpc-gateway`，同一 PR 先独立设计评审，后运行时和准确提交代码复审。本模块不是离线报告、桌面界面或完整 P5 交付。

## 目的及授权边界

为未来可信本机 Tor 服务映射提供最小 RPC 服务面，避免直接转发 CometBFT 的全部 RPC。只新增本机数字回环监听的运行时网关及实际命令行，不启动 Tor、不创建/发布 onion 服务、不修改 init/run，不接触钱包、验证者或 onion 私钥。公开部署、付费资源和真实资金仍禁止。主机及本机代理必须可信；网关不能阻止同机恶意进程访问原 RPC，也不能认证某连接来自 Tor。

客户端 -> 显式 onion/SOCKS -> 本机网关 -> 固定数字回环 CometBFT RPC。实验只使用真实回环 SOCKS 夹具；不能当作实际 Tor 电路、时序隐私或四真实机器的证据。客户端的独立创世/配置固定、法定票权签名、完整真实重执行和下一签名头状态匹配仍是可信性依据，网关不能用余额、进程健康或自报 hash 替代它们。

## 固定接口

网关命令独立于节点及钱包命令。必须显式提供无真实资金确认、已有公共网络配置及其独立 SHA256、监听地址、上游回环 RPC 地址及预期 onion endpoint。所有配置先校验，后监听；上游不能等于监听地址。监听和上游均只能是规范 `127.0.0.1:<1024..65535>`，上游 URL 使用现有 ValidateEndpoint。预期 onion endpoint 使用 PR39 原解析/checksum/version 规则，HTTP Host 必须精确匹配其 authority。不会通过 URL、请求头、DNS、环境代理、重定向或上游回执选择目的地。Host 是路由限制，不是客户端身份认证。

只允许 HTTP/1.x 的 `POST /` 和 `Content-Type: application/json`，拒绝绝对形式 URI、路径/query 变体、压缩请求、Upgrade/WebSocket、Origin、Cookie 和 Authorization。其它头不转发。响应只构造所需内容类型、长度和固定错误，不透传上游头或错误文本；不设访问日志。连接可能暴露 HTTP 协议本身的时间和长度，不声称消除流量关联。

请求为单个 JSON-RPC 2.0 对象，精确四字段 jsonrpc/id/method/params，递归在本接口对象层拒绝重复/未知字段；不接受批量、通知或 null id。id 是 0..9007199254740991 的规范十进制整数，不接受负数、指数、小数、布尔或字符串。

只允许四种方法：status（params 为精确空对象）、block 和 commit（params 只有 height，其值为规范十进制正整数字符串且不超过已固定 profile 的原高度上限）、broadcast_tx_sync（params 只有 tx，为规范标准 base64，解码后 1..28134 字节）。不提供 abci_query、net_info、genesis、dump_consensus_state、mempool 列表、交易索引、WebSocket 或管理调用。验证失败不能调用上游。

每个合法请求只调用一次现有 typed RPC 方法；上游使用 PR39 已有数字回环 peer，不新增通用反向代理，不转发原 JSON 或头。status 只返回客户端同步实际需要的 node_info.network 与 sync_info.latest_block_height，避免传播节点 moniker/listen address/ID。block/commit 返回标准 CometBFT 公共结果并用其原 JSON 编码。broadcast_tx_sync 只返回 code/hash，保留错误代码但剔除 log/info 等自报文本；成功仅是单个 mempool 接收，绝不是确认。传输失联/超时统一失败，绝不自动重试广播、重签或清预留。

## 资源及生命周期

请求体上限 65536 字节，覆盖原最大交易的 base64 及固定封装，不扩大原交易限额。响应完整封装后不超过原 2 MiB，超限在成功响应头发出前失败。不新增分页或无界查询。网络监听最多保留 32 个已接受连接，超额连接立即关闭；每个网关最多 2 个活动请求，含读体与上游处理，超额立即返回固定 503 而非无界等待队列。不能宣称抵抗全局 DoS 或提供共识公平性。

HTTP ReadHeaderTimeout 2 秒、ReadTimeout 5 秒、WriteTimeout 10 秒、IdleTimeout 10 秒，MaxHeaderBytes 32 KiB（Go HTTP 实现的内部容差不冒充精确字节承诺）。每次处理使用最长 8 秒且服从更短原请求的 context。所有限额为网关额外收紧，不扩大 PR39 上游 10 秒调用/5 秒响应头/2连接等预算。

context 取消或就绪回执写入失败时，停止接收和请求准入，关闭监听及已接受连接、取消上游调用并等待已准入处理者退出，然后关闭上游空闲连接。准入和等待的所有权必须同步，禁止 WaitGroup Add/Wait 竞态及握手后遗留关闭者。意外服务退出不是成功停止。命令只输出固定就绪记录及固定失败类别，不输出请求/交易字节、上游异常、路径、隔离参数或密钥。

## 实施及验收范围

推荐根模块 stdlib-only internal/rpcgate 实现严格协议/有界 HTTP 服务；labnet 使用已固定 Network 和现有 typed peer 适配；新增 zevune-rpc-gateway 真实命令。公共低层接口不能选择任意网络目标，完整 onion checksum 校验在实际 labnet/CLI 入口执行。低层测试用的可接受后端只在 *_test.go；运行时只接现有真实 RPC。

测试必须实际覆盖四方法成功、重复/缺失/未知 JSON 字段、批量/通知、id/height/base64边界、固定 Host/路径/方法/头、分块超大体、响应超限、上游失败、并发拒绝、真实回环连接上限、取消/关闭和就绪失败。检查没有上游请求时的非法输入，广播断链无二次调用。对请求解码 fuzz，并执行 race/vet。

双平台原生 operator_e2e 必须经过真实网关命令、原显式 SOCKS 客户端、真实四本机验证者、真实 Orchard 无价值付款和完整参考账本重执行；保留原 PR39 和全部错误后置状态/重启回归。构建网关直接使用准确源码，不扩张既有离线分发包或用 mock 代替原生证明。原 CI 时间预算、依赖版本、格式、锁、容量和同步写入保持。

独立设计评审只批准设计，随后准确实现另需独立非作者代码复审及必要 CI。测试和审查未实际取得时保持未验收。即使模块合并，也只接受受限 RPC 网关阶段；P5.private_transport 仍 in_progress，traffic_acceptance、四真实机器、30 天和专业外审仍须真实取得。

依据：PR39 PRIVATE_RPC_V1、原 PROOF_CONTRACT/ARCHITECTURE、固定 CometBFT v0.38.26 RPC 实现与 Go net/http Server。官方规格不是本项目通过安全审查的证明。
