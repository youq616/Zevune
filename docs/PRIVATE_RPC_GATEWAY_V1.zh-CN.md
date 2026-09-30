# P5 第二阶段：受限 RPC 服务网关

状态：设计检查点 `85f9f61686058d7bf43d4844aff358bdc0f9ab00` 已收到用户转交的独立会话无阻断结论；运行时候选 `7ac26ad8afaba2021bbd5df4b08c75d851a75d97` 的独立审查发现标准流取消阻断 B1。本版为 B1 修复候选，仍未验收，须按新 SHA 复审。基线 main `0e5fd16abfebec3cc5a3db6bb99d1e4e7335c2f6` / tree `36034da259fb7e28b8783097a6e4bdf48f57d6f0`，已有 PR39 onion/SOCKS 客户端保持不变。继续 `dev/p5-rpc-gateway` / PR40；设计评审不替代新代码提交的独立复审和实际 CI。本模块不是离线报告、桌面界面或完整 P5 交付。

## 目的及授权边界

为未来可信本机 Tor 服务映射提供最小 RPC 服务面，避免直接转发 CometBFT 的全部 RPC。只新增本机数字回环监听的运行时网关及实际命令行，不启动 Tor、不创建/发布 onion 服务、不修改 init/run，不接触钱包、验证者或 onion 私钥。公开部署、付费资源和真实资金仍禁止。主机及本机代理必须可信；网关不能阻止同机恶意进程访问原 RPC，也不能认证某连接来自 Tor。

客户端 -> 显式 onion/SOCKS -> 本机网关 -> 固定数字回环 CometBFT RPC。实验只使用真实回环 SOCKS 夹具；不能当作实际 Tor 电路、时序隐私或四真实机器的证据。客户端的独立创世/配置固定、法定票权签名、完整真实重执行和下一签名头状态匹配仍是可信性依据，网关不能用余额、进程健康或自报 hash 替代它们。

## 固定接口

网关命令独立于节点及钱包命令。必须显式提供无真实资金确认、已有公共网络配置及其独立 SHA256、监听地址、上游回环 RPC 地址及预期 onion endpoint。所有配置先校验，后监听；上游不能等于监听地址。监听和上游均只能是规范 `127.0.0.1:<1024..65535>`，上游 URL 使用现有 ValidateEndpoint。预期 onion endpoint 使用 PR39 原解析/checksum/version 规则，HTTP Host 必须精确匹配其 authority。不会通过 URL、请求头、DNS、环境代理、重定向或上游回执选择目的地。Host 是路由限制，不是客户端身份认证。

只允许 HTTP/1.0 或 HTTP/1.1 的 `POST /` 和单个精确 `Content-Type: application/json`，拒绝绝对形式 URI、路径/query 变体、压缩请求、Upgrade/WebSocket、Origin、Cookie 和 Authorization。其它头不转发。响应只构造所需内容类型、长度和固定错误，不透传上游头或错误文本；不设访问日志。连接可能暴露 HTTP 协议本身的时间和长度，不声称消除流量关联。

请求为单个 JSON-RPC 2.0 对象，精确四字段 jsonrpc/id/method/params，递归在本接口对象层拒绝重复/未知字段；不接受批量、通知或 null id。id 是 0..9007199254740991 的规范十进制整数，不接受负数、指数、小数、布尔或字符串。

只允许四种方法：status（params 为精确空对象）、block 和 commit（params 只有 height，其值为规范十进制正整数字符串且不超过已固定 profile 的原高度上限）、broadcast_tx_sync（params 只有 tx，为规范标准 base64，解码后 1..28134 字节）。不提供 abci_query、net_info、genesis、dump_consensus_state、mempool 列表、交易索引、WebSocket 或管理调用。验证失败不能调用上游。

每个合法请求只调用一次现有 typed RPC 方法；上游使用 PR39 已有数字回环 peer，不新增通用反向代理，不转发原 JSON 或头。status 只返回客户端同步实际需要的 node_info.network 与 sync_info.latest_block_height，避免传播节点 moniker/listen address/ID。block/commit 返回标准 CometBFT 公共结果并用其原 JSON 编码。broadcast_tx_sync 只返回 code/hash，保留错误代码但剔除 log/info 等自报文本；成功仅是单个 mempool 接收，绝不是确认。传输失联/超时统一失败，绝不自动重试广播、重签或清预留。

## 资源及生命周期

