# C6 原生审核：NOT_ACCEPTED

准确source `88146d54f2eaac39958ceaaea9e13f71832d536e`，tree `cbddd8e982eb9013d10010354e477b264e33841b`，base `6913d4ab2fda6956db37e0ceb49790a4518c2762`，PR13 synthetic `4bfe426af700303719bbc58344408e070af90467`。GitHub对象确认同tree、parents精确base/source；两份完整原件checkout均为该synthetic。

本次保存并审核的范围仅两份完整PR原件，共90,933 B：active-growth source job105167396367成功，Ubuntu integrated job105167396538失败。不是全部23job完成审核。source格式和双Go模块编译通过；完整原件22,777 B / SHA `cb5647a1089f7928ff897923edb355970ec4bc4fd4e410e060baf86142e83ddf`。

Ubuntu integrated原件68,156 B / SHA `a0368cb426a63c9ed4763cd88429f5744b0d0404b30c50e419f0e86903b40e40`。先完成全部default：18结果154 passed，lib140用66.85s，所有结果failed/ignored/filtered均0。新增wire::fixed_key_tests::concurrent_verifiers_share_only_the_fixed_key_and_keep_real_authorization_cold在raw639行10:32:56.4450467Z实际ok。default active_recovery_cli仍是0测试，不能计feature7通过。

随后原命令 cargo clippy --locked --release --all-targets -- -D warnings 在raw850行10:33:51.3461970Z报 duplicate_mod：src/../tests/support/fixtures.rs被多次加载为模块；lib test编译失败，raw859行退出101。同一个Rust步骤因此failure；后续worker build、全部Go集成/race/fuzz、最终drift未完成。该选定job测试实际已完整执行，不能称全部C6测试未运行；也不能以测试通过覆盖Clippy失败。

C6保持NOT_ACCEPTED。66.85s是本次精确library执行观察，不提供跨机器或生产性能保证。准确静态预期与后续默认原生独立子审只保留各自范围；任何新候选须单独确认来源并收集自己的原生矩阵。审计者未编辑源码、测试、workflow或触发CI。
