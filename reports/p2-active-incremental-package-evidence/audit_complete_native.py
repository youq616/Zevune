"""Independent structural gates for complete positive-candidate original evidence.

This reads all original bytes and all Rust names. It does not execute tests or
grant review approval; source meaning and non-Rust originals need human review.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from audit_native_structure_v2 import inspect_logs


def file_identity(path, root):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(root)), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    root = Path(__file__).resolve().parent
    label, head, tree, checkout = sys.argv[1:]
    base = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
    directory = root / f'{label}-native'
    manifest_path = root / f'{label}-native-original-manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    originals = manifest['files']
    assert len(originals) == len({f['path'] for f in originals})
    for file in originals:
        assert file_identity(root / file['path'], root) == file
    assert {str(p.relative_to(root)) for p in directory.rglob('*') if p.is_file()} == {f['path'] for f in originals}
    source = json.loads((root / f'{label}-native-source-scope.json').read_bytes())
    assert source['candidate'] == head and source['tree'] == tree and source['base'] == base
    source_commit_path = root / 'source-identities' / f'{label}-git-commit.json'
    checkout_commit_path = root / 'source-identities' / f'{label}-synthetic-git-commit.json'
    source_commit = json.loads(source_commit_path.read_bytes())
    checkout_commit = json.loads(checkout_commit_path.read_bytes())
    assert source_commit['sha'] == head and source_commit['tree']['sha'] == tree
    assert checkout_commit['sha'] == checkout and checkout_commit['tree']['sha'] == tree
    assert [p['sha'] for p in checkout_commit['parents']] == [base, head]
    structure = inspect_logs(directory, head, checkout)
    assert structure['log_count'] == 23
    logs = {int(row['path'][4:-4]): row for row in structure['records']}
    assert len(logs) == 23
    for row in logs.values():
        assert not row['errors'] and not row['format_hunks'] and row['cleanup_observed']
    run_list = json.loads((directory / 'runs.json').read_bytes())
    assert run_list['total_count'] == len(run_list['workflow_runs']) == 10
    workflow_jobs = {'scaffold-tests': 2, 'consensus-laboratory': 2, 'orchard-bridge': 2,
        'orchard-consensus-integration': 2, 'orchard-cryptography-laboratory': 2,
        'wallet-laboratory': 2, 'funded-wallet-consensus': 4, 'active-ledger-growth': 3,
        'payment-resource-baseline': 2, 'local-network-operator': 2}
    allowed_skips = {
        ('scaffold-tests', 'Race detector'),
        ('scaffold-tests', 'Bounded decoder fuzz smoke test'),
        ('scaffold-tests', 'Bounded journal decoder fuzz smoke test'),
        ('consensus-laboratory', 'Adapter race checks'),
        ('orchard-bridge', 'Boundary race checks'),
        ('orchard-bridge', 'Bounded decoder fuzz checks'),
        ('orchard-consensus-integration', 'Real adapter race checks'),
        ('orchard-consensus-integration', 'Local IPC race and bounded fuzz'),
        ('local-network-operator', 'Race and bounded fuzz checks'),
    }
    default_workflows = {'orchard-bridge', 'orchard-consensus-integration',
                         'orchard-cryptography-laboratory', 'wallet-laboratory'}
    jobs = []
    seen_skip = set()
    defaults = {'ubuntu': [], 'windows': []}
    default_harnesses = {'ubuntu': [], 'windows': []}
    funded_libraries = {}
    funded_interfaces = {}
    for run in run_list['workflow_runs']:
        assert run['name'] in workflow_jobs
        assert run['head_sha'] == head and run['event'] == 'pull_request'
        assert run['head_commit']['id'] == head and run['head_commit']['tree_id'] == tree
        assert run['run_attempt'] == 1 and run['status'] == 'completed' and run['conclusion'] == 'success'
        full = json.loads((directory / f'run-{run["id"]}.json').read_bytes())
        for key in ['id', 'name', 'head_sha', 'event', 'run_attempt', 'status', 'conclusion']:
            assert full[key] == run[key]
        assert full['head_commit']['id'] == head and full['head_commit']['tree_id'] == tree
        inventory = json.loads((directory / f'jobs-{run["id"]}.json').read_bytes())
        assert inventory['total_count'] == len(inventory['jobs']) == workflow_jobs[run['name']]
        for job in inventory['jobs']:
            assert job['head_sha'] == head and job['run_id'] == run['id']
            assert job['run_attempt'] == 1 and job['status'] == 'completed' and job['conclusion'] == 'success'
            platform = 'windows' if 'windows-latest' in job['name'] else 'ubuntu'
            for step in job['steps']:
                assert step['status'] == 'completed'
                if step['conclusion'] == 'skipped':
                    pair = (run['name'], step['name'])
                    assert platform == 'windows' and pair in allowed_skips and pair not in seen_skip
                    seen_skip.add(pair)
                else:
                    assert step['conclusion'] == 'success'
            log = logs[job['id']]
            harnesses = log['rust']['harnesses']
            record = {'workflow': run['name'], 'run': run['id'], 'platform': platform,
                      'id': job['id'], 'name': job['name'], 'url': job['html_url'],
                      'steps': job['steps'], 'harness_count': len(harnesses),
                      'passed_executions': sum(h['passed'] for h in harnesses)}
            jobs.append(record)
            if run['name'] in default_workflows:
                assert len(harnesses) == 20
                lib = next(h for h in harnesses if h['target'] == 'src/lib.rs')
                assert lib['passed'] == (163 if platform == 'windows' else 171)
                assert record['passed_executions'] == (177 if platform == 'windows' else 185)
                defaults[platform].append(set(lib['named_passes']))
                default_harnesses[platform].append([
                    (h['kind'], h['target'], h['passed'], sorted(h['named_passes']))
                    for h in harnesses])
                new = sorted(name for name in lib['named_passes'] if '::package::tests::' in name)
                assert new == source['expected'][platform]['new_library_names']
                cli = next(h for h in harnesses if h['target'] == 'tests/active_incremental_package_cli.rs')
                assert cli['passed'] == 0 and not cli['named_passes']
                assert not log['rust']['funded_plans'] and not log['rust']['funded_complete']
            elif run['name'] == 'funded-wallet-consensus':
                plans = log['rust']['funded_plans']
                assert len(plans) == 1
                plan = plans[0]
                assert log['rust']['funded_complete'] == [plan['cohort']]
                for command in plan['commands']:
                    assert command[:6] == ['cargo', 'test', '--locked', '--release', '--features', 'local-funding-lab']
                    assert command[command.index('--') + 1:] == ['--test-threads=1']
                    assert not {'--skip', '--ignored', '--no-run', '--exclude'}.intersection(command)
                if job['name'].startswith('funded-library '):
                    assert plan['cohort'] == 'library' and not plan['documentation_tests']
                    assert plan['test_targets'] == [['lib', 'zevune_orchard_lab']]
                    assert len(harnesses) == 1 and harnesses[0]['target'] == 'src/lib.rs'
                    lib = harnesses[0]
                    assert lib['passed'] == (182 if platform == 'windows' else 190)
                    names = set(lib['named_passes'])
                    assert sorted(n for n in names if '::package::tests::' in n) == source['expected'][platform]['new_library_names']
                    assert 'pool::active_flow_tests::real_payments_rotate_default_segments_cross_10000_and_reopen_through_10002' in names
                    funded_libraries[platform] = names
                else:
                    assert job['name'].startswith('funded ')
                    assert plan['cohort'] == 'interfaces' and plan['documentation_tests']
                    assert len(harnesses) == 22 and len(plan['test_targets']) == 21
                    assert Counter(kind for kind, name in plan['test_targets']) == Counter(bin=5, test=16)
                    actual_targets = set()
                    for h in harnesses:
                        if h['kind'] == 'doc':
                            assert h['target'] == 'zevune_orchard_lab'
                        elif h['target'].startswith('src/bin/'):
                            actual_targets.add(('bin', Path(h['target']).stem))
                        else:
                            assert h['target'].startswith('tests/')
                            actual_targets.add(('test', Path(h['target']).stem))
                    assert actual_targets == {tuple(item) for item in plan['test_targets']}
                    cli = next(h for h in harnesses if h['target'] == 'tests/active_incremental_package_cli.rs')
                    assert sorted(cli['named_passes']) == source['expected'][platform]['new_cli_names']
                    assert cli['passed'] == (7 if platform == 'windows' else 8)
                    assert record['passed_executions'] == (70 if platform == 'windows' else 71)
                    assert next(h for h in harnesses if h['target'] == 'tests/active_incremental_cli.rs')['passed'] == 7
                    funded_interfaces[platform] = record
            else:
                assert not harnesses
    assert len(jobs) == len({job['id'] for job in jobs}) == 23
    assert seen_skip == allowed_skips
    for platform in ['ubuntu', 'windows']:
        assert len(defaults[platform]) == 4
        assert all(names == defaults[platform][0] for names in defaults[platform])
        assert all(harnesses == default_harnesses[platform][0]
                   for harnesses in default_harnesses[platform])
        assert defaults[platform][0] <= funded_libraries[platform]
        assert len(funded_libraries[platform] - defaults[platform][0]) == 19
        assert platform in funded_interfaces
    assert structure['rust_harnesses'] == 206
    assert structure['rust_passed_executions'] == 1961
    result = {'status': 'STRUCTURAL_CHECKS_COMPLETE / INDEPENDENT_REVIEW_REQUIRED',
              'source': head, 'base': base, 'tree': tree, 'checkout': checkout,
              'git_identities': [file_identity(source_commit_path, root), file_identity(checkout_commit_path, root)],
              'manifest': file_identity(manifest_path, root),
              'original_count': len(originals), 'original_bytes': sum(f['bytes'] for f in originals),
              'originals': originals, 'runs': run_list['workflow_runs'], 'jobs': jobs,
              'step_counts': dict(Counter(step['conclusion'] for job in jobs for step in job['steps'])),
              'source_scope': file_identity(root / f'{label}-native-source-scope.json', root),
              'native_structure': structure}
    output = root / f'{label}-native-review-structural.json'
    assert not output.exists()
    output.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
    print(json.dumps({'output': file_identity(output, root), 'original_count': len(originals),
                      'original_bytes': result['original_bytes'], 'step_counts': result['step_counts'],
                      'harnesses': structure['rust_harnesses'], 'repeated_passes': structure['rust_passed_executions']}))


if __name__ == '__main__':
    main()
