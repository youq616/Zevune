"""Reviewer-only complete-original parsing; no test execution or automatic acceptance."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from native_audit_rust_helpers import identify, lines_from, parse_rust


def inspect_logs(directory, candidate, checkout):
    records = []
    for path in sorted(directory.glob('job-*.log')):
        raw = path.read_bytes()
        lines = lines_from(raw)
        identities = []
        for i, line in enumerate(lines[:-1]):
            if line.startswith('[command]') and line.endswith(' log -1 --format=%H'):
                identities.append(lines[i + 1].strip())
        assert identities == [checkout], (path, identities, checkout)
        fmt = []
        for line in lines:
            match = re.fullmatch(r'Diff in .*[\\/]integration[\\/]orchard[\\/](.+):(\d+):', line)
            if match:
                fmt.append({'path': 'integration/orchard/' + match[1].replace('\\', '/'),
                            'line': int(match[2])})
        errors = [{'line': i + 1, 'text': line} for i, line in enumerate(lines)
                  if line.startswith('##[error]')]
        rust = parse_rust(lines)
        records.append({'path': path.name, **identify(raw), 'decoded_lines': len(lines),
                        'checkout': identities, 'format_hunks': fmt,
                        'format_files': sorted({item['path'] for item in fmt}),
                        'errors': errors, 'rust': rust,
                        'commands': [{'line': i + 1, 'text': line} for i, line in enumerate(lines)
                                     if line.startswith(('##[group]Run ', 'RUN ', 'FUNDED_COHORT_'))],
                        'cleanup_observed': any('Cleaning up orphan processes' in line
                                                for line in lines[-30:])})
    return {'status': 'STRUCTURAL_OBSERVATION_ONLY / REVIEW_REQUIRED',
            'candidate': candidate, 'checkout': checkout,
            'log_count': len(records), 'log_bytes': sum(row['bytes'] for row in records),
            'decoded_lines': sum(row['decoded_lines'] for row in records),
            'rust_harnesses': sum(len(row['rust']['harnesses']) for row in records),
            'rust_passed_executions': sum(h['passed'] for row in records for h in row['rust']['harnesses']),
            'records': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('candidate')
    parser.add_argument('checkout')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert not args.output.exists(), 'review derivations are create-only'
    result = inspect_logs(args.directory, args.candidate, args.checkout)
    raw = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    args.output.write_bytes(raw)
    print(json.dumps({key: value for key, value in result.items() if key != 'records'}))
    print(json.dumps({'path': str(args.output), 'bytes': len(raw),
                      'sha256': hashlib.sha256(raw).hexdigest()}))


if __name__ == '__main__':
    main()
