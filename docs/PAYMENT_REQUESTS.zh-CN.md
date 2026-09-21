# 离线付款请求模块 v1

本模块提供 `payment_request.py create / inspect / prepare`，把交互输入的收款意图固定为
一个有界 `.zvrequest` 文件，随后核对网络、独立摘要和用户确认，再交给既有 Rust 钱包签名。
只用于 NO-FUNDS LAB2 本地实验，不联网、不广播、不处理真实资金；不是完整在线钱包。

## 安全边界

**请求是明文，不是签名、发票认证或付款成功凭证。** 它包含收款地址、金额、到期区块高度和
随机 nonce。任何人都可以创建或重算请求摘要；必须通过可信渠道核对请求摘要和收款人。
请求内不允许密码、手续费、可执行文件、钱包/账本路径、输出路径、脚本或任意扩展字段。
手续费由付款方在确认时输入，不由请求发起方决定。

独立保存的请求 SHA256 和独立可信创世 SHA256 都是必需输入；不能仅从同一不可信文件旁的
文本取得摘要并声称来源可信。相同创世的克隆链仍共享网络身份，这不识别所有分叉。
校验和只检测地址文本/网络标签，不认证接收者或曲线点；真实 Rust 后端重做网络、地址、历史、
余额、期限及证明验证。旧 LAB1 文件/接口不改，本新请求格式仅接受 LAB2。

nonce 只是区分请求，**不是链上单次使用防护**。同一请求在一笔付款已经确认之后仍可能被再次
用于新付款。用户必须自行对账；本模块没有已付款发票数据库，不能将可重复签名理解为幂等付款。
钱包现有 pending 预留仍会拒绝产生第二笔冲突付款。任何超时、中断或导出失败都不能当作取消；
先用原 `pending` 命令取回已保存的同一签名交易，不自动重新签名、解除预留、恢复旧钱包或重试。

## 使用

需要 Python 3.10+、可信本地创世与已验证的账本、原加密钱包及其独立保存回执、已核验摘要的
`zevune-wallet-local`。不安装依赖，不需要 Docker。v5 本地包包含新工具和本指南；源码入口带
`scripts/` 前缀，程序包入口不带。旧 v2/v3/v4 包仍按各自精确文件合同核验。

先通过原 `network-address` 命令取得 LAB2 接收地址，必须核对它属于独立选择的网络。

```powershell
python .\payment_request.py --no-real-funds create C:\Zevune\receive.zvrequest --genesis C:\Zevune\genesis.bin --genesis-sha256 $GenesisSha
```

交互输入地址、正整数测试金额、到期区块高度，键入 `CREATE` 同意保存明文意图。所有父目录
必须预先存在；已有目标（包括链接）拒绝覆盖。成功返回请求 SHA256，应另行安全交接。
字段使用固定规范 JSON（ASCII、排序键、紧凑分隔符、一个末尾 LF），总大小不超过2048字节。
金额最大为 2^63-2，至少为付款方手续费留一个整数单位；实际余额及手续费总额仍由钱包验证。
到期高度为1至2^64-1，不是墙上时钟时间，离线检查不预测当前高度或保证请求尚未过期。

```powershell
python .\payment_request.py --no-real-funds inspect C:\Zevune\receive.zvrequest --request-sha256 $RequestSha --genesis C:\Zevune\genesis.bin --genesis-sha256 $GenesisSha
```

`inspect` 不需要密码、不运行后端、不写文件，输出明确标注 `authenticated:false`、
`expiry_checked_against_ledger:false` 和 `single_use_enforced:false`。它会显示明文意图，
避免录屏、公共日志和不必要的传播。普通 Python 启动不会向程序包写入 `__pycache__`。

```powershell
python .\payment_request.py --no-real-funds prepare C:\Zevune\receive.zvrequest C:\Zevune\payment.tx --request-sha256 $RequestSha --genesis C:\Zevune\genesis.bin --genesis-sha256 $GenesisSha --wallet C:\Zevune\alice.wallet --wallet-pin $WalletPin --journal C:\Zevune\ledger --backend .\zevune-wallet-local.exe --backend-sha256 $BackendSha
```

核对显示的请求和网络，输入自己的正整数手续费，键入 `PREPARE` 才请求隐藏密码。密码不接受
命令行/环境变量输入，交互回显关闭失败就拒绝；私有金额、手续费、接收地址不进入子进程参数。
输出交易文件必须不存在，不能位于活动账本目录内，以免污染其固定命名成员。

程序在签名前检查钱包精确末端回执、公开完整链、真实密码认证和已观察到的文件变化，然后
调用原操作码4完成扫描、原证明/签名、加密 outbox 持久化和仅创建导出。随后核对返回网络、
交易摘要、已签名的公开手续费/到期高度、新回执和钱包原前缀，并重新认证最终钱包。
成功为 `request_prepared_not_broadcast`，不等于入块、确认、最终性或已支付。
返回的新回执必须独立保存；日志保存代数不是交易数，扫描可能增加记录。

## 并发、错误与兼容

操作前停止其他钱包写入者。Python 前后快照不提供跨进程原子事务，也不锁定未来签名权限；
最终操作仍依赖原 Rust 独占锁、状态规则和可信本地 OS/父目录。旧控制台及其他副本不受新的
全局互斥控制；本模块未增加这种锁，不声称消除了所有并发竞态。

失败保留部分或完整输出，不自动删除或替换。签名成功后，回执/输出后验检查仍可能失败，
因此错误消息始终要求先对账。请求和创世在密码输入后再次核对独立摘要；文件中的内容不能
指定钱包、后端或文件路径。超过限额、重复键、未知字段、非规范JSON、链接、截断、错误域、
旧末端回执和已有输出均拒绝。请求归档被 Git 忽略，CI不上传私有请求、钱包或交易文件。

共用的后端传输仅提取已有有界交换过程；旧 catalog.call 的2/6/9操作白名单不扩大。
新 RequestBackend 只增加显式 prepare 方法构造原操作码4。原300秒单调用超时、4096/1024
字节stdout/stderr上限、固定后端摘要和原同步、密码学、协议/钱包格式、依赖锁均保持。
Python/系统内存不保证安全擦除；Windows ACL/目录同步、物理断电/磁盘写满、恶意本地后端
和网络匿名不因本模块获得新保证。只读源码快照或独立代码审查不替代外部专业安全审计。

## 验证

```text
python -m unittest discover -s scripts/tests -p test_payment_request.py -v
python scripts/check_payment_request_backend.py <可信原生钱包后端>
```

单元测试中的合成公开帧只能验证格式/拒绝行为，不能验证密码学成功。真实原生测试使用随机
无价值钱包，完成请求创建、确认签名、恢复相同pending、保留余额预留、错误密码/网络/回执拒绝，
并故意丢弃一次**实际成功签名**的应用层回复，随后恢复原交易而非重签。这是测试驱动中断，
不是生产故障开关、内核故障或物理断电实验。最终验收以准确提交的Linux/Windows CI、完整
非作者审查和程序包执行记录为准。P4整体、Issue23和real_funds_allowed=false边界保持。

参考：Python官方 `json` 的重复键/非有限数默认行为与本模块的严格拒绝不同；
https://docs.python.org/3/library/json.html 。后端管道与超时语义见
https://docs.python.org/3/library/subprocess.html 。这些资料不是项目安全背书。
