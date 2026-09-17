原生证据独立审核结论：**PASS**。准确 C4 候选的 10 个 PR 工作流、23 个 jobs 均已实际完成并成功，23 份完整原生 job 日志已经读取、保存和计算 SHA-256。双平台真实 32+1 付款资源实验均通过独立原始 artifact 审核。此结论限于下述冻结场景与验收范围；代码独审原文另行归档，本审核没有编写项目 Rust、Go、Python 运行源码或工作流。

仓库：[youq616/Zevune](https://github.com/youq616/Zevune)，[PR11](https://github.com/youq616/Zevune/pull/11)。本机读审、原始 API / 日志 / artifact 收集及独立 JSON 算术验证由 `/root/p2_resource_native_audit` 完成；旧九工作流另由 `legacy_matrix` 收集完整原生日志并交独立子审核逐目标、逐测试名复核。PR/source events 与 push API 观察冻结于 `2026-09-17T06:48:04.656Z`，旧九 PR 工作流的最终 API 观察为 `2026-09-17T06:48:08.418Z`；机器快照生成于 `2026-09-17T06:56:51.171037+00:00`。生成时间不代表重新读取 API 的时间。

| 身份 | 准确值 |
| --- | --- |
| Source head | cd5fe98053ce64e1acc6796dae44ec0e822c124f |
| Source tree | cc60276872b26bbd2be1b0a0a62fceac325f5b45 |
| Base/main | 8324ec8bd153d9502e3e6761d25bfe281a5f3b44 |
| PR 实际 checkout | caece5bb6e82adc11156601880d7e1b4f2b5f463 |
| PR synthetic tree | cc60276872b26bbd2be1b0a0a62fceac325f5b45 |
| Push 实际 checkout | cd5fe98053ce64e1acc6796dae44ec0e822c124f |

每个 PR job 的实际 checkout 都来自其完整日志中的 `git log -1 --format=%H` 输出；合成提交的 Git 对象另经 GitHub API 核验，其父提交顺序为 base、source head，tree 与 C4 source tree 相同。运行记录、PR11 head/base、原始资源 setup/report 的 source/checkout/tree 相互吻合。Push 使用 source head 本身；两类事件独立列示。

PR 合计 283 个已记录步骤：success=274、skipped=9。下表的 step 数含 setup、post 和 complete；跳过步骤保留名称及条件，不计入执行覆盖。

| PR 工作流 / Run | Job | 结果 | 步骤 success / skipped | 完整日志 bytes / SHA-256 |
| --- | --- | --- | --- | --- |
| [active-ledger-growth / 35187184931](https://github.com/youq616/Zevune/actions/runs/35187184931) | [source / 105091658097](https://github.com/youq616/Zevune/actions/runs/35187184931/job/105091658097) | success | 9 总数；9 / 0 | 22861 / `8b8f92e3dd5cfc717acd6e2cd192514030a0e594e4804d28160c9c9a91d91360` |
| [active-ledger-growth / 35187184931](https://github.com/youq616/Zevune/actions/runs/35187184931) | [growth (ubuntu-latest) / 105098784268](https://github.com/youq616/Zevune/actions/runs/35187184931/job/105098784268) | success | 11 总数；11 / 0 | 38873 / `da97f94bde6c1a8ac53416f0061aedbab47eabd9c14353405f3acf8e37738c41` |
| [active-ledger-growth / 35187184931](https://github.com/youq616/Zevune/actions/runs/35187184931) | [growth (windows-latest) / 105098784318](https://github.com/youq616/Zevune/actions/runs/35187184931/job/105098784318) | success | 11 总数；11 / 0 | 39711 / `48b977d30c1b467bb144f75253380292b8524bbe5ebbca8d86c7eda80bae8164` |
| [consensus-laboratory / 35187184977](https://github.com/youq616/Zevune/actions/runs/35187184977) | [integration (windows-latest) / 105091658260](https://github.com/youq616/Zevune/actions/runs/35187184977/job/105091658260) | success | 12 总数；11 / 1 | 43147 / `119c62f5389c0f1bdfd715bd652dac9587f17c16fe76c599c9be4bcb6183e65c` |
| [consensus-laboratory / 35187184977](https://github.com/youq616/Zevune/actions/runs/35187184977) | [integration (ubuntu-latest) / 105091658437](https://github.com/youq616/Zevune/actions/runs/35187184977/job/105091658437) | success | 12 总数；12 / 0 | 42513 / `2a77ad1e39747b44b9b0b342de3d45c87b5b6d5fc8eb6e142b21c6f0bde56907` |
| [funded-wallet-consensus / 35187185000](https://github.com/youq616/Zevune/actions/runs/35187185000) | [funded-library (ubuntu-latest) / 105091658355](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658355) | success | 9 总数；9 / 0 | 49028 / `c8e1c544922ed4c6910bb2129987e34dbe8a7e0ecfcaaf96b44a935dd81a8337` |
| [funded-wallet-consensus / 35187185000](https://github.com/youq616/Zevune/actions/runs/35187185000) | [funded-library (windows-latest) / 105091658433](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658433) | success | 9 总数；9 / 0 | 48359 / `db78022fb3469290df68d8def45b667fde5e56130e3009bd22472326aa8b7007` |
| [funded-wallet-consensus / 35187185000](https://github.com/youq616/Zevune/actions/runs/35187185000) | [funded (ubuntu-latest) / 105091658522](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658522) | success | 15 总数；15 / 0 | 89398 / `56597e9aa83b072daf7ed0d6c8b770556fc9add727ac26b5f5a0eb5b233ae777` |
| [funded-wallet-consensus / 35187185000](https://github.com/youq616/Zevune/actions/runs/35187185000) | [funded (windows-latest) / 105091658599](https://github.com/youq616/Zevune/actions/runs/35187185000/job/105091658599) | success | 15 总数；15 / 0 | 91204 / `cfb8e008b66f13a8f6d3c41d6762f98399c33d1e7540f2cd19ad2e0e4c74d3ee` |
| [local-network-operator / 35187185059](https://github.com/youq616/Zevune/actions/runs/35187185059) | [operator (windows-latest) / 105091658402](https://github.com/youq616/Zevune/actions/runs/35187185059/job/105091658402) | success | 14 总数；13 / 1 | 96036 / `ddaf5fb49ebccab40a83c2ae46482f98b1536379992de209c41e9c98b3534a00` |
| [local-network-operator / 35187185059](https://github.com/youq616/Zevune/actions/runs/35187185059) | [operator (ubuntu-latest) / 105091658662](https://github.com/youq616/Zevune/actions/runs/35187185059/job/105091658662) | success | 14 总数；14 / 0 | 97718 / `448646e19fe02673ae8617049fef8fa8f63507f9c8c4e639d4a32103b3e3e25f` |
| [orchard-bridge / 35187184961](https://github.com/youq616/Zevune/actions/runs/35187184961) | [boundary (ubuntu-latest) / 105091658239](https://github.com/youq616/Zevune/actions/runs/35187184961/job/105091658239) | success | 16 总数；16 / 0 | 72499 / `026b658d97919550a8446ad9358aa6e18ba53ecf23cf2f701a7c7b8a965de0b9` |
| [orchard-bridge / 35187184961](https://github.com/youq616/Zevune/actions/runs/35187184961) | [boundary (windows-latest) / 105091658320](https://github.com/youq616/Zevune/actions/runs/35187184961/job/105091658320) | success | 16 总数；14 / 2 | 69535 / `8c094ce6b2ea4901c6108026e8b72580436115efbbb5ed372ae3d75626119a6d` |
| [orchard-consensus-integration / 35187184995](https://github.com/youq616/Zevune/actions/runs/35187184995) | [integrated (ubuntu-latest) / 105091658266](https://github.com/youq616/Zevune/actions/runs/35187184995/job/105091658266) | success | 15 总数；15 / 0 | 73727 / `5a42d72317570dab8b363e8ac3085d759a1be0e537cb725f9d6ebaa369ba37e0` |
| [orchard-consensus-integration / 35187184995](https://github.com/youq616/Zevune/actions/runs/35187184995) | [integrated (windows-latest) / 105091658449](https://github.com/youq616/Zevune/actions/runs/35187184995/job/105091658449) | success | 15 总数；13 / 2 | 71629 / `f4b51a61421b3916e84fed026acd4dddd6dfab94dfbf807d6ec84f8ea8deee08` |
| [orchard-cryptography-laboratory / 35187185001](https://github.com/youq616/Zevune/actions/runs/35187185001) | [tests (windows-latest) / 105091658125](https://github.com/youq616/Zevune/actions/runs/35187185001/job/105091658125) | success | 9 总数；9 / 0 | 57093 / `d5598d2593328fe45fd5d8f23f73f7ae33661f1271ccab4cb54b322ab0f7f275` |
| [orchard-cryptography-laboratory / 35187185001](https://github.com/youq616/Zevune/actions/runs/35187185001) | [tests (ubuntu-latest) / 105091658428](https://github.com/youq616/Zevune/actions/runs/35187185001/job/105091658428) | success | 9 总数；9 / 0 | 57543 / `3a398edef8b36a6a061a999b601c6a903dc165641cf505b59f6b6555dc8977ad` |
| [payment-resource-baseline / 35187185033](https://github.com/youq616/Zevune/actions/runs/35187185033) | [resources (ubuntu-latest) / 105091658303](https://github.com/youq616/Zevune/actions/runs/35187185033/job/105091658303) | success | 15 总数；15 / 0 | 54923 / `dbf818f452af5506e7c441c616e142001828eb82d685f8fdca720e57558874f1` |
| [payment-resource-baseline / 35187185033](https://github.com/youq616/Zevune/actions/runs/35187185033) | [resources (windows-latest) / 105091658502](https://github.com/youq616/Zevune/actions/runs/35187185033/job/105091658502) | success | 15 总数；15 / 0 | 56173 / `055a78ae6d26f06305692b0b34b802c3d89f6010785b4e5a4f8a6df87532fcc2` |
| [scaffold-tests / 35187184944](https://github.com/youq616/Zevune/actions/runs/35187184944) | [tests (windows-latest) / 105091658117](https://github.com/youq616/Zevune/actions/runs/35187184944/job/105091658117) | success | 12 总数；9 / 3 | 19227 / `2475b6b1b5ae05f109b7393ac4b3c481cc5055a10815bcd3a2fb63d66bb6bb73` |
| [scaffold-tests / 35187184944](https://github.com/youq616/Zevune/actions/runs/35187184944) | [tests (ubuntu-latest) / 105091658406](https://github.com/youq616/Zevune/actions/runs/35187184944/job/105091658406) | success | 12 总数；12 / 0 | 21325 / `cda0c83b526275900c62bf1ba7a1320e317df4d9e2629f0b2296b9535bef7c18` |
| [wallet-laboratory / 35187185026](https://github.com/youq616/Zevune/actions/runs/35187185026) | [wallet (windows-latest) / 105091658198](https://github.com/youq616/Zevune/actions/runs/35187185026/job/105091658198) | success | 9 总数；9 / 0 | 57066 / `c0f58f81b5bef630fd7b717572861f0cfe5b302de52d440559d86507144b3c32` |
| [wallet-laboratory / 35187185026](https://github.com/youq616/Zevune/actions/runs/35187185026) | [wallet (ubuntu-latest) / 105091658291](https://github.com/youq616/Zevune/actions/runs/35187185026/job/105091658291) | success | 9 总数；9 / 0 | 57502 / `fc33f7bf9a7cf9dba81916abdb4e2fb350dbfffe0b4eb133d6d592822362a305` |

旧矩阵的 100000-block growth 两个子 jobs 在 source job 成功后由 GitHub 实际创建；没有将尚未生成的矩阵项预计为通过。该实验保留自己的真实边界付款、完整重放和跨段结果，与新增 33 付款资源实验独立。全部实际 Go package 完成行、race/fuzz 命令和最后执行计数、Rust 各 Cargo target/result/cohort 完成行、Python 逐名结果及跳过原因保存在 `cd5fe98-ci.json`。

Rust 数字按实际命令执行分别记录。多个 cohort 的 filtered 数是实际过滤结果，不能抹成零；重复套件的 passed 合计是执行观察数，不是互异测试覆盖。Cargo stdout/stderr 可能交错，目标和结果按各自完整执行顺序配对，并经逐测试名复核。零测试目标明确保留，安装 clippy component 本身也不给 clippy 执行信用。

| PR 原生 job | Cargo targets / results | lib 各次结果 | 全部结果 passed / failed / ignored / filtered |
| --- | --- | --- | --- |
| funded-wallet-consensus / funded-library (ubuntu-latest) / 105091658355 | 1 / 1 | passed 140, filtered 0 | 140 / 0 / 0 / 0 |
| funded-wallet-consensus / funded-library (windows-latest) / 105091658433 | 1 / 1 | passed 134, filtered 0 | 134 / 0 / 0 / 0 |
| funded-wallet-consensus / funded (ubuntu-latest) / 105091658522 | 19 / 19 | 无 lib test 目标 | 49 / 0 / 0 / 0 |
| funded-wallet-consensus / funded (windows-latest) / 105091658599 | 19 / 19 | 无 lib test 目标 | 49 / 0 / 0 / 0 |
| orchard-bridge / boundary (ubuntu-latest) / 105091658239 | 17 / 17 | passed 121, filtered 0 | 135 / 0 / 0 / 0 |
| orchard-bridge / boundary (windows-latest) / 105091658320 | 17 / 17 | passed 115, filtered 0 | 129 / 0 / 0 / 0 |
| orchard-consensus-integration / integrated (ubuntu-latest) / 105091658266 | 17 / 17 | passed 121, filtered 0 | 135 / 0 / 0 / 0 |
| orchard-consensus-integration / integrated (windows-latest) / 105091658449 | 17 / 17 | passed 115, filtered 0 | 129 / 0 / 0 / 0 |
| orchard-cryptography-laboratory / tests (windows-latest) / 105091658125 | 17 / 17 | passed 115, filtered 0 | 129 / 0 / 0 / 0 |
| orchard-cryptography-laboratory / tests (ubuntu-latest) / 105091658428 | 17 / 17 | passed 121, filtered 0 | 135 / 0 / 0 / 0 |
| wallet-laboratory / wallet (windows-latest) / 105091658198 | 17 / 17 | passed 115, filtered 0 | 129 / 0 / 0 / 0 |
| wallet-laboratory / wallet (ubuntu-latest) / 105091658291 | 17 / 17 | passed 121, filtered 0 | 135 / 0 / 0 / 0 |

Python 的 Ran 数包含 skip；实际执行数与平台跳过分别如下。仅在 Windows 运行的三个新增文件共享场景，在 Windows 资源 suite 和完整 suite 都逐项 `ok`。唯一 Windows Python skip 是 `test_proc_pinned_identity_rechecks_both_sides_of_memory_read` 的 Linux proc descriptor 语义；Linux 的三个 skip 是新增 Windows 原生共享场景。

| PR 原生 job | Ran | 实际 pass | skip | 秒 |
| --- | --- | --- | --- | --- |
| funded-wallet-consensus / funded-library (ubuntu-latest) / 105091658355 | 13 | 13 | 0 | 0.007 |
| funded-wallet-consensus / funded-library (windows-latest) / 105091658433 | 13 | 13 | 0 | 0.025 |
| funded-wallet-consensus / funded (ubuntu-latest) / 105091658522 | 135 | 132 | 3 | 2.629 |
| funded-wallet-consensus / funded (windows-latest) / 105091658599 | 135 | 134 | 1 | 8.241 |
| local-network-operator / operator (windows-latest) / 105091658402 | 135 | 134 | 1 | 8.228 |
| local-network-operator / operator (ubuntu-latest) / 105091658662 | 135 | 132 | 3 | 2.786 |
| payment-resource-baseline / resources (ubuntu-latest) / 105091658303 | 53 | 50 | 3 | 2.488 |
| payment-resource-baseline / resources (windows-latest) / 105091658502 | 53 | 52 | 1 | 5.357 |

工作流层面实际跳过的步骤如下；这些与 Python unittest skip 是两套不同计数。

| Job | 跳过步骤 | 原条件 | 执行信用 |
| --- | --- | --- | --- |
| 105091658260 | Adapter race checks | runner.os == 'Linux' | 未运行 |
| 105091658402 | Race and bounded fuzz checks | runner.os == 'Linux' | 未运行 |
| 105091658320 | Boundary race checks | runner.os == 'Linux' | 未运行 |
| 105091658320 | Bounded decoder fuzz checks | runner.os == 'Linux' | 未运行 |
| 105091658449 | Real adapter race checks | runner.os == 'Linux' | 未运行 |
| 105091658449 | Local IPC race and bounded fuzz | runner.os == 'Linux' | 未运行 |
| 105091658117 | Race detector | runner.os == 'Linux' | 未运行 |
| 105091658117 | Bounded decoder fuzz smoke test | runner.os == 'Linux' | 未运行 |
| 105091658117 | Bounded journal decoder fuzz smoke test | runner.os == 'Linux' | 未运行 |

新增资源工作流的 Go fmt/vet/显式测试标签编译、Rust 固定 release 构建及 source/lock 无漂移步骤双平台均成功。`-run '^$'` 的编译检查不计作测试执行。真实 Go 完成行分别为 Ubuntu `TestActivePaymentResources32AndRecovery (169.32s)`、Windows `(215.25s)`；二者都输出实际 33 付款和 `PAYMENT_RESOURCE_RESULT passed`，不是只看 workflow 绿灯。

两份原始资源 ZIP 的官方 SHA-256 与本地下载 bytes 完全一致，ZIP 恰好仅有 `payment-resource-setup.json`、`payment-resources.json` 两个允许的公开 JSON。解压原件与 ZIP 成员逐字节复核；没有下载钱包或工作负载临时目录。初始 setup 的 `not_started` 是 setup 时点记录，不解释为最终状态。

| 平台 / Artifact | ZIP bytes / SHA-256 | 原始 report bytes / SHA-256 | 独立原件审核 |
| --- | --- | --- | --- |
| ubuntu / 10481864543 | 9287 / `88cdc486705bdaf6dd2917a175374f0b7f415a3abed5e445369c82ebecf69681` | 130207 / `267237f2487d95c9833fe64739673430ad1b3670c9788912558971b1c640ac16` | cd5fe98-ubuntu-independent-artifact-audit.json |
| windows / 10483445741 | 9433 / `9d5f14be60c0995881f7343b6995d706ff09f9bfcb353435b7a75c3ed24d37de` | 131239 / `443f57a7366f2149535dc95459c4f8b104c8569de4dc70fca7310b18c5ad0a96` | cd5fe98-windows-independent-artifact-audit.json |

独立验证器没有调用候选的语义校验函数。它从冻结实验次序重建全部 181 个操作，逐一匹配 362 条 started/completed 记录，包括第 32 笔后的 close、磁盘检查、新 worker reopen、钱包恢复，以及第 33 笔 prepare、精确 outbox restore 的相对顺序。每个平台恰有 9 个完整事件、9 次完整双进程采样、18 个正的有效 OS 样本、3 个具有稳定创建身份的进程生命周期；result timings 与全部 completed progress 逐项相同。14 个结果检查名及值全都核对通过，Go exit=0，failures 为空，unfinished_operation=null，last_confirmed_committed_blocks=33，registered_children_exit_confirmed=true。

| 角色 / 世代 | Ubuntu OS 生命周期峰值 B / MiB | Windows OS 生命周期峰值 B / MiB | 固定门槛 B |
| --- | --- | --- | --- |
| worker / 1 | 11,509,760 / 10.976562 | 13,123,584 / 12.515625 | 1,073,741,824 |
| worker / 2 | 11,649,024 / 11.109375 | 12,767,232 / 12.175781 | 1,073,741,824 |
| scenario / 1 | 180,588,544 / 172.222656 | 118,714,368 / 113.214844 | 1,073,741,824 |

上述值是九个握手观察点实际读取的每个进程世代 OS 生命周期驻留高水位：Linux VmRSS/VmHWM，Windows WorkingSetSize/PeakWorkingSetSize。第一代 worker 5 个样本、第二代 4 个、scenario 9 个；所有样本 identity 稳定、current≤peak、累计 peak 不下降、peak≤1 GiB。它们不是每阶段局部峰值、私有 heap、全机预算、内存分配硬限制或跨平台内存效率比。Go coordinator 与 Python supervisor 不在两个被测角色中；scenario 同时含 prover、独立账本、两钱包、缓存和 KDF。

| 总计时 / ms | Ubuntu | Windows |
| --- | --- | --- |
| Go workload | 169314 | 215236 |
| Supervisor | 169468 | 216311 |
| Supervised process | 169395 | 215561 |
| 181 个完成操作合计 | 168638 | 212500 |

固定预算未提高：Go 1200 秒、supervisor 共用截止 1230 秒、worker 启动和单请求各 60 秒、scenario 单响应 90 秒、采样握手 15 秒。按实际记录汇总的组合操作计时如下；一个组合操作可包含多个生产调用，不能改称单次 RPC 延迟。毫秒值 0 可表示小于计时精度，不表示没有成本。

| 组合操作 | 次数 | Ubuntu sum / min / max ms | Windows sum / min / max ms |
| --- | --- | --- | --- |
| scenario_start | 1 | 7547 / 7547 / 7547 | 9578 / 9578 / 9578 |
| worker_create | 1 | 2087 / 2087 / 2087 | 2753 / 2753 / 2753 |
| wallet_sync | 34 | 13935 / 54 / 591 | 17865 / 68 / 756 |
| prepare | 33 | 120409 / 3299 / 4045 | 149122 / 3835 / 5210 |
| candidate | 33 | 8846 / 106 / 432 | 11996 / 136 / 588 |
| worker_commit | 33 | 823 / 11 / 423 | 1333 / 20 / 583 |
| scenario_apply | 33 | 1299 / 36 / 51 | 1777 / 49 / 61 |
| duplicate_rejection | 5 | 1516 / 148 / 419 | 2034 / 188 / 565 |
| worker_close | 2 | 0 / 0 / 0 | 3 / 1 / 2 |
| disk_check | 2 | 0 / 0 / 0 | 0 / 0 / 0 |
| worker_reopen | 1 | 3132 / 3132 / 3132 | 4120 / 4120 / 4120 |
| wallet_recover | 1 | 5611 / 5611 / 5611 | 7465 / 7465 / 7465 |
| outbox_restore | 1 | 3431 / 3431 / 3431 | 4446 / 4446 / 4446 |
| finish | 1 | 2 / 2 / 2 | 8 / 8 / 8 |

两平台全部九个检查点的逻辑状态与钱包记录 / 文件长度逐项一致：32 笔时 66 commitments、64 nullifiers、32000 fees、钱包记录50/50；完整重放与钱包恢复保持该状态；第33笔 outbox 恢复后51/50，最终33笔为68/66/33000、钱包52/51，最终逻辑308756 B、单段tail308616 B、钱包1713368/1680420 B。nullifiers 含填充 action，不能称为真实输入数。额外 `cd5fe98-resource-cross-platform-consistency.json` 核对本次观察到的 ledger header140 + 固定完整帧9352×高度，以及钱包header72 + 保存记录32948×记录数；不把这组观察量改成通用生产限制。

Windows 三个新增原生测试保留实际 outstanding DELETE handle：证明旧 Win32 share=3 返回错误32、CRT旧读取被拒绝，而新的只读 share=7 reader 能读取精确JSON/digest；相同内容但文件身份替换和读后大小变化仍被拒绝。成功读测试没有执行 rename。C3 原始失败只保留 `protocol_file_read_failed`，没有 stage、errno/winerror 或失败文件seq，因此这些确定性回归不能反推 C3 唯一根因。

截至 `2026-09-17T06:48:04.656Z` 冻结观察，同 source 另有 8 个 push 工作流、17 个 jobs，实际已保存 16 份完整 push 日志。Push 结论统计为 `{"success": 16, "null": 1}`；未完成项 `[105091649795]` 无测试完成信用，已观测终态非成功项 `[]`。重复 push 不延迟已完整通过的 PR 验收，也不增加互异覆盖。其逐 run/job/step 和已取得日志的 bytes/hash 单独列入机器快照。

C1 `8f0de0d`、C2 `b6df895`、C3 `9e46e03` 全部保留为历史，不给 C4 通过信用：C1 存在审核发现的全局操作次序漏洞，C1/C2 Windows 测试 fixture 对不存在的 killpg mock 失败；C3 的 fixture 已通过但真实资源读取中断，仅有有效公开进度前缀。C3 的 last_confirmed=27 是已观察计数，不等于最终磁盘高度；commit_outcome_uncertain=false 只反映已记录的未完成 worker_commit 状态，不能证明未观察的操作结果确定。原始诊断的文件及哈希在机器快照中引用，未改写。

验收边界仍是固定单机场景。33 笔不覆盖64项授权缓存淘汰、64 anchors、65536 commitments、256次钱包保存、活动段轮换或完整容量边界；旧100000块增长实验独立保留。这里没有生产 TPS / p95 / WAN / 网络 finality / cold-disk / 真实断电 / 磁盘满 / 全容量或外部安全审计结论。三个已注册子进程的退出均确认；原始 cleanup 同时明确 `precheckpoint_child_tree_cleanup_confirmed=false`，它不是进程沙箱或任意后代退出保证。P2 整体仍处于开发阶段。

完整机器快照：`cd5fe98-ci.json`，1349246 B，SHA-256 `4f0dc512e6c636c09358f302eb4d28fe2ea3d9b06afe649fe0b10f0ec0757c88`。其包含每个实际 run/job/step、checkout、native 完成行、日志长度和SHA、跳过名称、双平台原始 artifact/ref、各世代全部测量和组合计时。原件保存采用完整 connector 解码日志的 UTF-8 bytes，保留已提供的 BOM/CRLF；日志 SHA 是这些保存 bytes 的散列。所有结论均由这些准确 C4 观察支撑，后续 merge 或文档提交的继承关系应另行记录。
