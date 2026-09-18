"""Independent audit of complete, immutable C1 native original files.

This reads retained evidence only. It does not run native workloads or import
prior-stage results, and it never upgrades this rejected candidate to PASS.
"""
from collections import Counter
from pathlib import Path
import hashlib
import json
import re
import subprocess
import zipfile

ROOT = Path('/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package')
REPO = ROOT.parent / 'Zevune'
BASE = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
SOURCE = '61c691270b91aece076177cb757e51e0e63fe310'
TREE = '56dad7fdaad64b2b29ddac6b9585b8695aa465d7'
CHECKOUT = 'bd710cf4c985012ca23e86c333567ce116de72bb'
REVIEWER = '/root/p2_package_native_audit/nonrust_logs'
NATIVE = ROOT / 'c1-native'


def read_json(path):
    def unique(pairs):
        out = {}
        for key, val in pairs:
            assert key not in out, (path, key)
            out[key] = val
        return out
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


manifest = read_json(ROOT / 'c1-native-original-manifest.json')
files = [identity(path) for path in sorted(NATIVE.rglob('*')) if path.is_file()]
assert files == manifest['files']
assert len(files) == 56 and sum(row['bytes'] for row in files) == 1367731
commits = []
for key, expected, tree in [('base', BASE, None), ('c1', SOURCE, TREE), ('c1-synthetic', CHECKOUT, TREE)]:
    path = ROOT / 'source-identities' / (key + '-git-commit.json')
    value = read_json(path)
    assert value['sha'] == expected
    if tree:
        assert value['tree']['sha'] == tree
    parents = [entry['sha'] for entry in value['parents']]
    if key == 'c1': assert parents == [BASE]
    if key == 'c1-synthetic': assert parents == [BASE, SOURCE]
    commits.append({**identity(path), 'sha': expected, 'tree': value['tree']['sha'], 'parents': parents})

initial_pr_path = ROOT / 'source-identities/c1-initial-pr.json'
initial_pr = read_json(initial_pr_path)
assert initial_pr['number'] == 17 and initial_pr['head']['sha'] == SOURCE and initial_pr['base']['sha'] == BASE
assert initial_pr['merge_commit_sha'] == CHECKOUT

unchanged_paths = ['.github/workflows', 'scripts', 'integration/cometbft',
                   'internal/poolbridge', 'go.mod', 'go.sum']
assert subprocess.check_output(['git', 'diff', '--name-only', BASE, SOURCE, '--', *unchanged_paths], cwd=REPO) == b''
workflow_identities = []
for path in sorted((REPO / '.github/workflows').glob('*.yml')):
    raw = subprocess.check_output(['git', 'show', SOURCE + ':' + str(path.relative_to(REPO))], cwd=REPO)
    assert raw == path.read_bytes()
    workflow_identities.append({'path': str(path.relative_to(REPO)), 'bytes': len(raw),
                                'sha256': hashlib.sha256(raw).hexdigest()})
assert len(workflow_identities) == 12

expected_workflows = {'scaffold-tests', 'consensus-laboratory', 'orchard-bridge',
    'orchard-consensus-integration', 'orchard-cryptography-laboratory', 'wallet-laboratory',
    'funded-wallet-consensus', 'active-ledger-growth', 'payment-resource-baseline', 'local-network-operator'}