请求体上限 65536 字节，覆盖原最大交易的 base64 及固定封装，不扩大原交易限额。响应完整封装后不超过原 2 MiB，超限在成功响应头发出前失败。不新增分页或无界查询。网络监听最多保留 32 个已接受连接，超额连接立即关闭；每个网关最多 2 个活动请求，含读体与上游处理，超额立即返回固定 503 而非无界等待队列。不能宣称抵抗全局 DoS 或提供共识公平性。

HTTP ReadHeaderTimeout 2 秒、ReadTimeout 5 秒、WriteTimeout 10 秒、IdleTimeout 10 秒，MaxHeaderBytes 32 KiB（Go HTTP 实现的内部容差不冒充精确字节承诺）。每次处理使用最长 8 秒且服从更短原请求的 context。所有限额为网关额外收紧，不扩大 PR39 上游 10 秒调用/5 秒响应头/2连接等预算。

服务根 context 取消或就绪回执写入失败时，停止接收和请求准入，关闭监听及已接受连接、取消上游调用并等待已登记处理者退出，然后关闭上游空闲连接。单请求取消只取消该请求及其上游调用，不能停止整个服务。准入和等待的所有权必须同步，禁止 WaitGroup Add/Wait 竞态及握手后遗留关闭者。意外服务退出不是成功停止。命令只输出固定就绪记录及固定失败类别，不输出请求/交易字节、上游异常、路径、隔离参数或密钥。

## 实施及验收范围

根模块 stdlib-only internal/rpcgate 实现严格协议/有界 HTTP 服务；labnet 使用已固定 Network 和现有 typed peer 适配；新增 zevune-rpc-gateway 真实命令。公共低层接口不能选择任意网络目标，完整 onion checksum 校验在实际 labnet/CLI 入口执行。低层测试用的可接受后端只在 *_test.go；运行时只接现有真实 RPC。

测试必须实际覆盖四方法成功、重复/缺失/未知 JSON 字段、批量/通知、id/height/base64边界、固定 Host/路径/方法/头、分块超大体、响应超限、上游失败、并发拒绝、真实回环连接上限、取消/关闭和就绪失败。检查没有上游请求时的非法输入，广播断链无二次调用。对请求解码 fuzz，并执行 race/vet。

双平台原生 operator_e2e 必须经过真实网关命令、原显式 SOCKS 客户端、真实四本机验证者、真实 Orchard 无价值付款和完整参考账本重执行；保留原 PR39 和全部错误后置状态/重启回归。构建网关直接使用准确源码，不扩张既有离线分发包或用 mock 代替原生证明。原 CI 时间预算、依赖版本、格式、锁、容量和同步写入保持。

独立设计评审只批准设计，随后准确实现另需独立非作者代码复审及必要 CI。测试和审查未实际取得时保持未验收。即使模块合并，也只接受受限 RPC 网关阶段；P5.private_transport 仍 in_progress，traffic_acceptance、四真实机器、30 天和专业外审仍须真实取得。

依据：PR39 PRIVATE_RPC_V1、原 PROOF_CONTRACT/ARCHITECTURE、固定 CometBFT v0.38.26 RPC 实现与 Go net/http Server。官方规格不是本项目通过安全审查的证明。

## 独立设计审查后的实现细化

审查来源是用户转交的未参与设计编写的独立会话报告，Reviewed commit 为 `85f9f61686058d7bf43d4844aff358bdc0f9ab00` / tree `987525c682e742db1135a7470f5f81f5b7b24812`。其结论为无设计阻断、保留 R1–R4 四项中等非阻断风险；未运行测试，未提交 GitHub 审批。PR40 评论 `5903296247` 记录收件和来源，未提供可独立访问的原会话链接；不冒充 Codex 审查额度已恢复。

R1：网关的所有 HTTP 响应使用 `Connection: close`，开启标准库 FullDuplex 禁止响应前隐式排空未读体。拒绝路径先使读截止时间到期，再发送固定错误；清理同样先到期读截止时间、再 Close 请求体。活动槽位覆盖读体、上游、写入/flush 和显式体清理。额外拒绝处理者也登记到服务等待集合，不能成为停机后的遗留工作。该版本明确付出每次请求新建下游 TCP/SOCKS 连接的代价，不宣传连接复用或时序隐私。实际 TCP 测试包含第三连接只发头、不发送固定长度或分块体的场景。

