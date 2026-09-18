"""Freeze C2's independent native rejection after reading the non-Rust report."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent
HEAD = 'f51c8db240933256870ff03c07bc68915b4ac4a1'
TREE = '7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400'
BASE = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
CHECKOUT = 'aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f'


def identity(name):
    raw = (ROOT / name).read_bytes()
    return {'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read(name):
    return json.loads((ROOT / name).read_bytes())


def main():
    s = read('c2-native-review-structural.json')
    assert (s['source'], s['tree'], s['base'], s['checkout']) == (HEAD,TREE,BASE,CHECKOUT)
    assert s['original_count'] == 62 and s['original_bytes'] == 1937332
    manifest = read('c2-native-original-manifest.json')
    for original in manifest['files']:
        assert identity(original['path']) == original
    n = read('c2-native-nonrust-review.json')
    conclusion = n.get('conclusion', n.get('status',''))
    assert 'C2' in conclusion and 'REJECT' in conclusion
    assert (ROOT / 'c2-native-nonrust-review.md').is_file()
    attachments = [identity(name) for name in [
        'c2-native-review-structural.json','c2-native-original-manifest.json',
        'c2-native-source-scope.json','c2-native-nonrust-review.md','c2-native-nonrust-review.json',
        'c2-resource-independent-review.json','c2-operator-independent-review.json',
        'c2-native-format-reconstruction.json','native-expectation.md',
        'audit_complete_c2_native.py','audit_native_structure.py','native_audit_rust_helpers.py']]
    report = {'conclusion':'REJECTED_NATIVE_C2','reviewer':'/root/p2_package_native_audit',
        'independent_non_author':True,'base':BASE,'source':HEAD,'tree':TREE,'checkout':CHECKOUT,
        'pr':'https://github.com/youq616/Zevune/pull/17',
        'all_original_bytes_and_sha256_recomputed':True,'original_manifest':identity('c2-native-original-manifest.json'),
        'original_count':62,'original_bytes':1937332,'structure':s,
        'nonrust_conclusion':conclusion,'attachments':attachments,
        'findings':[{'severity':'stage_acceptance_blocker','code':'C2_CLIPPY_DROP_NON_DROP',
            'detail':'Ten required default/interfaces jobs fail strict unchanged Clippy on src/pool/active/package/tests.rs:354 drop(reader), exit 101. Funded-library jobs both actually pass; interfaces Rust/package CLI and subsequent funded workflow interoperability/four-node steps do not run.'}],
        'actual_rust':{'harness_results':162,'repeated_passes':1820,'default_jobs':8,
            'default_library_ubuntu':171,'default_library_windows':163,
            'funded_library_ubuntu':190,'funded_library_windows':182,
            'new_library_names_per_platform':17,'new_library_repeated_passes':170,
            'new_cli_executions':0,'failed':0,'ignored':0,'measured':0,'filtered':0},
        'scope_limits':['No local Rust/Go execution or downloaded binary execution.',
            'C2 observed passes do not substitute for C3 exact-source execution.',
            'Resource baseline does not measure all-process peak memory of new package CLI.',
            'No external audit, production readiness, real funds, finality, full capacity or physical power-loss guarantee.']}
    out = ROOT / 'c2-native-review.json'
    assert not out.exists()
    out.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    table = '\n'.join(f'| {r["name"]} | [{r["id"]}]({r["html_url"]}) | {r["conclusion"]} |' for r in s['runs'])
    artifacts = '\n'.join(f'| `{f["path"]}` | {f["bytes"]} | `{f["sha256"]}` |' for f in [identity('c2-native-review.json')]+attachments)
    text = f'''**REJECTED_NATIVE_C2 — C2 仍未通过本阶段原生验收。**

审核日期：2026-09-18 UTC。本报告由非作者任务 `/root/p2_package_native_audit` 形成，
未修改实现、测试、设计、workflows、验收预算或锁依赖。原 C1 格式拒绝报告保持原字节。
C2 的格式已通过，但 10 个必需 jobs 在 strict Clippy 因同一个 `drop_non_drop` 错误失败。
下述真实成功按各自执行范围保留；它们不能解除整个 C2 的阻断。

| 身份 | 准确值 |
|---|---|
| 仓库 / PR | `youq616/Zevune` / [#17](https://github.com/youq616/Zevune/pull/17) |
| 阶段 base | `{BASE}` |
| base tree | `b5841120084a72c5948b0a2754f712e5f67ad602` |
| C2 source | `{HEAD}` |
| C2 tree | `{TREE}` |
| C2 parent | `61c691270b91aece076177cb757e51e0e63fe310`（C1） |
| PR actual checkout | `{CHECKOUT}` |
| checkout parents / tree | `[base, C2]`；tree 与 C2 相同 |

审核者独立查询了 GitHub 的准确 runs/jobs 和 Git identities，并将实际日志 checkout、
顶层 run/job head、run head_commit tree 与保存 API 及 Git 对象交叉核对。全部 23 个
实际 checkout 均为上述 synthetic。嵌套 PR 关联对象可能随 live PR 更新，不用它取代
历史 run 的顶层 head 或日志 checkout；原 API 不为消除这种差异而重写。

**完整终态与证据闭包。**

| 必需 workflow | 实际 run | 终态 |
|---|---|---|
{table}

10 个 workflows 全部 attempt 1，**5 success / 5 failure**。实际 23 个 jobs 中
**13 success / 10 failure**，无取消或 job 级跳过。steps 为 **228 success、10 failure、
45 skipped**；失败后的跳过与正常 Windows 条件跳过分别理解，不把全部 45 项当允许漏跑。
funded run 的四个 jobs 中，两个 library 成功、两个 interfaces 失败；不能把整个 run
失败误写成四个 jobs 均未通过测试。

`c2-native/` 的 **62 个原件、1,937,332 B** 已逐字节重算长度/SHA-256并核对目录闭包，
包含完整10终态run、jobs、artifact API与 runs 列表、23完整logs、双平台资源原ZIP和
精确setup/result成员、operator原manifest成员。完整 logs 共 **1,337,508 B /15,734行**。
原件保留 BOM/CRLF，日志解析副本去时间/ANSI不改变原字节；API JSON属于connector提供的
结构化保存结果，不声称保留网络传输编码。两份 operator 完整二进制ZIP在scratch分项
审核中实际下载并逐成员读取，但不作为仓库内原件；目录统计不包含这些大ZIP。

**已执行的 Rust 与严格阻断。**

| Rust cohort | 实际 jobs | 每 job harness | Ubuntu 实际通过 | Windows 实际通过 | 后续 |
|---|---:|---:|---:|---:|---|
| default（bridge/integrated/crypto/wallet） | 8 | 20 | 库171、总185 | 库163、总177 | 随后 strict Clippy 失败 |
| funded-library | 2 | 1 | 库190 | 库182 | cohort 完成、source不变检查通过 |
| funded interfaces | 2 | 0 | 0 | 0 | 测试前的 strict Clippy 阻断 |

合计 **162 个完整 Rust harness result、1,820 次重复具名通过执行**；这是各job累计，
不是1,820个唯一测试。每个result对应准确target、`running N`、独立具名结果和0 failed/
ignored/measured/filtered。同平台四个 default 库名称集合完全相同；funded library 精确
包含对应 default 库全集并新增19个既有funded-only名称。

本阶段新增库19个定义，各平台17个适用名称（物理7、公开API10），在8个default与
2个funded-library jobs均逐名通过，共170次重复执行。默认feature下新CLI目标的0项
result不算CLI执行；两个funded interfaces在测试之前失败，所以新增8个CLI定义
（Ubuntu适用8、Windows7）在C2合计**0次执行**。

两个 funded-library 都真正完成动态 library cohort：Cargo计划仅选择准确lib target，
保留 `--locked --release --features local-funding-lab --lib -- --test-threads=1`，
最后均有 `FUNDED_COHORT_COMPLETE library`。Ubuntu [job105658336250](https://github.com/youq616/Zevune/actions/runs/35362925680/job/105658336250)
190项/235.33秒；Windows [job105658336169](https://github.com/youq616/Zevune/actions/runs/35362925680/job/105658336169)
182项/266.84秒。四个 `active_flow_tests` 两端均有真实具名ok，包括原有两笔真实付款、
默认1MiB轮转、跨10000及重开10002的主测试。本阶段源码使第二笔真实花费的来源为
增量恢复目录，并保留旧归档/计划/余额/费用/双花断言；重算帧摘要和later pin的坏binding
signature直接经包与有效base组合到达Authorization拒绝。该实际库范围成立，不扩展为
尚未执行的新CLI、任意错误实例的完整proof验证或funded workflow后续四节点场景。

10个失败jobs都由相同严格Clippy诊断阻断：
`src/pool/active/package/tests.rs:354` 的 `drop(reader)` 将不实现Drop的
`JoinedReader<'_, '_>` 传给 `std::mem::drop`。固定 `-D warnings` 使
`clippy::drop_non_drop` 成为error，随后 `lib test` 编译检查exit101。全部完整诊断在仅
去时间/ANSI和统一平台源码路径分隔符后相等，SHA-256为
`b2d89ce9d42b20247886ed2ec77073f08a29c7e75520589ba9be145eab03baa8`。
这是严格lint失败；已通过的Rust断言不会被改称失败，也不能抵消该gate失败。

C1→C2恰为原生formatter的7文件30hunks，审核者独立将原输出作用于C1 Git blobs后与C2
逐字节相等；C2→后续C3仅删除上述多余 `drop(reader);` 一行。源修复来源与候选验收
分开记录。没有加allow、跳过测试、增大预算或修改workflow；C3仍须使用自身完整原件
得出新结论，C2报告永久保持拒绝。

**实际非 Rust 成功与未执行范围。**

另一非作者分项任务 `/root/p2_package_native_audit/nonrust_logs` 对全量原始日志/API/
资源和bundle字节独立核对，正式原文已由本任务阅读全文并纳入。其结论为
`{conclusion}`。

- 基础scaffold/consensus两平台、growth的source与双平台、payment resource双平台、
  operator双平台均实际成功；Go编译空过滤、Python平台skip、race/fuzz具名范围分别核算。
  bridge/integrated的Clippy后步骤没有执行，funded interfaces后续真实Python互通和
  funded四节点付款/钱包恢复也没有执行，不用operator自身场景代替这些缺失范围。
- 两平台增长日志均实际完成100000次提交，99998空块/2付款，15段、15018544B、
  固定1048576B段限额，完整重放后继续100001。Ubuntu增长72160ms/重放2082ms；
  Windows617840ms/2757ms。原预算未改。这是local worker增长，不声称四节点
  100000高度、100000笔付款、全容量或新package命令的大容量基准。
- 双平台资源artifact各有实际setup/result两成员，ZIP大小/摘要与API匹配、成员原字节
  与保留文件相等。各自32+1付款、9events、362progress/181操作、18samples、14checks
  和cleanup已核对。Ubuntu两worker/场景 lifetime peaks 为11325440/11612160/
  180039680B；Windows13119488/12644352/117415936B，均在固定1GiB门槛内。
  这是既有付款资源回归，不是新package CLI的所有进程峰值测量。
- 双平台operator原ZIP均恰好1manifest+5payload；全部payload流式重算length/SHA并
  验证CRC，与准确synthetic/tree、构建回执、artifact metadata一致。Linux payload
  共47866947B、Windows44563437B；两文本payload与准确Git blobs逐字节一致。
  未运行下载二进制，未独立重建，也不表示代码签名或可复现构建已证明。

**冻结原文及适用边界。**

| 原件 / 派生审核 | bytes | SHA-256 |
|---|---:|---|
{artifacts}

结构化记录只作全量观察与交叉校验；本正式原文及JSON的 `REJECTED_NATIVE_C2` 是
独立阅读后的结论。审核者没有本地Rust/Go工具链执行、修改候选源或合入。准确C2的
成功与缺失全部保留，不追认C1、不前借C3结果；不表示外部专业安全审计、生产存储、
真实资金、最终性、快照状态导入、真实磁盘满/物理掉电、全容量或任意敌对文件系统保证。
'''
    out = ROOT / 'c2-native-review.md'
    assert not out.exists()
    out.write_bytes(text.encode())
    print(json.dumps([identity('c2-native-review.md'),identity('c2-native-review.json')]))


if __name__ == '__main__':
    main()