runs_data = read_json(NATIVE / 'runs.json')
runs = runs_data['workflow_runs']
assert runs_data['total_count'] == len(runs) == 10
assert {run['name'] for run in runs} == expected_workflows
all_jobs, run_summaries = [], []
for run in runs:
    run_id = run['id']
    complete = read_json(NATIVE / f'run-{run_id}.json')
    for obj in (run, complete):
        assert obj['head_sha'] == SOURCE and obj['head_commit']['tree_id'] == TREE
        assert obj['event'] == 'pull_request' and obj['run_attempt'] == 1 and obj['status'] == 'completed'
        assert obj['conclusion'] in {'success', 'failure'}
        assert len(obj['pull_requests']) == 1
        pr = obj['pull_requests'][0]
        assert pr['number'] == 17 and pr['base']['sha'] == BASE
        assert pr['head']['sha'] == 'f51c8db240933256870ff03c07bc68915b4ac4a1'  # live PR projection after C2
    assert run['conclusion'] == complete['conclusion']
    group = read_json(NATIVE / f'jobs-{run_id}.json')
    assert group['total_count'] == len(group['jobs'])
    for job in group['jobs']:
        assert job['run_id'] == run_id and job['head_sha'] == SOURCE
        assert job['run_attempt'] == 1 and job['status'] == 'completed'
        assert all(step['status'] == 'completed' for step in job['steps'])
    all_jobs.extend(group['jobs'])
    artifacts = read_json(NATIVE / f'artifacts-{run_id}.json')
    assert artifacts['total_count'] == len(artifacts['artifacts'])
    if run['name'] != 'payment-resource-baseline': assert artifacts['total_count'] == 0
    run_summaries.append({'id': run_id, 'name': run['name'], 'conclusion': run['conclusion'],
                          'attempt': 1, 'url': run['html_url'], 'jobs': len(group['jobs']),
                          'artifacts': artifacts['total_count'],
                          'mutable_nested_pr_head_observed': run['pull_requests'][0]['head']['sha']})
assert len(all_jobs) == 22 and len({job['id'] for job in all_jobs}) == 22
assert Counter(run['conclusion'] for run in runs) == {'failure': 8, 'success': 2}
assert Counter(job['conclusion'] for job in all_jobs) == {'failure': 17, 'success': 4, 'skipped': 1}

