"""Freeze an explicit documentation/evidence allowlist after runtime acceptance.

This helper proves tree inheritance and upload bytes. It does not grant review,
CI, or merge acceptance. Binary originals are uploaded as base64 Git blobs.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/workspace/scratch/1753b04c9dbb/Zevune')
HERE = Path(__file__).parent
DOCS = {'README.md', 'PROJECT_STATUS.json', 'docs/DELIVERY_PLAN.zh-CN.md'}
PREFIX = 'reports/p2-active-incremental-package-'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['prepare', 'metadata', 'content'])
    p.add_argument('--label', required=True)
    p.add_argument('--parent')
    p.add_argument('--source')
    p.add_argument('--file-index', type=int)
    p.add_argument('--offset', type=int, default=0)
    args = p.parse_args()
    assert args.label.isalnum()
    target = HERE / (args.label + '-upload.json')
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
    assert args.parent and args.source
    assert git('rev-parse', 'HEAD').decode().strip() == args.parent
    source_tree = git('rev-parse', args.source + '^{tree}').decode().strip()
    parent_tree = git('rev-parse', args.parent + '^{tree}').decode().strip()
    assert source_tree == parent_tree, 'Runtime merge must retain exact accepted tree'
    paths = json.loads((HERE / 'docs-paths.json').read_bytes())
    assert isinstance(paths, list) and paths == sorted(set(paths))
    assert DOCS <= set(paths)
    assert all(path in DOCS or path.startswith(PREFIX) for path in paths)
    assert all(not Path(path).is_absolute() and '..' not in Path(path).parts for path in paths)
    pending = set(git('diff', '--name-only', 'HEAD').decode().splitlines())
    pending.update(git('ls-files', '--others', '--exclude-standard').decode().splitlines())
    assert pending == set(paths), sorted(pending.symmetric_difference(paths))
    subprocess.run(['git', 'add', '--', *paths], cwd=ROOT, check=True)
    subprocess.run(['git', 'diff', '--cached', '--check'], cwd=ROOT, check=True)
    assert not git('diff', '--name-only')
    assert set(git('diff', '--cached', '--name-only', args.parent).decode().splitlines()) == set(paths)
    # Because the parent tree is identical to the accepted tree, every other
    # source, test, workflow, lock and historical artifact remains byte-exact.
    assert set(git('diff', '--cached', '--name-only', args.source).decode().splitlines()) == set(paths)
    rows = []
    for path in paths:
        raw = (ROOT / path).read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        assert git('ls-files', '-s', '--', path).startswith(b'100644 ')
        assert git('rev-parse', ':' + path).decode().strip() == blob
        assert git('show', ':' + path) == raw
        try:
            content, encoding = raw.decode('utf-8'), 'utf-8'
        except UnicodeDecodeError:
            content, encoding = base64.b64encode(raw).decode('ascii'), 'base64'
        rows.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': blob,
                     'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                     'encoding': encoding, 'content': content})
    value = {'source': args.source, 'source_tree': source_tree, 'parent': args.parent,
             'parent_tree': parent_tree, 'tree': git('write-tree').decode().strip(),
             'scope': 'Documentation and explicitly selected evidence only; native and independent review still required',
             'files': rows}
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    assert not target.exists(), 'Frozen documentation payload may not be replaced'
    target.write_bytes(raw)
    print(json.dumps({'path': str(target), 'tree': value['tree'],
                      'files': len(rows), 'bytes': sum(row['bytes'] for row in rows)}))


if __name__ == '__main__':
    main()
