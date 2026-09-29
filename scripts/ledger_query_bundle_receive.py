#!/usr/bin/env python3
"""NO-FUNDS receipt workflow over the unchanged C31 evidence bundle API.

Review is read-only. Explicit execution either creates one new directory or
checks an existing one; it never runs the received tasks or removes failures.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ledger_query_evidence_bundle as bundle

files, task = bundle.files, bundle.task
FIELDS = ('operation', 'bundle', 'bundle_sha256', 'destination')
OPERATIONS = ('unpack', 'verify-directory')
MAX_TEXT_BYTES = 32768


@dataclass(frozen=True)
class Form:
    operation: str
    bundle: Path
    bundle_sha256: str
    destination: Path


def prepare(values: dict[str, str]) -> Form:
    """Validate the complete local form before reading any file."""
    files.require(type(values) is dict and set(values) == set(FIELDS), 'incomplete_receive_form')
    files.require(type(values['operation']) is str and values['operation'] in OPERATIONS,
                  'explicit_receive_operation_required')
    pin = task.digest(values['bundle_sha256'])
    paths = [task.absolute(Path(task.view.bounded(values[key], 'directory')))
             for key in ('bundle', 'destination')]
    files.require(not paths[0].is_relative_to(paths[1]), 'bundle_must_be_outside_destination')
    return Form(values['operation'], paths[0], pin, paths[1])


def validate_form(form: Form) -> None:
    files.require(type(form) is Form, 'invalid_receive_form')
    values = dict(operation=form.operation, bundle=str(form.bundle), bundle_sha256=form.bundle_sha256,
                  destination=str(form.destination))
    files.require(prepare(values) == form, 'invalid_receive_form')


@dataclass(frozen=True)
class Approval:
    form: Form
    snapshot: bundle.Snapshot
    destination_parent: tuple
    destination_chain: tuple | None


def validate(approval: Approval) -> None:
    """Pure structural/content validation, not new filesystem authorization."""
    files.require(type(approval) is Approval, 'invalid_receive_approval')
    validate_form(approval.form)
    snap = approval.snapshot
    files.require(type(snap) is bundle.Snapshot and snap.path == approval.form.bundle
                  and type(snap.identity) is tuple and type(snap.parent_chain) is tuple
                  and type(approval.destination_parent) is tuple, 'invalid_receive_snapshot')
    files.require(bundle.decode(snap.raw, approval.form.bundle_sha256) == snap.entries,
                  'reviewed_bundle_mismatch')
    files.require((approval.form.operation == 'unpack' and approval.destination_chain is None) or
                  (approval.form.operation == 'verify-directory' and type(approval.destination_chain) is tuple),
                  'invalid_destination_binding')


def approve(form: Form) -> Approval:
    validate_form(form)
    snapshot = bundle.load(form.bundle, form.bundle_sha256)
    parent = task.view._chain(form.destination.parent)
    if form.operation == 'unpack':
        files.new_file(form.destination)  # Existence check only; directories are also refused.
        chain = None
    else:
        chain = task.view._chain(form.destination)
    bundle.unchanged(snapshot)
    return Approval(form, snapshot, parent, chain)


def manifest(approval: Approval) -> str:
    validate(approval)
    result = bundle.summary(approval.snapshot, 'receive_review')
    lines = [f"{row['filename']} | {row['kind']} | {row['bytes']}字节 | {row['query_count']}个查询ID\n"
             f"文件 SHA256：{row['sha256']}\n任务内容 SHA256：{row['request_sha256']}"
             for row in result['entries']]
    return '\n\n'.join(lines)


def review_text(approval: Approval) -> str:
    form = approval.form
    title = '还原到全新目录（将写入文件）' if form.operation == 'unpack' else '只读核验已有目录（不写入）'
    return (f'{title}\n包文件：{form.bundle}\n独立包 SHA256：{form.bundle_sha256}\n'
            f'目标目录：{form.destination}\n\n完整有序清单：\n{manifest(approval)}\n\n'
            '默认取消；明确确认才执行所选操作。核验绑定当前包文件身份和目标父目录。\n'
            '失败可能留下部分或完整新目录，不自动删除、续装或重试。关闭等待真实结束。\n'
            '包未加密；不验证原件当前存在、签名、账本或付款，不执行收到的任务。NO-FUNDS。')


@dataclass(frozen=True)
class Display:
    form: Form
    text: str


def present(result: dict, approval: Approval) -> Display:
    """Exact canonical receipt matching also distinguishes bool from int."""
    validate(approval)
    operation = approval.form.operation
    expected = bundle.summary(approval.snapshot, 'evidence_bundle_' + operation.replace('-', '_'))
    expected.update(directory_bytes_verified=True)
    if operation == 'unpack':
        expected.update(created=True)
    else:
        expected.update(unpack_call_success_verified=False)
    files.require(type(result) is dict and files.canonical(result) == files.canonical(expected),
                  'receive_receipt_mismatch')
    title = '本次新目录还原调用已完成' if operation == 'unpack' else '本次目录字节核验完成；不证明以前还原调用成功'
    text = (f'{title}\n包 SHA256：{approval.form.bundle_sha256}\n目录：{approval.form.destination}\n\n'
            f'{manifest(approval)}\n\n原件存在性、签名和账本均未验证；不执行任务，不授予付款权限。\n'
            '这是操作结束时的观察，不是后续持续监控。NO-FUNDS。')
    files.require(len(text.encode('utf-8')) <= MAX_TEXT_BYTES, 'receive_display_limit')
    return Display(approval.form, text)


def execute(approval: Approval) -> Display:
    validate(approval)
    form = approval.form
    bundle.unchanged(approval.snapshot)
    files.require(task.view._chain(form.destination.parent) == approval.destination_parent,
                  'reviewed_destination_parent_changed')
    if form.operation == 'unpack':
        files.new_file(form.destination)
        result = bundle.unpack(form.bundle, form.bundle_sha256, form.destination)
    else:
        files.require(task.view._chain(form.destination) == approval.destination_chain,
                      'reviewed_destination_changed')
        result = bundle.verify_directory(form.bundle, form.bundle_sha256, form.destination)
    display = present(result, approval)
    bundle.unchanged(approval.snapshot)
    files.require(task.view._chain(form.destination.parent) == approval.destination_parent,
                  'receive_destination_parent_changed')
    if form.operation == 'verify-directory':
        files.require(task.view._chain(form.destination) == approval.destination_chain,
                      'reviewed_destination_changed')
    bundle.metadata_unchanged(approval.snapshot)
    return display