ansi = re.compile(r'\x1b\[[0-9;]*m')
timestamp = re.compile(r'^\d{4}-\d\d-\d\dT\S+\s?')
observations = []
for job in sorted(all_jobs, key=lambda item: item['id']):
    item = {key: job[key] for key in ('id', 'name', 'workflow_name', 'conclusion', 'html_url', 'steps')}
    log = NATIVE / f"job-{job['id']}.log"
    if job['conclusion'] == 'skipped':
        assert job['name'] == 'growth' and job['steps'] == [] and not log.exists()
        item['execution_scope'] = 'zero-step unexpanded matrix dependency skip; neither platform ran'
        observations.append(item)
        continue
    raw = log.read_bytes()
    lines = [ansi.sub('', timestamp.sub('', line)) for line in raw.decode('utf-8-sig').splitlines()]
    assert [x.removeprefix('Complete job name: ') for x in lines if x.startswith('Complete job name: ')] == [job['name']]
    checkouts = [lines[i + 1] for i, line in enumerate(lines) if line.startswith('[command]') and 'log -1 --format=%H' in line]
    assert checkouts == [CHECKOUT]
    assert any('Cleaning up orphan processes' in line for line in lines)
    item.update({'log': identity(log), 'line_count': len(lines), 'has_utf8_bom': raw.startswith(b'\xef\xbb\xbf'),
                 'crlf_count': raw.count(b'\r\n'), 'checkout': CHECKOUT, 'complete_cleanup_marker': True})
    commands, packages, cases, py_cases, py_suites, fuzz, errors = [], [], [], [], [], [], []
    current_fuzz = None
    for index, line in enumerate(lines):
        command = line.removeprefix('##[group]Run ')
        if re.match(r'^(?:GOMAXPROCS=\d+ )?go (?:test|vet|build|mod)\b', command):
            if not commands or commands[-1]['command'] != command or commands[-1]['line'] != index:
                commands.append({'line': index + 1, 'command': command})
        if re.match(r'^(?:ok|FAIL|\?)\s+github\.com/youq616/Zevune', line):
            packages.append({'line': index + 1, 'text': line, 'compile_only': '[no tests to run]' in line,
                             'no_test_files': '[no test files]' in line})
        match = re.fullmatch(r'(\s*)--- (PASS|FAIL|SKIP): (\S+) \(([^)]+)\)', line)
        if match:
            cases.append({'line': index + 1, 'name': match[3], 'status': match[2], 'duration': match[4],
                          'nested': bool(match[1])})
        if re.match(r'^test_.*\.\.\. (?:ok|skipped|FAIL|ERROR)', line):
            py_cases.append({'line': index + 1, 'text': line, 'skipped': '... skipped ' in line})
        match = re.fullmatch(r'Ran (\d+) tests? in ([0-9.]+)s', line)
        if match:
            ending = next((x for x in lines[index + 1:index + 5] if x.startswith(('OK', 'FAILED'))), None)
            assert ending and ending.startswith('OK')
            skips = re.search(r'skipped=(\d+)', ending)
            count, skipped = int(match[1]), int(skips[1]) if skips else 0
            assert len(py_cases) == count and sum(x['skipped'] for x in py_cases) == skipped
            py_suites.append({'discovered': count, 'passed': count - skipped, 'skipped': skipped,
                              'seconds': float(match[2]), 'ending': ending, 'cases': py_cases})
            py_cases = []
        if line.startswith('fuzz: elapsed: 0s, gathering baseline coverage: 0/'):
            assert current_fuzz is None
            current_fuzz = {'lines': [], 'entered': False}
        if line.startswith('fuzz: '):
            assert current_fuzz is not None
            current_fuzz['lines'].append(line)
            if 'now fuzzing with' in line: current_fuzz['entered'] = True
            match = re.search(r'execs: (\d+).*new interesting: (\d+) \(total: (\d+)\)', line)
            if match: current_fuzz.update(executions=int(match[1]), new_interesting=int(match[2]), corpus=int(match[3]))
        if line == 'PASS' and current_fuzz is not None:
            current_fuzz['passed'] = True
            assert current_fuzz['entered'] and current_fuzz['executions'] > 0
            fuzz.append(current_fuzz)
            current_fuzz = None
        if line.startswith('##[error]'): errors.append(line)
    assert current_fuzz is None and py_cases == []
    assert not [case for case in cases if case['status'] == 'FAIL']
    assert not [line for line in lines if re.match(r'^test result:|^running \d+ tests?$', line)]
    assert not [line for line in lines if re.match(r'^FUNDED_COHORT_COMPLETE|^.*ACTIVE_GROWTH_RESULT committed|^PAYMENT_RESOURCE_RESULT (passed|failed)', line)]
    fmt_headers = [line for line in lines if line.startswith('Diff in ')]
    if job['conclusion'] == 'failure':
        assert errors == ['##[error]Process completed with exit code 1.']
        assert len(fmt_headers) == 30
        normalized_paths = [re.sub(r':\d+:$', '', line.partition('/Zevune/')[2]) if '/Zevune/' in line
                            else re.sub(r':\d+:$', '', line.partition('\\Zevune\\')[2]).replace('\\', '/') for line in fmt_headers]
        if '' in normalized_paths:
            normalized_paths = [re.sub(r':\d+:$', '', re.split(r'Zevune[\\/]', line)[-1]).replace('\\', '/') for line in fmt_headers]
        assert len(set(normalized_paths)) == 7, normalized_paths
    else:
        assert not errors and not fmt_headers
    item.update({'go_commands': commands, 'go_package_results': packages, 'go_named_results': cases,
                 'go_top_level_passes': sum(row['status'] == 'PASS' and not row['nested'] for row in cases),
                 'go_all_named_passes_including_nested': sum(row['status'] == 'PASS' for row in cases),
                 'go_skips': [row for row in cases if row['status'] == 'SKIP'], 'python_suites': py_suites,
                 'fuzz_engine_runs': fuzz, 'errors': errors, 'format_diff_hunks': len(fmt_headers),
                 'go_versions': sorted({line for line in lines if line.startswith('go version go')}),
                 'group_headers': [line for line in lines if line.startswith('##[group]')],
                 'rust_test_harnesses': 0})
    observations.append(item)

