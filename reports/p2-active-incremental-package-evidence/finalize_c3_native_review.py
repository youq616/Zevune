"""Freeze the exact C3 native review after full original and non-Rust inspection."""
from pathlib import Path
from collections import Counter
import hashlib
import json

ROOT = Path(__file__).resolve().parent
HEAD = 'cb0804e7c921a456cbbafab313b3a4a4501b8f5e'
TREE = '21de343c12bc27cb1022ffd7ebd451abe0e61f29'
BASE = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
CHECKOUT = '3dfa8d77921693b9e99af5b94af198498b9422e9'


def identity(name):
    raw = (ROOT / name).read_bytes()
    return {'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def read(name):
    return json.loads((ROOT / name).read_bytes())


def main():
    s = read('c3-native-review-structural.json')
    assert (s['source'],s['tree'],s['base'],s['checkout']) == (HEAD,TREE,BASE,CHECKOUT)
    assert s['original_count'] == 62 and s['original_bytes'] == 2017223
    assert s['step_counts'] == {'success':274,'skipped':9}
    assert s['native_structure']['rust_harnesses'] == 206
    assert s['native_structure']['rust_passed_executions'] == 1961
    assert len(s['jobs']) == 23
    assert len(s['runs']) == 10 and len({r['name'] for r in s['runs']}) == 10
    manifest = read('c3-native-original-manifest.json')
    for original in manifest['files']:
        assert identity(original['path']) == original
    assert {str(p.relative_to(ROOT)) for p in (ROOT/'c3-native').rglob('*') if p.is_file()} == {f['path'] for f in manifest['files']}
    commit = read('source-identities/c3-git-commit.json')
    assert [p['sha'] for p in commit['parents']] == ['f51c8db240933256870ff03c07bc68915b4ac4a1']
    n = read('c3-native-nonrust-review.json')
    conclusion = n.get('conclusion',n.get('status',''))
    assert 'PASS' in conclusion and 'C3' in conclusion and 'NONRUST' in conclusion
    assert (ROOT/'c3-native-nonrust-review.md').is_file()
    scope = read('c3-native-source-scope.json')
    seen = {'ubuntu':set(),'windows':set()}
    cli_seen = {'ubuntu':set(),'windows':set()}
    logs = {int(r['path'][4:-4]):r for r in s['native_structure']['records']}
    for job in s['jobs']:
        for h in logs[job['id']]['rust']['harnesses']:
            if h['target']=='src/lib.rs':
                seen[job['platform']].update(n for n in h['named_passes'] if '::package::tests::' in n)
            elif h['target']=='tests/active_incremental_package_cli.rs':
                cli_seen[job['platform']].update(h['named_passes'])
    for platform in seen:
        assert sorted(seen[platform]) == scope['expected'][platform]['new_library_names']
        assert sorted(cli_seen[platform]) == scope['expected'][platform]['new_cli_names']
    assert len(seen['ubuntu']|seen['windows']) == 19
    assert len(cli_seen['ubuntu']|cli_seen['windows']) == 8
    attachments = [identity(name) for name in [
        'native-expectation.md','c3-native-review-structural.json','c3-native-source-scope.json',
        'c3-native-original-manifest.json','c3-native-nonrust-review.md','c3-native-nonrust-review.json',
        'c3-resource-independent-review.json','c3-operator-independent-review.json',
        'rust-parser-v2-observation.json','native_audit_rust_helpers.py','audit_native_structure.py',
        'native_audit_rust_helpers_v2.py','audit_native_structure_v2.py','audit_complete_native.py',
        'c1-native-review.md','c1-native-review.json','c2-native-review.md','c2-native-review.json']]
    report = {'conclusion':'PASS_NATIVE_C3','reviewer':'/root/p2_package_native_audit',
        'independent_non_author':True,'base':BASE,'source':HEAD,'tree':TREE,'checkout':CHECKOUT,
        'pr':'https://github.com/youq616/Zevune/pull/17',
        'all_original_bytes_and_sha256_recomputed':True,'all_complete_job_logs_parsed':True,
        'all_original_nonrust_logs_and_artifacts_independently_reviewed':True,
        'original_count':62,'original_bytes':2017223,'structure':s,
        'nonrust_conclusion':conclusion,'source_inventory':scope,'attachments':attachments,
        'actual_rust':{'harness_results':206,'repeated_passes':1961,
            'default_jobs':8,'funded_library_jobs':2,'funded_interface_jobs':2,
            'default_library_ubuntu':171,'default_library_windows':163,
            'funded_library_ubuntu':190,'funded_library_windows':182,
            'funded_interfaces_ubuntu':71,'funded_interfaces_windows':70,
            'new_definitions_union':27,'new_library_definitions_union':19,
            'new_library_names_per_platform':17,'new_library_repeated_passes':170,
            'new_cli_ubuntu':8,'new_cli_windows':7,'new_total_repeated_passes':185,
            'failed':0,'ignored':0,'measured':0,'filtered':0},
        'findings':[],
        'parser_revision':'v2 pairs two complete ordered Cargo/stdout streams, preserving all per-harness strictness and original v1 evidence; not a product change.',
        'scope_limits':['Exact C3 native evidence only; source correctness reviews remain separate.',
            'No local Rust/Go workload execution and no downloaded binary execution.',
            'Resource regression does not measure all-process peak memory of new package CLI.',
            '100000 local worker commits are not 100000 four-node consensus heights or 100000 payments.',
            'No state snapshot import, pruning, production storage, real funds, finality or external professional security audit credit.',
            'No physical power-loss, real-disk-full, full-capacity, macOS or arbitrary hostile filesystem guarantee.']}
    out = ROOT/'c3-native-review.json'
    assert not out.exists()
    out.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    table = '\n'.join(f'| {r["name"]} | [{r["id"]}]({r["html_url"]}) | {sum(j["run"]==r["id"] for j in s["jobs"])} | success |' for r in s['runs'])
    artifacts = '\n'.join(f'| `{f["path"]}` | {f["bytes"]} | `{f["sha256"]}` |' for f in [identity('c3-native-review.json')]+attachments)
    text = f'''**PASS_NATIVE_C3 — 准确 C3 的本阶段原生验收证据通过独立审核。**

审核日期：2026-09-18 UTC；任务 `/root/p2_package_native_audit`。本审核者没有编写本候选
实现、测试、设计、workflow，未调整验收预算。结论形成于完整10个终态PR workflows、
23个jobs的所有原始日志/API/工件到齐、逐字节完整性复核及非作者分项原文全文阅读之后。
没有发现本范围内尚未关闭的原生验收阻断；这不替代其他独立源码审核或扩大产品能力。

| 身份 | 准确值 |
|---|---|
| 仓库 / PR | `youq616/Zevune` / [#17](https://github.com/youq616/Zevune/pull/17) |
| 阶段 base | `{BASE}` |
| base tree | `b5841120084a72c5948b0a2754f712e5f67ad602` |
| C3 source | `{HEAD}` |
| C3 tree | `{TREE}` |
| C3 parent | `f51c8db240933256870ff03c07bc68915b4ac4a1`（C2） |
| actual PR checkout | `{CHECKOUT}` |
| checkout parents / tree | 精确为 `[base, C3]`；tree 与 C3 相同 |

审核者通过 GitHub 插件独立查询 source/synthetic commit、准确PR runs及jobs，和root
保存的完整终态原件、本地精确Git对象交叉核对。全部23份日志的实际checkout一致，
全部run/job顶层head和run head_commit tree准确绑定C3；不把会随live PR更新的嵌套
PR关联对象用作历史运行身份。base→C3只有冻结范围的12个路径；原有全部workflows、
工具链、锁依赖、调度器、Go/resource/growth实现与预算未改变。

**完整矩阵和原始证据。**

| 必需 workflow | 实际 PR run | jobs | 终态 |
|---|---|---:|---|
{table}

10个workflows均为pull_request、attempt1、completed/success；23个实际jobs全部success，
无cancelled、无失败、无job级skip。步骤合计**274 success /9 skipped**，9项全部是原有
Windows条件skip：scaffold3、consensus1、bridge2、integrated2、operator1；对应Linux
命令实际执行。全部要求的fmt、strictClippy、source/lock不变检查和cleanup均有自身原文。
仓库另外两个workflow是push-only source archive及本次路径不触发的notice inventory，
没有冒充本次PR测试覆盖。原始期望没有事后修改成通过结果。

`c3-native/`共**62个原件 /2,017,223 B**，目录集合、每件长度与SHA-256全部独立重算，
与冻结manifest完全一致。包含完整runs列表、10份run/10份jobs/10份artifact API、
**23份完整logs /1,417,655 B /16,675解码行**，双平台资源原ZIP及四个精确JSON成员，
双平台operator原manifest。BOM/CRLF原字节保持，解码解析副本不改写原文；API原件是
connector提供的结构化内容，不声称保留底层HTTP传输编码。operator大ZIP另在scratch
真实下载、全成员读取并验证；仓库证据保留其API、manifest和完整校验记录，不放二进制。

**Rust cohort 和全部新增具名用例。**

| 完整 cohort | 实际 jobs | 每 job harness | Ubuntu passed | Windows passed |
|---|---:|---:|---:|---:|
| default：bridge/integrated/crypto/wallet | 8 | 20 | 库171、总185 | 库163、总177 |
| funded-library | 2 | 1 | 190 | 182 |
| funded interfaces：5bins+16integration+doc | 2 | 22 | 71 | 70 |

合计**206个完整Rust harness result、1,961次重复具名通过执行**。这是各job累计，
不是1,961个唯一测试。每个harness均核对target、`running N`、具名pass数量与result，
failed/ignored/measured/filtered均0。同平台四个default jobs的完整target顺序、各target
pass数与名称集合全部相同。funded库包含对应default库全体并新增19个既有funded-only
测试；两个动态cohort保持完整target分区，未加test-name filter、skip、ignore或no-run。

新增源码定义共**27个**：物理package8、公开API11、CLI8。实际各OS适用库17个
（物理7+API10）；它们在8个default和2个funded-library jobs逐名全部通过，共170次。
两个funded interfaces再执行新CLI **Ubuntu8 /Windows7**，共15次。新增定义跨两平台
联合全部有具名覆盖，累计185次；平台差异来自源码cfg，不是忽略或漏跑。默认feature
中的新CLI目标为0项，只保留其编译/空harness事实，不把它算作实际CLI执行。

Ubuntu新CLI在[job105660992545](https://github.com/youq616/Zevune/actions/runs/35363727269/job/105660992545)
8项/211.73秒；Windows在[job105660992463](https://github.com/youq616/Zevune/actions/runs/35363727269/job/105660992463)
7项/267.15秒。两端旧active_incremental_cli各7项、active_recovery_cli各7项及其它既有
目标保留。完整interfaces计划选5个bin与16个integration target，另执行doc，最后均有
`FUNDED_COHORT_COMPLETE interfaces`；doc的0项结果不授予文档测试样例执行信用。

审核者完整读取三个新测试文件、实际active_flow修改与辅助编码/恢复函数，将静态名称
和cfg逐个映射到实际日志，未把名称相似当作相同语义。新增覆盖包括：独立格式编码和
精确物理字节；genesis/空尾/新段/相同内容空包；元数据、pin、offset、length与EOF；
短读写/Interrupted、注入失败残留、失败reader不可继续；重算pin的早轮转/跨段frame到达
真实组合replay拒绝；包/目录拥有者锁及最后drop释放；Unix链接/名称替换与Windows
保留句柄行为；真实CLI子进程三命令、独立双pin、移除later后验证/新目录恢复、普通后续
提交、已有/嵌套输出拒绝，以及只读stdout失败仍保留完整输出供显式再次验证。

新CLI fixture主要采用真实普通空块提交，物理层私有fixture只证明传输字节；这些不冒充
新增真实付款。真实付款覆盖来自修改后的既有funded library主流程：两端4个active_flow
均具名通过，库总耗时Ubuntu154.70秒/Windows436.12秒。原来两笔genuine付款生成次数
未增加，第一笔导致正常1MiB轮转后，**第二笔真实花费确实从增量恢复返回的目录继续**，
普通prepare/commit跨10000到10001，另一次包恢复后重花被拒绝并正常提交10002。旧归档、
只读计划、余额/费用/双花及源不变断言仍保留。新损坏向量只改新增第二笔binding signature，
重算普通帧摘要及later物理pin，以有效base和新包直接调用open到达Authorization拒绝，
没有先打开坏later目录遮蔽组合入口；不声称该坏签名实例必然执行了后续所有proof步骤。

**原生日志解析修正，独立于产品修复。**

Ubuntu wallet原日志105660991474中，两个0-test stdout result（589/594行）早于对应
Cargo stderr Running announcement（596/597行）。原v1解析器假定announcement已到达，
因此在读取这份真实成功日志时产生AssertionError；该观察和v1原字节均保留。它不是
产品失败，也没有因此重跑、改写或删除CI日志。

v2分别收集完整Cargo announcement与stdout harness结果，保持各流内部执行顺序，要求
总数严格相等后按ordinal配对；每个running N、具名数量、零fail/ignored/filtered和最终
cohort完整性条件不变。v1/v2在完整C1 21份+C2 23份日志上解析对象逐一相等；C3再核对
同平台四个default完整target/name集合及动态funded target并集。上述两个新CLI/恢复CLI
空目标仍为0，没有制造执行信用。`rust-parser-v2-observation.json`保存完整失败观察、
原文身份、实际行、对照结果及新旧helper哈希。此改动仅修正审核工具，候选C3源码未改。

**Go、Python、真实网络、增长和工件。**

非作者分项 `/root/p2_package_native_audit/nonrust_logs` 对所有原始API/logs、资源ZIP及
operator全部payload独立阅读全文/全字节核对，其最终原文已由本任务完整读回，结论
`{conclusion}`。使用准确C3证据，不继承任何C1/C2通过项。

- 适用Go test/vet、Linux race和8个真实bounded fuzz引擎通过；fuzz分别为scaffold
  2×3秒、bridge2×10秒、integrated1×10秒、operator3×3秒，原参数和预算保持。
  编译用 `-run '^$'` 不算测试运行。Python8次suites累计672发现/660通过/12平台skip，
  是135个既有名称的重复范围，Linux/Windows共享测试的适用端均实际执行。
- 两个平台实际Go→Rust授权、Orchard四进程集成、funded四节点非零A→B→C、钱包outbox
  恢复、节点离线及整网重启、错误post-state拒绝与operator流程完成。funded专用
  四节点test Ubuntu61.32秒/Windows91.34秒；其两次local样本为6139/6330ms和
  8824/12055ms，包含backup/rescan、signed-header及独立replay。没有把两样本叫p95、
  TPS、WAN或生产付款速度。Python互通的prepare计时范围也保持local_prepare_not_finality。
- 两平台growth实际100000 commits（99998空/2付款）、15段/15018544B、固定1MiB段限额，
  完整重放后继续100001。Ubuntu增长68105ms、重放2436ms；Windows418674ms、2743ms。
  它是local worker增长，不是100000四节点高度、100000笔付款、超过64MiB或全容量证明。
- 两平台资源32+1真实付款均有9events、362progress/181严格有序操作、18内存samples、
  14checks、最终result、具名PASS和登记子进程退出。实际setup/result原成员与原ZIP
  完全相等、ZIP匹配API；初始setup的not_started不被当作最终结果。最终height33、
  commitments68/nullifiers66/fees33000，逻辑308756B/1段。Ubuntu两worker/scenario
  生命周期峰值11522048/11685888/176529408B；Windows13053952/12783616/117739520B，
  全在固定1GiB门槛内。原Go1200/supervisor1230/handshake15/start-request60/scenario90
  秒预算不变；这些不是新package CLI所有进程峰值、每阶段独立峰值或跨平台性能比较。
- operator两原ZIP的全部5payload各自流式重算长度/SHA/CRC，manifest、builder receipt、
  artifact metadata和准确synthetic/tree一致，两文本与精确Git blobs逐字节相同。
  下载二进制没有在本地执行，也没有独立重建；完整性不等于代码签名或可复现构建证明。

**历史拒绝、冻结记录与限制。**

C1永久保持REJECTED_NATIVE_C1：17个fmt失败jobs，0 Rust执行；C2永久保持
REJECTED_NATIVE_C2：10个strictClippy失败jobs，同时保留其真实部分成功。C1→C2只是
7文件30个原生fmt hunks；C2→C3只是删一个多余 `drop(reader);`，没有allow、断言或
预算变化。C3 PASS来源于自身完整矩阵与本次独立读取，未事后改写早期结论。

| 原文 / 审计记录 | bytes | SHA-256 |
|---|---:|---|
{artifacts}

本任务没有本地Rust/Go workload执行、下载binary执行、重新采集OS数据或合入操作。
结构化checker不是自动批准器；本原文及JSON的PASS_NATIVE_C3是全原件、源码测试含义
及独立分项复核后的限定结论。它支持本阶段NO-FUNDS活动账本持久增量包的原生验收，
不宣称状态快照导入、剪枝、生产存储、真实资金、最终性、专业外部安全审计，或真实
磁盘满/物理掉电、全容量、macOS、任意敌对文件系统保证。阶段发布和文档验收由root
结合独立代码审核及准确merge/evidence身份另行闭合。
'''
    out = ROOT/'c3-native-review.md'
    assert not out.exists()
    out.write_bytes(text.encode())
    print(json.dumps([identity('c3-native-review.md'),identity('c3-native-review.json')]))


if __name__ == '__main__':
    main()
