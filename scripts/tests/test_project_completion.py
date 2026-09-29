"""Bookkeeping tests only: synthetic records do not certify experiments or audits."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_project_completion as check

ROOT = Path(__file__).resolve().parents[2]
COMMIT = '1234567890abcdef1234567890abcdef12345678'


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='completion-record-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.document = json.loads((ROOT / 'PROJECT_COMPLETION.json').read_text(encoding='utf-8'))
        self.document['candidate_commit'] = COMMIT
        references = {self.document['scope_document'], *self.document['specifications']['paths']}
        for group in self.document['work_packages']:
            for row in group['criteria']:
                references.update(row['sources'])
        for name in references:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('Synthetic bookkeeping fixture; not engineering acceptance.\n')
        self.save()

    def save(self):
        (self.root / 'PROJECT_COMPLETION.json').write_text(json.dumps(self.document), encoding='utf-8')

    def row(self, package='P1', criterion='network_identity'):
        return next(r for g in self.document['work_packages'] if g['id'] == package
                    for r in g['criteria'] if r['id'] == criterion)

    def evidence(self, row, kind, facts=None, commit=COMMIT):
        name = f"reports/fixture-{row['id']}-{kind}.txt"
        target = self.root / name
        target.parent.mkdir(exist_ok=True)
        raw = ('Synthetic ' + kind + ' record; does not verify its claimed kind.\n').encode()
        target.write_bytes(raw)
        item = dict(kind=kind, path=name, sha256=hashlib.sha256(raw).hexdigest(),
                    source_commit=commit, facts={} if facts is None else facts)
        row['evidence'].append(item)
        return item

    def accept(self, row):
        row['status'] = 'accepted'
        for kind in sorted(check.ACCEPTED_EVIDENCE):
            self.evidence(row, kind)

    def evaluate(self):
        return check.evaluate(self.root, self.document)

    def test_current_real_repository_is_incomplete_not_bad_record(self):
        result = check.inspect(ROOT)
        self.assertTrue(result['record_valid'])
        self.assertEqual(result['total_criteria'], 24)
        self.assertFalse(result['gate_records_complete']['C'])
        self.assertFalse(result['release_authorized'])
        self.assertFalse(result['evidence_facts_independently_verified'])
        self.assertEqual({r['id'].split('.')[0] for r in result['criteria']}, set(check.REQUIRED))

    def test_implemented_is_not_accepted_and_missing_gates_are_enumerated(self):
        answer = self.evaluate()
        self.assertEqual(answer['accepted_records'], 0)
        self.assertEqual(len(answer['missing_by_gate']['C']), 24)
        self.assertIn('P5.private_transport', answer['missing_by_gate']['C'])
        self.assertTrue(any(r['status'] == 'implemented' for r in answer['criteria']))

    def test_every_work_package_and_criterion_must_remain(self):
        original = copy.deepcopy(self.document)
        for index in range(8):
            self.document = copy.deepcopy(original)
            self.document['work_packages'].pop(index)
            with self.assertRaises(check.InvalidRecord): self.evaluate()
        for group in original['work_packages']:
            self.document = copy.deepcopy(original)
            next(g for g in self.document['work_packages'] if g['id'] == group['id'])['criteria'].pop()
            with self.assertRaises(check.InvalidRecord): self.evaluate()

    def test_duplicate_unknown_or_renamed_scope_cannot_pass(self):
        for field, value in (('id','P9'),('id',True)):
            original=copy.deepcopy(self.document)
            self.document['work_packages'][0][field]=value
            with self.assertRaises(check.InvalidRecord): self.evaluate()
            self.document=original
        self.document['work_packages'][1] = copy.deepcopy(self.document['work_packages'][0])
        with self.assertRaises(check.InvalidRecord): self.evaluate()

    def test_unknown_row_status_and_fields_refuse(self):
        row=self.row()
        for state in ('done', True, None, 'ACCEPTED'):
            row['status']=state
            with self.assertRaises(check.InvalidRecord): self.evaluate()
        row['status']='in_progress';row['auto_accept']=True
        with self.assertRaises(check.InvalidRecord): self.evaluate()

    def test_target_or_permission_cannot_be_changed_or_numeric_false(self):
        original=copy.deepcopy(self.document)
        for key, value in (('target','A'),('target','B'),('real_funds_allowed',True),
                           ('real_funds_allowed',0),('public_deployment_authorized',0),
                           ('scope_frozen',1),('scope_document','README.md'),('candidate_commit','0'*40)):
            self.document=copy.deepcopy(original);self.document[key]=value
            with self.subTest(key=key),self.assertRaises(check.InvalidRecord):self.evaluate()

    def test_accepted_without_all_evidence_categories_fails(self):
        row=self.row();row['status']='accepted'
        for kind in ('code','test','ci'):
            with self.assertRaises(check.InvalidRecord):self.evaluate()
            self.evidence(row,kind)
        with self.assertRaises(check.InvalidRecord):self.evaluate()
        self.evidence(row,'independent_review')
        self.assertEqual(self.evaluate()['accepted_records'],1)

    def test_evidence_sha_and_commit_are_strict(self):
        row=self.row();self.accept(row);item=row['evidence'][0];original=copy.deepcopy(item)
        for key,value in (('sha256','0'*64),('sha256',True),('source_commit','0'*40),
                          ('source_commit','LATEST'),('source_commit','A'*40),('kind','approval')):
            item.clear();item.update(original);item[key]=value
            with self.subTest(key=key),self.assertRaises(check.InvalidRecord):self.evaluate()

    def test_corrupt_or_missing_evidence_file_refuses(self):
        row=self.row();self.accept(row);path=self.root/row['evidence'][0]['path']
        path.write_bytes(b'changed')
        with self.assertRaises(check.InvalidRecord):self.evaluate()
        path.unlink()
        with self.assertRaises(OSError):self.evaluate()

    def test_same_file_cannot_be_counted_as_different_evidence_kinds(self):
        row=self.row();self.accept(row)
        first=copy.deepcopy(row['evidence'][0]);first['kind']='experiment'
        row['evidence'].append(first)
        with self.assertRaises(check.InvalidRecord):self.evaluate()

    def test_different_candidate_approvals_cannot_accept_one_criterion(self):
        row=self.row();self.accept(row);row['evidence'][0]['source_commit']='f'*40
        with self.assertRaisesRegex(check.InvalidRecord,'mixes'):self.evaluate()

    def test_machines_must_be_experiment_fact_not_unrelated_metadata(self):
        row=self.row('P3','four_machine_faults');self.accept(row)
        row['evidence'][0]['facts']={'distinct_machines':4}
        self.evidence(row,'experiment')
        with self.assertRaisesRegex(check.InvalidRecord,'real-world'):self.evaluate()
        row['evidence'][-1]['facts']={'distinct_machines':3}
        with self.assertRaises(check.InvalidRecord):self.evaluate()
        row['evidence'][-1]['facts']={'distinct_machines':4}
        result=self.evaluate()
        self.assertNotIn('P3.four_machine_faults',result['missing_by_gate']['C'])
        self.assertFalse(result['evidence_facts_independently_verified'])

    def test_thirty_day_observation_cannot_be_one_day_or_bool(self):
        row=self.row('P7','soak_30_days');self.accept(row)
        item=self.evidence(row,'experiment',{'continuous_seconds':86400})
        with self.assertRaises(check.InvalidRecord):self.evaluate()
        item['facts']['continuous_seconds']=True
        with self.assertRaises(check.InvalidRecord):self.evaluate()
        item['facts']['continuous_seconds']=2592000
        self.assertEqual(self.evaluate()['accepted_records'],1)

    def test_specialist_security_audit_cannot_be_replaced_by_agent_review(self):
        row=self.row('P8','independent_security_audit');self.accept(row)
        with self.assertRaisesRegex(check.InvalidRecord,'external security'):self.evaluate()
        self.evidence(row,'security_audit')
        self.assertEqual(self.evaluate()['accepted_records'],1)

    def test_complete_synthetic_records_still_grant_no_release_permission(self):
        # Testing record validation only, not synthesizing an accepted real project.
        for group in self.document['work_packages']:
            for row in group['criteria']:
                self.accept(row)
                qualified=group['id']+'.'+row['id']
                if qualified in check.MANDATORY_FACTS:
                    key,minimum=check.MANDATORY_FACTS[qualified]
                    self.evidence(row,'experiment',{key:minimum})
                if qualified=='P8.independent_security_audit':self.evidence(row,'security_audit')
        answer=self.evaluate();self.assertTrue(answer['gate_records_complete']['C'])
        self.assertEqual(answer['accepted_records'],24)
        for key in ('release_authorized','real_funds_allowed','public_deployment_authorized',
                    'evidence_facts_independently_verified'):self.assertIs(answer[key],False)

    def test_bad_json_duplicate_fields_nonfinite_and_size_refuse(self):
        for data in (b'{"format":1,"format":2}',b'{"x":NaN}',b'\xff',b'',b' '*(check.MAX_BYTES+1)):
            with self.assertRaises((ValueError,UnicodeError)):check.parse(data)
        with self.assertRaises(ValueError):check.parse(bytearray(b'{}'))
        with self.assertRaises(ValueError):check.evaluate(self.root,check.parse(b'[]'))

    def test_source_paths_cannot_escape_repository(self):
        row=self.row()
        for path in ('../outside','/etc/passwd','a/../b','a//b','a/./b','C:/file','x\\file','a\nfile'):
            row['sources']=[path]
            with self.subTest(path=path),self.assertRaises(check.InvalidRecord):self.evaluate()

    def test_source_and_evidence_extents_bounded(self):
        path=self.root/self.row()['sources'][0];path.write_bytes(b'x'*(check.MAX_BYTES+1))
        with self.assertRaises(check.InvalidRecord):self.evaluate()

    def test_hardlinked_source_refused(self):
        path=self.root/self.row()['sources'][0];os.link(path,self.root/'alias')
        with self.assertRaises(check.InvalidRecord):self.evaluate()

    @unittest.skipUnless(os.name=='posix','POSIX symbolic link fixture')
    def test_symlink_parent_and_target_refused(self):
        path=self.root/self.row()['sources'][0];old=path.with_suffix('.held');path.rename(old);path.symlink_to(old)
        with self.assertRaises(check.InvalidRecord):self.evaluate()

    def test_record_changes_at_final_reread_refused(self):
        actual=check.read_file;calls=[]
        def changed(root,name):
            value=actual(root,name)
            if name=='PROJECT_COMPLETION.json':
                calls.append(1)
                if len(calls)>1:return value+b' '
            return value
        with patch.object(check,'read_file',side_effect=changed),self.assertRaises(check.InvalidRecord):check.inspect(self.root)

    def test_live_evidence_summary_does_not_modify_any_inputs(self):
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        check.inspect(self.root)
        self.assertEqual(before,{str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_real_cli_report_and_failing_completion_gate(self):
        for flag,code in (('--report',0),('--require-complete',2)):
            out=subprocess.run([sys.executable,'-B',check.__file__,'--root',str(self.root),flag],capture_output=True,timeout=10)
            self.assertEqual(out.returncode,code,out.stderr)
            answer=json.loads(out.stdout);self.assertTrue(answer['record_valid'])
            self.assertFalse(answer['gate_records_complete']['C'])
        (self.root/'PROJECT_COMPLETION.json').write_text('{')
        out=subprocess.run([sys.executable,'-B',check.__file__,'--root',str(self.root),'--report'],capture_output=True,timeout=10)
        self.assertEqual(out.returncode,1);self.assertEqual(out.stdout,b'')

    def test_all_current_specs_and_historical_provenance_are_explicit(self):
        status=json.loads((ROOT/'PROJECT_STATUS.json').read_text(encoding='utf-8'))
        specs=json.loads((ROOT/'PROJECT_COMPLETION.json').read_text(encoding='utf-8'))['specifications']
        self.assertFalse(status['remote_source_complete'])
        self.assertFalse(specs['historical_originals_recovered'])
        self.assertEqual(set(specs['paths']),set(status['missing_documents']))
        for path in specs['paths']:
            self.assertIn('历史原稿',(ROOT/path).read_text(encoding='utf-8'))
        self.assertFalse(status['real_funds_allowed']);self.assertFalse(status['public_network_deployed'])


if __name__=='__main__':unittest.main()
