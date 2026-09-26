#!/usr/bin/env python3
"""Read-only view of pinned local reconciliation results; never wallet authentication.

No password, backend, network, signing, retry, reservation clearing or writes.
The caller supplies an independent report digest, checkpoint and genesis digest.
A verified historical file set does not prove settlement or the current chain.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import stat
import unicodedata

import wallet_reconcile as reconciliation

files = reconciliation.files
Checkpoint = reconciliation.Checkpoint
FIELDS = {"directory": 4096, "report_sha256": 64, "checkpoint": 256, "genesis_sha256": 64}
REPORT_FIELDS = {"format", "result", "independent_ancestor", "source_receipt", "copy_receipt",
                 "checkpoint", "genesis_sha256", "height", "txid", "pending", "broadcast_status",
                 "source_retained", "active_wallet_replaced", "retry_authorized", "latest_inferred",
                 "finality_verified", "real_funds_allowed"}
NOTICE = "NO-FUNDS｜仅核验本地对账文件；不认证钱包、不签名、不广播、不认定付款成功。"
FAILURE = "核验未完成。保留原目录、交易和独立回执；不要重签、清除预留或盲目重试。"


def bounded(value: str, field: str) -> str:
    files.require(type(value) is str and 0 < len(value) <= FIELDS[field]
                  and not any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in value),
                  "invalid_reconciliation_view_field")
    return value


@dataclass(frozen=True)
class Intent:
    directory: Path
    report_sha256: str
    checkpoint: str
    genesis_sha256: str


def prepare(values: dict[str, str]) -> Intent:
    """Validate the entire form before accessing even the directory."""
    files.require(type(values) is dict and set(values) == set(FIELDS), "incomplete_view_input")
    clean = {name: bounded(values[name], name) for name in FIELDS}
    folder = Path(clean["directory"])
    files.require(folder.is_absolute() and ".." not in folder.parts
                  and len(clean["directory"].encode("utf-8")) <= 4096, "bounded_absolute_directory_required")
    for key in ("report_sha256", "genesis_sha256"):
        files.require(files.HEX.fullmatch(clean[key]) is not None, "independent_digest_required")
    checkpoint = Checkpoint.parse(clean["checkpoint"])
    files.require(checkpoint.genesis == clean["genesis_sha256"], "checkpoint_network_mismatch")
    return Intent(folder, clean["report_sha256"], checkpoint.encoded, clean["genesis_sha256"])


def _chain(folder: Path) -> tuple:
    result = []
    for part in (*reversed(folder.parents), folder):
        info = part.lstat()
        files.require(stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                      "plain_view_directory_required")
        result.append((str(part), info.st_dev, info.st_ino, info.st_mode))
    files.directory(folder)
    return tuple(result)


def _decode(raw: bytes, intent: Intent) -> dict:
    files.require(type(raw) is bytes and 0 < len(raw) <= files.MAX_MANIFEST, "bounded_report_required")
    files.require(hashlib.sha256(raw).hexdigest() == intent.report_sha256, "report_digest_mismatch")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            files.require(key not in out, "duplicate_report_field")
            out[key] = value
        return out
    def nonfinite(_):
        raise ValueError("nonfinite_report_number")
    report = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    files.require(type(report) is dict and set(report) == REPORT_FIELDS
                  and raw == files.canonical(report), "noncanonical_reconciliation_report")
    pin = Checkpoint.parse(intent.checkpoint)
    files.require(report["format"] == reconciliation.FORMAT and report["checkpoint"] == intent.checkpoint
                  and report["genesis_sha256"] == intent.genesis_sha256
                  and type(report["height"]) is int and report["height"] == pin.height,
                  "report_checkpoint_mismatch")
    files.require(type(report["pending"]) is bool and report["source_retained"] is True
                  and report["broadcast_status"] == "unknown"
                  and all(report[key] is False for key in ("active_wallet_replaced", "retry_authorized",
                          "latest_inferred", "finality_verified", "real_funds_allowed")), "report_scope_mismatch")
    for key in ("independent_ancestor", "source_receipt", "copy_receipt"):
        files.receipt(report[key])
    ancestor, source, copy = (report[key] for key in ("independent_ancestor", "source_receipt", "copy_receipt"))
    a, s, c = (int(value[64:80], 16) for value in (ancestor, source, copy))
    files.require(ancestor[:64] == source[:64] == copy[:64] and a <= s <= c <= min(256, s + 1)
                  and (a != s or ancestor == source) and (s != c or source == copy), "report_receipt_relation")
    if report["pending"]:
        files.require(report["result"] == "pending_recovered_not_broadcast" and type(report["txid"]) is str
                      and files.HEX.fullmatch(report["txid"]) is not None, "invalid_pending_report")
    else:
        files.require(report["result"] == "no_pending_not_settlement_proof" and report["txid"] is None,
                      "invalid_no_pending_report")
    return report


@dataclass(frozen=True)
class View:
    report_sha256: str
    genesis_sha256: str
    checkpoint: str
    checkpoint_height: int
    copy_receipt: str
    wallet_records: int
    wallet_bytes: int
    pending_file_present: bool
    txid: str | None
    transaction_bytes: int
    expiry_height: int | None
    expiry_relation: str

    def summary(self) -> dict:
        return dict(asdict(self), format="zevune-reconciliation-view-1", file_integrity_verified=True,
                    state="pending_file_broadcast_unknown" if self.pending_file_present else "no_pending_outcome_unknown",
                    wallet_authenticated=False, transaction_authorization_verified=False, ledger_replayed=False,
                    current_chain_height=None, original_source_presence_verified=False,
                    broadcast_status="unknown", settlement_status="unknown", retry_authorized=False,
                    finality_verified=False, real_funds_allowed=False, read_only=True)

    def render(self) -> str:
        status = ("保留了待发送交易文件；广播和结算状态未知。" if self.pending_file_present else
                  "没有待发送交易文件；不能据此区分已入账、已到期或本来没有待发送交易。")
        expiry = {"unknown": "未知（没有待发送文件）",
                  "not_expired_at_checkpoint": "在该历史检查点尚未超过到期高度；不是现在仍可付款",
                  "expired_at_checkpoint": "文件到期高度早于该检查点；不得据此重签或清除预留"}[self.expiry_relation]
        return (f"{status}\n\n历史检查点高度：{self.checkpoint_height}\n当前链高度：未知\n"
                f"待发送交易ID：{self.txid or '无；不是结算证明'}\n"
                f"交易到期高度：{self.expiry_height if self.expiry_height is not None else '未知'}\n"
                f"到期比较：{expiry}\n钱包保存记录：{self.wallet_records} / 256\n"
                f"钱包文件字节：{self.wallet_bytes}\n待发送文件字节：{self.transaction_bytes}\n\n"
                f"副本回执：{self.copy_receipt}\n网络摘要：{self.genesis_sha256}\n"
                f"报告摘要：{self.report_sha256}\n\n"
                "以上仅为本次读取的文件完整性与公开字段；未解密钱包、验证交易授权或重放账本。\n"
                "原钱包是否仍保留、是否已广播、是否已结算均未验证。不要重签、自动重试或清除预留。")


def inspect(intent: Intent) -> View:
    files.require(type(intent) is Intent, "invalid_view_intent")
    files.require(prepare({"directory": str(intent.directory), "report_sha256": intent.report_sha256,
                           "checkpoint": intent.checkpoint, "genesis_sha256": intent.genesis_sha256}) == intent,
                  "invalid_view_intent")
    folder = intent.directory
    chain, root_stamp = _chain(folder), files.identity(folder.lstat())
    marker = files.read_file(folder / reconciliation.MARKER, files.MAX_MANIFEST)
    report = _decode(marker[0], intent)
    expected = {reconciliation.MARKER, "wallet.journal"} | ({"pending.tx"} if report["pending"] else set())
    reconciliation.ledger.names(folder, expected)
    wallet = files.read_file(folder / "wallet.journal", files.MAX_WALLET)
    files.wallet_bytes_summary(wallet[0], report["copy_receipt"])
    for key in ("independent_ancestor", "source_receipt"):
        files.require(reconciliation.public_tip(wallet[0], report[key]) == report["copy_receipt"],
                      "report_ancestor_not_in_copy")
    transaction, expiry, relation = None, None, "unknown"
    if report["pending"]:
        transaction = files.read_file(folder / "pending.tx", reconciliation.MAX_PAYMENT)
        raw = transaction[0]
        # Public header only, exactly the existing LAB2 offsets. This is NOT a
        # second Orchard decoder, proof verifier or spendability decision.
        files.require(98 <= len(raw) <= reconciliation.MAX_PAYMENT and raw[:8] == b"ZVORLAB2"
                      and raw[8:40].hex() == intent.genesis_sha256
                      and hashlib.sha256(raw).hexdigest() == report["txid"], "pending_file_mismatch")
        expiry = int.from_bytes(raw[40:48], "big")
        files.require(expiry > 0, "invalid_pending_expiry")
        relation = "expired_at_checkpoint" if expiry < report["height"] else "not_expired_at_checkpoint"
    observed = {"wallet.journal": (wallet, files.MAX_WALLET), reconciliation.MARKER: (marker, files.MAX_MANIFEST)}
    if transaction is not None:
        observed["pending.tx"] = (transaction, reconciliation.MAX_PAYMENT)
    # Ordinary changes must not mix files from different observed generations.
    # Stopped writers/trusted host remain prerequisites; no atomic-snapshot claim.
    for name, (before, maximum) in observed.items():
        files.require(files.read_file(folder / name, maximum) == before, "view_source_changed")
    reconciliation.ledger.names(folder, expected)
    for name, (before, _) in observed.items():
        files.require(files.identity((folder / name).lstat()) == before[1], "view_source_changed")
    files.require(_chain(folder) == chain and files.identity(folder.lstat()) == root_stamp,
                  "view_directory_changed")
    return View(intent.report_sha256, intent.genesis_sha256, intent.checkpoint, report["height"],
                report["copy_receipt"], int(report["copy_receipt"][64:80], 16), len(wallet[0]),
                report["pending"], report["txid"], 0 if transaction is None else len(transaction[0]), expiry, relation)


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **dict(kwargs, allow_abbrev=False))

    def error(self, message):
        self.exit(64, "Invalid reconciliation-view arguments. Use --help; never supply secrets.\n")


def write_output(text: str) -> None:
    """The CLI's redirected output is UTF-8 even on legacy-codepage Windows.

    Text-only embedding streams retain their own policy. A failed/short write
    remains a failed call; consumers must also require normal exit status zero.
    """
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(text)
        return
    raw = (text + "\n").encode("utf-8")
    if stream.write(raw) != len(raw):
        raise OSError("incomplete_view_output")
    stream.flush()


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--genesis-sha256", required=True)
    parser.add_argument("--text", action="store_true", help="display Chinese explanation instead of JSON")
    args = parser.parse_args(argv)
    try:
        result = inspect(prepare({key: getattr(args, key) for key in FIELDS}))
        write_output(result.render() if args.text else json.dumps(result.summary(), sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print("Reconciliation view interrupted. Inputs retained; do not retry payment.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError):
        print("Reconciliation view failed. Inputs retained; do not re-sign or infer settlement.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
