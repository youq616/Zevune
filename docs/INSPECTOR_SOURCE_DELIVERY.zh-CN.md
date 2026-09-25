# 核查桌面离线源码交付 v1

本模块把只读钱包核查桌面的固定运行源码打包成独立目录，并提供不执行包内程序的完整性检查。
它不是完整安装器、在线更新器、代码签名或安全审计。仍然禁止真实资金；通过校验不改变候选的
验收状态。原 `wallet_inspector_desktop.py` 及 Rust/Go 后端、协议、锁、容量和 v2-v9 包合同不变。

## 两个操作

入口为可信仓库中的 `scripts/inspector_source_bundle.py`。仅用 Python 3.10+ 标准库；构建另需
可信 Git 与已有本地 Git 对象，校验不需要 Git/Tk。构建缺少对象会失败，不连接远端补下载。
工具本身必须从可信来源取得，不要从待验证目录运行一个自带“校验器”。

Windows PowerShell 示例（将路径与完整40位提交号替换为独立确认的实际值）：

```powershell
$repo = 'C:\Projects\Zevune'
$commit = '<独立确认的40位小写Git提交号>'
$out = 'C:\ZevuneDeliveries\inspector-source-v1'
python "$repo\scripts\inspector_source_bundle.py" --no-real-funds build --repository $repo --source-commit $commit --output $out
```

父目录必须预先存在，输出目录必须全新、位于源码仓库之外。构建仅从指定提交的 Git blob 读取
九份 Python 源码和原核查指南，不从工作目录复制，也不包含后端程序、密码、钱包、测试数据、
日志、工具自身或新的交付说明。工作区修改、未跟踪文件及 Git 换行/过滤器不参与构建。
准确完整提交号必填；HEAD、分支、标签、缩写和隐式“最新”不被接受。Git replacement refs 与
继承的其他仓库环境变量不改变选定对象。构建不会切换、重置或修改已有源码文件。

成功输出 JSON 中的 `manifest_sha256` 应由可信构建方通过独立渠道保留/交付。再次校验时：

```powershell
$manifest = '<独立取得的64位小写清单SHA256>'
python "$repo\scripts\inspector_source_bundle.py" --no-real-funds verify --bundle $out --source-commit $commit --manifest-sha256 $manifest
```

不要从收到的清单自行算出摘要再将其作为“独立可信摘要”。同时修改文件及同包清单不能取得外部
摘要的信任。源码提交及树字段由可信构建过程记录；离线校验并未独立取得远端 Git 历史或验证
提交者签名，也不把清单内的字段本身当成完整的 Git 成员关系证明。

校验成功只说明本次读取的固定字节与独立清单摘要一致，`accepted` 与 `real_funds_allowed`
始终为 false，`code_signature_verified` 为 false；不会自动启动桌面、导入包内代码或调用后端。

## 校验后显式启动

确认来源、代码验收状态及独立后端信息后，可由操作者另行启动无价值测试界面：

```powershell
python "$out\wallet_inspector_desktop.py" --no-real-funds
```

运行需要 Python/Tk、图形桌面及独立核验的原 `zevune-wallet-local` 后端。后端不在源码包内，
应继续放在原已核验的程序包目录；不要把新源码塞进旧 v9 精确文件清单目录。Linux 命令相同，
路径改为绝对 POSIX 路径。`--help` 不要求图形环境，也不要求后端。

包中的共享依赖仍含原命令行工具能力；“只读”约束针对指定核查桌面入口，不声称其他共享脚本
被物理移除了所有写入能力。该入口只调用原 op9，具体密码、回执、容量及关闭语义见包内原指南。

## 固定格式与失败策略

格式名 `zevune-inspector-source-1`，平面目录恰好10份 payload 和一个 `INSPECTOR-SOURCE.json`。
每份 payload 至多512 KiB、总量至多4 MiB、清单至多32 KiB。清单绑定固定文件名、原源码路径、
长度、SHA256、Git blob ID、完整提交与树 ID。文件缺失、多出、重复、大小或摘要不符均拒绝。
数字0不等于安全标志false；未知格式、未知字段、重复JSON字段和不规范路径不能被静默接受。

构建在创建目标前核对源码范围和静态导入关系；普通静态导入引用了未交付的非标准库模块时拒绝。
这只是防止遗漏依赖，不是 Python 动态行为分析或恶意代码沙箱。运行代码依然必须审查。

拒绝符号链接、Windows reparse point、硬链接 payload、非普通文件和链接父目录。读取时使用
文件身份/大小/修改状态复核，并在末尾重新核对目录、清单及已读文件元数据。
路径与句柄的设备、文件ID、大小、类型、链接数及reparse标志必须相同；各自的完整元数据
（含权限和时间戳）分别以前后同一API的基线核对，不要求Windows两种查询方式呈现相同时间戳。这不构成跨文件
原子快照、完整ACL检查，也不能防御恶意操作系统、精心竞争或校验后的篡改。应停止其他写入并
使用可信父目录和主机；校验不是将来的执行锁，修改或移动后应重新核验。

构建使用仅创建语义，每份文件写完同步，清单最后创建。任何错误保留部分目标，不删除、覆盖或
自动重试；遇到已有目标直接失败。普通写入/同步错误不报告成功。未声明目录fsync、事务安装、
物理断电安全或严格全局执行时限；失败后留下完整字节也不是本次构建成功，必须另行独立校验。

工具退出码：成功0、失败1、参数错误64、用户中断130。运行错误仅给固定脱敏提示，不回显路径、
错误对象或参数。无实时监控、网络下载、自动激活、后台更新或钱包操作。

## 验证范围

`test_inspector_source_bundle.py` 使用真实 Git 对象、文件与子进程，验证固定范围、旧包合同隔离、
所有 payload 篡改、清单攻击、静态依赖遗漏、链接/路径、并发变更检查、创建失败与普通CLI。
合成错误仅注入拒绝或IO失败，不替代任何正向钱包密码学认证。

`check_inspector_source_delivery.py` 在仓库外建立真实交付目录，先用独立进程校验，再显式运行
原26项真实Tk测试。子进程在隔离Python环境中强制核对全部九个运行模块确实来自交付目录，
测试后再次核验字节。传入 `--backend` 时额外运行原六组真正钱包认证/预留不变场景；不传入时
明确报告该原生部分未执行。CI在Windows与Linux分别重建固定Rust1.98.1原后端并传入此参数。

来源语义参照 Git 官方 `GIT_NO_REPLACE_OBJECTS` / `GIT_NO_LAZY_FETCH` 与 Python `os.lstat` /
`os.open` 文档。具体测试结果必须对应准确候选提交，不沿用历史结果作为新版本验收。

本模块不解决Issue23、P2/P4全阶段、网络隐私或外部专业安全审计；独立非作者审查之前不合入main。
