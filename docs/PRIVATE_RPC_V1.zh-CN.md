# P5 第一阶段：显式 onion v3 RPC 传输合同

状态：已有运行时实现候选，尚未阶段验收；本文件不是 P5 完成证明。基线为已合入 PR38 的 `5b7174c292fbfaf9808d434b809904fac4da5844`，tree `cf477e52899dc580934ced82f6c93eeff864ce56`。原 DELIVERY_PLAN 的 P1—P8 与所有验收门槛保持。

## 本阶段边界

只为现有 labnet RPC 接入一个可显式选择、失败即停止的传输。`SyncOptions.SOCKSProxy` 非空时，sync/submit 的所有 Status、Commit、Block、BroadcastTxSync 请求必须使用同一受限 onion peer；空值保留原数字回环客户端。CLI 的 `--socks-proxy` 只属于 sync/submit；显式空参数必须拒绝，不能被解释为退出隐私模式。不会修改节点 init/run 的四回环节点规则，不启动 Tor、不创建 onion 服务、不公开部署、不使用真实资金。

这不是完整 P3/P4/P5：还没有多机节点操作、动态验证者、完整在线钱包、实际 Tor 服务/流量实验或全面查询隐私。一次同步及随后提交在同一 peer 内可关联；每次顶层操作建立新 peer，不跨操作共享连接池或隔离参数。该边界不能宣称抵抗全局观察者或隐藏同一付款流程。

## 输入及信任边界

1. 隐私端点只能为精确 `http://<56个小写base32字符>.onion:<十进制端口>`，端口1—65535且无前导零。禁止缺省端口、子域、尾点、大小写变体、IP、普通域、用户信息、路径（含尾斜线）、query、fragment、percent/opaque变体。按 Tor 官方格式解码35字节，要求version=3，使用现有锁定的 x/crypto SHA3-256 核对两字节校验和。校验和不是服务所有者或链身份认证；Ed25519服务密钥有效性及握手由可信 Tor 实现验证。
2. SOCKS代理只能为精确数字 `127.0.0.1:<port>`，端口1024—65535且无前导零。禁止DNS、IPv6、环境代理、远端代理和URL形式。客户端仅对这个数字回环地址执行tcp4拨号。请求的网络与目标必须和构造时冻结的onion目标完全匹配，禁止任意目标拨号。
3. 用户独立固定的网络配置/创世/验证者和程序摘要不变。SOCKS回执不证明进程一定是Tor，更不证明代理实际实施隔离。主机、代理程序及配置必须可信；恶意本机进程或代理不在此传输防线内。

## SOCKS握手与隔离

客户端只发送 SOCKS5 METHOD=USERNAME/PASSWORD：`05 01 02`。不声明no-auth；代理选择任何其他方法、错误版本或截断即关闭，不发HTTP、不重试认证、不降级。不能直接使用当前 x/net/proxy.SOCKS5 的默认认证协商，因为其配置Auth时仍声明no-auth。

RFC1929用户名固定为九字节 `<torS0X>0`；密码为每个peer独立读取32个crypto/rand随机字节后编码的64个小写hex字符，表示 Tor stream-isolation parameter。失败取得随机数则拒绝创建peer。它不是钱包密码、代理访问口令或服务端认证；不落盘、不进入URL、日志、回执、命令行或环境变量。用户名/密码协商必须返回 `01 00` 才发送CONNECT。

CONNECT只能为 `05 01 00 03 <len> <原onion主机名字节> <U16BE(port)>`。不进行本地DNS，不发送RESOLVE/BIND/UDP，不使用乐观HTTP数据。要求成功回复版本5、保留字节0、REP=0；有界完整消费IPv4/IPv6/非空域名BND.ADDR及端口。不使用该BND地址重新拨号。错误、未知类型、截断、拒绝和Tor扩展错误均停止。

代理TCP连接保持2秒上限；从拨号到完整SOCKS握手最多5秒，且服从更短的调用context。握手取消会关闭真实socket，清理取消监听者后才归还连接；成功后清除握手deadline，不能让过期监听者关闭已复用连接。握手错误只向上返回固定错误类别，不回显代理字节或隔离参数。

