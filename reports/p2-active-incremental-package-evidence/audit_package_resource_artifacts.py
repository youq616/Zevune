"""Independently recheck full native payment-resource artifacts for one candidate.

Reads immutable originals and exact source; does not execute downloaded/native
programs, perform payments, collect fresh OS samples, or accept the whole stage.
"""
from pathlib import Path
from collections import Counter
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
ROOT = Path('/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package')
REPO = ROOT.parent / 'Zevune'
BASE = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
CONFIG = {
 'c2': ('f51c8db240933256870ff03c07bc68915b4ac4a1', '7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400',
        'aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f', 35362925495),
 'c3': ('cb0804e7c921a456cbbafab313b3a4a4501b8f5e', '21de343c12bc27cb1022ffd7ebd451abe0e61f29',
        '3dfa8d77921693b9e99af5b94af198498b9422e9', 35363727198),
}
CANDIDATE = sys.argv[1]
SOURCE, TREE, CHECKOUT, RUN = CONFIG[CANDIDATE]
NATIVE = ROOT / (CANDIDATE + '-native')
script = REPO / 'scripts/check_payment_resources.py'
assert script.read_bytes() == subprocess.check_output(['git', 'show', SOURCE + ':scripts/check_payment_resources.py'], cwd=REPO)
assert subprocess.check_output(['git', 'diff', '--name-only', BASE, SOURCE, '--',
    'scripts/check_payment_resources.py', 'internal/poolbridge/payment_resource_e2e_test.go',
    '.github/workflows/payment-resources.yml'], cwd=REPO) == b''
spec = importlib.util.spec_from_file_location('p2package_resource_validator', script)
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read(path, maximum=2 << 20):
    return validator.decode_json(path.read_bytes(), maximum)


