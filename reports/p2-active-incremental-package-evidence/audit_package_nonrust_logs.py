"""Read full available terminal native originals without assuming a full matrix.

This emits a derived partial observation only. Actual final review requires the
complete run/job/artifact manifest and independent artifact verification too.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path('/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package')
REPO = ROOT.parent / 'Zevune'
BASE = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
CONFIG = {
 'c2': ('f51c8db240933256870ff03c07bc68915b4ac4a1', '7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400', 'aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f'),
 'c3': ('cb0804e7c921a456cbbafab313b3a4a4501b8f5e', '21de343c12bc27cb1022ffd7ebd451abe0e61f29', '3dfa8d77921693b9e99af5b94af198498b9422e9'),
}
CANDIDATE = sys.argv[1]
SOURCE, TREE, CHECKOUT = CONFIG[CANDIDATE]
NATIVE = ROOT / (CANDIDATE + '-native')
EXPECTED = {'scaffold-tests', 'consensus-laboratory', 'orchard-bridge',
    'orchard-consensus-integration', 'orchard-cryptography-laboratory', 'wallet-laboratory',
    'funded-wallet-consensus', 'active-ledger-growth', 'payment-resource-baseline', 'local-network-operator'}


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def unique(pairs):
    out = {}
    for key, val in pairs:
        assert key not in out
        out[key] = val
    return out


def read(path):
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


assert subprocess.check_output(['git', 'diff', '--name-only', BASE, SOURCE, '--',
    '.github/workflows', 'scripts', 'integration/cometbft', 'internal/poolbridge', 'go.mod', 'go.sum'], cwd=REPO) == b''
all_runs, all_jobs, api_identities, observations = [], [], [], []
for run_path in sorted(NATIVE.glob('run-*.json')):
    run = read(run_path)
    run_id = run['id']
    assert run['name'] in EXPECTED and run['head_sha'] == SOURCE and run['head_commit']['tree_id'] == TREE
    assert run['event'] == 'pull_request' and run['run_attempt'] == 1 and run['status'] == 'completed'
    assert run['conclusion'] in {'success', 'failure'}
    assert run['pull_requests'][0]['number'] == 17 and run['pull_requests'][0]['base']['sha'] == BASE
    job_path, artifact_path = NATIVE / f'jobs-{run_id}.json', NATIVE / f'artifacts-{run_id}.json'
    group, artifacts = read(job_path), read(artifact_path)
    assert group['total_count'] == len(group['jobs'])
    assert artifacts['total_count'] == len(artifacts['artifacts'])
    api_identities.extend(identity(path) for path in [run_path, job_path, artifact_path])
    all_runs.append({'id': run_id, 'name': run['name'], 'conclusion': run['conclusion'], 'attempt': 1,
                     'url': run['html_url'], 'jobs': len(group['jobs']), 'artifacts': artifacts['total_count'],
                     'mutable_nested_pr_head_observed': run['pull_requests'][0]['head']['sha']})
    for job in group['jobs']:
        assert job['run_id'] == run_id and job['head_sha'] == SOURCE and job['run_attempt'] == 1
        assert job['status'] == 'completed' and job['conclusion'] in {'success', 'failure', 'skipped'}
        assert all(step['status'] == 'completed' for step in job['steps'])
        all_jobs.append(job)

for job in sorted(all_jobs, key=lambda row: row['id']):
    item = {key: job[key] for key in ('id', 'name', 'workflow_name', 'conclusion', 'html_url', 'steps')}
    path = NATIVE / f"job-{job['id']}.log"
    if job['conclusion'] == 'skipped':
        assert not job['steps'] and not path.exists()
        item['scope'] = 'zero-step skipped job, no workload executed'
        observations.append(item)
        continue
    raw = path.read_bytes()
    lines = [re.sub(r'\x1b\[[0-9;]*m', '', re.sub(r'^\d{4}-\d\d-\d\dT\S+\s?', '', line))
             for line in raw.decode('utf-8-sig').splitlines()]
    assert [line.removeprefix('Complete job name: ') for line in lines if line.startswith('Complete job name: ')] == [job['name']]
    checkouts = [lines[index + 1] for index, line in enumerate(lines)
                 if line.startswith('[command]') and 'log -1 --format=%H' in line]
    assert checkouts == [CHECKOUT]
    assert any('Cleaning up orphan processes' in line for line in lines)
    commands, cases, packages, suites, python_cases, fuzz, significant, builder = [], [], [], [], [], [], [], []
    current_fuzz = None
    for index, line in enumerate(lines):
        command = line.removeprefix('##[group]Run ')
        if re.match(r'^(?:GOMAXPROCS=\d+ )?go (?:test|vet|build|mod)\b', command):
            if not commands or commands[-1]['command'] != command or commands[-1]['line'] != index:
                commands.append({'line': index + 1, 'command': command})
        if re.match(r'^(?:ok|FAIL|\?)\s+github\.com/youq616/Zevune', line):
            packages.append({'line': index + 1, 'text': line, 'compile_only': '[no tests to run]' in line,
                             'no_test_files': '[no test files]' in line})
        matched = re.fullmatch(r'(\s*)--- (PASS|FAIL|SKIP): (\S+) \(([^)]+)\)', line)
        if matched:
            cases.append({'line': index + 1, 'name': matched[3], 'status': matched[2], 'duration': matched[4], 'nested': bool(matched[1])})
        if re.match(r'^test_.*\.\.\. (?:ok|skipped|FAIL|ERROR)', line):
            python_cases.append({'line': index + 1, 'text': line, 'skipped': '... skipped ' in line})
        matched = re.fullmatch(r'Ran (\d+) tests? in ([0-9.]+)s', line)
        if matched:
            ending = next((row for row in lines[index + 1:index + 5] if row.startswith(('OK', 'FAILED'))), None)
            assert ending and ending.startswith('OK')
            skip_match = re.search(r'skipped=(\d+)', ending)
            count, skips = int(matched[1]), int(skip_match[1]) if skip_match else 0
            assert len(python_cases) == count and sum(row['skipped'] for row in python_cases) == skips
            suites.append({'discovered': count, 'passed': count - skips, 'skipped': skips,
                           'seconds': float(matched[2]), 'ending': ending, 'cases': python_cases})
            python_cases = []
        if line.startswith('fuzz: elapsed: 0s, gathering baseline coverage: 0/'):
            assert current_fuzz is None
            current_fuzz = {'lines': [], 'entered': False}
        if line.startswith('fuzz: '):
            assert current_fuzz is not None
            current_fuzz['lines'].append(line)
            if 'now fuzzing with' in line: current_fuzz['entered'] = True
            matched = re.search(r'execs: (\d+).*new interesting: (\d+) \(total: (\d+)\)', line)
            if matched: current_fuzz.update(executions=int(matched[1]), new_interesting=int(matched[2]), corpus=int(matched[3]))
        if line == 'PASS' and current_fuzz is not None:
            assert current_fuzz['entered'] and current_fuzz['executions'] > 0
            current_fuzz['passed'] = True
            fuzz.append(current_fuzz)
            current_fuzz = None
        if any(marker in line for marker in ['ACTIVE_BOUNDARY', 'ACTIVE_GROWTH_', 'PAYMENT_RESOURCE_RESULT',
                    'FUNDED_LOCAL', 'all-four-node restart', 'shipped init/run/sync/submit commands:',
                    'genesis-bound signatures, downgrade rejection, actual nonzero']):
            significant.append({'line': index + 1, 'text': line})
        if line.startswith('{"built":'):
            builder.append(json.loads(line))
    assert current_fuzz is None and python_cases == []
    fuzz_commands = [row['command'] for row in commands if '-fuzz' in row['command']]
    assert len(fuzz_commands) == len(fuzz), (job['id'], fuzz_commands, fuzz)
    for command, engine in zip(fuzz_commands, fuzz): engine['command'] = command
    assert not [row for row in cases if row['status'] == 'FAIL']
    assert not [row for row in packages if row['text'].startswith('FAIL')]
    errors = [line for line in lines if line.startswith('##[error]')]
    if job['conclusion'] == 'success': assert not errors
    item.update({'log': identity(path), 'complete_log_lines_scanned': len(lines), 'has_utf8_bom': raw.startswith(b'\xef\xbb\xbf'),
        'crlf_count': raw.count(b'\r\n'), 'checkout': CHECKOUT, 'cleanup_marker': True,
        'go_versions': sorted({line for line in lines if line.startswith('go version go')}),
        'go_commands_observed': commands, 'go_package_results': packages, 'go_named_results': cases,
        'go_top_level_passes': sum(row['status'] == 'PASS' and not row['nested'] for row in cases),
        'go_all_named_passes_including_nested': sum(row['status'] == 'PASS' for row in cases),
        'go_skips': [row for row in cases if row['status'] == 'SKIP'], 'python_suites': suites,
        'fuzz_engine_runs': fuzz, 'significant_lines': significant, 'bundle_builder_receipts': builder,
        'error_lines': errors, 'group_headers': [line for line in lines if line.startswith('##[group]')]})
    observations.append(item)

logs = [row for row in observations if 'log' in row]
result = {'kind': 'PARTIAL_ORIGINAL_OBSERVATION_NOT_COMPLETE_MATRIX_ACCEPTANCE',
    'reviewer': '/root/p2_package_native_audit/nonrust_logs', 'candidate': CANDIDATE,
    'head': SOURCE, 'base': BASE, 'tree': TREE, 'checkout': CHECKOUT,
    'expected_workflows': sorted(EXPECTED), 'not_yet_reviewed_workflows': sorted(EXPECTED - {run['name'] for run in all_runs}),
    'workflow_budget_source_unchanged_from_base': True, 'original_api_files': api_identities,
    'runs': all_runs, 'jobs': observations,
    'totals': {'runs': len(all_runs), 'run_outcomes': dict(Counter(run['conclusion'] for run in all_runs)),
        'jobs': len(all_jobs), 'job_outcomes': dict(Counter(job['conclusion'] for job in all_jobs)),
        'steps': dict(Counter(step['conclusion'] for job in all_jobs for step in job['steps'])),
        'complete_logs': len(logs), 'log_bytes': sum(row['log']['bytes'] for row in logs),
        'python_suites': sum(len(row['python_suites']) for row in logs),
        'python_discovered_repeated': sum(suite['discovered'] for row in logs for suite in row['python_suites']),
        'python_passed_repeated': sum(suite['passed'] for row in logs for suite in row['python_suites']),
        'python_skipped_repeated': sum(suite['skipped'] for row in logs for suite in row['python_suites']),
        'go_fuzz_engine_runs': sum(len(row['fuzz_engine_runs']) for row in logs)},
    'limitations': ['Complete retained logs were scanned; source-specific execution observations only.',
        'Whole-matrix review and complete artifact manifest are required separately.',
        'Rust harnesses are reviewed by the parent native auditor, not counted here.',
        'No locally executed native workload; no cross-candidate credit.',
        'Declared commands require successful API step and actual outputs for execution credit.',
        'Repeated suites, nested tests, fuzz seeds and compile-only outputs do not create new unique tests.']}
path = ROOT / f'{CANDIDATE}-nonrust-observations-partial.json'
path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
print(json.dumps({'output': identity(path), 'totals': result['totals'], 'pending': result['not_yet_reviewed_workflows']},ensure_ascii=False,indent=2))
for row in logs:
    print(json.dumps({'job': row['id'], 'name': row['name'], 'workflow': row['workflow_name'], 'outcome': row['conclusion'],
        'go_pass': row['go_top_level_passes'], 'go_all_pass': row['go_all_named_passes_including_nested'], 'skips': row['go_skips'],
        'fuzz': [{'command': engine['command'], 'executions': engine['executions']} for engine in row['fuzz_engine_runs']],
        'python': [{key:suite[key] for key in ['discovered','passed','skipped']} for suite in row['python_suites']],
        'markers': row['significant_lines'], 'builder': row['bundle_builder_receipts']},ensure_ascii=False))
