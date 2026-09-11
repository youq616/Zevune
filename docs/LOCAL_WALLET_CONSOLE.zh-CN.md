# 本地钱包控制台（实验用途）

**仅用于没有价值的本地测试资产，不是主网钱包，也不提供网络匿名保证。** 此入口复用真实 Orchard 证明及现有加密钱包存储，不新增验证捷径。

## 能做什么、不能做什么

能够创建加密钱包、派生接收地址、创建加密备份、将备份恢复到新文件、扫描重新验证的本地账本、构造并保存付款、导出签名交易，以及恢复同一笔待发送交易。

控制台不广播、不自动重试、不访问 RPC 或远程节点。需要调用方持有可信的本地账本；不能在另一个节点占用同一账本文件时抢占其文件锁。不具备在线轻钱包同步、助记词、硬件签名、多设备并发、密码修改、日志压缩或生产部署能力。

多节点非零金额支付由独立的 `funded-wallet-consensus` 测试验证；控制台测试验证的是操作入口和本地账本。不要把两组分别通过的测试写成“控制台已实现在线多节点收付款”。

## 构建

从仓库根目录构建，需已安装仓库固定的 Rust 工具链；Python 前端只使用 Python 3.10+ 标准库。脚本不安装依赖，不需要 Docker。

```text
cargo build --manifest-path integration/orchard/Cargo.toml --locked --release --features local-funding-lab --bin zevune-wallet-local
python scripts/zevune_wallet.py --help
```

默认构建不启用该实验功能。每次前端和后端运行均要求 `--no-real-funds`。前端默认寻找上述编译出的程序，可用 `--backend` 明确指定可信本地可执行文件，或额外用 `--backend-sha256` 核对独立获得的摘要。摘要核对不是恶意操作系统防护或代码签名认证。

## Windows PowerShell 示例

下面仅展示本地操作；没有自动启用公网、节点端口或支付广播。在可信的个人目录中工作，避免 PowerShell 的安装目录。

```powershell
$work = Join-Path $env:LOCALAPPDATA 'Zevune\wallet-lab'
New-Item -ItemType Directory -Force -Path $work | Out-Null
python scripts/zevune_wallet.py --no-real-funds create "$work\alice.zwallet"
python scripts/zevune_wallet.py --no-real-funds address "$work\alice.zwallet" --index 1
python scripts/zevune_wallet.py --no-real-funds backup "$work\alice.zwallet" "$work\alice-backup.zwallet"
python scripts/zevune_wallet.py --no-real-funds restore "$work\alice-backup.zwallet" "$work\alice-restored.zwallet"
```

密码通过隐藏输入读取；新钱包要求输入两次。无法关闭终端回显时拒绝操作，不降级为明文回显。不要将密码写在命令、环境变量、脚本或聊天中。16 至 1024 是 UTF-8 字节长度边界，不是密码强度保证。

创建一个固定总量 100000 的本地测试创世账本：

```powershell
python scripts/zevune_wallet.py --no-real-funds init-test-ledger "$work\alice.zwallet" --journal "$work\state.journal" --genesis "$work\public-genesis.bin"
```

**这是显式创建一条新的本地测试账本，不是向已有链增发。** 创世清单含公开地址、金额和资产记录开口，不保护初始分配隐私。生成的 `genesis_sha256` 必须独立保存；不能用一个未验证的远程节点同时提供的文件和摘要替代可信来源。

将上一条返回的真实摘要填入 `$genesisHash` 后查询：

```powershell
$genesisHash = '<独立保存的64字符创世摘要>'
python scripts/zevune_wallet.py --no-real-funds status "$work\alice.zwallet" --journal "$work\state.journal" --genesis "$work\public-genesis.bin" --genesis-sha256 $genesisHash
```

构造付款时，接收地址、金额、手续费、过期高度通过交互输入，不进入子进程参数或环境变量。需要明确输入 `PREPARE`，这只是授权本地签名，不是网络转账：

```powershell
python scripts/zevune_wallet.py --no-real-funds prepare "$work\alice.zwallet" "$work\signed-payment.bin" --journal "$work\state.journal" --genesis "$work\public-genesis.bin" --genesis-sha256 $genesisHash
python scripts/zevune_wallet.py --no-real-funds pending "$work\alice.zwallet" "$work\same-payment.bin" --journal "$work\state.journal" --genesis "$work\public-genesis.bin" --genesis-sha256 $genesisHash
```

所有输出文件均为仅创建，不覆盖旧文件。`prepare` 先持久化加密预留和签名交易，再导出公开交易字节；导出失败不会释放预留或创建另一笔付款。`pending` 重新扫描后恢复相同的字节和交易标识，不重新签名。终端中断、写入错误、超时或回复丢失都不表示交易一定没有保存，必须先对账。

## 检查点、地址和边界

每次成功返回的 `receipt` 是 144 个小写十六进制字符，可通过全局 `--pin` 参数（置于子命令前）核对文件祖先。例如 `--pin <独立保存的receipt> address ...`。没有独立检查点时，完整的旧加密文件仍可能通过解密。receipt 不是区块签名、网络最终性证书或账户密钥；公开它可能暴露本地文件关联。

`zvlab:` 地址是临时、带校验和的本地显示格式，不是正式 Zevune、Zcash Unified Address 或任何主网标准。43 字节 Orchard 接收地址的编码交给上游验证，显示校验和只用于发现输入错误，不认证交易对手。未来的正式地址与网络域隔离需要独立设计，不能静默把本实验地址当成主网地址。

前后端请求有固定操作码、长度上限和精确字段数量。后端只从私有 stdin 管道接收，拒绝未知操作、截断、尾部、多余字段和相对路径。前端使用 `shell=False`，不向后端继承无关环境变量。返回只包含操作状态、本人请求的地址/余额和摘要，不打印种子、查看密钥或证明见证；用户仍应避免终端录屏及日志记录。

现有钱包日志容量为 256 条，超过上限拒绝写入而非自动丢弃记录。所有目录、设备和操作系统仍需可信；Windows ACL、目录替换、硬链接、多副本并发、交换分区及进程内存都不在完整保护保证之内。Python 字符串与系统副本没有可靠擦除保证。公开交易文件包含密文及签名，但本地文件时间和操作时序可能泄露信息。

初始化涉及多个新文件，不提供跨文件系统的整体原子事务。部分失败可能留下新创世清单或新账本，但不会覆盖已有钱包/账本，也不会自动删除以掩盖失败。恢复备份会生成另一份钱包副本，不应同时使用多个副本签名。
