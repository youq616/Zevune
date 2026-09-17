# C4 CI 开销诊断勘误（独立原件）

本勘误由非作者审核代理 `/root/p2_archive_review` 出具，只更正原诊断的一处证据描述，不修改候选代码、测试、工作流、原审核或原诊断。原诊断 `c4-ci-overhead-diagnostic.md` 保持原字节：11451 B，SHA-256 `d85901f61ea58ff5e068ae666af9fa4f4bf371efdc34687a0b839f04623260d8`。

经根代理指出后，我重新独立读取 `c4/job-105145581152.log`（71552 B，SHA-256 `0bcd032629d75209a336a7f4892943b3a6677bf92156922a9a795613478cdd6a`）。第 894 行记录 Ubuntu bridge 的 `go test -race ./internal/orchardbridge -count=1 -timeout=2m` 开始；第 905 行于 2026-09-17 10:03:31.5940782 UTC 明确输出 `ok github.com/youq616/Zevune/internal/orchardbridge 1.326s`；第 906 行于 10:03:31.6388747 UTC 才记录 `The operation was canceled.`。

因此，原诊断表中“race 无成功结果”的表述过宽，现更正为：**race 命令已有成功结果；所在步骤及 job 仍以 cancelled 结束，后续 fuzz/source-drift 没有完成验收。** 不能把取消的步骤、未执行的后续步骤或整个逻辑 gate 计为成功；同样不能抹去日志已经明确证明的 race 命令成功。本次错误属于我对命令结果与步骤状态的区分不够精确。

该更正不改变原诊断中重复构建固定验证密钥的静态证据与性能推断边界，不补足 C4 缺失的平台验收，也不为尚未审查的新候选 C5 提供任何验收信用。原 C4 代码审核仅适用于其已注明的准确 source/tree 和静态范围。
