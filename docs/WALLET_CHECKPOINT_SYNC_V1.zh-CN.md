# P4：检查点约束的钱包重扫

状态：实现候选，尚未验收；独立代码复审与准确提交的双平台原生测试必须另外取得。它是原 `P4.restart_and_confirmation` 和在线支付整合所需的运行时前置条件，不是新的报告/桌面/交接模块，也不是完整在线钱包。

## 现有缺口与范围

网络模块已经按独立固定的配置验证法定票权签名、完整重执行区块，并在持久化前比对下一签名头的 AppHash。随后旧钱包 `status` 会另行打开并重扫本地参考账本，但不要求其仍处于调用者刚才验证的准确高度/状态。本次在既有 Rust 钱包命令及 Python 入口内新增一个收紧模式，将这两个阶段之间的本地状态交接显式约束起来。

本模式不会访问网络或验证共识签名，不把调用者提供的 hash 自动升级成可信检查点。预期高度与 AppHash 必须由调用者独立认证，例如来自既有完整网络同步；不能从准备扫描的文件或不可信节点回执自取后声称已认证。可信本机、独立可信程序摘要、私有目录及合作式文件锁仍为前提；不承诺恶意文件系统或同机权限攻击防护。

实际在线钱包编排、无手工管理参考日志的普通支付、结果未知/重启自动对账及远端动态验证者信任仍未交付。新增网络到钱包的自动编排应另作跨边界设计和非作者评审；本模式只增强已有本地账本重扫边界，不新增网络信任源、密码算法或状态证明捷径。

## 固定接口与顺序

原 `zevune-wallet-local` 的 `ZVWCLI01` 私有 stdin 帧增加 opcode `11`，不改变 opcode `0..10` 的形状或旧行为。`11` 必须含独立保留的钱包回执（原72字节祖先约束，不是链上最终性证明），精确6个字段：钱包绝对路径、参考账本绝对路径、公共创世清单绝对路径、独立创世 SHA256、规范十进制高度、规范小写64字符非零 AppHash。原16KiB请求、字段/密码/钱包容量及存储边界保持。该操作不接收支付意图、不构造新的付款或证明、不导出/广播交易。

顺序是：检查完整帧、回执存在性和检查点语法 → 固定摘要读取并完整解释创世 → `open_pool` 实际持锁打开并完整授权重放参考账本 → 比对准确高度和 AppHash → 从**同一个持锁 PoolStore**提取原可信历史 → 打开和解锁既有 WalletStore → 调用原钱包 sync 持久化扫描结果 → 返回状态 → 释放钱包和池。

高度允许0，对应创世；预期高度较新、较旧或同高度不同状态均拒绝，不把“至少达到”当作“精确匹配”。不会先对一个句柄检查再重新按路径打开；池锁覆盖历史提取及钱包同步写入。所有锁均使用原非阻塞获取方式，不增加等待锁队列或死锁规避性解锁窗口。

检查点不匹配时钱包尚未打开，不能更新钱包字节、余额、预留或 pending。匹配后钱包沿用原历史验证和持久化规则：实际入账可正常解除已花费的 pending，但没有再次广播、重签、自动回滚或清空预留命令。成功同步以后若输出失败，钱包可能已经持久化，调用方仍须对账而不是盲目重试。

## 返回值及现有 Python 命令

外层仍为 `ok:true`、`scope:"local_journal_only_no_funds"`。保留原网络身份3字段、height/balance/available/pending/receipt，新增：`result:"checkpoint_matched_wallet_scanned"`、`checkpoint_matched:true` 及准确小写 `app_hash`。没有 `confirmed`、`finality` 或“全网最新”字段；匹配仅指相同本地重执行状态。

既有 `scripts/zevune_wallet.py` 增加 `status-at-checkpoint` 子命令，必须同时显式提供 `--pin`、`--backend-sha256`、原独立创世摘要及该子命令的 `--expected-height` 和 `--expected-app-hash`。这些参数只涉及本地公用信任元数据。密码继续隐藏提示后只通过后端 stdin 传入，禁止把密码、密钥或支付意图放到 argv/env。参数形状示例（大写值为占位符）：

```text
python scripts/zevune_wallet.py --no-real-funds --backend TRUSTED_WALLET_BINARY --backend-sha256 INDEPENDENT_BINARY_SHA256 --pin RETAINED_WALLET_RECEIPT status-at-checkpoint WALLET --journal REFERENCE_JOURNAL --genesis PUBLIC_GENESIS --genesis-sha256 INDEPENDENT_GENESIS_SHA256 --expected-height VERIFIED_HEIGHT --expected-app-hash VERIFIED_APP_HASH
```

前端先校验参数再读取文件/询问密码/启动子进程；严格检查新响应的完整字段、类型、准确检查点、网络身份、有限测试供给和回执。不接受同名数字字符串/布尔高度，不因旧后端不认识 opcode11 而退回不受约束的 status，不自动重试。旧 `status` 仍明确只是本地状态，未被悄悄重新解释为已认证模式。

## 实际测试边界

新增 Rust 单元测试直接使用真实 TestGenesis/PoolStore/WalletStore：两种存储 profile 的同一池句柄锁、状态移动拒绝、检查点错误先于缺失/损坏钱包的打开；实际 Orchard 付款的加密 pending 经错误检查点保持精确字节，并仅在匹配已提交交易的状态下由原 sync 对账。新的 `wallet_checkpoint_cli` 集成目标启动**实际钱包二进制**，在两种 profile 下测试不匹配无钱包变化、成功同步、参考状态前移后旧检查点拒绝、格式拒绝及新高度持久化。

Python 测试检查原十一个操作编号/帧不变、新帧、完整响应类型、启动前拒绝及失败不降级。前端测试的 mock 仅隔离子进程入口，不提供接受型证明后端；密码学测试使用真实 Orchard，不以 Python 测试替代 Rust 原生执行。

原 `funded-wallet-consensus` 已有双平台的库与 interfaces 两个完整测试组。动态 Cargo 目标清单会将新增集成目标纳入 interfaces；没有更改目标调度器、工具链/依赖、30分钟作业或15分钟原付款回归预算，没有删除旧测试。存在测试源码不等于执行通过；本地 Python 验证、Rust 原生结果、独立非作者结论必须分别记录准确提交。没有 Cargo/原生平台时保持未核实，不制造模拟运行证据。

本阶段不依赖 PR40 未合并网关，基于实际 main 上原样的钱包/池实现单独推进；PR40 源码冻结不动。不能因此把 `P4.integrated_online_payment`、整个P4/P5或P1—P8标为已验收。真实Tor流量、四真实机器、30天和专业外审条件仍独立存在；不得合并、部署或使用真实资金。
