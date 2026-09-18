"""Freeze a rejected candidate review from its complete immutable originals."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HEAD = '61c691270b91aece076177cb757e51e0e63fe310'
BASE = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
TREE = '56dad7fdaad64b2b29ddac6b9585b8695aa465d7'
CHECKOUT = 'bd710cf4c985012ca23e86c333567ce116de72bb'


def identity(path):
    raw = (ROOT / path).read_bytes()
    return {'path': path, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read(path):
    return json.loads((ROOT / path).read_bytes())


manifest = read('c1-native-original-manifest.json')
for file in manifest['files']:
    assert identity(file['path']) == file
assert len(manifest['files']) == 56
assert sum(file['bytes'] for file in manifest['files']) == 1367731
assert {str(p.relative_to(ROOT)) for p in (ROOT / 'c1-native').rglob('*') if p.is_file()} == {f['path'] for f in manifest['files']}
structure = read('c1-native-review-structural.json')
assert structure['candidate'] == HEAD and structure['checkout'] == CHECKOUT
assert (structure['log_count'], structure['log_bytes'], structure['decoded_lines']) == (21, 1056143, 12260)
assert structure['rust_harnesses'] == structure['rust_passed_executions'] == 0
assert sum(len(row['format_hunks']) == 30 for row in structure['records']) == 17
nonrust = read('c1-native-nonrust-review.json')
assert nonrust['conclusion'] == 'C1_REJECTED_NATIVE_FMT_FAILURE_NONRUST_LIMITED_COVERAGE_ONLY'
assert (nonrust['base'], nonrust['source'], nonrust['tree'], nonrust['checkout']) == (BASE, HEAD, TREE, CHECKOUT)
assert (ROOT / 'c1-native-nonrust-review.md').is_file()
runs = read('c1-native/runs.json')
assert runs['total_count'] == len(runs['workflow_runs']) == 10
jobs = []
rows = []
for run in runs['workflow_runs']:
    assert run['head_sha'] == HEAD and run['event'] == 'pull_request'
    assert run['run_attempt'] == 1 and run['status'] == 'completed'
    full = read(f'c1-native/run-{run["id"]}.json')
    for field in ['id', 'name', 'head_sha', 'event', 'run_attempt', 'status', 'conclusion']:
        assert full[field] == run[field]
    current_jobs = read(f'c1-native/jobs-{run["id"]}.json')
    assert current_jobs['total_count'] == len(current_jobs['jobs'])
    for job in current_jobs['jobs']:
        assert job['head_sha'] == HEAD and job['run_id'] == run['id']
        assert job['run_attempt'] == 1 and job['status'] == 'completed'
        if job['conclusion'] == 'skipped':
            assert job['name'] == 'growth' and not job['steps']
        jobs.append(job)
    rows.append({'workflow': run['name'], 'run': run['id'], 'url': run['html_url'],
                 'conclusion': run['conclusion'], 'jobs': current_jobs['total_count']})
assert Counter(job['conclusion'] for job in jobs) == Counter(failure=17, success=4, skipped=1)
step_counts = Counter(step['conclusion'] for job in jobs for step in job['steps'])
assert step_counts == Counter(success=152, failure=17, skipped=92)
report = {
    'conclusion': 'REJECTED_NATIVE_C1', 'reviewer': '/root/p2_package_native_audit',
    'independent_non_author': True, 'base': BASE, 'source': HEAD, 'tree': TREE,
    'checkout': CHECKOUT, 'pr': 'https://github.com/youq616/Zevune/pull/17',
    'all_manifest_original_bytes_and_sha256_recomputed': True,
    'original_manifest': identity('c1-native-original-manifest.json'),
    'original_count': 56, 'original_bytes': 1367731,
    'runs': rows, 'jobs': jobs, 'step_counts': dict(step_counts),
    'structure': structure, 'source_inventory': read('c1-native-source-scope.json'),
    'nonrust_review': [identity('c1-native-nonrust-review.md'), identity('c1-native-nonrust-review.json')],
    'formatter_failure': {'files': 7, 'hunks_per_failed_job': 30, 'failed_jobs': 17,
        'normalized_full_diff_lines_per_job': 361,
        'normalized_full_diff_sha256': '4076072eb907a56badca018a344fdaf5a0981c908da46c0d00b672a4a1b72b36'},
    'nested_pr_head_is_current_not_historical_run_source': True,
    'followup_formatter_reconstruction': identity('c2-native-format-reconstruction.json'),
    'findings': [{'severity': 'stage_acceptance_blocker', 'code': 'C1_FMT_NOT_CANONICAL',
        'detail': '17 required native jobs failed the unchanged cargo fmt gate; 7 files, 30 identical hunks. No Rust test, Clippy, package CLI, genuine funded recovery, growth, resource workload or operator bundle credit for C1.'}],
    'scope_limits': ['No local native execution.', 'No source correctness approval is implied by limited Go/Python passes.',
        'C2 and later candidates require their own full exact-source matrix and independent reviews.',
        'No production, real-funds, finality, external-security-audit, real-power-loss or full-capacity credit.'],
}
json_path = ROOT / 'c1-native-review.json'
assert not json_path.exists()
json_path.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
table = '\n'.join(f'| {row["workflow"]} | [{row["run"]}]({row["url"]}) | {row["jobs"]} | {row["conclusion"]} |' for row in rows)
attachments = '\n'.join(f'| `{file["path"]}` | {file["bytes"]} | `{file["sha256"]}` |' for file in [
    identity('c1-native-review.json'), identity('c1-native-review-structural.json'),
    identity('c1-native-nonrust-review.md'), identity('c1-native-nonrust-review.json'),
    identity('c1-native-original-manifest.json'), identity('c1-native-source-scope.json'),
    identity('c2-native-format-reconstruction.json')])
text = f'''**REJECTED_NATIVE_C1 — PR #17 的 C1 未通过原生验收，不能按此候选合入或标记本阶段完成。**

审核日期：2026-09-18 UTC。独立审核任务 `/root/p2_package_native_audit`，未编写候选
实现、测试、设计或 workflow。本报告在 C1 全部 PR runs 达到终态、完整原件到齐，并读完
另一非作者分项审核原文后形成。C1 的阻断是既有 `cargo fmt --all -- --check` 失败；
对有限 Go/Python 成功逐项保留，不用它们替代未执行的 Rust 或恢复场景。

| 身份 | 准确值 |
|---|---|
| 仓库 / PR | `youq616/Zevune` / [#17](https://github.com/youq616/Zevune/pull/17) |
| 阶段 base | `{BASE}` |
| base tree | `b5841120084a72c5948b0a2754f712e5f67ad602` |
| C1 source | `{HEAD}` |
| C1 tree | `{TREE}` |
| 实际 PR checkout | `{CHECKOUT}` |
| source parents | 精确为 base |
| checkout parents/tree | 精确为 `[base, C1]`；tree 与 C1 一致 |

本任务独立查询 GitHub 的 source commit、synthetic commit、完整 PR run 列表与 jobs，
并与 root 保留的终态原件、本地准确 Git 对象比较。全部 21 份真实 job 日志的实际 checkout
均为上述 C1 synthetic commit。C1 的原始初始 PR 对象正确记录 C1 head；终态 runs/run
对象中嵌套 `pull_requests[0].head.sha` 已随 PR 更新为后来的 C2，这属于当前 PR 关联信息。
它不替代顶层 `run.head_sha`、`job.head_sha` 和实际 checkout。原始 API 内容没有为消除
这种区别而改写，也没有把 C2 的当前 PR 身份误当 C1 的执行树。

已完整读取 AGENTS、STAGE_REVIEW、冻结前设计与全部 12 个 workflow、funded target
调度脚本及其测试、Cargo feature/工具链接线、Rust 原生日志解析代码；从 C1 Git blobs
独立列出新增测试定义与 cfg gates，读取真实付款主流程的完整增量 diff 及新增调用辅助函数。
另以完整原始日志字节做哈希、解码、身份、错误、格式块及 Rust harness 解析，直接检查
原生 formatter 输出与故障前后实际命令。非 Rust 的全部场景细读和原始工件逐项复核由
`/root/p2_package_native_audit/nonrust_logs` 独立完成，其原文已整合，未用作者汇总代替。

**完整终态与原始证据。**

| 必需 workflow | 实际 PR run | API jobs 数 | 终态 |
|---|---|---:|---|
{table}

准确 C1 共 10 个 PR workflows，全部 attempt 1，8 failure / 2 success。jobs API 共返回
22 项：17 failure、4 success、1 skipped。原成功矩阵应有 23 个实际 jobs；本次 growth
的 source 先失败，矩阵尚未展开，API 只保留一个无步骤的 `growth` skipped 占位。
这个占位不代表两个平台执行，也不为它虚构 log。实际有 21 份完整日志。

所有实际步骤合计 **152 success、17 failure、92 skipped**。大多数 skipped 是失败后的
依赖步骤，不是正常成功矩阵的 9 个 Windows 条件 skip，不能把它们归入允许漏跑清单。
source/锁依赖和必需预算保持原值，所有 workflows、funded 调度器、资源与增长相关源码
相较 base 未变化。本次没有降低验收门槛。

`c1-native/` 共 **56 个原件、1,367,731 B**：完整 runs 列表、10 份 run、10 份 jobs、
10 份 artifact metadata、21 份 logs，以及两个原始资源 ZIP 和两个精确 setup 成员。
全部原件长度/SHA-256 均由本审核者逐字节重算，并与冻结 manifest 及实际目录集合核对。
21 份 logs 共 **1,056,143 B、12,260 解码行**；BOM/CRLF 原始字节保持，不经文本换行
规范化重写。connector 的 API JSON 属结构化保存结果，不声称是网络传输原始字节。

**阻断发现：固定 formatter 不接受 C1。**

17 个失败 jobs 都在 Rust 格式 gate 返回非零：同一组 **7 文件、30 个 hunks**。
其中物理 package tests 7 hunks、物理 package implementation 3、active.rs 1、真实
active_flow tests 1、公开 recovery package tests 11、公开 package implementation 4、
新 CLI tests 3。全部 17 份完整 formatter 块在仅去时间/ANSI及统一平台路径分隔符后，
均为同样 361 行，SHA-256 `4076072eb907a56badca018a344fdaf5a0981c908da46c0d00b672a4a1b72b36`。
不是只根据一个 badge 或作者转述判断失败。

示例原件是 Ubuntu wallet [job 105656510131](https://github.com/youq616/Zevune/actions/runs/35362376487/job/105656510131)，
40,556 B，SHA-256 `247217a4771742d0e14f66222cc6e9657d1969e290c3052272a44c9e5a927080`。
其 Rust 1.98.1 setup 正常，`cargo fmt --all -- --check` 输出上述差异并 exit 1，后面的
真实 Rust tests、strict Clippy、source drift 检查 skipped。这是规范格式验收阻断，
不是已经执行 Rust 测试后观察到业务断言失败，也不是 Rust 编译已经通过的证据。

C1 全部 21 日志共 **0 个 Rust harness result、0 次 Rust 通过执行**。新增测试静态
清单为 19 个库定义（各平台应执行 17）、8 个 funded CLI 定义（Ubuntu 应执行 8、
Windows 7），合计 27 个定义；本次这些数字仅是源码期望，没有一项在 C1 获得原生
执行信用。真实付款主流程已在源码接入增量恢复路径，重算摘要及 pin 的坏 binding
signature 也直接指向组合 Authorization gate，但该主测试在 C1 没有运行，不能写为已验证。

修复建议是严格采用原生 formatter 输出并对新的准确候选重新跑完整矩阵和独立审核。
后来的 C2 为 `f51c8db240933256870ff03c07bc68915b4ac4a1`，本审核者把上述 30 hunks
独立作用于 C1 的 7 个 Git blobs，结果逐字节等于 C2，且 C1→C2 没有其它变更路径；
这一事实仅说明格式修复来源，不能追认 C1 或代替 C2 自身 CI。C2 与后续候选的实际
执行、其它阻断和最终结论另存新原文。

**保留的有限非 Rust 覆盖。**

完整分项原文结论为 `C1_REJECTED_NATIVE_FMT_FAILURE_NONRUST_LIMITED_COVERAGE_ONLY`。
本任务已阅读全文，核对其身份、manifest、数字和原文哈希，与总审结果一致。

- `scaffold-tests` 两平台和 `consensus-laboratory` 两平台的 4 个 jobs 实际成功。
  根 Go test/vet、适用 Linux race、两个 decoder bounded fuzz，以及 CometBFT 普通
  adapter/独立进程测试和适用 race 在其准确范围完成。Linux 两个 fuzz 引擎实际记录
  8,456 与 109,831 executions；这些不是新增包测试，也不等于真实 Orchard funded 场景。
- 格式失败之前另有实际 Python 检查：8 个 suites，合计 672 次发现、660 次通过、
  12 次平台跳过；它们属于 135 个既有唯一名称的重复运行。保留 135-suite 的
  Ubuntu132+3 skip / Windows134+1 skip、53-suite 的50+3 /52+1，以及13个 scheduler
  单测两端执行。Go `-run '^$'` 仅编译检查，不能冒充运行证明。
- 两个平台资源 artifact 均实际上传，但各 ZIP 只有 `payment-resource-setup.json`。
  Ubuntu ZIP459 B / setup456 B，Windows ZIP463 B / setup466 B；ZIP 摘要与 API 一致，
  成员字节与保存文件相等，source/checkout/tree 均准确绑定 C1。它们都明确为
  `observed_execution_status: not_started`，没有 payment-resources.json、events、progress
  或 memory samples，因此没有 32+1 工作量或 OS 资源预算通过结论。
- 原生增长 workload、funded 四节点付款/钱包恢复、实际 operator 流程及可执行 bundle
  均未完成；operator 没有产出 bundle。C1 不授予增量 pack/verify/restore CLI、恢复后
  真实付款、100000 块增长或真实资源回归执行信用。

**冻结原文与限制。**

| 原文 / 派生审计记录 | bytes | SHA-256 |
|---|---:|---|
{attachments}

结构化解析文件刻意保持 `STRUCTURAL_OBSERVATION_ONLY / REVIEW_REQUIRED`，它不是
自动批准器。最终 JSON/本原文的 REJECTED_NATIVE_C1 是独立审核读取完整候选证据后的
结论。原 expectation、初始未完成 API 观察、当前完整拒绝及后续候选记录分别保存，
不修改 C1 原结论为通过。

审核者没有本地执行 Rust/Go workload 或下载的二进制，没有修改源代码/测试/workflow、
降低预算或执行合入。本报告只支持明确拒绝 C1 并保留其有限实际结果，不表示代码正确性
全面审查通过、专业外部安全审计、最终性、生产存储/真钱能力，也没有真实磁盘满、物理
掉电、全容量或任意敌对文件系统保证。本阶段仍待准确后续候选的完整验收。
'''
md_path = ROOT / 'c1-native-review.md'
assert not md_path.exists()
md_path.write_bytes(text.encode('utf-8'))
print(json.dumps([identity('c1-native-review.md'), identity('c1-native-review.json')], ensure_ascii=False))
