"""Real Git objects and filesystem tests, never an accepting wallet verifier."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inspector_source_bundle as delivery

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'scripts/inspector_source_bundle.py'


def git(root, *args, input=None):
    return subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=root, input=input,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30).stdout.strip()


class SourceDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory(prefix='inspector-delivery-tests-')
        cls.addClassCleanup(cls.base.cleanup)
        cls.workspace = Path(cls.base.name).resolve()
        cls.repo = cls.workspace / 'source'
        cls.repo.mkdir()
        git(cls.repo, 'init', '-q')
        git(cls.repo, 'config', 'user.name', 'Delivery tests')
        git(cls.repo, 'config', 'user.email', 'tests@example.invalid')
        for name, source in delivery.SOURCES.items():
            dest = cls.repo / source
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes((ROOT / source).read_bytes())
        git(cls.repo, 'add', '.')
        git(cls.repo, 'commit', '-qm', 'Real selected source fixture; not an upstream commit')
        cls.commit = git(cls.repo, 'rev-parse', 'HEAD').decode()
        cls.original = cls.workspace / 'original'
        cls.result = delivery.build(cls.repo, cls.commit, cls.original)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.workspace)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'delivery'
        shutil.copytree(self.original, self.folder)
        self.pin = self.result['manifest_sha256']

    def verify(self, pin=None):
        return delivery.verify(self.folder, self.pin if pin is None else pin, self.commit)

    def rewrite(self, mutate):
        path = self.folder / delivery.MANIFEST
        manifest = json.loads(path.read_bytes())
        mutate(manifest)
        raw = json.dumps(manifest).encode()
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def test_exact_real_git_build_and_read_only_verification(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        with patch.object(delivery.subprocess, 'run', side_effect=AssertionError('verify must not launch')):
            result = self.verify()
        self.assertTrue(result['integrity_verified'])
        self.assertFalse(result['payload_executed'])
        self.assertFalse(result['accepted'])
        self.assertFalse(result['code_signature_verified'])
        self.assertFalse(result['real_funds_allowed'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir()})
        for name, source in delivery.SOURCES.items():
            expected = subprocess.check_output(['git', '--no-replace-objects', 'cat-file', 'blob',
                                                self.commit + ':' + source], cwd=self.repo, timeout=30)
            self.assertEqual(before[name], expected)  # Preserve CRLF and trailing whitespace too.

    @staticmethod
    def changed_stat(info, **changes):
        fields = {key: getattr(info, key) for key in (
            'st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
        fields['st_file_attributes'] = getattr(info, 'st_file_attributes', 0)
        fields.update(changes)
        return SimpleNamespace(**fields)

    def test_stable_path_and_handle_metadata_routes_can_differ(self):
        # Real file and descriptor, only synthetic stat presentation. This is
        # not a substitute for successful wallet authentication or native CI.
        path = self.folder / 'wallet_health.py'
        expected = path.read_bytes()
        real_fstat = delivery.os.fstat
        def route(fd):
            info = real_fstat(fd)
            return self.changed_stat(info, st_mtime_ns=info.st_mtime_ns-123,
                                     st_ctime_ns=info.st_ctime_ns-456,
                                     st_mode=info.st_mode ^ stat.S_IWUSR)
        with patch.object(delivery.os, 'fstat', side_effect=route):
            data, _ = delivery.read_plain(path, delivery.MAX_FILE)
        self.assertEqual(data, expected)

    def test_change_within_handle_metadata_route_is_rejected(self):
        path = self.folder / 'wallet_health.py'
        original = path.read_bytes()
        real_fstat = delivery.os.fstat
        calls = []
        def changing(fd):
            info = real_fstat(fd)
            calls.append(1)
            return self.changed_stat(info, st_mtime_ns=info.st_mtime_ns-123,
                                     st_ctime_ns=info.st_ctime_ns-456+len(calls))
        with patch.object(delivery.os, 'fstat', side_effect=changing):
            with self.assertRaises(ValueError):delivery.read_plain(path, delivery.MAX_FILE)
        self.assertEqual(len(calls), 2, 'did not reach the after-read handle check')
        self.assertEqual(path.read_bytes(), original)

    def test_cross_route_file_identity_is_never_relaxed(self):
        path = self.folder / 'wallet_health.py'
        before = path.lstat()
        real_fstat = delivery.os.fstat
        for field, value in (('st_dev', before.st_dev+1), ('st_ino', before.st_ino+1),
                             ('st_size', before.st_size+1), ('st_nlink', 2),
                             ('st_mode', stat.S_IFDIR|0o700), ('st_file_attributes', 0x400)):
            with self.subTest(field=field):
                def wrong(fd):return self.changed_stat(real_fstat(fd), **{field:value})
                with patch.object(delivery.os, 'fstat', side_effect=wrong):
                    with self.assertRaises(ValueError):delivery.read_plain(path, delivery.MAX_FILE)

    def test_change_within_path_metadata_route_is_rejected(self):
        path = self.folder / 'wallet_health.py'
        before = path.lstat()
        real_fstat = delivery.os.fstat
        def handle(fd):
            info = real_fstat(fd)
            return self.changed_stat(info, st_ctime_ns=info.st_ctime_ns-456)
        after = self.changed_stat(before, st_ctime_ns=before.st_ctime_ns+1)
        with patch.object(delivery.os, 'fstat', side_effect=handle), \
                patch.object(Path, 'lstat', side_effect=[before, after]) as query:
            with self.assertRaises(ValueError):delivery.read_plain(path, delivery.MAX_FILE)
        self.assertEqual(query.call_count, 2, 'did not reach the final path check')

    def test_wrong_pins_are_rejected_before_any_payload_open(self):
        with patch.object(delivery, 'read_plain', wraps=delivery.read_plain) as reader:
            with self.assertRaises(ValueError):
                delivery.verify(self.folder, '0'*64, self.commit)
            self.assertEqual(reader.call_count, 1)
        for bad in (None, 0, '', 'A'*64, '../secret', '0'*65):
            with self.subTest(pin=bad), self.assertRaises(ValueError):
                delivery.verify(self.folder, bad, self.commit)
        with self.assertRaises(ValueError):
            delivery.verify(self.folder, self.pin, '0'*40)

    def test_duplicate_top_level_manifest_keys_rejected_with_matching_pin(self):
        path = self.folder / delivery.MANIFEST
        raw = path.read_bytes().rstrip()[:-1] + b',"accepted":false}'
        path.write_bytes(raw)
        with self.assertRaises(ValueError):self.verify(hashlib.sha256(raw).hexdigest())

    def test_duplicate_nested_manifest_keys_rejected(self):
        path = self.folder / delivery.MANIFEST
        raw = path.read_bytes().replace(b'"files": [', b'"files": [', 1)
        raw = raw.replace(b'"git_blob":', b'"size":1,"git_blob":', 1)
        path.write_bytes(raw)
        with self.assertRaises(ValueError):self.verify(hashlib.sha256(raw).hexdigest())

    def test_policy_flags_must_be_literal_false(self):
        original = (self.folder / delivery.MANIFEST).read_bytes()
        for field in ('accepted', 'real_funds_allowed', 'native_backend_included'):
            for value in (0, True, None, 'false'):
                with self.subTest(field=field, value=value):
                    (self.folder / delivery.MANIFEST).write_bytes(original)
                    pin = self.rewrite(lambda m: m.__setitem__(field, value))
                    with self.assertRaises(ValueError):self.verify(pin)

    def test_unknown_missing_fields_and_wrong_format_refused(self):
        original = (self.folder / delivery.MANIFEST).read_bytes()
        for mutate in (lambda m:m.update(extra=1), lambda m:m.pop('source_kind'),
                       lambda m:m.update(format='zevune-local-bundle-9'),
                       lambda m:m.update(source_tree=False), lambda m:m.update(entrypoint='other.py')):
            (self.folder / delivery.MANIFEST).write_bytes(original)
            with self.assertRaises(ValueError):self.verify(self.rewrite(mutate))

    def test_unsafe_duplicate_missing_and_extra_file_records(self):
        original = (self.folder / delivery.MANIFEST).read_bytes()
        for mutate in (lambda m:m['files'][0].update(name='../escape'),
                       lambda m:m['files'][0].update(name='C:\\escape'),
                       lambda m:m['files'][0].update(name='wallet_inspector_desktop.py:stream'),
                       lambda m:m['files'][0].update(name=m['files'][1]['name']),
                       lambda m:m['files'].pop(), lambda m:m['files'].append(m['files'][0]),
                       lambda m:m['files'][0].update(source_path='other/path.py')):
            (self.folder / delivery.MANIFEST).write_bytes(original)
            with self.assertRaises(ValueError):self.verify(self.rewrite(mutate))

    def test_entry_sizes_and_hashes_strict(self):
        original = (self.folder / delivery.MANIFEST).read_bytes()
        for field, value in (('size', True), ('size', 0), ('size', -1), ('size', delivery.MAX_FILE+1),
                             ('sha256', 'F'*64), ('git_blob', 'a'*39), ('git_blob', False)):
            (self.folder / delivery.MANIFEST).write_bytes(original)
            with self.assertRaises(ValueError):self.verify(self.rewrite(lambda m:m['files'][0].update({field:value})))

    def test_aggregate_declared_size_is_bounded(self):
        pin = self.rewrite(lambda m:[e.update(size=delivery.MAX_FILE) for e in m['files']])
        with self.assertRaises(ValueError):self.verify(pin)

    def test_every_payload_tamper_fails_even_same_length(self):
        for name in delivery.SOURCES:
            path = self.folder / name
            original = path.read_bytes()
            path.write_bytes(bytes([original[0]^1]) + original[1:])
            with self.subTest(name=name), self.assertRaises(ValueError):self.verify()
            path.write_bytes(original)

    def test_rehashed_payload_cannot_bypass_independent_manifest_pin(self):
        path = self.folder / 'wallet_inspector_desktop.py'
        data = path.read_bytes()+b'\n# changed\n'
        path.write_bytes(data)
        self.rewrite(lambda m:[e.update(size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                      git_blob=delivery.blob_id(data))
                               for e in m['files'] if e['name']==path.name])
        with self.assertRaises(ValueError):self.verify()

    def test_extra_hidden_file_and_directory_rejected(self):
        for name in ('.hidden', '__pycache__', 'extra.py', 'WALLET_INSPECTOR_DESKTOP.PY'):
            path=self.folder/name
            path.mkdir()
            with self.subTest(name=name), self.assertRaises(ValueError):self.verify()
            path.rmdir()

    def test_missing_payload_rejected(self):
        (self.folder/'wallet_health.py').unlink()
        with self.assertRaises(ValueError):self.verify()

    def test_directory_in_place_of_payload_rejected(self):
        path=self.folder/'wallet_health.py';path.unlink();path.mkdir()
        with self.assertRaises(ValueError):self.verify()

    def test_oversize_manifest_and_payload_rejected(self):
        path=self.folder/delivery.MANIFEST;raw=path.read_bytes()
        path.write_bytes(b' '* (delivery.MAX_MANIFEST+1))
        with self.assertRaises(ValueError):self.verify()
        path.write_bytes(raw)
        (self.folder/'wallet_health.py').write_bytes(b'x'*(delivery.MAX_FILE+1))
        with self.assertRaises(ValueError):self.verify()

    def test_payload_hardlink_rejected_without_reading_it(self):
        path=self.folder/'wallet_health.py'
        os.link(path,Path(self.temp.name)/'alias')
        with self.assertRaises(ValueError):self.verify()

    @unittest.skipUnless(os.name=='posix', 'POSIX symlink/FIFO case; reparse policy tested separately')
    def test_symlink_root_parent_payload_and_fifo_refused(self):
        alias=Path(self.temp.name)/'alias';alias.symlink_to(self.folder,target_is_directory=True)
        with self.assertRaises(ValueError):delivery.verify(alias,self.pin,self.commit)
        nested=self.folder/'wallet_health.py';data=nested.read_bytes();nested.unlink()
        outside=Path(self.temp.name)/'outside';outside.write_bytes(data);nested.symlink_to(outside)
        with self.assertRaises(ValueError):self.verify()
        nested.unlink();os.mkfifo(nested)
        with self.assertRaises(ValueError):self.verify()
        top_alias=Path(self.temp.name)/'parent-alias';top_alias.symlink_to(self.temp.name,target_is_directory=True)
        with self.assertRaises(ValueError):delivery.verify(top_alias/'delivery',self.pin,self.commit)

    def test_windows_reparse_attribute_is_rejected(self):
        class Info:
            st_mode=stat.S_IFREG|0o600
            st_file_attributes=0x400
        self.assertTrue(delivery.linked(Info()))

    def test_ordinary_change_after_earlier_payload_read_is_detected(self):
        real=delivery.read_plain
        changed=[]
        def read(path, maximum):
            data, info=real(path,maximum)
            if path.name=='zevune_wallet.py' and not changed:
                changed.append(True)
                with (self.folder/'wallet_health.py').open('ab') as handle:handle.write(b'\n')
            return data,info
        with patch.object(delivery,'read_plain',side_effect=read):
            with self.assertRaises(ValueError):self.verify()
        self.assertEqual(changed,[True])

    def test_extra_file_added_during_check_is_detected(self):
        real=delivery.read_plain
        def read(path, maximum):
            answer=real(path,maximum)
            if path.name=='zevune_wallet.py':(self.folder/'extra').write_bytes(b'inert')
            return answer
        with patch.object(delivery,'read_plain',side_effect=read):
            with self.assertRaises(ValueError):self.verify()

    def test_existing_output_never_overwritten_or_removed(self):
        before=(self.folder/delivery.MANIFEST).read_bytes()
        with self.assertRaises(ValueError):delivery.build(self.repo,self.commit,self.folder)
        self.assertEqual(before,(self.folder/delivery.MANIFEST).read_bytes())

    def test_partial_write_failure_retained_and_not_verifiable(self):
        output=Path(self.temp.name)/'partial';real=delivery.write_new;count=[]
        def write(path,data):
            count.append(path)
            if len(count)==2:
                path.write_bytes(data[:11])
                raise OSError('injected_write_failure')
            real(path,data)
        with patch.object(delivery,'write_new',side_effect=write):
            with self.assertRaises(OSError):delivery.build(self.repo,self.commit,output)
        self.assertTrue(output.is_dir())
        self.assertEqual(len(list(output.iterdir())),2)
        self.assertFalse((output/delivery.MANIFEST).exists())
        with self.assertRaises(ValueError):delivery.verify(output,self.pin,self.commit)

    def test_manifest_is_written_last_and_fsync_failure_not_success(self):
        output=Path(self.temp.name)/'failed-sync'
        with patch.object(delivery.os,'fsync',side_effect=OSError('injected_sync_failure')):
            with self.assertRaises(OSError):delivery.build(self.repo,self.commit,output)
        self.assertEqual(len(list(output.iterdir())),1)
        self.assertFalse((output/delivery.MANIFEST).exists())

    def test_exact_pin_not_head_branch_or_tag(self):
        for ref in ('HEAD','main',self.commit[:8],'../secret','--help',None):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                delivery.build(self.repo,ref,Path(self.temp.name)/'never')
        tree=git(self.repo,'rev-parse','HEAD^{tree}').decode()
        with self.assertRaises(ValueError):delivery.capture(self.repo,tree)

    def test_source_worktree_changes_untracked_files_and_filters_not_inputs(self):
        work=Path(self.temp.name)/'repo';shutil.copytree(self.repo,work)
        (work/'scripts/wallet_inspector_desktop.py').write_bytes(b'not the pinned bytes')
        (work/'scripts/unexpected.py').write_bytes(b'not included')
        (work/'.gitattributes').write_text('*.py filter=sentinel\n',encoding='utf-8')
        git(work,'config','filter.sentinel.smudge','exit 99')
        output=Path(self.temp.name)/'exact'
        result=delivery.build(work,self.commit,output)
        self.assertEqual(result['manifest_sha256'],self.pin)
        self.assertEqual((output/'wallet_inspector_desktop.py').read_bytes(),(self.original/'wallet_inspector_desktop.py').read_bytes())
        self.assertEqual((work/'scripts/wallet_inspector_desktop.py').read_bytes(),b'not the pinned bytes')
        self.assertFalse((output/'unexpected.py').exists())

    def test_replacement_refs_and_inherited_repository_environment_ignored(self):
        work=Path(self.temp.name)/'repo';shutil.copytree(self.repo,work)
        original=git(work,'rev-parse',self.commit+':scripts/wallet_health.py').decode()
        replacement=git(work,'hash-object','-w','--stdin',input=b'not real code\n').decode()
        git(work,'replace',original,replacement)
        with patch.dict(os.environ,{'GIT_DIR':str(Path(self.temp.name)/'missing'), 'GIT_TRACE':'1',
                                    'GIT_CONFIG_COUNT':'0', 'GIT_ICASE_PATHSPECS':'1'}):
            result=delivery.build(work,self.commit,Path(self.temp.name)/'exact')
        self.assertEqual(result['manifest_sha256'],self.pin)

    def changed_commit(self, mutate):
        work=Path(self.temp.name)/'repo';shutil.copytree(self.repo,work)
        mutate(work)
        git(work,'add','-A');git(work,'commit','-qm','Mutated source fixture')
        return work,git(work,'rev-parse','HEAD').decode()

    def test_missing_transitive_dependency_rejected_before_output(self):
        work,commit=self.changed_commit(lambda p:(p/'scripts/ledger_restore.py').unlink())
        output=Path(self.temp.name)/'not-created'
        with self.assertRaises(ValueError):delivery.build(work,commit,output)
        self.assertFalse(output.exists())

    def test_new_static_dependency_fails_closed_until_contract_updated(self):
        work,commit=self.changed_commit(lambda p:(p/'scripts/wallet_inspector_desktop.py').write_bytes(b'import undelivered_dependency\n'))
        output=Path(self.temp.name)/'not-created'
        with self.assertRaises(ValueError):delivery.build(work,commit,output)
        self.assertFalse(output.exists())

    def test_relative_import_refused(self):
        payloads={name:(self.original/name).read_bytes() for name in delivery.SOURCES}
        payloads['wallet_inspector_desktop.py']=b'from . import hidden\n'
        with self.assertRaises(ValueError):delivery.check_static_imports(payloads)

    def test_nonregular_git_blob_and_oversized_source_refused(self):
        work=Path(self.temp.name)/'repo';shutil.copytree(self.repo,work)
        oid=git(work,'hash-object','-w','--stdin',input=b'elsewhere').decode()
        git(work,'update-index','--cacheinfo','120000,'+oid+',scripts/wallet_health.py')
        tree=git(work,'write-tree').decode()
        commit=git(work,'commit-tree',tree,'-p',self.commit,'-m','Symlink fixture').decode()
        with self.assertRaises(ValueError):delivery.capture(work,commit)
        with patch.object(delivery,'MAX_FILE',1):
            with self.assertRaises(ValueError):delivery.capture(self.repo,self.commit)

    def test_output_paths_and_nested_repository_are_refused(self):
        with self.assertRaises(ValueError):delivery.build(self.repo,self.commit,self.repo/'output')
        with self.assertRaises(ValueError):delivery.build(self.repo,self.commit,Path('relative'))
        with self.assertRaises(ValueError):delivery.capture(self.repo/'scripts',self.commit)
        with self.assertRaises(ValueError):delivery.verify(Path('relative'),self.pin,self.commit)

    def test_cli_help_has_no_tk_git_or_bytecode_requirement(self):
        folder=Path(self.temp.name)/'tool';folder.mkdir();tool=folder/TOOL.name;shutil.copy2(TOOL,tool)
        before={p.name:p.read_bytes() for p in folder.iterdir()}
        result=subprocess.run([sys.executable,str(tool),'--help'],cwd=folder,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir()})

    def test_cli_verify_and_redacted_failure(self):
        command=[sys.executable,str(TOOL),'--no-real-funds','verify','--bundle',str(self.folder),
                 '--source-commit',self.commit,'--manifest-sha256',self.pin]
        result=subprocess.run(command,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['integrity_verified'])
        command[-1]='PRIVATE_SENTINEL'
        result=subprocess.run(command,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,1)
        self.assertNotIn(b'PRIVATE',result.stderr+result.stdout)
        self.assertNotIn(str(self.folder).encode(),result.stderr+result.stdout)
        result=subprocess.run([sys.executable,str(TOOL),'--PRIVATE_SENTINEL'],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,64)
        self.assertNotIn(b'PRIVATE',result.stderr+result.stdout)

    def test_git_transport_disabled_and_stderr_not_forwarded(self):
        with patch.object(delivery.subprocess, 'run', wraps=subprocess.run) as run:
            self.assertEqual(delivery.git_bytes(self.repo,'cat-file','-t',self.commit),b'commit\n')
        env=run.call_args.kwargs['env']
        self.assertEqual(env['GIT_NO_LAZY_FETCH'],'1')
        self.assertEqual(env['GIT_ALLOW_PROTOCOL'],'')
        self.assertEqual(env['GIT_CONFIG_VALUE_0'],'never')
        self.assertEqual(env['GIT_NO_REPLACE_OBJECTS'],'1')

    def test_cli_build_from_real_commit(self):
        output=Path(self.temp.name)/'cli-built'
        result=subprocess.run([sys.executable,str(TOOL),'--no-real-funds','build','--repository',str(self.repo),
                               '--source-commit',self.commit,'--output',str(output)],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['manifest_sha256'],self.pin)


if __name__=='__main__':unittest.main()