R2：外层 JSON-RPC 的 id 是原数字整数，0 不省略；status 高度为十进制字符串；broadcast code 为 uint32 JSON 数字，0 不省略；32 字节 hash 为大写十六进制字符串，不是 base64。block/commit 内层仅由固定 CometBFT 的 cmtjson 编码。最小 status 还核对固定 Network 的 ChainID；空结果、缺少块/签名头或非 32 字节广播 hash 不能包装成成功。网关不凭这些检查替代客户端完整链验证。

```json
{"jsonrpc":"2.0","id":0,"method":"status","params":{}}
{"jsonrpc":"2.0","id":0,"result":{"node_info":{"network":"example-chain"},"sync_info":{"latest_block_height":"7"}}}
{"jsonrpc":"2.0","id":1,"method":"block","params":{"height":"7"}}
{"jsonrpc":"2.0","id":2,"method":"commit","params":{"height":"7"}}
{"jsonrpc":"2.0","id":3,"method":"broadcast_tx_sync","params":{"tx":"AA=="}}
{"jsonrpc":"2.0","id":3,"result":{"code":0,"hash":"ABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABAB"}}
```

这些只说明编码类型，示例 tx 不是合法 Orchard 付款、示例 hash/network 不是可信状态。block/commit 样例内层以原 CometBFT 类型为准；`TestGatewayOriginalClientDecodesEveryField` 用原客户端跨真实 HTTP 解码并断言它们的实际字段，不使用空 result 路由测试代替兼容性。

R3：在原 8 秒 handler 上限内，新增更短的 4 秒上游调用/完整读体预算；下游写入/flush 最多 1 秒且不超过较短请求期限。固定错误输出最多 1 秒。原客户端 5 秒响应头和 10 秒调用预算完全不改。上传体耗时、调度和编码仍占用端到端时间，4 秒并非成功保证；超时仍可能产生广播结果未知。测试包含上游及时发头而持续拖延 body，以及完整收到广播后断链，断链后不能二次提交。底层在未写出请求字节前可能安全重拨，不冒称一次 typed 调用意味着严格一次 TCP 尝试。

R4：服务根取消拥有监听、已接受 socket、请求准入及共享上游生命周期；请求取消只传给自己的处理和上游。关闭标志及 WaitGroup.Add 共用互斥锁，停机后禁止新登记，所有已登记 handler 退出后才关闭上游空闲连接。慢头连接在 Accept 阶段即占 32 个 socket 上限。就绪输出预算 2 秒、命令失败输出预算 1 秒；标准流现在必须通过下述 B1 能力入口，不能再以 io.ReadCloser/io.WriteCloser 或进程内 os.Pipe 的行为推断继承标准流可取消。输出不创建 goroutine；stdin watcher 通过实际读期限退出，先 join 再 Close。

HTTP 帧解析仍委托 Go 标准库：核心严格检查原 RequestURI、Host 和所需头的存在性/单值，并拒绝 Expect、Trailer、Proxy-Authorization；分块体读完后再次拒绝未声明 trailer。标准库可能在 handler 之前拒绝或规范化部分 HTTP 帧（例如相同 Content-Length），其协议错误和内部容差不是网关自有 JSON 错误承诺，也不表示所有 HTTP 原始字节只有一种拼写。原请求、头和 parser 错误都不转交上游。

## 命令与当前证据边界

在已经独立核验的本机无价值网络上，从 `integration/cometbft` 构建 `go build -mod=readonly ./cmd/zevune-rpc-gateway`。运行参数形状如下；所有大写占位值须取自独立可信本地配置，网关不会自行发现端点或创建 Tor 服务。该命令现在要求监督进程按下节提供受支持的专用继承管道；以下仅是参数形状，不承诺直接连接终端或普通 Windows shell 同步管道可以启动：

```text
zevune-rpc-gateway --no-real-funds --config ABSOLUTE_PUBLIC_CONFIG_PATH --config-sha256 INDEPENDENT_CONFIG_SHA256 --listen 127.0.0.1:28080 --upstream http://127.0.0.1:26657 --onion-endpoint CANONICAL_ONION_V3_HTTP_URL --stop-on-stdin-eof
```

就绪固定行是 `{"gateway":"ready","real_funds_allowed":false}`，不是共识、Tor 或付款确认。`--stop-on-stdin-eof` 可选，退出还支持进程中断信号；没有公开监听开关、任意上游参数透传或自动重试开关。

