**C3 fuzz 预算表述澄清；原生通过结论不变。**

2026-09-18 UTC，独立原生审核任务 `/root/p2_package_native_audit`。
本说明绑定 PR #17 的准确 C3 source
`cb0804e7c921a456cbbafab313b3a4a4501b8f5e`、tree
`21de343c12bc27cb1022ffd7ebd451abe0e61f29`。

原分项 `c3-native-nonrust-review.md` 为 19,741 B，SHA-256
`8f15ef020c7f1bfdb6bc09a7d67a43b61e47eb2cb372d993e441d761f8416597`。
其 fuzz 节开头关于“实际尾部耗时可能因收尾变为 4 s，但命令预算仍是固定 3 s”的说明，
**只适用于下表五个 `-fuzztime=3s` 命令**，不泛指全部八个引擎。
原分项随后逐项表格以及父审核报告的分类是准确的。

| Linux workflow | 实际引擎数 | 每个命令的准确预算 |
|---|---:|---|
| scaffold-tests | 2 | `-fuzztime=3s -parallel=2` |
| local-network-operator | 3 | `-fuzztime=3s -parallel=2` |
| orchard-bridge | 2 | `-fuzztime=10s -parallel=2` |
| orchard-consensus-integration | 1 | `-fuzztime=10s -parallel=2` |

因此，本轮实际为 **5 个 3 秒命令、3 个 10 秒命令，共 8 个真实 fuzz 引擎**，
全部使用 `-parallel=2`。实际输出的收尾耗时不改变命令参数；没有统一降为 3 秒。
各命令、执行次数和对应原日志见上述冻结分项的逐项表与 JSON。

本说明只消除报告用语歧义，没有产品、测试、CI 或预算修复，也没有重跑任何任务。
`PASS_NONRUST_NATIVE_C3` 与 `PASS_NATIVE_C3` 结论保持不变。原分项 MD/JSON
及父审核 MD/JSON 全部保持原字节和原 SHA-256；本说明作为追加原件独立归档。

对应原分项 JSON 为 516,810 B，SHA-256
`19d6cdaf3d44a3972883a2261115171b70b21a154fdb9e7c83487c2e8d16b30e`；
父审核 `c3-native-review.md` 为 14,595 B，SHA-256
`546ca765251ba5744f830567e31947cf0ffd9a63ae4164cab68124c4df884b6f`。