run_path = NATIVE / f'run-{RUN}.json'
job_path = NATIVE / f'jobs-{RUN}.json'
artifact_path = NATIVE / f'artifacts-{RUN}.json'
run, jobs, artifacts = read(run_path), read(job_path), read(artifact_path)
assert run['id'] == RUN and run['name'] == 'payment-resource-baseline'
assert run['head_sha'] == SOURCE and run['head_commit']['tree_id'] == TREE
assert run['status'] == 'completed' and run['conclusion'] == 'success' and run['run_attempt'] == 1
assert run['event'] == 'pull_request'
assert jobs['total_count'] == len(jobs['jobs']) == 2
assert artifacts['total_count'] == len(artifacts['artifacts']) == 2
outputs = []
for platform, native_platform in [('ubuntu', 'linux'), ('windows', 'win32')]:
    job = next(row for row in jobs['jobs'] if row['name'] == f'resources ({platform}-latest)')
    assert job['run_id'] == RUN and job['head_sha'] == SOURCE and job['run_attempt'] == 1
    assert job['status'] == 'completed' and job['conclusion'] == 'success'
    assert len(job['steps']) == 15 and all(step['status'] == 'completed' and step['conclusion'] == 'success' for step in job['steps'])
    raw_log_path = NATIVE / f"job-{job['id']}.log"
    raw_log = raw_log_path.read_bytes()
    lines = [re.sub(r'\x1b\[[0-9;]*m', '', re.sub(r'^\d{4}-\d\d-\d\dT\S+\s?', '', value))
             for value in raw_log.decode('utf-8-sig').splitlines()]
    checkouts = [lines[index + 1] for index, value in enumerate(lines)
                 if value.startswith('[command]') and 'log -1 --format=%H' in value]
    assert checkouts == [CHECKOUT]
    assert any('Cleaning up orphan processes' in line for line in lines)
    assert not [line for line in lines if line.startswith('##[error]')]
    passed_test = [line for line in lines if line.startswith('--- PASS: TestActivePaymentResources32AndRecovery ')]
    assert len(passed_test) == 1 and lines.count('PAYMENT_RESOURCE_RESULT passed') == 1
    fixed_final_marker = 'PAYMENT_RESOURCE_RESULT paid_blocks=33 actions_per_payment=2 commitments=68 nullifiers=66 fees=33000; complete Summary/capacity, full replay, receipt-bound wallets, exact outbox, physical frames and rejection non-mutation passed'
    assert sum(fixed_final_marker in line for line in lines) == 1
    assert any("subprocess.run(['go', 'test', '-c', '-mod=readonly', '-tags=payment_resource_e2e'," in line for line in lines)
    assert any("subprocess.run(['go', 'vet', '-mod=readonly', '-tags=payment_resource_e2e'," in line for line in lines)
    assert any('cargo +1.98.1 build --manifest-path integration/orchard/Cargo.toml --locked --release --features local-funding-lab --bins' == line for line in lines)

    metadata = next(row for row in artifacts['artifacts'] if f'-{platform}-latest-' in row['name'])
    assert metadata['workflow_run']['id'] == RUN and metadata['workflow_run']['head_sha'] == SOURCE
    assert metadata['expired'] is False and metadata['name'].endswith(CHECKOUT)
    zip_path = NATIVE / f'payment-resources-{platform}.zip'
    setup_path = NATIVE / f'payment-resources-{platform}-setup.json'
    result_path = NATIVE / f'payment-resources-{platform}-result.json'
    assert zip_path.stat().st_size == metadata['size_in_bytes']
    assert 'sha256:' + identity(zip_path)['sha256'] == metadata['digest']
    with zipfile.ZipFile(zip_path) as archive:
        assert sorted(archive.namelist()) == ['payment-resource-setup.json', 'payment-resources.json']
        assert archive.read('payment-resource-setup.json') == setup_path.read_bytes()
        assert archive.read('payment-resources.json') == result_path.read_bytes()
    setup, data = read(setup_path), read(result_path)
    assert setup['schema_version'] == 1 and setup['kind'] == 'workflow_setup_observation'
    assert setup['observed_execution_status'] == 'not_started'
    assert setup['source_head'] == SOURCE and setup['checkout_commit'] == CHECKOUT and setup['checkout_tree'] == TREE
    assert data['schema_version'] == 1 and data['status'] == 'passed' and data['platform'] == native_platform
    assert data['scope'] == 'fixed_32_plus_1_no_funds_payment_resource_baseline'
    actual = data['metadata']
    assert actual['source_head'] == SOURCE and actual['source_tree'] == TREE
    assert actual['checkout_commit'] == CHECKOUT and actual['checkout_tree'] == TREE
    assert actual['toolchains']['go'].startswith('go version go1.27.1 ')
    assert actual['toolchains']['rustc'].startswith('rustc 1.98.1 ')
    assert actual['toolchains']['cargo'].startswith('cargo 1.98.1 ')
    assert data['targets'] == validator.initial_evidence()['targets']
    assert data['measurement_limits'] == validator.initial_evidence()['measurement_limits']
    assert data['go_exit_code'] == 0 and data['failures'] == []
    assert data['unfinished_operation'] is None and data['commit_outcome_uncertain'] is False
    assert data['last_confirmed_committed_blocks'] == 33
    assert data['cleanup'] == {'initial_roles_registered': True,
        'precheckpoint_child_tree_cleanup_confirmed': False, 'registered_children_exit_confirmed': True,
        'registered_processes': 3, 'scope': 'retained_identities_and_normal_Go_cleanup_not_a_process_sandbox'}
    assert set(data['executables_sha256']) == {'go_test', 'worker', 'scenario'}
    assert all(re.fullmatch('[0-9a-f]{64}', value) for value in data['executables_sha256'].values())
    assert len(data['events']) == len(data['memory_checkpoints']) == 9
    pending = None
    for seq, item in enumerate(data['progress'], 1):
        validator.checked_progress(item, seq, pending)
        pending = item if item['status'] == 'started' else None
    assert pending is None and len(data['progress']) == 2 * len(validator.EXPECTED_OPERATIONS) == 362
    # Check the ordered contract directly as well as the exact source validators.
    assert [tuple(item[key] for key in ['operation', 'payment_index', 'committed_blocks'])
            for item in data['progress'][::2]] == [(name, payment, before) for name, payment, before, after in validator.EXPECTED_OPERATIONS]
    assert [tuple(item[key] for key in ['operation', 'payment_index', 'committed_blocks'])
            for item in data['progress'][1::2]] == [(name, payment, after) for name, payment, before, after in validator.EXPECTED_OPERATIONS]
    for seq, event in enumerate(data['events'], 1):
        validator.checked_event(event, seq)
        if seq > 1:
            previous = data['events'][seq - 2]
            assert event['elapsed_ms'] >= previous['elapsed_ms']
            if event['height'] == previous['height']: assert event['state'] == previous['state']
            else: assert event['state']['logical_bytes'] > previous['state']['logical_bytes']
    validator.checked_result(data['result'], data['events'], data['progress'])
    result = {key: value for key, value in sorted(data['result'].items())}
    result['checks'] = dict(sorted(result['checks'].items()))
    fields = ['schema_version', 'seq', 'operation', 'payment_index', 'committed_blocks', 'status', 'duration_ms']
    result['timings'] = {'operations': [{key: item[key] for key in fields} for item in result['timings']['operations']],
                         'total_ms': result['timings']['total_ms']}
    encoded = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()
    assert hashlib.sha256(encoded).hexdigest() == data['result_sha256']
    process_identities, peaks, checkpoints = {}, {}, []
    method, kind = {'linux': ('linux_proc_VmRSS_VmHWM', 'linux_proc_starttime_ticks'),
                    'win32': ('windows_GetProcessMemoryInfo_WorkingSetSize_PeakWorkingSetSize', 'windows_creation_filetime_100ns')}[native_platform]
    for event, checkpoint in zip(data['events'], data['memory_checkpoints']):
        assert set(checkpoint) == {'measurement_complete', 'phase', 'samples', 'seq'}
        assert checkpoint['measurement_complete'] is True
        assert checkpoint['seq'] == event['seq'] and checkpoint['phase'] == event['phase']
        assert len(checkpoint['samples']) == 2
        row = {'seq': event['seq'], 'phase': event['phase'], 'height': event['height'],
               'elapsed_ms': event['elapsed_ms'], **event['state'],
               'wallet_records': [w['records_used'] for w in event['wallets']],
               'wallet_bytes': [w['file_bytes'] for w in event['wallets']], 'samples': []}
        for announced, sample in zip(event['processes'], checkpoint['samples']):
            assert set(sample) == {'current_bytes', 'generation', 'identity', 'method', 'os_lifetime_peak_bytes', 'role'}
            assert sample['role'] == announced['role'] and sample['generation'] == announced['generation']
            assert sample['identity']['pid'] == announced['pid']
            assert sample['method'] == method and sample['identity']['creation_identity_kind'] == kind
            assert re.fullmatch('[1-9][0-9]*', sample['identity']['creation_identity'])
            validator.checked_uint(sample['identity']['pid'], validator.MAX_PID, 1)
            validator.checked_uint(sample['identity']['parent_pid'], validator.MAX_PID, 1)
            key = sample['role'] + '_' + str(sample['generation'])
            if key in process_identities: assert process_identities[key] == sample['identity']
            else:
                assert sample['identity'] not in process_identities.values()
                process_identities[key] = sample['identity']
            current, peak = validator.checked_memory(sample['current_bytes'], sample['os_lifetime_peak_bytes'])
            validator.check_budget(validator.MemorySample(validator.ProcessIdentity(**sample['identity']), current, peak, method))
            assert peak >= peaks.get(key, 0)
            peaks[key] = peak
            row['samples'].append({'key': key, 'current_bytes': current, 'os_lifetime_peak_bytes': peak})
        checkpoints.append(row)
    assert set(process_identities) == {'worker_1', 'worker_2', 'scenario_1'}
    assert len({value['parent_pid'] for value in process_identities.values()}) == 1
    assert int(process_identities['worker_2']['creation_identity']) > int(process_identities['worker_1']['creation_identity'])
    validator.checked_uint(data['supervisor_elapsed_ms'], 1230000)
    validator.checked_uint(data['supervised_process_elapsed_ms'], data['supervisor_elapsed_ms'])
    summaries = [line for line in lines if re.fullmatch(r'Ran \d+ tests? in [0-9.]+s', line)]
    assert len(summaries) == 1 and summaries[0].startswith('Ran 53 tests in ')
    unique_cases = [line for line in lines if re.match(r'^test_.*\.\.\. (?:ok|skipped)', line)]
    assert len(unique_cases) == 53
    assert sum('... skipped ' in line for line in unique_cases) == (3 if platform == 'ubuntu' else 1)
    outputs.append({'platform': native_platform, 'status': 'PASS_' + CANDIDATE.upper() + '_RESOURCE_SCOPE_ONLY',
        'job': {'id': job['id'], 'name': job['name'], 'url': job['html_url'], 'steps': job['steps']},
        'artifact': metadata, 'originals': [identity(path) for path in [raw_log_path, zip_path, setup_path, result_path]],
        'metadata': actual, 'executable_hashes_observed': data['executables_sha256'],
        'setup_observation': setup, 'source_validation_script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
        'result_raw_go_encoding_digest_matched': data['result_sha256'], 'event_count': 9, 'memory_samples': 18,
        'progress_records': 362, 'completed_operations': 181,
        'process_identities': process_identities, 'max_observed_OS_lifetime_peak_bytes_by_process_generation': peaks,
        'checkpoint_summary': checkpoints, 'cleanup': data['cleanup'], 'result': {key: value for key, value in data['result'].items() if key != 'timings'},
        'total_ms': data['result']['timings']['total_ms'], 'supervisor_elapsed_ms': data['supervisor_elapsed_ms'],
        'supervised_process_elapsed_ms': data['supervised_process_elapsed_ms'],
        'actual_log_markers': [passed_test[0], *[line for line in lines if 'PAYMENT_RESOURCE_RESULT' in line]],
        'python_test_summary': summaries[0], 'python_named_cases': unique_cases,
        'complete_raw_log_lines_scanned': len(lines), 'log_bom': raw_log.startswith(b'\xef\xbb\xbf'),
        'log_crlf_count': raw_log.count(b'\r\n'), 'limitations': data['measurement_limits']})

