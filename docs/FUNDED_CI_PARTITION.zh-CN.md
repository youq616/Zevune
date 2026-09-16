# P2.4 验收修复：完整测试目标分组，不减少验证

本改动接续 `e125750aba769bd5f216019e4d9680cc993aa89b`。上一轮
`funded-wallet-consensus` 的 Windows 原生任务 `104684728596` 在原有30分钟
任务期限触发取消。日志显示库单元测试116项已通过，之后的集成测试尚未全部
完成，Python/Rust互操作与四节点付款步骤未执行。这不能记作完整验收成功。

## 改动

同一工作流在 Windows 和 Ubuntu 各运行两个独立任务，仍保留每个任务30分钟
上限、两个编译任务与两个Rayon线程。没有增加权限、放宽警告、关闭校验或缩减
测试数据，也没有改变Rust、Go、钱包、协议及依赖源码。

- `funded-library`：完整的实验特性库单元测试，包含真实证明、备份、索引、故障
  注入与路径身份检查。
- `funded`：所有可执行程序单元测试、所有集成测试和文档测试，然后运行原有
  Python/Rust互操作、真实非零金额四节点付款与加密恢复。全部严格静态检查、
  Python测试和依赖未变化检查仍保留。

两组在隔离的runner执行，不在同一Cargo输出目录并发重建。没有把一个任务的
成功当作另一组成功；整个工作流必须全部成功，取消或任何失败仍阻止验收。

## 防止分组遗漏

`scripts/run_funded_rust.py` 调用 Cargo 的 `metadata --no-deps --locked`，读取
当前固定crate的真实目标清单。库交给library组，其余bin/test目标按名字全部
交给interfaces组，并单独执行文档测试。不是靠手工维护若干测试名称或模糊匹配。

新增bin/test目标自动加入；未知目标种类、未选择的required-features、关闭test
或关闭库doctest、错误workspace、非法名称或重复目标会明确失败，要求更新分组
策略。当前crate没有example或bench；未来添加时不能静默漏过。

所有测试继续使用`--locked --release --features local-funding-lab`与单测试线程。
不使用`--skip`、`--ignored`、`--no-run`或名称过滤器。`--plan-only`只打印执行
计划，不输出完成标识，不能被当作测试结果。子进程非零立即失败，不执行后续
计划命令，不吞掉真实失败。

`--tests`并不是“只运行integration tests”：它也包含库和可执行程序测试。
因此interfaces组使用从元数据获得的明确`--bin`/`--test`目标，文档测试另行
执行，避免再次执行完整库测试。Cargo目标选择语义依据：
https://doc.rust-lang.org/cargo/commands/cargo-test.html#target-selection

## 验证范围

新增Python回归仅测试目标分配、错误传播及计划输出，不模拟证明验证。验证应
比较两组目标并集与原crate完整目标集合，检查无重叠，并实际执行两组真实
Cargo命令。Cargo源码中的平台/特性条件仍正常生效，例如默认worker拒绝测试
资金的用例在默认特性工作流执行，不能把实验特性下的0测试目标说成也执行了它。

本说明不是测试通过记录。本轮准确提交的原生CI、本人的冻结后复核与不同代理
的独立审核须分别读取后才可合入。上一次提交的测试和审查不能自动批准新的
脚本和工作流。该改动是P2.4验收收尾，不是已经开发完增量备份或整个P2。

## 接手复核：最后构建也固定工具链

接手审核发现，interfaces组最后的 `cargo build --manifest-path ...` 在仓库根目录
执行，不能依靠下级 `integration/orchard/rust-toolchain.toml` 选择编译器。
rustup按当前目录向上查找工具链配置；`--manifest-path`只选择Cargo清单，
安装1.98.1本身也不等于将其设为默认值。

该构建命令现在显式使用 `cargo +1.98.1 build`，使后续互操作和四节点测试使用
指定版本构建的程序。调度器仍在清单所在目录运行元数据和全部测试命令；
其他编译选项、测试目标、平台、超时与权限均不改变。此前的成功CI保留为
此前提交的执行记录，不代替修正后提交的验证。

依据：[rustup工具链覆盖规则](https://rust-lang.github.io/rustup/overrides.html)。