logs = [item for item in observations if 'log' in item]
assert len(logs) == 21 and sum(item['log']['bytes'] for item in logs) == 1056143
assert len(list(NATIVE.glob('job-*.log'))) == 21
resource_metadata = read_json(NATIVE / 'artifacts-35362376595.json')['artifacts']
resources = []
for platform in ('ubuntu', 'windows'):
    metadata = next(row for row in resource_metadata if f'-{platform}-latest-' in row['name'])
    zip_path = NATIVE / f'payment-resources-{platform}.zip'
    setup_path = NATIVE / f'payment-resources-{platform}-setup.json'
    assert metadata['workflow_run']['id'] == 35362376595 and metadata['workflow_run']['head_sha'] == SOURCE
    assert metadata['expired'] is False and metadata['name'].endswith(CHECKOUT)
    assert zip_path.stat().st_size == metadata['size_in_bytes']
    assert 'sha256:' + identity(zip_path)['sha256'] == metadata['digest']
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.namelist() == ['payment-resource-setup.json']
        assert archive.read('payment-resource-setup.json') == setup_path.read_bytes()
    setup = read_json(setup_path)
    assert setup['schema_version'] == 1 and setup['kind'] == 'workflow_setup_observation'
    assert setup['source_head'] == SOURCE and setup['checkout_commit'] == CHECKOUT and setup['checkout_tree'] == TREE
    assert setup['observed_execution_status'] == 'not_started'
    resources.append({'platform': platform, 'artifact_id': metadata['id'], 'metadata': metadata,
                      'zip': identity(zip_path), 'setup': identity(setup_path), 'setup_content': setup,
                      'workload_result_present': False, 'events': 0, 'progress_records': 0, 'memory_samples': 0})

result = {'schema_version': 1, 'reviewer': REVIEWER,
    'conclusion': 'C1_REJECTED_NATIVE_FMT_FAILURE_NONRUST_LIMITED_COVERAGE_ONLY',
    'independent_non_author': True, 'source': SOURCE, 'base': BASE, 'tree': TREE, 'checkout': CHECKOUT,
    'source_originals': commits, 'initial_pr_original': identity(initial_pr_path),
    'nested_live_pr_head_is_not_run_source_identity': True, 'original_manifest': identity(ROOT / 'c1-native-original-manifest.json'),
    'originals_count': len(files), 'originals_bytes': sum(row['bytes'] for row in files),
    'all_originals_sha256_and_length_verified': True, 'originals': files,
    'unchanged_scope_compared_to_base': unchanged_paths, 'workflow_identities': workflow_identities,
    'runs': run_summaries, 'jobs': observations, 'resources': resources,
    'totals': {'workflows': 10, 'workflow_success': 2, 'workflow_failure': 8,
               'jobs': 22, 'job_success': 4, 'job_failure': 17, 'job_skipped_unexpanded_matrix': 1,
               'complete_logs': len(logs), 'log_bytes': sum(item['log']['bytes'] for item in logs),
               'steps': dict(Counter(step['conclusion'] for job in all_jobs for step in job['steps'])),
               'python_suites': sum(len(item['python_suites']) for item in logs),
               'python_discovered_repeated_executions': sum(suite['discovered'] for item in logs for suite in item['python_suites']),
               'python_passed_repeated_executions': sum(suite['passed'] for item in logs for suite in item['python_suites']),
               'python_skipped_repeated_executions': sum(suite['skipped'] for item in logs for suite in item['python_suites']),
               'go_fuzz_engine_runs': sum(len(item['fuzz_engine_runs']) for item in logs),
               'rust_harnesses': 0, 'growth_workloads': 0, 'resource_workloads': 0, 'operator_bundles': 0},
    'limitations': ['No local Go or Rust workload was executed by this reviewer.',
        'Complete decoded raw log bytes were read, hashed and parsed; report facts cite actual API steps and log lines.',
        'Python repeats, nested Go tests and fuzz seeds are not distinct new-case totals.',
        'Compile-only Go invocations are not executed unit test credit.',
        'Setup not_started artifacts carry identity only, not resource workload or OS memory credit.',
        'No later candidate, previous phase, production readiness, finality or security audit credit.']}
output = ROOT / 'c1-native-nonrust-review.json'
output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
print(json.dumps({'output': identity(output), 'totals': result['totals']}, ensure_ascii=False, indent=2))
for item in logs:
    print(json.dumps({'id': item['id'], 'name': item['name'], 'workflow': item['workflow_name'],
        'top_level_go_pass': item['go_top_level_passes'], 'all_go_pass': item['go_all_named_passes_including_nested'],
        'python': [{key: row[key] for key in ('discovered', 'passed', 'skipped')} for row in item['python_suites']],
        'go_fuzz': len(item['fuzz_engine_runs'])},ensure_ascii=False))
