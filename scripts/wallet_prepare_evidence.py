"""Fixed first-payment ENOSPC receipt checks; never decrypt or authorize a wallet.

The native test authenticates with WalletStore and real Orchard operations.
These independent public-byte checks only bind that test's retained evidence.
"""
from __future__ import annotations

from pathlib import Path
import re

CASES = {"wallet_prepare_enospc_rejects_partial_outbox_and_recovers": "source/wallet.journal"}
HEADER = 72
RECORD = 32948
PAGE = 4096
TMPFS_BYTES = 8 * 1024 * 1024
BEFORE = HEADER + 2 * RECORD
AFTER = ((BEFORE + PAGE - 1) // PAGE) * PAGE
FINAL = HEADER + 4 * RECORD
HEX = re.compile(r"[0-9a-f]{64}\Z")
TRUE_FIELDS = {
    "wallet_io", "store_unavailable", "no_payment_returned", "pool_unchanged_on_failure",
    "reopen_rejected", "source_prefix_preserved", "backup_unchanged", "empty_outbox_restored",
    "new_pending_exact", "duplicate_rejected", "continuation_done", "retained_receipts_unchanged",
}
INTEGERS = {
    "target_dev", "target_ino", "target_nlink", "before_len", "after_len", "frame_len",
    "changed_suffix_len", "receipt_generation", "pending_generation", "final_generation",
    "backup_len", "restored_len", "filler_errno", "filler_bytes",
}
HASHES = {
    "before_sha256", "after_sha256", "receipt_pin_sha256", "pending_pin_sha256",
    "final_pin_sha256", "backup_sha256", "restored_sha256",
}
FIELDS = TRUE_FIELDS | INTEGERS | HASHES | {
    "schema_version", "case", "profile", "filesystem", "target_rel", "real_funds_allowed",
}


def validate_receipt(receipt: dict, case: str) -> None:
    if (case not in CASES or type(receipt) is not dict or set(receipt) != FIELDS
            or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
            or receipt["case"] != case or receipt["target_rel"] != CASES[case]
            or receipt["profile"] != "wallet_prepare_v1" or receipt["filesystem"] != "tmpfs"):
        raise ValueError("unexpected_prepare_receipt")
    if (any(receipt[key] is not True for key in TRUE_FIELDS)
            or receipt["real_funds_allowed"] is not False):
        raise ValueError("prepare_invariant_not_confirmed")
    if any(type(receipt[key]) is not int or not 0 <= receipt[key] < 2**64 for key in INTEGERS):
        raise ValueError("invalid_prepare_integer")
    if any(type(receipt[key]) is not str or not HEX.fullmatch(receipt[key]) for key in HASHES):
        raise ValueError("invalid_prepare_digest")
    exact = dict(target_nlink=1, before_len=BEFORE, after_len=AFTER, frame_len=RECORD,
                 changed_suffix_len=AFTER - BEFORE, receipt_generation=2,
                 pending_generation=3, final_generation=4, backup_len=BEFORE,
                 restored_len=FINAL, filler_errno=28)
    if (any(receipt[key] != value for key, value in exact.items())
            or receipt["target_ino"] == 0 or not 0 < receipt["filler_bytes"] < TMPFS_BYTES
            or receipt["filler_bytes"] % PAGE
            or receipt["before_sha256"] != receipt["backup_sha256"]
            or len({receipt[key] for key in ("receipt_pin_sha256", "pending_pin_sha256", "final_pin_sha256")}) != 3):
        raise ValueError("invalid_prepare_relationship")


def verify_files(mount: Path, control: Path, receipt: dict, case: str, uid: int,
                 *, read_file, read_chain) -> None:
    """Use the harness's bounded identity readers, with no alternate trust path."""
    validate_receipt(receipt, case)
    device = control.stat().st_dev
    pins = []
    for name, field, generation in (("checkpoint.bin", "receipt_pin_sha256", 2),
                                    ("pending-checkpoint.bin", "pending_pin_sha256", 3),
                                    ("final-checkpoint.bin", "final_pin_sha256", 4)):
        path = control / name
        if path.resolve(strict=True) != path:
            raise ValueError("prepare_pin_path_changed")
        info, digest, raw = read_file(path, 72, capture=True)
        if (info.st_uid != uid or info.st_dev != device or info.st_size != 72
                or digest != receipt[field] or int.from_bytes(raw[32:40], "big") != generation):
            raise ValueError("prepare_pin_identity_mismatch")
        pins.append(raw)
    if not pins[0][:32] == pins[1][:32] == pins[2][:32]:
        raise ValueError("prepare_journal_identity_mismatch")
    info, digest, backup = read_chain(control / "backup/wallet.journal", pins[0], require_tip=True)
    if (info.st_uid != uid or info.st_dev != device or info.st_size != BEFORE
            or digest != receipt["backup_sha256"]):
        raise ValueError("prepare_backup_identity_mismatch")
    source = mount / CASES[case]
    if source.resolve(strict=True) != source:
        raise ValueError("prepare_source_path_changed")
    info, digest, damaged = read_file(source, TMPFS_BYTES, capture=True)
    if (info.st_uid != uid or info.st_dev != mount.stat().st_dev
            or info.st_dev != receipt["target_dev"] or info.st_ino != receipt["target_ino"]
            or info.st_nlink != 1 or info.st_size != AFTER or digest != receipt["after_sha256"]
            or damaged[:BEFORE] != backup or damaged[BEFORE:BEFORE + 8] != (3).to_bytes(8, "big")
            or damaged[BEFORE + 8:BEFORE + 40] != pins[0][40:]):
        raise ValueError("prepare_damaged_prefix_mismatch")
    # Bind both the recovered pending record AND the confirmed final record.
    # Hash-chain checks do not replace native AEAD/authorization verification.
    path = control / "restored/wallet.journal"
    first_identity = None
    for index, checkpoint in enumerate(pins):
        info, digest, restored = read_chain(path, checkpoint, require_tip=index == 2)
        identity = (info.st_dev, info.st_ino, info.st_size, digest)
        if (info.st_uid != uid or info.st_dev != device or info.st_size != FINAL
                or digest != receipt["restored_sha256"] or restored[:BEFORE] != backup
                or (first_identity is not None and identity != first_identity)):
            raise ValueError("prepare_restored_identity_mismatch")
        first_identity = identity
