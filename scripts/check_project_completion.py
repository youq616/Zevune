#!/usr/bin/env python3
"""Repository completion ledger: consistency checks are NOT an engineering audit.

Reads only bounded repository records. Never deploys, executes tests, contacts a
service or grants a funding permission. --require-complete gates the maintenance ledger;
--report is a usable status report even while implementation remains incomplete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys

SCHEMA = 'zevune-project-completion-1'
MAX_BYTES = 262144
STATUSES = {'not_implemented', 'in_progress', 'implemented', 'evidence_missing', 'accepted'}
REQUIRED = {
    'P1': ('network_identity', 'protocol_freeze', 'upgrade_recovery'),
    'P2': ('durable_archive', 'snapshot_incremental', 'capacity_and_fault_acceptance'),
    'P3': ('remote_node_operations', 'authenticated_remote_sync', 'four_machine_faults'),
    'P4': ('local_wallet_and_recovery', 'integrated_online_payment', 'restart_and_confirmation'),
    'P5': ('threat_model_review', 'private_transport', 'traffic_acceptance'),
    'P6': ('rules_and_conservation', 'validator_transitions', 'permissionless_model'),
    'P7': ('end_to_end_distribution', 'soak_30_days', 'failure_closure'),
    'P8': ('source_and_distribution', 'independent_security_audit', 'release_and_drills'),
}
EVIDENCE_KINDS = {'code', 'test', 'ci', 'independent_review', 'experiment', 'security_audit'}
ACCEPTED_EVIDENCE = {'code', 'test', 'ci', 'independent_review'}
MANDATORY_FACTS = {
    'P3.four_machine_faults': ('distinct_machines', 4),
    'P7.soak_30_days': ('continuous_seconds', 30 * 24 * 60 * 60),
}


class InvalidRecord(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise InvalidRecord(message)


def plain(value, maximum=4096):
    require(type(value) is str and 0 < len(value.encode('utf-8')) <= maximum
            and all(ord(c) >= 32 for c in value), 'invalid text field')
    return value


def read_file(root: Path, name: str) -> bytes:
    """Only regular, single-link records below this trusted source root."""
    plain(name)
    path = PurePosixPath(name)
    require(not path.is_absolute() and str(path) == name and '\\' not in name
            and ':' not in name and all(p not in ('.', '..') for p in path.parts), 'invalid source path')
    target = root
    for part in path.parts:
        target = target / part
        info = target.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'linked source path')
    before = target.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= MAX_BYTES,
            'invalid record extent')
    with target.open('rb') as stream:
        import os
        opened = os.fstat(stream.fileno())
        require(os.path.samestat(before, opened), 'record replaced before read')
        raw = stream.read(MAX_BYTES + 1)
    after = target.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_nlink)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)
            and len(raw) == before.st_size, 'record changed while reading')
    return raw


def parse(raw: bytes):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'invalid JSON extent')
    def pairs(values):
        result = {}
        for k, v in values:
            require(k not in result, 'duplicate JSON field')
            result[k] = v
        return result
    def nonfinite(_):
        raise InvalidRecord('nonfinite JSON value')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=nonfinite)


def evaluate(root: Path, document: dict) -> dict:
    """Validate maintenance records and their cited byte identities, not their truth.

    Evidence is supplied by maintainers and must undergo the independent review
    process. Hash checks here do NOT authenticate a reviewer, CI service or a
    thirty-day measurement. All permission flags remain false, even at exit 0.
    """
    fields = {'format', 'scope_document', 'target', 'real_funds_allowed',
              'public_deployment_authorized', 'scope_frozen', 'work_packages', 'candidate_commit', 'specifications'}
    require(type(document) is dict and set(document) == fields, 'completion document fields')
    require(document['format'] == SCHEMA and document['target'] == 'C'
            and document['scope_frozen'] is True and document['real_funds_allowed'] is False
            and document['public_deployment_authorized'] is False, 'scope or permission changed')
    require(document['scope_document'] == 'docs/DELIVERY_PLAN.zh-CN.md', 'wrong frozen scope')
    read_file(root, document['scope_document'])
    candidate = document['candidate_commit']
    require(type(candidate) is str and re.fullmatch('[0-9a-f]{40}', candidate) is not None
            and candidate != '0' * 40, 'invalid candidate commit')
    specifications = document['specifications']
    spec_paths = {'docs/ARCHITECTURE.zh-CN.md', 'docs/PERFORMANCE.zh-CN.md', 'docs/PROOF_CONTRACT.md',
                  'docs/ROADMAP.md', 'docs/SOURCES.md', 'docs/THREAT_MODEL.zh-CN.md'}
    require(type(specifications) is dict and set(specifications) ==
            {'origin', 'runtime_base_commit', 'historical_originals_recovered', 'paths'}, 'specification fields')
    require(specifications['origin'] == 'new_current_source_reconstruction_not_historical_originals'
            and specifications['historical_originals_recovered'] is False, 'historical provenance changed')
    base = specifications['runtime_base_commit']
    require(type(base) is str and re.fullmatch('[0-9a-f]{40}', base) is not None and base != '0'*40,
            'invalid specification baseline')
    paths = specifications['paths']
    require(type(paths) is list and len(paths) == 6 and all(type(p) is str for p in paths)
            and set(paths) == spec_paths, 'current specification set changed')
    for name in paths:
        read_file(root, name)
    groups = document['work_packages']
    require(type(groups) is list and len(groups) == len(REQUIRED), 'all eight work packages required')
    ids, accepted, records, evidence_counts = set(), set(), [], {}
    for group in groups:
        require(type(group) is dict and set(group) == {'id', 'title', 'criteria'}, 'package fields')
        package = group['id']
        require(type(package) is str and package in REQUIRED and package not in ids, 'package identity')
        ids.add(package); plain(group['title'], 128)
        criteria = group['criteria']
        require(type(criteria) is list and len(criteria) == len(REQUIRED[package]), 'criterion count')
        seen = set()
        for row in criteria:
            require(type(row) is dict and set(row) == {'id', 'status', 'reason', 'sources', 'evidence'}, 'criterion fields')
            cid, state = row['id'], row['status']
            require(type(cid) is str and cid in REQUIRED[package] and cid not in seen, 'criterion identity')
            seen.add(cid)
            require(type(state) is str and state in STATUSES, 'invalid criterion status')
            plain(row['reason'])
            sources = row['sources']
            require(type(sources) is list and 1 <= len(sources) <= 8, 'criterion sources required')
            for source in sources:
                read_file(root, source)
            proof = row['evidence']
            require(type(proof) is list and len(proof) <= 16, 'evidence bounds')
            kinds, evidence_ids, experiment_facts, commits = set(), set(), {}, set()
            for item in proof:
                require(type(item) is dict and set(item) == {'kind', 'path', 'sha256', 'source_commit', 'facts'}, 'evidence fields')
                kind = item['kind']
                require(type(kind) is str and kind in EVIDENCE_KINDS, 'evidence kind')
                digest, commit = item['sha256'], item['source_commit']
                require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest) is not None
                        and type(commit) is str and re.fullmatch('[0-9a-f]{40}', commit) is not None
                        and commit != '0' * 40,
                        'evidence identity')
                raw = read_file(root, item['path'])
                require(hashlib.sha256(raw).hexdigest() == digest, 'evidence digest mismatch')
                require(item['path'] not in evidence_ids, 'duplicate evidence file')
                evidence_ids.add(item['path']); kinds.add(kind); commits.add(commit)
                require(type(item['facts']) is dict and len(item['facts']) <= 8, 'evidence facts')
                for key, value in item['facts'].items():
                    plain(key, 128)
                    require(type(value) is int and 0 <= value <= 2**63 - 1, 'invalid numeric fact')
                    if kind == 'experiment':
                        experiment_facts.setdefault(key, []).append(value)
            qualified = package + '.' + cid
            if state == 'accepted':
                require(ACCEPTED_EVIDENCE <= kinds, 'accepted criterion lacks code/test/CI/review evidence')
                require(commits == {candidate}, 'accepted evidence mixes candidate commits or uses a stale candidate')
                if qualified in MANDATORY_FACTS:
                    key, minimum = MANDATORY_FACTS[qualified]
                    require('experiment' in kinds and experiment_facts.get(key)
                            and all(v >= minimum for v in experiment_facts[key]), 'required real-world observation missing')
                if qualified == 'P8.independent_security_audit':
                    require('security_audit' in kinds, 'external security audit missing')
                accepted.add(qualified)
            evidence_counts[qualified] = len(proof)
            records.append({'id': qualified, 'status': state, 'reason': row['reason']})
    all_ids = {p + '.' + c for p, rows in REQUIRED.items() for c in rows}
    require(ids == set(REQUIRED), 'work package set changed')
    gates = {'C': all_ids}  # Intermediate A/B still use the complete original human-reviewed plan.
    return {'format': SCHEMA, 'record_valid': True, 'scope_frozen': True,
            'scope_authority': 'docs/DELIVERY_PLAN.zh-CN.md',
            'category_records_do_not_replace_detailed_acceptance_clauses': True,
            'target': 'C', 'candidate_commit': candidate, 'total_criteria': len(records), 'accepted_records': len(accepted),
            'gate_records_complete': {level: needed <= accepted for level, needed in gates.items()},
            'missing_by_gate': {level: sorted(needed - accepted) for level, needed in gates.items()},
            'criteria': records, 'evidence_file_counts': evidence_counts,
            'assessment_scope': 'maintainer_record_consistency_not_technical_acceptance',
            'evidence_facts_independently_verified': False, 'release_authorized': False,
            'public_deployment_authorized': False, 'real_funds_allowed': False}


def inspect(root: Path) -> dict:
    root = root.resolve(strict=True)
    raw = read_file(root, 'PROJECT_COMPLETION.json')
    result = evaluate(root, parse(raw))
    require(read_file(root, 'PROJECT_COMPLETION.json') == raw, 'completion ledger changed')
    result['completion_record_sha256'] = hashlib.sha256(raw).hexdigest()
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--report', action='store_true', help='print valid records, including all missing gates')
    mode.add_argument('--require-complete', action='store_true', help='exit 2 when target C records are incomplete')
    args = p.parse_args(argv)
    try:
        result = inspect(args.root)
        sys.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True) + '\n')
        sys.stdout.flush()
        return 2 if args.require_complete and not result['gate_records_complete']['C'] else 0
    except (ValueError, OSError, TypeError, KeyError, RecursionError):
        print('Project completion record invalid; no acceptance or release permission.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Project completion check interrupted.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
