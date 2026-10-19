# PR #48 候选的 Actions 核验，2026-10-19

观察范围：head `5540cd494ad8a3655e8aa2dd77ed7fc91817de46` 关联的全部事件。GitHub Actions 查询返回 total_count=49，per_page=100 的第1页返回49项；47 success、2 failure，无正在运行项。此处的 run 数包含 push / pull_request 重复运行，不能称49套独立验收。

完整运行ID、事件、head SHA、时间与链接保存在 [机器可读快照](project-state-2026-10-19.json)。本次读取既有结果，没有重新执行运行时代码或把旧结果当作文档提交的新测试。

## retained lifecycle 两次失败

| 事件 | run | Windows job | Linux / race |
|---|---|---|---|
| pull_request | [38076005759](https://github.com/youq616/Zevune/actions/runs/38076005759) | [114282982219](https://github.com/youq616/Zevune/actions/runs/38076005759/job/114282982219)，failure | upstream Ubuntu 114282982388、race 114282982404 均 success |
| push | [38076001650](https://github.com/youq616/Zevune/actions/runs/38076001650) | [114282969468](https://github.com/youq616/Zevune/actions/runs/38076001650/job/114282969468)，failure | upstream Ubuntu 114282969464、race 114282969317 均 success |

两次 Windows 均在 `Run retained upstream and new lifecycle tests explicitly` 失败，后续 `Preserve original application shutdown and restart checks` 与 `Verify no tracked source drift` 为 skipped，不能写成通过。该步骤先执行 retained 模块的 go test 再执行 go vet；前面的测试失败不能证明后面的 vet 已执行。

### PR 事件的已读日志

- `TestWALCrash/many_non-empty_blocks` 失败；终止 panic 为 `precommit step; +2/3 prevoted for an invalid block: wrong Block.Header.LastBlockID`。
- `TestNodeSetPrivValIPC` 失败；`listen unix /tmp/kms.…sock: bind: A socket operation encountered a dead network.`
- 日志包含故障注入中的多条 `WAL panicked`；不把每条注入日志独立判成新根因。上面列的是测试失败与终止表现，根因仍需调查。

### push 事件的已读日志

- `TestWALCrash/many_non-empty_blocks` 失败，并记录 `Timed out waiting for new block`。
- `TestHandshakeReplaySome/mode_0_multi` 失败；终止 panic 为签名状态临时文件 rename 到 `priv_validator_state_…` 时 `Access is denied`，栈经过 `FilePVLastSignState.Save`。
- `TestNodeSetPrivValIPC` 同样为 Unix socket bind 的 `A socket operation encountered a dead network`。

这里只引用与工程诊断相关的最小摘录；没有重新发布完整日志中的大段WAL测试十六进制数据。完整日志链接保持可追溯。这些观察不证明几个表现有同一个根因，也不证明与 Issue #23 的增长时延属于同一故障。

## 源码身份

push Windows checkout 是 `5540cd494ad8a3655e8aa2dd77ed7fc91817de46`。PR Windows checkout 是 GitHub 合成合并提交 `9ecd55891b29d4d981324428d758f662a73a8391`，并非字面上的 head SHA；已另读两者 Git tree，均为 `0a287892cfa97347e496b25a334f919847daecca`。因此本记录明确保留提交不同、源码树相同的事实，不把所有工作流都一概称为直接checkout head。

Linux retained upstream 与 race 任务成功，包含对应生命周期与原集成race步骤；这不能豁免 Windows 失败。PR #48仍是草稿且未合并；这份报告不是非作者代码验收或专业安全审计。
