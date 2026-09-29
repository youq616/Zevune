#!/usr/bin/env python3
"""NO-FUNDS read-only change comparison across pinned task files and audit reports.

Each input kind is explicit; no format fallback and no report-to-source lookup.
Report integrity never establishes the original task's current existence.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import dataclass
import json
from pathlib import Path

import ledger_query_audit as reports
import ledger_query_request_audit as changes

task = reports.task
FORMAT = 'zevune-ledger-query-evidence-compare-1'
MAX_OUTPUT_BYTES = changes.MAX_OUTPUT_BYTES
KINDS = ('task', 'report')


@dataclass(frozen=True)
class Source:
    kind: str
    path: Path
    sha256: str


def validate_source(source: Source) -> None:
    """Pure input checks for BOTH sides must finish before either side is read."""
    task.files.require(type(source) is Source and type(source.kind) is str and source.kind in KINDS,
                       'explicit_evidence_kind_required')
    task.digest(source.sha256)
    task.absolute(source.path)


@dataclass(frozen=True)
class _Loaded:
    source: Source
    snapshot: task.Snapshot | reports.AuditSnapshot

    def provenance(self) -> dict:
        is_task = self.source.kind == 'task'
        request_digest = self.source.sha256 if is_task else self.snapshot.request_sha256
        return dict(kind=self.source.kind, input_sha256=self.source.sha256,
                    input_bytes=len(self.snapshot.raw), request_sha256=request_digest,
                    request_bytes=len(task.encode(self.snapshot.request)),
                    request_digest_basis='external_task_pin' if is_task else 'verified_report_content',
                    source_file_rechecked=is_task)

    def unchanged(self) -> None:
        if self.source.kind == 'task':
            task.unchanged(self.snapshot)
        else:
            reports.unchanged(self.snapshot)

    def metadata_unchanged(self) -> None:
        # Both existing snapshot types have these path/identity/parent fields.
        # Final metadata after both full rereads catches ordinary late changes,
        # not malicious timestamp restoration or cross-file atomicity.
        snapshot = self.snapshot
        task.files.require(task.view._chain(snapshot.path.parent) == snapshot.parent_chain,
                           'comparison_parent_changed')
        info = snapshot.path.lstat()
        task.files.require(task.files.regular(info) and task.files.identity(info) == snapshot.identity,
                           'comparison_input_changed')


def _load(source: Source) -> _Loaded:
    loader = task.load if source.kind == 'task' else reports.load
    return _Loaded(source, loader(source.path, source.sha256))


def compare(before: Source, after: Source, *, details: bool = False) -> dict:
    """Normalize only through the original decoders, then reuse the same diff.

    Before/after are caller labels, not verified chronology. A report pin binds
    the task content embedded in that report, not a separately read task file.
    The comparison neither executes a query nor authorizes reuse of consent.
    """
    task.files.require(type(details) is bool, 'comparison_details_must_be_boolean')
    validate_source(before)
    validate_source(after)
    left, right = _load(before), _load(after)
    difference = changes.describe(left.snapshot.request, right.snapshot.request, details=details)
    answer = dict(format=FORMAT, before=left.provenance(), after=right.provenance(),
                  input_bytes_identical=left.snapshot.raw == right.snapshot.raw,
                  comparison_complete=True, input_integrity_verified=True, input_files_unchanged=True,
                  difference=difference, execution_performed=False, signature_verified=False,
                  backend_verified=False, ledger_replayed=False, checkpoint_chain_relation_verified=False,
                  approval_reusable=False, requires_explicit_execution_confirmation=True,
                  finality_verified=False, retry_authorized=False, real_funds_allowed=False)
    task.files.require(len(json.dumps(answer, sort_keys=True).encode('utf-8')) <= MAX_OUTPUT_BYTES,
                       'comparison_output_limit')
    left.unchanged()
    right.unchanged()
    left.metadata_unchanged()
    right.metadata_unchanged()
    return answer


def render(result: dict) -> str:
    """Render this call's in-memory result; do not deserialize untrusted results."""
    labels = {'task': '当前任务文件', 'report': '内容审计报告（未读取原任务）'}
    lines = ['查询任务内容变更比较（不是执行记录或付款证明）']
    for key, label in (('before', '前项'), ('after', '后项')):
        item = result[key]
        lines.append(f"{label}：{labels[item['kind']]}\n输入文件 SHA256：{item['input_sha256']}")
    body = dict(result['difference'], before_request_sha256=result['before']['request_sha256'],
                after_request_sha256=result['after']['request_sha256'])
    lines.append(changes.render(body))
    lines.append('报告中的任务摘要由已核验报告内容绑定；未检查对应原任务当前是否存在。前后标签不证明时间顺序。')
    return '\n\n'.join(lines)


class Parser(task.Parser):
    def error(self, message):
        self.exit(64, 'Invalid evidence-comparison arguments. Use --help; never supply secrets.\n')


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    for side in ('before', 'after'):
        parser.add_argument('--' + side, required=True, type=Path)
        parser.add_argument('--' + side + '-sha256', required=True)
        parser.add_argument('--' + side + '-kind', required=True, choices=KINDS)
    parser.add_argument('--details', action='store_true', help='explicitly include IDs and complete public pins')
    parser.add_argument('--text', action='store_true', help='Chinese explanation instead of JSON')
    args = parser.parse_args(argv)
    try:
        before = Source(args.before_kind, args.before, args.before_sha256)
        after = Source(args.after_kind, args.after, args.after_sha256)
        answer = compare(before, after, details=args.details)
        text = render(answer) if args.text else json.dumps(answer, sort_keys=True)
        task.files.require(len(text.encode('utf-8')) <= MAX_OUTPUT_BYTES, 'comparison_output_limit')
        task.view.write_output(text)
        return 0
    except KeyboardInterrupt:
        print('Evidence comparison interrupted. Preserve inputs; no complete result or permission.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError):
        print('Evidence comparison failed. Preserve inputs; no complete result or permission.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