output = {'schema_version': 1, 'reviewer': '/root/p2_package_native_audit/nonrust_logs',
    'candidate': CANDIDATE, 'head': SOURCE, 'base': BASE, 'tree': TREE, 'checkout': CHECKOUT,
    'conclusion': 'PASS_RETAINED_RESOURCE_SCOPE_ONLY_CANDIDATE_ACCEPTANCE_NOT_GRANTED',
    'new_OS_measurements_collected_by_reviewer': False, 'native_programs_executed_by_reviewer': False,
    'original_api_files': [identity(path) for path in [run_path, job_path, artifact_path]],
    'run': {'id': RUN, 'url': run['html_url'], 'conclusion': run['conclusion'], 'attempt': 1},
    'platforms': outputs,
    'limitations': ['Both complete resource ZIPs and all progress/events/measurements checked independently.',
        'This is the existing fixed 32+1 workload, not the new incremental package CLI resource measurement.',
        'No prior or later candidate receives this source-specific execution credit.',
        ('C2 remains rejected overall due to strict Clippy failures elsewhere; matrix review is separate.' if CANDIDATE == 'c2' else 'C3 full native matrix acceptance is pending separately; this result accepts only its resource scope.')]}
path = ROOT / f'{CANDIDATE}-resource-independent-review.json'
path.write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
print(json.dumps({'output': identity(path)}, ensure_ascii=False))
for row in outputs:
    print(json.dumps({'platform': row['platform'], 'job': row['job']['id'], 'artifact': row['artifact']['id'],
                      'total_ms': row['total_ms'], 'supervisor_elapsed_ms': row['supervisor_elapsed_ms'],
                      'peaks': row['max_observed_OS_lifetime_peak_bytes_by_process_generation'],
                      'result': row['result'], 'checkpoints': row['checkpoint_summary']},ensure_ascii=False,indent=2))
