#!/usr/bin/env python3
"""Real offline audit CLI lifecycle with subprocess/network/ledger access denied.

Only this driver's temporary public task and audit files are created/changed.
This is not a wallet or native verification test; the product must never run one.
"""
import sys
sys.dont_write_bytecode = True

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import ledger_query_audit as audit

ROOT = Path(__file__).resolve().parent
GUARD = r'''
import sys
from pathlib import Path
attempts = []
def guard(event, args):
    forbidden = event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.posix_spawnp') or event.startswith('socket.')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        import os
        name = Path(os.fsdecode(args[0])).name
        forbidden = forbidden or name.endswith('.journal') or name == 'genesis'
    if forbidden:
        attempts.append(event)
        raise PermissionError('audit must not execute or access a ledger/network')
sys.addaudithook(guard)
sys.path.insert(0, sys.argv[1])
import ledger_query_audit as audit
assert Path(audit.__file__).resolve().parent == Path(sys.argv[1]).resolve()
status = audit.main(sys.argv[2:])
assert not attempts, 'forbidden operation was attempted even if caught'
raise SystemExit(status)
'''


def request_fixture():
    # Syntactically valid public checkpoint only. No real ledger or executable exists.
    checkpoint = (b'ZVARCP01' + b'g'*32 + (7).to_bytes(8,'big') + b'a'*32
                  + (1158).to_bytes(8,'big') + (108).to_bytes(4,'big')
                  + (1).to_bytes(4,'big') + b'l'*32).hex()
    return audit.task.prepare(checkpoint, 'd'*64, 'e'*64, tuple(f'{i:064x}' for i in reversed(range(32))))


def run():
    with tempfile.TemporaryDirectory(prefix='zevune-offline-audit-') as temporary:
        root = Path(temporary).resolve()
        source, target = root/'task.json', root/'audit.json'
        request = request_fixture()
        raw = audit.task.encode(request)
        source.write_bytes(raw)
        source_pin = hashlib.sha256(raw).hexdigest()
        calls = []
        def cli(args, expected=0):
            process = subprocess.run([sys.executable,'-I','-S','-B','-c',GUARD,str(ROOT),
                                      '--no-real-funds',*args],capture_output=True,timeout=15,cwd=root)
            assert process.returncode == expected, (process.returncode, process.stderr)
            calls.append((args[0], process.returncode))
            if expected:
                assert not process.stdout
                return None
            assert not process.stderr
            return json.loads(process.stdout)
        task_args = ['--request',str(source),'--request-sha256',source_pin]
        initial = cli(['inspect',*task_args])
        exported = cli(['export',*task_args,'--destination',str(target)])
        assert initial['audit_sha256'] == exported['audit_sha256']
        assert target.read_bytes() == audit.files.canonical(initial['report'])
        assert exported['query_count'] == 32 and source.read_bytes() == raw
        audit_args = ['--audit',str(target),'--audit-sha256',exported['audit_sha256']]
        standalone = cli(['verify',*audit_args])
        assert standalone['source_file_rechecked'] is False
        checked = cli(['recheck',*audit_args,*task_args])
        assert checked['source_file_rechecked'] is True
        assert checked['query_executed'] is checked['signature_verified'] is checked['real_funds_allowed'] is False
        for key in ('backend_verified','ledger_replayed','retry_authorized'):
            assert checked[key] is False
        original_report = target.read_bytes()
        cli(['export',*task_args,'--destination',str(target)],1)
        assert target.read_bytes() == original_report
        source.write_bytes(raw+b'x')
        cli(['recheck',*audit_args,*task_args],1)
        source.unlink()
        assert cli(['verify',*audit_args])['source_file_rechecked'] is False
        cli(['recheck',*audit_args,*task_args],1)
        source.write_bytes(raw)  # Separate copy before a NEW recheck is valid, not original-inode proof.
        assert cli(['recheck',*audit_args,*task_args])['source_file_rechecked'] is True
        target.write_bytes(original_report+b'x')
        cli(['verify',*audit_args],1)
        assert source.read_bytes() == raw
        assert {p.name for p in root.iterdir()} == {'task.json','audit.json'}
    assert not root.exists()
    result = dict(operation='offline_query_audit_integration', maximum_id_count=32,
                  actual_cli_commands=len(calls), forbidden_process_network_ledger_attempts=0,
                  missing_source_not_misreported=True, changed_inputs_rejected=True,
                  existing_output_preserved=True, native_query_executed=False,
                  temporary_files_removed=True, real_funds_allowed=False)
    print(json.dumps(result, sort_keys=True))
    return result


if __name__=='__main__':
    run()
