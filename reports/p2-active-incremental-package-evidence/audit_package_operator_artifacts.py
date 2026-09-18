"""Verify every retained operator ZIP member without executing any payload."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import zipfile

ROOT = Path('/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package')
REPO = ROOT.parent / 'Zevune'
CONFIG = {
 'c2': ('f51c8db240933256870ff03c07bc68915b4ac4a1', '7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400', 'aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f', 35362925534),
 'c3': ('cb0804e7c921a456cbbafab313b3a4a4501b8f5e', '21de343c12bc27cb1022ffd7ebd451abe0e61f29', '3dfa8d77921693b9e99af5b94af198498b9422e9', 35363727265),
}
CANDIDATE = sys.argv[1]
SOURCE, TREE, CHECKOUT, RUN = CONFIG[CANDIDATE]
NATIVE = ROOT / (CANDIDATE + '-native')


def unique(pairs):
    out = {}
    for key, val in pairs:
        assert key not in out
        out[key] = val
    return out


def read(path):
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def digest(path):
    size, hasher = 0, hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            size += len(block)
            hasher.update(block)
    return {'path': str(path.relative_to(ROOT)), 'bytes': size, 'sha256': hasher.hexdigest()}


run_path = NATIVE / f'run-{RUN}.json'
jobs_path = NATIVE / f'jobs-{RUN}.json'
artifacts_path = NATIVE / f'artifacts-{RUN}.json'
run, jobs, artifacts = read(run_path), read(jobs_path), read(artifacts_path)
assert run['id'] == RUN and run['name'] == 'local-network-operator'
assert run['head_sha'] == SOURCE and run['head_commit']['tree_id'] == TREE
assert run['status'] == 'completed' and run['conclusion'] == 'success' and run['event'] == 'pull_request'
assert run['run_attempt'] == 1 and jobs['total_count'] == len(jobs['jobs']) == artifacts['total_count'] == len(artifacts['artifacts']) == 2
outputs = []
for platform, runner in [('linux', 'ubuntu'), ('windows', 'windows')]:
    suffix = '.exe' if platform == 'windows' else ''
    expected_files = {name + suffix for name in ['zevune-network', 'zevune-pool-worker', 'zevune-wallet-local']} | {'zevune_wallet.py', 'LOCAL_NETWORK_OPERATOR.zh-CN.md'}
    job = next(job for job in jobs['jobs'] if job['name'] == f'operator ({runner}-latest)')
    assert job['status'] == 'completed' and job['conclusion'] == 'success' and job['head_sha'] == SOURCE
    assert job['run_attempt'] == 1 and job['run_id'] == RUN
    assert all(step['status'] == 'completed' and step['conclusion'] == ('skipped' if platform == 'windows' and step['name'] == 'Race and bounded fuzz checks' else 'success') for step in job['steps'])
    raw_log_path = NATIVE / f"job-{job['id']}.log"
    raw = raw_log_path.read_bytes()
    lines = [re.sub(r'\x1b\[[0-9;]*m', '', re.sub(r'^\d{4}-\d\d-\d\dT\S+\s?', '', line)) for line in raw.decode('utf-8-sig').splitlines()]
    assert [lines[i + 1] for i, line in enumerate(lines) if line.startswith('[command]') and 'log -1 --format=%H' in line] == [CHECKOUT]
    receipt = [json.loads(line, object_pairs_hook=unique) for line in lines if line.startswith('{"built":')]
    assert len(receipt) == 1
    receipt = receipt[0]
    assert receipt['built'] is True and receipt['source_commit'] == CHECKOUT and receipt['real_funds_allowed'] is False
    artifact = next(item for item in artifacts['artifacts'] if item['name'] == 'zevune-local-lab-' + ('Linux' if platform == 'linux' else 'Windows'))
    assert artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == SOURCE and artifact['expired'] is False
    zip_path = ROOT / 'payloads' / f'{CANDIDATE}-operator-{platform}.zip'
    archive_identity = digest(zip_path)
    assert archive_identity['bytes'] == artifact['size_in_bytes']
    assert 'sha256:' + archive_identity['sha256'] == artifact['digest']
    manifest_path = NATIVE / f'operator-{platform}-manifest.json'
    manifest_raw = manifest_path.read_bytes()
    assert len(manifest_raw) <= 65536
    assert hashlib.sha256(manifest_raw).hexdigest() == receipt['manifest_sha256']
    manifest = json.loads(manifest_raw, object_pairs_hook=unique)
    assert set(manifest) == {'format', 'source_commit', 'source_tree', 'build_source', 'real_funds_allowed',
        'public_network_supported', 'network_anonymity_implemented', 'scope', 'toolchains', 'files'}
    assert manifest['format'] == 'zevune-local-bundle-2'
    assert manifest['source_commit'] == CHECKOUT and manifest['source_tree'] == TREE
    assert manifest['build_source'] == 'isolated_exact_git_blobs' and manifest['scope'] == 'single_machine_fixed_validator_test_lab'
    assert all(manifest[key] is False for key in ['real_funds_allowed', 'public_network_supported', 'network_anonymity_implemented'])
    assert set(manifest['toolchains']) == {'go', 'rust'}
    assert manifest['toolchains']['go'].startswith('go version go1.27.1 ') and manifest['toolchains']['rust'].startswith('rustc 1.98.1 ')
    assert len(manifest['files']) == 5 and {item['name'] for item in manifest['files']} == expected_files
    checked = []
    with zipfile.ZipFile(zip_path) as archive:
        assert len(archive.namelist()) == 6 and set(archive.namelist()) == expected_files | {'BUNDLE-MANIFEST.json'}
        assert archive.read('BUNDLE-MANIFEST.json') == manifest_raw
        for entry in manifest['files']:
            assert set(entry) == {'name', 'size', 'sha256'}
            assert type(entry['size']) is int and 1 <= entry['size'] <= 128 * (1 << 20)
            assert re.fullmatch('[0-9a-f]{64}', entry['sha256'])
            info = archive.getinfo(entry['name'])
            assert not info.is_dir() and info.file_size == entry['size']
            size, hasher, first = 0, hashlib.sha256(), b''
            with archive.open(entry['name']) as stream:
                for block in iter(lambda: stream.read(1 << 20), b''):
                    if not first: first = block[:4]
                    size += len(block)
                    hasher.update(block)
            assert size == entry['size'] and hasher.hexdigest() == entry['sha256']
            row = {'name': entry['name'], 'bytes': size, 'sha256': hasher.hexdigest(), 'zip_crc32_checked_by_complete_read': True}
            source_path = {'zevune_wallet.py': 'scripts/zevune_wallet.py', 'LOCAL_NETWORK_OPERATOR.zh-CN.md': 'docs/LOCAL_NETWORK_OPERATOR.zh-CN.md'}.get(entry['name'])
            if source_path:
                blob = subprocess.check_output(['git', 'show', SOURCE + ':' + source_path], cwd=REPO)
                assert archive.read(entry['name']) == blob
                row.update(git_blob_path=source_path, git_blob_byte_equality=True)
            else:
                assert first.startswith(b'MZ' if platform == 'windows' else b'\x7fELF')
                row['recognized_executable_container'] = 'PE/MZ' if platform == 'windows' else 'ELF'
                row['executed'] = False
            checked.append(row)
    outputs.append({'platform': platform, 'job_id': job['id'], 'job_url': job['html_url'],
        'artifact': artifact, 'zip_original': archive_identity, 'manifest_original': digest(manifest_path),
        'log_original': digest(raw_log_path), 'build_receipt': receipt, 'manifest': manifest,
        'payloads_checked': checked, 'payload_count': 5, 'total_payload_bytes': sum(item['bytes'] for item in checked),
        'conclusion': 'PASS_ALL_PAYLOAD_INTEGRITY_AND_SOURCE_SCOPE_ONLY',
        'binaries_executed': False, 'independent_rebuild_performed': False})
output = {'schema_version': 1, 'reviewer': '/root/p2_package_native_audit/nonrust_logs',
    'candidate': CANDIDATE, 'head': SOURCE, 'tree': TREE, 'checkout': CHECKOUT,
    'status': 'PASS_RETAINED_OPERATOR_BUNDLES_SCOPE_ONLY',
    'api_originals': [digest(path) for path in [run_path, jobs_path, artifacts_path]],
    'platforms': outputs, 'limitations': ['All five payloads were fully streamed and hashed per platform; no downloaded binary was executed.',
        'Integrity and source tree binding only, not code signing, reproducible-build proof or external audit.',
        'Downloaded binary ZIPs stay in scratch; retain metadata, manifests and these derived digest results in repository evidence.',
        ('Whole candidate acceptance remains separate; C2 is rejected due to strict Clippy failures.' if CANDIDATE == 'c2' else 'Whole candidate acceptance remains pending the complete C3 matrix and independent final review.')]}
path = ROOT / f'{CANDIDATE}-operator-independent-review.json'
path.write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
print(json.dumps({'output': digest(path), 'platforms': outputs},ensure_ascii=False,indent=2))
