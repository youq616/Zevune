#!/usr/bin/env python3
"""NO-FUNDS single-pass historical batch desktop; never a payment command.

The old batch window remains N scans. This explicit entry accepts only the
one-pass result contract and keeps all original admission/closing semantics.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import dataclass
import queue
import threading

import ledger_transaction_batch_once as once
import ledger_transaction_batch_desktop as previous

files, lifecycle = previous.files, previous.lifecycle
prepare, parse_ids = previous.prepare, previous.parse_ids
NOTICE = 'NO-FUNDS｜单遍历史批量核查：一次记录定位，前后指纹另读；不是结算或重试许可。'


def review_text(intent: once.Intent) -> str:
    labels = dict(zip(once.single.FIELDS, previous.single_ui.LABELS))
    fields = '\n\n'.join(f'{labels[name]}\n{getattr(intent.source, name)}' for name in once.batch.COMMON_FIELDS)
    ids = '\n'.join(f'{index + 1:02d}  {txid}' for index, txid in enumerate(intent.txids))
    return (fields + f'\n\n完整冻结清单（{len(intent.txids)}项，保持输入顺序）\n' + ids +
            '\n\n默认取消。明确确认后执行一次原 verify-active 和一次完整记录定位。'
            '\n原生重放与前后指纹另行读盘；单遍不代表全流程只读一次或固定加速倍数。'
            '\n整批共享原300秒预算；任何失败撤销全部结果，不授权签名、广播或付款重试。')


@dataclass(frozen=True)
class OnceDisplay(previous.BatchDisplay):
    """Distinct immutable output: an old batch display cannot pass this boundary."""


def present(result: dict, intent: once.Intent) -> OnceDisplay:
    """Validate the new contract before reusing old row/scope metadata checks.

    Projection is private validation data only, never a query, a replay reply or
    a displayed old-format result. The original result object is not modified.
    """
    files.require(type(intent) is once.Intent and type(intent.source) is once.single.Intent
                  and type(intent.txids) is tuple, 'invalid_once_display_intent')
    fields = {name: str(getattr(intent.source, name)) if name in ('journal', 'backend')
              else getattr(intent.source, name) for name in once.batch.COMMON_FIELDS}
    files.require(once.prepare(dict(fields, txids=intent.txids)) == intent, 'invalid_once_display_intent')
    required = {'format', 'history_scan_count', 'scanned_records', 'scanned_transactions'}
    forbidden = {'scanned_records_per_query', 'scanned_transactions_per_query'}
    files.require(type(result) is dict and required <= set(result) and not forbidden & set(result),
                  'invalid_once_display_fields')
    files.require(type(result['format']) is str and result['format'] == 'zevune-ledger-transaction-batch-once-1'
                  and type(result['history_scan_count']) is int and result['history_scan_count'] == 1,
                  'once_display_scan_contract_mismatch')
    normalized = dict(result)
    normalized['format'] = 'zevune-ledger-transaction-batch-1'
    normalized['history_scan_count'] = len(intent.txids)
    normalized['scanned_records_per_query'] = normalized.pop('scanned_records')
    normalized['scanned_transactions_per_query'] = normalized.pop('scanned_transactions')
    validated = previous.present(normalized, intent)  # All other fields/types/pins/order/rows remain mandatory.
    text = once.render(result) + '\n\n这是单次历史观察，不会后台刷新。复制的是查询ID，不是付款凭证。'
    files.require(len(text.encode('utf-8')) <= once.MAX_OUTPUT_BYTES, 'bounded_once_display_required')
    return OnceDisplay(text, None, validated.txids)


def _execute(channel, released, completed, request):
    intent = result = None
    outcome = lifecycle.Completion(None)
    try:
        released.wait()
        intent, request[0] = request[0], None
        if intent is not None:
            result = once.lookup_batch_once(intent)  # Actual native-verified one-pass core only.
            outcome = lifecycle.Completion(present(result, intent))
    except BaseException:
        pass  # Fixed failure, no exception/traceback/native payload in the GUI queue.
    finally:
        intent = result = None
        request[0] = None
        try:
            channel.put_nowait(outcome)
        except BaseException:
            pass
        finally:
            completed.set()


class OnceJob(lifecycle.LedgerJob):
    def __init__(self, intent: once.Intent):
        files.require(type(intent) is once.Intent, 'invalid_once_job')
        self.channel = queue.Queue(maxsize=1)
        self.released, self.completed = threading.Event(), threading.Event()
        self.request = [intent]
        self.start_attempted = self.consumed = False
        self.thread = threading.Thread(target=_execute,
                                       args=(self.channel, self.released, self.completed, self.request),
                                       name='zevune-one-pass-historical-lookup', daemon=False)


class Workbench(previous.Workbench):
    """Share every action-boundary sync and lifecycle method without global replacement."""
    def __init__(self, root):
        super().__init__(root)
        root.title('Zevune｜单遍批量历史交易核查 · NO-FUNDS')
        form = self.entries['journal'].master
        for widget in form.master.grid_slaves(row=0):
            widget.configure(text=NOTICE)
        self.confirm_button.configure(text='确认单遍核查历史')
        self.details.master.configure(text='2  单遍输入确认 / 完整历史结果')
        self.status.set('每行填写一个交易ID；本入口只运行单遍定位，原生重放和指纹检查仍保留。')

    def _review_description(self, intent):
        return review_text(intent)

    def _new_job(self, intent):
        return OnceJob(intent)

    def _valid_display(self, result):
        return type(result) is OnceDisplay


def main(argv=None):
    parser = once.batch.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
        Workbench(root)
        root.mainloop()
        return 0
    except Exception:
        print('Single-pass desktop could not finish. Preserve inputs; no payment retry is authorized.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
