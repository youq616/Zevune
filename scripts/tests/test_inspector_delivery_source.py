"""The new delivery workflow must cover every runtime and test dependency."""
import ast
from pathlib import Path
import re
import os
import subprocess
import tempfile
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import inspector_source_bundle as delivery
ROOT=Path(__file__).resolve().parents[2]
WORKFLOW=ROOT/'.github/workflows/inspector-source-delivery.yml'


class DeliverySourceTests(unittest.TestCase):
    def test_source_allowlist_covers_existing_runtime_imports(self):
        payloads={name:(ROOT/source).read_bytes() for name,source in delivery.SOURCES.items()}
        delivery.check_static_imports(payloads)
        self.assertEqual(len(payloads),10)
        self.assertNotIn('inspector_source_bundle.py',payloads)
        self.assertTrue(all(not name.endswith('.exe') for name in payloads))

    def test_events_cover_all_static_transitive_test_and_runtime_inputs(self):
        pending=[ROOT/'scripts'/n for n in ('inspector_source_bundle.py','check_inspector_source_delivery.py',
                 'check_wallet_inspector_gui.py','check_wallet_inspector_backend.py')]
        pending += [Path(__file__),ROOT/'scripts/tests/test_inspector_source_bundle.py',
                    ROOT/'scripts/tests/test_wallet_inspector_desktop.py',ROOT/'scripts/tests/test_verify_local_lab.py']
        dependencies=set(delivery.SOURCES.values())|{str(WORKFLOW.relative_to(ROOT)),
                                                    'docs/INSPECTOR_SOURCE_DELIVERY.zh-CN.md'}
        visited=set()
        while pending:
            path=pending.pop()
            if path in visited:continue
            visited.add(path);dependencies.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                modules=([a.name for a in node.names] if isinstance(node,ast.Import) else
                         [node.module] if isinstance(node,ast.ImportFrom) and node.level==0 and node.module else [])
                for module in modules:
                    for directory in (ROOT/'scripts',ROOT/'scripts/tests'):
                        candidate=directory/(module.split('.')[0]+'.py')
                        if candidate.is_file():pending.append(candidate)
        text=WORKFLOW.read_text()
        blocks=dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',text,re.M))
        self.assertEqual(set(blocks),{'push','pull_request'})
        for name,body in blocks.items():
            paths=ast.literal_eval(re.findall(r'^    paths: (.+)$',body,re.M)[0])
            self.assertTrue(dependencies <= set(paths),(name,dependencies-set(paths)))

    def test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source(self):
        source=WORKFLOW.read_text()
        script=re.search(r"python - <<'PY_SOURCE'\n(.*?)          PY_SOURCE",source,re.S).group(1)
        script='\n'.join(line[10:] for line in script.splitlines())
        with tempfile.TemporaryDirectory(prefix='delivery-source-guard-') as temporary:
            root=Path(temporary).resolve()
            def git(*args):
                return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL,text=True).strip()
            git('init','-q');git('config','user.name','Source guard test')
            git('config','user.email','guard@example.invalid')
            (root/'source.txt').write_text('inert test source\n')
            git('add','.');git('commit','-qm','Source guard fixture')
            expected=git('rev-parse','HEAD')
            def check(commit):
                return subprocess.run([sys.executable,'-c',script],cwd=root,
                                      env={**os.environ,'ZEVUNE_SOURCE_HEAD':commit},
                                      capture_output=True,timeout=15)
            self.assertEqual(check(expected).returncode,0)
            self.assertNotEqual(check('0'*40).returncode,0)
            (root/'source.txt').write_text('changed source\n')
            self.assertNotEqual(check(expected).returncode,0)

    def test_workflow_pins_source_and_keeps_real_native_execution(self):
        text=WORKFLOW.read_text()
        self.assertIn('ref: ${{ github.event.pull_request.head.sha || github.sha }}',text)
        self.assertIn("assert git('rev-parse', 'HEAD') == expected",text)
        self.assertIn('persist-credentials: false',text)
        self.assertIn('os: [ubuntu-latest, windows-latest]',text)
        self.assertIn('cargo +1.98.1 build',text)
        self.assertIn("'--backend', str(backend)",text)
        self.assertIn('check=True, timeout=750',text)
        self.assertNotIn('continue-on-error',text)
        self.assertNotIn('upload-artifact',text)
        for name in ('test_inspector_source_bundle.py','test_inspector_delivery_source.py','test_verify_local_lab.py'):
            self.assertIn('python -m unittest discover -s scripts/tests -p '+name+' -v',text)


if __name__=='__main__':unittest.main()
