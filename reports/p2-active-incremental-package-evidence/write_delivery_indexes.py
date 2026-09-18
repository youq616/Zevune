"""Author delivery indexes, produced only after exact native review and actual merge.

Original reviewer files and native bytes are never rewritten by this helper.
The indexes do not constitute independent review or new native execution.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json

HERE = Path(__file__).parent
OUT = HERE / 'handoff-draft' / 'reports'
PREFIX = 'p2-active-incremental-package'
BASE = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
BASE_TREE = 'b5841120084a72c5948b0a2754f712e5f67ad602'
SOURCE = 'cb0804e7c921a456cbbafab313b3a4a4501b8f5e'
TREE = '21de343c12bc27cb1022ffd7ebd451abe0e61f29'
CHECKOUT = '3dfa8d77921693b9e99af5b94af198498b9422e9'


def read(name):
    return json.loads((HERE / name).read_bytes())


def identity(name):
    raw = (HERE / name).read_bytes()
    return {'path': 'reports/' + PREFIX + '-evidence/' + name,
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def write(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    path = OUT / (PREFIX + '-' + name)
    if path.exists():
        assert path.read_bytes() == raw, 'May not overwrite a frozen index'
    else:
        path.open('xb').write(raw)
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def candidate(label):
    folder = label + '-native/'
    runs = read(folder + 'runs.json')
    assert runs['total_count'] == len(runs['workflow_runs']) == 10
    workflows, all_jobs, steps, logs = [], [], Counter(), []
    for run in runs['workflow_runs']:
        assert run['event'] == 'pull_request' and run['run_attempt'] == 1
        assert run['status'] == 'completed'
        detail = read(folder + 'run-' + str(run['id']) + '.json')
        assert detail['head_sha'] == run['head_sha']
        batch = read(folder + 'jobs-' + str(run['id']) + '.json')
        assert batch['total_count'] == len(batch['jobs'])
        jobs = []
        for job in batch['jobs']:
            assert job['status'] == 'completed' and job['head_sha'] == run['head_sha']
            steps.update(x['conclusion'] for x in job['steps'])
            row = {'id': job['id'], 'name': job['name'], 'url': job['html_url'],
                   'status': job['status'], 'conclusion': job['conclusion'],
                   'steps': [{'number': s['number'], 'name': s['name'],
                              'status': s['status'], 'conclusion': s['conclusion']}
                             for s in job['steps']]}
            if job['steps']:
                row['complete_log'] = identity(folder + 'job-' + str(job['id']) + '.log')
                logs.append(row['complete_log'])
            jobs.append(row)
        all_jobs.extend(jobs)
        workflows.append({'name': run['name'], 'id': run['id'], 'url': run['html_url'],
                          'head_sha': run['head_sha'], 'attempt': run['run_attempt'],
                          'conclusion': run['conclusion'], 'jobs': jobs,
                          'run_original': identity(folder + 'run-' + str(run['id']) + '.json'),
                          'jobs_original': identity(folder + 'jobs-' + str(run['id']) + '.json'),
                          'artifacts_original': identity(folder + 'artifacts-' + str(run['id']) + '.json')})
    assert len({j['id'] for j in all_jobs}) == len(all_jobs)
    return {'source': runs['workflow_runs'][0]['head_sha'],
            'run_outcomes': dict(Counter(x['conclusion'] for x in workflows)),
            'job_outcomes': dict(Counter(x['conclusion'] for x in all_jobs)),
            'steps': dict(steps), 'runs': len(workflows), 'jobs': len(all_jobs),
            'complete_logs': len(logs), 'complete_log_bytes': sum(x['bytes'] for x in logs),
            'native_manifest': identity(label + '-native-original-manifest.json'),
            'independent_native_report': identity(label + '-native-review.md'),
            'independent_native_detail': identity(label + '-native-review.json'),
            'independent_nonrust_report': identity(label + '-native-nonrust-review.md'),
            'workflows': workflows}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    native, nonrust = read('c3-native-review.json'), read('c3-native-nonrust-review.json')
    assert native['conclusion'] == 'PASS_NATIVE_C3'
    assert nonrust['conclusion'] == 'PASS_NONRUST_NATIVE_C3'
    assert native['source'] == SOURCE and native['tree'] == TREE
    receipt = read('source-identities/runtime-merge-receipt.json')
    merge, closed = read('source-identities/runtime-git-commit.json'), read('source-identities/runtime-merged-pr.json')
    assert merge['tree']['sha'] == TREE and [p['sha'] for p in merge['parents']] == [BASE, SOURCE]
    assert closed['merged'] is True and closed['head']['sha'] == SOURCE
    assert closed['merge_commit_sha'] == merge['sha']
    assert receipt['actual_runtime_merge_commit'] == merge['sha']
    current = candidate('c3')
    assert current['source'] == SOURCE
    assert current['run_outcomes'] == {'success': 10} and current['job_outcomes'] == {'success': 23}
    assert current['steps'].get('failure', 0) == 0 and current['steps']['skipped'] == 9
    assert current['complete_logs'] == 23
    reviews = []
    for reviewer, status, name in [
        ('/root/p2_package_design_review', 'PASS_DESIGN', 'design-review.md'),
        ('/root/p2_package_storage_review', 'PASS_DESIGN', 'design-storage-review.md'),
        ('/root/p2_package_design_review', 'PASS_CODE', 'c3-code-review.md'),
        ('/root/p2_package_storage_review', 'PASS_CODE', 'c3-storage-review.md'),
        ('/root/p2_package_native_audit', 'PASS_NATIVE_C3', 'c3-native-review.md'),
        ('/root/p2_package_native_audit/nonrust_logs', 'PASS_NONRUST_NATIVE_C3', 'c3-native-nonrust-review.md')]:
        reviews.append({'reviewer': reviewer, 'status': status, 'original': identity(name)})
    ci = {'kind': 'author_index_of_complete_originals_and_independent_reviews_not_an_independent_review',
          'stage': 'P2_active_incremental_package_and_new_directory_full_replay_restore',
          'repository': 'youq616/Zevune', 'pr': 'https://github.com/youq616/Zevune/pull/17',
          'base': BASE, 'base_tree': BASE_TREE, 'source': SOURCE, 'tree': TREE,
          'PR_checkout': CHECKOUT, 'PR_checkout_ordered_parents': [BASE, SOURCE],
          'PR_checkout_tree': TREE, 'accepted_runtime': current,
          'rejected_candidates': {'c1': candidate('c1'), 'c2': candidate('c2')},
          'independent_reviews': reviews,
          'independent_native_details': identity('c3-native-review.json'),
          'independent_nonrust_details': identity('c3-native-nonrust-review.json'),
          'scope': 'All outcomes derived from the exact candidate original API and complete logs; named Rust/Go/Python coverage and platform limits are in independent reports. Repeated jobs and zero-test targets are not extra unique test credit.',
          'actual_runtime_merge_commit': merge['sha'],
          'runtime_merge_receipt': identity('source-identities/runtime-merge-receipt.json'),
          'original_manifest': 'reports/' + PREFIX + '-original-manifest.json',
          'representation_scope': 'Connector-decoded UTF-8 content is preserved byte-exact including BOM/CRLF; it is not raw HTTP transport. Resource ZIPs and members are preserved, operator full ZIP payloads were independently checked in scratch but only manifests and checks are archived.',
          'documentation_followup': 'Exact documentation head/tree, independent review, actual automatic CI and docs merge are recorded in its PR linked from runtime PR17; no future or self-referential documentation identity is asserted here.'}
    merge_index = {'kind': 'author_observed_actual_runtime_merge_and_combined_acceptance_not_independent_review',
                   'stage': ci['stage'], 'repository': ci['repository'], 'pr': ci['pr'],
                   'base': BASE, 'base_tree': BASE_TREE, 'accepted_source': SOURCE,
                   'accepted_tree': TREE, 'PR_checkout': CHECKOUT,
                   'actual_runtime_merge_commit': merge['sha'], 'actual_runtime_merge_tree': TREE,
                   'actual_runtime_merge_ordered_parents': [BASE, SOURCE],
                   'merged_at': closed['merged_at'], 'exact_runtime_tree_inherited': True,
                   'runtime_merge_receipt': ci['runtime_merge_receipt'],
                   'independent_reviews': reviews, 'all_required_PR_jobs_success': True,
                   'required_runs': 10, 'distinct_jobs': 23, 'open_stage_blockers': 0,
                   'C1_C2_rejections_preserved': True,
                   'boundaries': {'P2': 'in_progress', 'incremental_backup_implemented': True,
                                  'incremental_backup_scope': 'NO_FUNDS_ZVTGEN03_active_package_two_independent_pins_full_replay_restore_to_new_directory_only',
                                  'snapshot_state_import_implemented': False, 'production_storage_ready': False,
                                  'audited': False, 'real_funds_allowed': False,
                                  'CLI_full_replays': {'pack': 6, 'verify': 3, 'restore': 8}},
                   'documentation_followup': ci['documentation_followup']}
    print(json.dumps([write('ci.json', ci), write('merge.json', merge_index)], ensure_ascii=False))


if __name__ == '__main__':
    main()