## HTTP及账本不变量

保留现有10秒HTTP调用、5秒响应头、2MiB正文、32KiB响应头、每host最多2连接、无压缩、仅固定host根路径POST、拒绝重定向及非200的限制；不扩大原验收时间预算。每个隐私peer独立http.Transport，Proxy=nil，自定义DialContext唯一通路。WSEvents不启动。代理停机、no-auth、认证失败、目标错误、重定向、超时均没有DNS/直连或其他代理回退。关闭peer清理空闲连接。

只替换传输，不修改固定票权签名校验、区块连接/数据校验、tip-1完整真实重执行、下一已签名头的后置状态匹配、检查点核对顺序、worker独占锁、原子提交或容量。submit仍只广播同一已签名字节一次，mempool接受不是确认；结果未知不清预留、不重签、不自动重播。不会上传钱包、验证者或onion服务私钥。

## 实际测试与验收

实现必须覆盖规范地址及Tor公开地址向量、坏checksum/版本/别名输入；真实回环假SOCKS服务逐字节验证唯一方法、认证、域名CONNECT及其顺序；分片/截断/错误回复、no-auth、认证拒绝、代理不可用、取消和deadline；每peer隔离值不同、同peer重连一致、并发与关闭；HTTP重定向/压缩/过大响应拒绝，以及设置恶意HTTP_PROXY/ALL_PROXY后仍不经环境代理。假SOCKS服务只能证明客户端协议与失败行为，不代表实际Tor电路或匿名性。

必须将sync/submit调用接到该peer并保留原完整回归；准确候选需独立非作者代码审查及既有必要CI。没有实际运行的检查保持未测。原生Orchard/Go/Rust整合不得被假验证器替代。生产依赖版本、账本格式、同步写入、锁及限额保持；如将x/crypto从间接依赖改为直接依赖，仍固定现有v0.33.0和原校验和。

独立设计审查先于运行时接线；代码审查另按最终准确head进行。该客户端阶段至多使P5.private_transport进入in_progress，不能接受P5.traffic_acceptance或P3.four_machine_faults。后续实际Tor/onion实验、四真实机器、30天运行及专业安全审查必须真实取得。

### 首个实现候选的实测边界（2026-09-29）

设计检查点 `89a2419df8d9e235f038dae5145c75d3b3a0c18f` 已获独立非作者 Codex 复审，PR39 评论 `5891207488` 明确命名该提交并称未发现重大问题。此结论只审查设计，不接受随后代码候选。

本地 Go1.23.2/Linux 对准确 `private_socks.go` 与 `private_socks_test.go` 执行了 `go test -race -v -count=1 private_socks.go private_socks_test.go`，9个顶层测试及其子测试通过，包括实际5秒握手超时。原请求取消测试按 Go1.27.1 `net/http.Transport.getConn` 的 `context.WithoutCancel` 行为真实分离context；实现显式保留原请求生命周期，完成握手后不保留socket关闭者。

本地环境无法取得完整依赖且没有Cargo，完整包测试在依赖前置阶段失败；不得将该子集结果说成完整Go/Rust整合通过。新增HTTP/CLI测试和 `operator_e2e` 真实证明付款、签名状态重执行测试已进入原双平台工作流；准确候选的实际CI及独立代码审查仍须在PR39核对。端到端测试只用本机固定转发SOCKS夹具，验证者/Orchard/worker/CLI保持真实，绝不代表实际Tor或四机器验收。

## 一手规范（2026-09-29重新核对）

- Tor SOCKS extensions：https://spec.torproject.org/socks-extensions.html ，特别是USERNAME/PASSWORD扩展和stream isolation；格式0由Tor0.4.9.1-alpha及Arti1.2.8开始原生支持，较早实现按legacy参数解释，不据此声称已测兼容性。
- onion v3地址：https://spec.torproject.org/rend-spec/encoding-onion-addresses.html 。
- SOCKS5与RFC1929：https://www.rfc-editor.org/rfc/rfc1928 和 https://www.rfc-editor.org/rfc/rfc1929 。

上游规格不等于Zevune通过安全审计；实际代理版本、配置与流量验收仍待固定。
