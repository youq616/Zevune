#!/usr/bin/env python3
"""NO-FUNDS read-only change audit of two independently pinned query tasks.

Compare public request content, never ledger state, native programs or approval.
Before/after are caller labels, not verified chronology. Identical content is not
permission to reuse an earlier execution confirmation. No files are written.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

import json
from pathlib import Path

import ledger_query_request as task

FORMAT = 'zevune-ledger-query-request-audit-1'
MAX_OUTPUT_BYTES = 32768
PIN_FIELDS = ('checkpoint', 'genesis_sha256', 'backend_sha256')


def describe(before: task.Request, after: task.Request, *, details: bool = False) -> dict:
    """Pure public differences only. This helper does not claim file integrity.

    Position shifts include insertions/removals. Relative order compares only
    retained IDs, so adding an ID before existing ones is not called a reorder.
    """
    task.files.require(type(details) is bool, 'audit_details_must_be_boolean')
    task.encode(before)
    task.encode(after)
    left = {txid: index for index, txid in enumerate(before.txids)}
    right = {txid: index for index, txid in enumerate(after.txids)}
    removed = [txid for txid in before.txids if txid not in right]
    added = [txid for txid in after.txids if txid not in left]
    retained_before = [txid for txid in before.txids if txid in right]
    retained_after = [txid for txid in after.txids if txid in left]
    shifted = [txid for txid in retained_before if left[txid] != right[txid]]
    pin_changes = [name for name in PIN_FIELDS if getattr(before, name) != getattr(after, name)]
    sequence_changed = before.txids != after.txids
    changed_fields = pin_changes + (['txids'] if sequence_changed else [])
    left_height = task.once.single.Checkpoint.parse(before.checkpoint).height
    right_height = task.once.single.Checkpoint.parse(after.checkpoint).height
    relation = 'equal' if left_height == right_height else ('higher' if right_height > left_height else 'lower')
    result = dict(content_identical=not changed_fields, changed_fields=changed_fields,
                  trust_inputs_changed=bool(pin_changes), changed_trust_fields=pin_changes,
                  before_query_count=len(before.txids), after_query_count=len(after.txids),
                  added_count=len(added), removed_count=len(removed), retained_count=len(retained_before),
                  query_set_changed=bool(added or removed), query_sequence_changed=sequence_changed,
                  retained_order_changed=retained_before != retained_after,
                  retained_position_changed_count=len(shifted),
                  before_checkpoint_height=left_height, after_checkpoint_height=right_height,
                  after_height_comparison=relation, details_included=details)
    if details:
        result['details'] = dict(
            before=before.document(), after=after.document(),
            added=[dict(txid=value, after_index=right[value]) for value in added],
            removed=[dict(txid=value, before_index=left[value]) for value in removed],
            retained=[dict(txid=value, before_index=left[value], after_index=right[value])
                      for value in retained_before])
    return result


def _metadata_unchanged(snapshot: task.Snapshot) -> None:
    """Catch ordinary changes to the earlier file during the later full reread.

    This is not a cross-file lock or an atomic/hostile-filesystem guarantee.
    """
    task.files.require(task.view._chain(snapshot.path.parent) == snapshot.parent_chain,
                       'audit_request_parent_changed')
    info = snapshot.path.lstat()
    task.files.require(task.files.regular(info) and task.files.identity(info) == snapshot.identity,
                       'audit_request_identity_changed')


def audit(before: Path, before_sha256: str, after: Path, after_sha256: str,
          *, details: bool = False) -> dict:
    """Read both tasks under independent pins and recheck both before returning.

    Same-file comparisons are allowed but not deduplicated. A valid digest for
    one side never substitutes for the separately required digest on the other.
    """
    task.files.require(type(details) is bool, 'audit_details_must_be_boolean')
    for value in (before_sha256, after_sha256):
        task.digest(value)
    for path in (before, after):
        task.absolute(path)
    left = task.load(before, before_sha256)
    right = task.load(after, after_sha256)
    difference = describe(left.request, right.request, details=details)
    answer = dict(format=FORMAT, before_request_sha256=before_sha256,
                  after_request_sha256=after_sha256, before_request_bytes=len(left.raw),
                  after_request_bytes=len(right.raw), audit_complete=True,
                  request_integrity_verified=True, input_files_unchanged=True,
                  execution_performed=False, signature_verified=False, ledger_replayed=False,
                  checkpoint_chain_relation_verified=False, approval_reusable=False,
                  requires_explicit_execution_confirmation=True, finality_verified=False,
                  retry_authorized=False, real_funds_allowed=False, **difference)
    # Form/size checks happen before final source checks, not after them.
    task.files.require(len(json.dumps(answer, sort_keys=True).encode('utf-8')) <= MAX_OUTPUT_BYTES,
                       'audit_output_limit')
    task.unchanged(left)
    task.unchanged(right)
    _metadata_unchanged(left)
    _metadata_unchanged(right)
    return answer


def render(result: dict) -> str:
    """Present this module's own result; no parsing of external audit reports."""
    state = '任务内容相同' if result['content_identical'] else '任务内容发生变化'
    changes = {'checkpoint': '检查点', 'genesis_sha256': '签名域摘要',
               'backend_sha256': '原生程序摘要', 'txids': '查询ID清单'}
    lines = [state + '（仅已核验的文件内容，不是执行授权）',
             f"原任务 SHA256：{result['before_request_sha256']}\n新任务 SHA256：{result['after_request_sha256']}",
             '变更项：' + ('、'.join(changes[item] for item in result['changed_fields']) or '无'),
             f"ID数量：{result['before_query_count']} → {result['after_query_count']}；"
             f"新增{result['added_count']}，删除{result['removed_count']}，保留{result['retained_count']}",
             f"保留ID相对顺序改变：{'是' if result['retained_order_changed'] else '否'}；"
             f"位置改变数量：{result['retained_position_changed_count']}",
             f"检查点高度数值：{result['before_checkpoint_height']} → {result['after_checkpoint_height']}",
             '高度大小不证明同一条链、追加关系、最新状态或哪个任务更可信。',
             '未执行查询、未验证签名或账本；相同内容也不复用旧确认，须另行明确确认执行。NO-FUNDS。']
    if result['details_included']:
        lines += ['以下是明确请求显示的公开明细（可能关联交易）：',
                  json.dumps(result['details'], sort_keys=True, ensure_ascii=True)]
    else:
        lines.append('默认不输出交易ID和完整信任依据；--details 明确显示。文件摘要仍可能关联任务。')
    return '\n'.join(lines)


class Parser(task.Parser):
    def error(self, message):
        self.exit(64, 'Invalid task-audit arguments. Use --help; never supply wallet secrets.\n')


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    for side in ('before', 'after'):
        parser.add_argument('--' + side, required=True, type=Path)
        parser.add_argument('--' + side + '-sha256', required=True)
    parser.add_argument('--details', action='store_true', help='explicitly include public IDs and full pins')
    parser.add_argument('--text', action='store_true', help='Chinese explanation instead of JSON')
    args = parser.parse_args(argv)
    try:
        result = audit(args.before, args.before_sha256, args.after, args.after_sha256, details=args.details)
        text = render(result) if args.text else json.dumps(result, sort_keys=True)
        task.files.require(len(text.encode('utf-8')) <= MAX_OUTPUT_BYTES, 'audit_output_limit')
        task.view.write_output(text)
        return 0
    except KeyboardInterrupt:
        print('Task audit interrupted. No complete audit; preserve both inputs.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError):
        print('Task audit failed. No complete audit or execution permission; preserve both inputs.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
