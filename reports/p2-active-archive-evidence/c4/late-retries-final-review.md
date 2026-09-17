# C4 晚到重跑最终记录

C4 首轮冻结快照保持 NOT_ACCEPTED：18 success、5 cancelled。根代理此前已请求的四个同源单 job 重跑现均完成，实际2 success、2 cancelled；不再触发重跑，不转移 C5/C6 验收信用。

| 新 job | 结果 | 原生 UTC 起止 | 完整 raw B | 实际测试边界 |
|---|---|---|---:|---|
|105156825897 Windows wallet|success|09:53:00–10:17:52|59,932|default18结果/146 passed；Clippy/drift全部完成|
|105160660583 Ubuntu bridge|success|10:06:04–10:25:13|75,567|default18结果/153 passed；Go真实互操作/race/fuzz/drift全部完成|
|105159915319 Windows crypto|cancelled|10:03:31–10:28:43|55,427|default18结果/146 passed，lib132用1125.51s；随后Clippy依赖检查取消，drift skipped|
|105160666174 Windows integrated|cancelled|10:06:04–10:31:17|60,300|13完整结果/139 passed，lib132用1098.11s；real_bundle前两具名用例ok但无该target结果，第三real_proofs_two_hops_and_adversarial_cases只有开始；Clippy/build及后续Go/drift未完成|

两个取消均只有 operation canceled 原文，未补推断为测试失败或确定超时根因。四组成功兄弟 job 的新 ID 仍只映射首轮已有执行，不计新运行、不复制相同日志。最终27份独立执行完整日志为首轮23＋重跑4，共1,573,284 B；其中首轮结果与重跑结果分别保留，不能写成首次全矩阵通过。

本附录 JSON 保存精确 SHA、逐 step 结论与实际边界；8份 late-run-*-final.json 保存四个 run 的 attempt2最终run/jobs原件。所有新大日志按.part、完整字节验证、SHA及原子发布方式保存。先前 stable-archive-manifest.json 和首轮总报告均保持不变，新增文件使用独立 late-stable-archive-manifest.json。