现有 network-operator 双平台工作流增加网关核心 test/vet、原客户端协议测试、新网关二进制及追加的真实付款 E2E；保留原无网关私密 RPC 用例与错误后置状态用例。Linux 另运行 race/fuzz，Windows 不冒称执行 Linux-only 步骤。源码中有测试并不意味着某个候选运行过；PR 记录必须绑定实际提交/tree 和对应日志。旧分发包的内容和格式不变，新增网关不是可信发布制品。本地稀疏 stdlib 测试不能替代嵌套 CometBFT/Rust 的原生整合验收。

## B1：继承标准流能力与修复验收

用户转交的独立运行时审查固定于 `7ac26ad8afaba2021bbd5df4b08c75d851a75d97` / tree `01424b8bd3a2ce4d290f478fc20761ccd2c8c9d7`，结论存在 P2 生命周期阻断；作者收件记录为 PR40 评论 `5907886214`。报告核对原双平台 CI 成功，但指出实际继承标准流的 Close 不保证中断在途 I/O。报告未提供可访问的原会话链接，也没有发布 GitHub 审批；本修复不自行宣布已获得复审通过。

`OpenInput/OpenOutput` 只接收具体 `*os.File`，调用即移交该端点的独占所有权，成功和失败均消费原文件；外部不得再对同一端点执行 I/O 或改动模式。允许父进程持有相反端点（例如保持 stdin 写端打开）；不允许其它任务/进程同时读写已移交的子进程端点。新 `Input/Output` 不暴露内部描述符，没有任意 Writer 适配入口。

| 平台 | 支持路径 | 明确拒绝的路径 |
| --- | --- | --- |
| Linux | 对继承 FIFO/pipe 通过 `/proc/self/fd` 重开独立 `O_NONBLOCK` 描述符，核对方向及 inode，并检查 deadline 能力；不使用 dup+SetNonblock 改动父端共享标志 | 缺少 procfs、文件/终端/其它设备、错误方向、无法启用 deadline |
| Windows（固定 Go 1.27.1） | 专用继承的 `FILE_FLAG_OVERLAPPED` pipe；在没有在途 I/O 时解除旧 Go 包装的 IOCP 关联，复制句柄、关闭旧包装，并用非原 stdin 数值的句柄重新注册；实际 SetDeadline 必须成功 | 普通同步 CreatePipe/os.Pipe、终端、普通文件，以及 IOCP/deadline 建立失败；不声称支持同步管道 |
| 其它系统 | 未建立支持合同 | 在监听及读任务之前失败 |

stdout 与 stderr 必须各自为受支持的独占管道；仅在启用 `--stop-on-stdin-eof` 时要求 stdin 同样合格。stderr 能力最先建立；不支持时返回非零退出码且不输出诊断，绝不回退到可能阻塞的裸 stderr。拒绝不支持的标准流是有意收紧的命令入口兼容性，不是让这些流“变得可取消”。尚未交付通用 Windows shell 启动器；测试中的 overlapped pipe 构造器只提供真实 OS 测试管道，不进入网关命令依赖链。

实际 Read/Write 使用每次至多 50ms、且不超过 context 的 OS/runtime deadline，在短期限返回后检查取消。输出在调用者任务内完成，不存在超时后等待写 goroutine 的分支；stdin 唯一 watcher 在每次读取间检查取消，退出后再释放文件。就绪失败仍执行原 HTTP 服务清理，再退出命令；失败输出仍保留 1 秒预算。期限不是实时调度承诺，可信本机内核和运行时仍为前提。

新增 `TestRealGatewayInheritedStandardStreamLifecycle` 必须在两平台实际启动网关二进制：stdin 父端保持打开时以 Linux SIGTERM / Windows 定向 CTRL_BREAK 取消；stdout 预先填满时等候就绪超时；stderr 预先填满时触发参数失败；stdin 等待期间监听失败；普通文件拒绝，以及 Windows 同步继承管道拒绝。退出及监听关闭先断言，之后才能关闭/排空父端。Windows 支持路径用真实 overlapped 本地管道，不用进程内可协作 writer。所有 child Wait 任务有明确 join，正常成功不能依赖测试强杀；超时强杀是测试失败后的清理。

根模块的继承管道子进程用例是标准流机制测试，不是实际网关命令验收。完整命令、公共配置 Load、HTTP 清理和真实付款仍由原生 operator_e2e 覆盖。原 R1–R3 运行时代码、客户端、证明/存储规则及原 CI 预算不变；本次未取得的新 SHA CI 或独立复审不得引用旧 SHA 成功来替代。
