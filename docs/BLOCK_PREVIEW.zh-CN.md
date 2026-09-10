# M2 第一部分：区块预执行与带校验提交

版本：0.1.2-dev。范围是单机状态机接口与摘要计算优化；未接入 CometBFT，未实现真实证明或支付。

## 接口与不变量

`Engine.PreviewBlock(height, txs)` 使用与 ApplyBlock 相同的验证路径，在临时状态副本上执行候选区块。成功后只返回 BlockPreview，不改变已提交高度、承诺、nullifier、根窗口或日志文件，也不预占交易。同一已提交状态可以检查多个互相竞争的候选。

BlockPreview 绑定高度、已提交状态的 BaseAppHash、有序完整交易信封的 BlockID，以及预期执行后的完整 Summary。BlockID 包含证明字节，并使用独立的原型域分离前缀。它不是 CometBFT 的区块哈希，不是签名、零知识证明或共识凭证。

`Engine.CommitPreview(preview, txs)` 在写锁内检查当前基准，重新验证全部交易与证明，比对候选的完整字节摘要和结果，再沿用写日志、File.Sync、发布内存状态的路径。调用方传入的 preview 不被当作可信授权。陈旧基准、修改后的交易、伪造的结果或重复提交均不能推进账本；成功提交后再次提交同一 preview 返回 ErrStalePreview。

ApplyBlock、PreviewBlock、CommitPreview 共用 stageBlockLocked，避免预执行与实际执行采用两套规则。原 ApplyBlock 仍用于现有本地测试与日志重放；目前没有启用任何公网共识调用方。

存储失败仍遵循 M1 的故障规则：内存不推进，并拒绝后续操作；写盘或同步失败不等于磁盘一定回滚，必须关闭并重新验证。未提交的 preview 不被保存到日志。重启后即使调用方保留了旧描述，也必须基准仍一致且重新验证通过，才能提交。

## 并发、资源和安全边界

验证器属于可信本地实现，必须确定性、无副作用、并发安全，不得反向调用同一 Engine 而造成锁重入。调用方不得在调用过程中并发修改交易及嵌套切片。预执行结果不持有调用方可修改的状态切片。

每个区块仍受 128 笔和 2 MiB 信封总量限制。状态复制与哈希排序仍随历史增长；没有宣称可承载生产数据规模。预执行和提交都会验证证明，当前没有缓存绕过或跳过证明的选项。

没有新增 HTTP 区块提交、管理员确认、自动出块或付款入口。运行程序继续使用 UnavailableVerifier；测试中能接受的公开校验和替身仅存在于 `_test.go`。

## 摘要优化与兼容性

状态摘要改为流式写入 SHA-256，不再先创建完整转录字节缓冲。旧版字节顺序、协议常量、交易 ID 和 app hash 定义不变。测试保留原 M1 编码器，对 100 组合成状态逐一核对结果，并保留旧版固定值回归。

`BenchmarkSummaryEncoding` 只测合成内存状态的摘要编码。报告的 B/op 是每次操作的累计内存分配，不是进程峰值内存；ns/op 不是真实转账时间。运行：

```powershell
go test ./internal/ledger -run '^$' -bench '^BenchmarkSummaryEncoding$' -benchmem -benchtime=200ms -count=3 -cpu=1
```

## Windows 更新

先 Ctrl+C 停止旧进程，在原项目目录执行：

```powershell
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "更新失败。" }
go test ./... -count=1
if ($LASTEXITCODE -ne 0) { throw "测试失败。" }
go run ./cmd/zevuned -version
if ($LASTEXITCODE -ne 0) { throw "版本检查失败。" }
go run ./cmd/zevuned -data-dir "$env:LOCALAPPDATA\Zevune\devnet"
```

`-version` 输出 Zevune 0.1.2-dev 后退出，不打开监听端口或数据目录。状态接口新增 software_version，已有的 storage 语义不变。无需删除日志或重新安装依赖。height=0、payments_enabled=false 和 finality_available=false 仍是正常状态。

## 后续共识接入要求

本轮不是完整 ABCI 适配器。CometBFT 的应用规范要求提案处理不修改已提交状态，FinalizeBlock 不能提前持久化，持久化应在 Commit 完成。因此不能简单地把会写盘的 CommitPreview 放进 FinalizeBlock；仍需实现 FinalizeBlock/Commit 之间的应用生命周期、恢复握手、结果映射与多节点测试。

官方设计参考：
- https://github.com/cometbft/cometbft/blob/main/spec/abci/abci%2B%2B_app_requirements.md
- https://github.com/cometbft/cometbft/blob/main/spec/abci/abci%2B%2B_basic_concepts.md

这些参考不表示本项目已经依赖、兼容或通过认证的某个 CometBFT 版本。具体版本、接口映射及网络安全模型仍须独立验证。
