"""Freeze exact allowlisted stage files; this helper does not accept or publish them."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/workspace/scratch/1753b04c9dbb/Zevune')
SCRATCH = Path(__file__).parent
BASE = '2cc87a2207d502ac5cfe00ea52e525c1516917e5'
DESIGN_SHA256 = 'b85805f2d664d32839f5f9cd113ac5508e0b3f944839e1d80042faf279675a41'
PATHS = [
    'docs/ACTIVE_INCREMENTAL_PACKAGE_V1.zh-CN.md',
    'integration/orchard/src/bin/zevune-pool-recovery.rs',
    'integration/orchard/src/pool/active.rs',
    'integration/orchard/src/pool/active/package.rs',
    'integration/orchard/src/pool/active/package/tests.rs',
    'integration/orchard/src/pool/active_flow_tests.rs',
    'integration/orchard/src/pool/recovery/active.rs',
    'integration/orchard/src/pool/recovery/active/incremental.rs',
    'integration/orchard/src/pool/recovery/active/package.rs',
    'integration/orchard/src/pool/recovery/active/package/tests.rs',
    'integration/orchard/src/recovery_package_output.rs',
    'integration/orchard/tests/active_incremental_package_cli.rs',
]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'metadata', 'content'])
    parser.add_argument('--parent')
    parser.add_argument('--label', required=True)
    parser.add_argument('--file-index', type=int)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()
    assert args.label.isalnum()
    target = SCRATCH / (args.label + '-upload.json')
    if args.mode != 'prepare':
        value = json.loads(target.read_bytes())
        if args.mode == 'metadata':
            for row in value['files']:
                row['content_characters'] = len(row.pop('content'))
            print(json.dumps(value, ensure_ascii=False))
        else:
            row = value['files'][args.file_index]
            assert 0 <= args.offset <= len(row['content'])
            print(json.dumps({'path': row['path'], 'offset': args.offset,
                              'content': row['content'][args.offset:args.offset + 24000]},
                             ensure_ascii=False))
        return
    assert args.parent and git('rev-parse', 'HEAD').decode().strip() == args.parent
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, args.parent], cwd=ROOT, check=True)
    design = (ROOT / PATHS[0]).read_bytes()
    assert len(design) == 13361 and hashlib.sha256(design).hexdigest() == DESIGN_SHA256
    pending = set(git('diff', '--name-only', 'HEAD').decode().splitlines())
    pending.update(git('ls-files', '--others', '--exclude-standard').decode().splitlines())
    assert pending <= set(PATHS), sorted(pending - set(PATHS))
    assert all((ROOT / path).is_file() for path in PATHS)
    subprocess.run(['git', 'add', '--', *PATHS], cwd=ROOT, check=True)
    subprocess.run(['git', 'diff', '--cached', '--check'], cwd=ROOT, check=True)
    assert not git('diff', '--name-only')
    changed = git('diff', '--cached', '--name-only', args.parent).decode().splitlines()
    assert changed and set(changed) <= set(PATHS)
    assert set(git('diff', '--cached', '--name-only', BASE).decode().splitlines()) == set(PATHS)
    rows = []
    for path in changed:
        raw = (ROOT / path).read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        assert git('ls-files', '-s', '--', path).startswith(b'100644 ')
        assert git('rev-parse', ':' + path).decode().strip() == blob
        assert git('show', ':' + path) == raw
        rows.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': blob,
                     'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                     'content': raw.decode('utf-8')})
    value = {'stage_base': BASE, 'parent': args.parent,
             'parent_tree': git('rev-parse', args.parent + '^{tree}').decode().strip(),
             'tree': git('write-tree').decode().strip(), 'stage_paths': PATHS, 'files': rows}
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if target.exists():
        assert target.read_bytes() == raw, 'Frozen upload payload cannot be overwritten'
    else:
        target.write_bytes(raw)
    print(json.dumps({'path': str(target), 'tree': value['tree'],
                      'changed_from_parent': len(rows), 'bytes': sum(r['bytes'] for r in rows)}))


if __name__ == '__main__':
    main()
