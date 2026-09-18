"""Read every C2 original and preserve exact mixed results; never accepts C2."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from audit_native_structure import inspect_logs
from native_audit_rust_helpers import lines_from

ROOT = Path(__file__).resolve().parent
HEAD = 'f51c8db240933256870ff03c07bc68915b4ac4a1'
TREE = '7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400'
BASE = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
CHECKOUT = 'aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f'


def identity(path):
    raw = (ROOT / path).read_bytes()
    return {'path': path, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read(path):
    return json.loads((ROOT / path).read_bytes())


def main():
    manifest = read('c2-native-original-manifest.json')
    for item in manifest['files']:
        assert identity(item['path']) == item
    assert len(manifest['files']) == len({f['path'] for f in manifest['files']})
    assert {str(p.relative_to(ROOT)) for p in (ROOT / 'c2-native').rglob('*') if p.is_file()} == {f['path'] for f in manifest['files']}
    for label, commit in [('c2-git-commit', HEAD), ('c2-synthetic-git-commit', CHECKOUT)]:
        obj = read(f'source-identities/{label}.json')
        assert obj['sha'] == commit and obj['tree']['sha'] == TREE
        if commit == CHECKOUT:
            assert [p['sha'] for p in obj['parents']] == [BASE, HEAD]
    source = read('c2-native-source-scope.json')
    assert (source['candidate'], source['tree'], source['base']) == (HEAD, TREE, BASE)
    structure = inspect_logs(ROOT / 'c2-native', HEAD, CHECKOUT)
    assert structure['log_count'] == 23
    assert structure['rust_harnesses'] == 162 and structure['rust_passed_executions'] == 1820
    logs = {int(row['path'][4:-4]): row for row in structure['records']}
    for row in logs.values():
        assert not row['format_hunks'] and row['cleanup_observed']
    runs = read('c2-native/runs.json')
    assert runs['total_count'] == len(runs['workflow_runs']) == 10
    assert Counter(r['conclusion'] for r in runs['workflow_runs']) == Counter(success=5, failure=5)
    expected_counts = {'scaffold-tests':2,'consensus-laboratory':2,'orchard-bridge':2,
        'orchard-consensus-integration':2,'orchard-cryptography-laboratory':2,
        'wallet-laboratory':2,'funded-wallet-consensus':4,'active-ledger-growth':3,
        'payment-resource-baseline':2,'local-network-operator':2}
    default_workflows = {'orchard-bridge','orchard-consensus-integration','orchard-cryptography-laboratory','wallet-laboratory'}
    default_names = {'ubuntu':[], 'windows':[]}
    funded_names = {}
    jobs = []
    failure_blocks = []
    for run in runs['workflow_runs']:
        assert run['head_sha'] == HEAD and run['event'] == 'pull_request'
        assert run['head_commit']['id'] == HEAD and run['head_commit']['tree_id'] == TREE
        assert run['status'] == 'completed' and run['run_attempt'] == 1
        full = read(f'c2-native/run-{run["id"]}.json')
        for key in ['id','name','head_sha','event','run_attempt','status','conclusion']:
            assert full[key] == run[key]
        assert full['head_commit']['id'] == HEAD and full['head_commit']['tree_id'] == TREE
        inv = read(f'c2-native/jobs-{run["id"]}.json')
        assert inv['total_count'] == len(inv['jobs']) == expected_counts[run['name']]
        for job in inv['jobs']:
            assert job['head_sha'] == HEAD and job['run_id'] == run['id'] and job['run_attempt'] == 1
            assert job['status'] == 'completed' and job['conclusion'] in ['success','failure']
            assert all(s['status'] == 'completed' for s in job['steps'])
            platform = 'windows' if 'windows-latest' in job['name'] else 'ubuntu'
            log = logs[job['id']]
            harnesses = log['rust']['harnesses']
            record = {'workflow':run['name'],'run':run['id'],'job':job['id'],
                'name':job['name'],'platform':platform,'url':job['html_url'],
                'conclusion':job['conclusion'],'steps':job['steps'],
                'harnesses':len(harnesses),'passed_executions':sum(h['passed'] for h in harnesses)}
            jobs.append(record)
            if job['conclusion'] == 'failure':
                assert len(log['errors']) == 1 and log['errors'][0]['text'] == '##[error]Process completed with exit code 101.'
                lines = lines_from((ROOT / 'c2-native' / log['path']).read_bytes())
                errors = [i for i,l in enumerate(lines) if l.startswith('error:')]
                assert len(errors) == 2
                assert lines[errors[0]].startswith('error: call to `std::mem::drop` with a value that does not implement `Drop`.')
                assert lines[errors[1]] == 'error: could not compile `zevune-orchard-lab` (lib test) due to 1 previous error'
                block = '\n'.join(lines[errors[0]:errors[1]]).replace('src\\pool\\active\\package\\tests.rs','src/pool/active/package/tests.rs')+'\n'
                assert hashlib.sha256(block.encode()).hexdigest() == 'b2d89ce9d42b20247886ed2ec77073f08a29c7e75520589ba9be145eab03baa8'
                failure_blocks.append({'job':job['id'],'line':errors[0]+1,'normalized_sha256':hashlib.sha256(block.encode()).hexdigest(),'diagnostic':block})
            else:
                assert not log['errors']
            if run['name'] in default_workflows:
                assert job['conclusion'] == 'failure' and len(harnesses) == 20
                lib = next(h for h in harnesses if h['target'] == 'src/lib.rs')
                assert lib['passed'] == (163 if platform == 'windows' else 171)
                assert record['passed_executions'] == (177 if platform == 'windows' else 185)
                assert sorted(n for n in lib['named_passes'] if '::package::tests::' in n) == source['expected'][platform]['new_library_names']
                default_names[platform].append(set(lib['named_passes']))
                assert next(h for h in harnesses if h['target'] == 'tests/active_incremental_package_cli.rs')['passed'] == 0
                assert not log['rust']['funded_plans'] and not log['rust']['funded_complete']
            elif run['name'] == 'funded-wallet-consensus':
                if job['name'].startswith('funded-library '):
                    assert job['conclusion'] == 'success' and len(harnesses) == 1
                    lib = harnesses[0]
                    assert lib['target'] == 'src/lib.rs' and lib['passed'] == (182 if platform == 'windows' else 190)
                    assert log['rust']['funded_complete'] == ['library']
                    assert log['rust']['funded_plans'] == [{'cohort':'library', 'commands':[['cargo','test','--locked','--release','--features','local-funding-lab','--lib','--','--test-threads=1']], 'documentation_tests':False, 'test_targets':[['lib','zevune_orchard_lab']]}]
                    assert sorted(n for n in lib['named_passes'] if '::package::tests::' in n) == source['expected'][platform]['new_library_names']
                    assert len([n for n in lib['named_passes'] if '::active_flow_tests::' in n]) == 4
                    funded_names[platform] = set(lib['named_passes'])
                else:
                    assert job['name'].startswith('funded ') and job['conclusion'] == 'failure'
                    assert not harnesses and not log['rust']['funded_plans'] and not log['rust']['funded_complete']
            else:
                assert job['conclusion'] == 'success' and not harnesses
    assert len(jobs) == len({j['job'] for j in jobs}) == 23
    assert Counter(j['conclusion'] for j in jobs) == Counter(success=13,failure=10)
    assert len(failure_blocks) == 10
    for platform in ['ubuntu','windows']:
        assert len(default_names[platform]) == 4
        assert all(names == default_names[platform][0] for names in default_names[platform])
        assert default_names[platform][0] <= funded_names[platform]
        assert len(funded_names[platform] - default_names[platform][0]) == 19
    result = {'status':'COMPLETE_ORIGINAL_OBSERVATION / C2_REJECTED_CLIPPY / INDEPENDENT_REVIEW_REQUIRED',
        'source':HEAD,'tree':TREE,'base':BASE,'checkout':CHECKOUT,
        'manifest':identity('c2-native-original-manifest.json'),
        'original_count':len(manifest['files']),'original_bytes':sum(f['bytes'] for f in manifest['files']),
        'runs':runs['workflow_runs'],'jobs':jobs,
        'step_counts':dict(Counter(s['conclusion'] for j in jobs for s in j['steps'])),
        'clippy_failures':failure_blocks,'source_scope':identity('c2-native-source-scope.json'),
        'native_structure':structure}
    out = ROOT / 'c2-native-review-structural.json'
    assert not out.exists()
    out.write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps({'output':identity(out.name),'original_count':result['original_count'],'original_bytes':result['original_bytes'],'steps':result['step_counts'],'harnesses':162,'repeated_passes':1820}))


if __name__ == '__main__':
    main()
