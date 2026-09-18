#!/usr/bin/env python3
"""Prepare a byte-preserving, explicitly frozen P2 package evidence archive.

This author utility never judges stage acceptance, calls GitHub, executes a
downloaded artifact, modifies repository files, or rewrites an original. Its
only archive output is SCRATCH/handoff-draft/reports/. First inspect the fixed
specification, then supply a root-confirmed review lock after the real runtime
merge. Freeze records every admitted source file. Build rechecks the complete
freeze before writing any archive bytes. Existing different outputs are errors.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Any
from urllib.parse import parse_qsl, urlsplit
import zipfile


SCRATCH = Path(__file__).absolute().parent
REPOSITORY = SCRATCH.parent / "Zevune"
SPEC_PATH = SCRATCH / "evidence-spec.json"
FREEZE_PATH = SCRATCH / "evidence-freeze.json"
OUTPUT = SCRATCH / "handoff-draft"
PREFIX = "reports/p2-active-incremental-package-evidence"
MANIFEST_TARGET = "reports/p2-active-incremental-package-original-manifest.json"
MAX_BYTES = 16 * 1024 * 1024
ATTRIBUTES = b"* -text\n"
SPEC_FORMAT = "zevune-active-incremental-package-evidence-spec-1"
LOCK_FORMAT = "zevune-active-incremental-package-review-lock-1"
FREEZE_FORMAT = "zevune-active-incremental-package-evidence-freeze-1"
MANIFEST_FORMAT = "zevune-active-incremental-package-original-manifest-1"
BASE = "2cc87a2207d502ac5cfe00ea52e525c1516917e5"
CANDIDATES = {
    "c1": ("61c691270b91aece076177cb757e51e0e63fe310", "56dad7fdaad64b2b29ddac6b9585b8695aa465d7", "bd710cf4c985012ca23e86c333567ce116de72bb"),
    "c2": ("f51c8db240933256870ff03c07bc68915b4ac4a1", "7dd3f2fbf6ef5c13bffc2853bd09b6fa17a9c400", "aad3cfbb99350b2e8db1ac7abe718b5684a5ab1f"),
    "c3": ("cb0804e7c921a456cbbafab313b3a4a4501b8f5e", "21de343c12bc27cb1022ffd7ebd451abe0e61f29", "3dfa8d77921693b9e99af5b94af198498b9422e9"),
}
NATIVE_COUNTS = {"c1": (56, 22, 21), "c2": (62, 23, 23), "c3": (62, 23, 23)}
MERGE_PATHS = tuple(f"source-identities/{name}.json" for name in (
    "runtime-merge-result", "runtime-merged-pr", "runtime-git-commit",
    "runtime-main-branch", "runtime-merge-receipt",
))
READ_REPORTS = tuple(sorted([
    "design-review.md", "design-storage-review.md", "native-expectation.md",
    *(f"{c}-{part}.md" for c in CANDIDATES for part in (
        "code-review", "storage-review", "native-review", "native-nonrust-review")),
]))
LOCKED_PATHS = frozenset([
    *READ_REPORTS, *MERGE_PATHS,
    *(f"{c}-{part}.json" for c in CANDIDATES for part in (
        "native-review", "native-nonrust-review", "native-original-manifest")),
])
OMITTED_PAYLOADS = frozenset(
    f"payloads/{c}-operator-{platform}.zip"
    for c in ("c2", "c3") for platform in ("linux", "windows")
)


class ArchiveError(Exception):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def identity(raw: bytes) -> dict[str, Any]:
    return {"bytes": len(raw), "sha256": digest(raw)}


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=no_duplicate_keys)
    except (UnicodeError, ValueError) as error:
        raise ArchiveError(f"invalid JSON: {label}") from error


def relative(value: str) -> str:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise ArchiveError("noncanonical evidence path")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(x in (".", "..") for x in path.parts):
        raise ArchiveError(f"noncanonical evidence path: {value}")
    return value


def components(path: Path) -> None:
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ArchiveError(f"symlinked evidence path component: {part}")


def stamp(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def raw_file(path: Path) -> bytes:
    components(path)
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise ArchiveError(f"required file is missing: {path}") from error
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise ArchiveError(f"not an admitted bounded regular file: {path}")
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if stamp(opened) != stamp(before):
            raise ArchiveError(f"source changed before read: {path}")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(raw) != before.st_size or stamp(after) != stamp(before) or stamp(path.lstat()) != stamp(before):
        raise ArchiveError(f"source changed while reading: {path}")
    return raw


def reject_sensitive(raw: bytes, label: str) -> None:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise ArchiveError(f"non-UTF-8 content outside explicitly admitted resource ZIPs: {label}") from error
    if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
        raise ArchiveError(f"private-key marker in evidence: {label}")
    if re.search(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b", text):
        raise ArchiveError(f"unmasked credential-shaped value in evidence: {label}")
    for match in re.finditer(r"https?://[^\s<>\"']+", text.replace("\\/", "/")):
        try:
            query = parse_qsl(urlsplit(match.group()).query, keep_blank_values=True)
        except ValueError:
            continue
        if any(key.lower() in {"sig", "signature", "x-amz-signature", "x-goog-signature", "access_token"} and value not in {"", "***"} for key, value in query):
            raise ArchiveError(f"signed or credential-bearing URL in evidence: {label}")


def load_spec() -> tuple[dict[str, Any], bytes]:
    raw = raw_file(SPEC_PATH)
    spec = parse_json(raw, SPEC_PATH.name)
    if spec.get("format") != SPEC_FORMAT or not isinstance(spec.get("files"), list):
        raise ArchiveError("invalid explicit evidence specification")
    paths: set[str] = set()
    for row in spec["files"]:
        if set(row) != {"path", "kind", "representation"}:
            raise ArchiveError("specification file entry has unexpected keys")
        path = relative(row["path"])
        if path in paths or path.startswith(("payloads/", "carriers/", "handoff-draft/")) or "upload" in path:
            raise ArchiveError(f"duplicate or forbidden fixed source path: {path}")
        if "/" in path and not path.startswith("source-identities/"):
            raise ArchiveError(f"fixed source path is outside the stage allowlist: {path}")
        paths.add(path)
    if not LOCKED_PATHS.issubset(paths):
        raise ArchiveError("specification omits a required frozen original")
    if spec.get("native_manifests") != [f"{c}-native-original-manifest.json" for c in CANDIDATES]:
        raise ArchiveError("unexpected native manifest list")
    return spec, raw


def verify_identity(raw: bytes, expected: Any, label: str) -> None:
    if not isinstance(expected, dict) or set(expected) != {"bytes", "sha256"} or type(expected["bytes"]) is not int or re.fullmatch(r"[0-9a-f]{64}", str(expected["sha256"])) is None:
        raise ArchiveError(f"invalid frozen identity: {label}")
    if identity(raw) != expected:
        raise ArchiveError(f"frozen bytes/SHA-256 mismatch: {label}")


def load_lock(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.parent != SCRATCH:
        raise ArchiveError("review lock must be an explicit file directly in this stage scratch")
    raw = raw_file(path)
    lock = parse_json(raw, path.name)
    if set(lock) != {"format", "confirmed_by", "runtime_merge_sha", "runtime_merge_tree", "read_original_reports", "frozen_files"}:
        raise ArchiveError("review lock has unexpected or missing keys; a template is not confirmation")
    if lock["format"] != LOCK_FORMAT or lock["confirmed_by"] != "/root":
        raise ArchiveError("review lock lacks the author's explicit root confirmation")
    if sorted(lock["read_original_reports"]) != list(READ_REPORTS):
        raise ArchiveError("review lock must identify all 15 root-read original reports")
    if set(lock["frozen_files"]) != LOCKED_PATHS:
        raise ArchiveError("review lock must freeze exactly the 29 required report/manifest/merge records")
    if re.fullmatch(r"[0-9a-f]{40}", str(lock["runtime_merge_sha"])) is None or lock["runtime_merge_tree"] != CANDIDATES["c3"][1]:
        raise ArchiveError("review lock does not identify an actual merge of the accepted runtime tree")
    for rel, expected in sorted(lock["frozen_files"].items()):
        verify_identity(raw_file(SCRATCH / rel), expected, rel)
    return lock, raw


def native_kind(rel: str) -> tuple[str, str]:
    name = PurePosixPath(rel).name
    if name == "runs.json":
        return "github_actions_complete_workflow_runs_page", "connector_decoded_utf8_original"
    if re.fullmatch(r"(?:run|jobs|artifacts)-[0-9]+\.json", name):
        return "github_actions_complete_" + name.split("-")[0] + "_api_record", "connector_decoded_utf8_original"
    if re.fullmatch(r"job-[0-9]+\.log", name):
        return "github_actions_complete_job_log", "connector_decoded_utf8_original"
    if re.fullmatch(r"payment-resources-(?:ubuntu|windows)\.zip", name):
        return "github_downloaded_complete_resource_zip", "downloaded_artifact_original_bytes"
    if re.fullmatch(r"payment-resources-(?:ubuntu|windows)-(?:setup|result)\.json", name):
        return "github_resource_zip_member", "extracted_member_original_bytes"
    if re.fullmatch(r"operator-(?:linux|windows)-manifest\.json", name):
        return "github_operator_zip_manifest_member_only", "extracted_member_original_bytes"
    raise ArchiveError(f"unknown path in native manifest: {rel}")


def expand_native(selected: dict[str, dict[str, str]], source: dict[str, bytes]) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for candidate, (file_count, job_count, log_count) in NATIVE_COUNTS.items():
        manifest_name = f"{candidate}-native-original-manifest.json"
        manifest = parse_json(source[manifest_name], manifest_name)
        rows = manifest.get("files")
        if not isinstance(rows, list) or len(rows) != file_count:
            raise ArchiveError(f"incomplete frozen native inventory: {candidate}")
        admitted: set[str] = set()
        for row in rows:
            rel = relative(row["path"])
            if not rel.startswith(f"{candidate}-native/") or len(PurePosixPath(rel).parts) != 2 or rel in admitted:
                raise ArchiveError(f"duplicate or out-of-scope native original: {rel}")
            kind, representation = native_kind(rel)
            raw = raw_file(SCRATCH / rel)
            verify_identity(raw, {"bytes": row["bytes"], "sha256": row["sha256"]}, rel)
            selected[rel] = {"path": rel, "kind": kind, "representation": representation}
            source[rel] = raw
            admitted.add(rel)
        directory = SCRATCH / f"{candidate}-native"
        actual = {str(path.relative_to(SCRATCH)) for path in directory.rglob("*") if path.is_file() or path.is_symlink()}
        if actual != admitted:
            raise ArchiveError(f"native directory differs from its explicit frozen inventory: {candidate}")
        runs = parse_json(source[f"{candidate}-native/runs.json"], candidate)["workflow_runs"]
        runs_page = parse_json(source[f"{candidate}-native/runs.json"], candidate)
        if runs_page["total_count"] != 10 or len(runs) != 10 or len({r["id"] for r in runs}) != 10:
            raise ArchiveError(f"native run page is incomplete: {candidate}")
        jobs_seen: set[int] = set()
        with_logs: set[int] = set()
        zero_step_omissions: list[int] = []
        expected_paths = {f"{candidate}-native/runs.json"}
        for listed in runs:
            run_id = listed["id"]
            names = {part: f"{candidate}-native/{part}-{run_id}.json" for part in ("run", "jobs", "artifacts")}
            expected_paths.update(names.values())
            for run in (listed, parse_json(source[names["run"]], names["run"])):
                if run["id"] != run_id or run["head_sha"] != CANDIDATES[candidate][0] or run["event"] != "pull_request" or run["run_attempt"] != 1 or run["status"] != "completed" or not run["conclusion"]:
                    raise ArchiveError(f"native run identity/terminal state mismatch: {candidate}/{run_id}")
            page = parse_json(source[names["jobs"]], names["jobs"])
            if page["total_count"] != len(page["jobs"]):
                raise ArchiveError(f"incomplete jobs page: {candidate}/{run_id}")
            artifact_page = parse_json(source[names["artifacts"]], names["artifacts"])
            if artifact_page["total_count"] != len(artifact_page["artifacts"]):
                raise ArchiveError(f"incomplete artifact page: {candidate}/{run_id}")
            for job in page["jobs"]:
                job_id = job["id"]
                if job_id in jobs_seen or job["run_id"] != run_id or job["head_sha"] != CANDIDATES[candidate][0] or job["run_attempt"] != 1 or job["status"] != "completed" or not job["conclusion"]:
                    raise ArchiveError(f"native job identity/terminal state mismatch: {candidate}/{job_id}")
                jobs_seen.add(job_id)
                log = f"{candidate}-native/job-{job_id}.log"
                if job["steps"]:
                    if log not in admitted:
                        raise ArchiveError(f"executed native job has no complete retained log: {job_id}")
                    expected_paths.add(log)
                    with_logs.add(job_id)
                elif candidate == "c1" and job["conclusion"] == "skipped" and job["name"] == "growth" and job.get("runner_id") is None and log not in admitted:
                    zero_step_omissions.append(job_id)
                else:
                    raise ArchiveError(f"unexpected native job without steps: {candidate}/{job_id}")
        api_log_paths = {rel for rel in admitted if PurePosixPath(rel).name == "runs.json" or re.fullmatch(r"(?:run|jobs|artifacts)-[0-9]+\.json|job-[0-9]+\.log", PurePosixPath(rel).name)}
        if expected_paths != api_log_paths or len(jobs_seen) != job_count or len(with_logs) != log_count or len(zero_step_omissions) != (1 if candidate == "c1" else 0):
            raise ArchiveError(f"native file/run/job/log coverage mismatch: {candidate}")
        observed[candidate] = {"files": len(admitted), "runs": len(runs), "jobs": len(jobs_seen), "logs": len(with_logs), "zero_step_job_logs_intentionally_absent": zero_step_omissions}
    return observed


def validate_merge(lock: dict[str, Any], source: dict[str, bytes]) -> None:
    parent = BASE
    for candidate, (head, tree, synthetic) in CANDIDATES.items():
        commit = parse_json(source[f"source-identities/{candidate}-git-commit.json"], candidate)
        checkout = parse_json(source[f"source-identities/{candidate}-synthetic-git-commit.json"], candidate)
        if commit["sha"] != head or commit["tree"]["sha"] != tree or [x["sha"] for x in commit["parents"]] != [parent]:
            raise ArchiveError(f"source candidate identity mismatch: {candidate}")
        if checkout["sha"] != synthetic or checkout["tree"]["sha"] != tree or [x["sha"] for x in checkout["parents"]] != [BASE, head]:
            raise ArchiveError(f"synthetic checkout identity mismatch: {candidate}")
        parent = head
    merge_sha = lock["runtime_merge_sha"]
    commit = parse_json(source["source-identities/runtime-git-commit.json"], "runtime git commit")
    pr = parse_json(source["source-identities/runtime-merged-pr.json"], "runtime merged PR")
    branch = parse_json(source["source-identities/runtime-main-branch.json"], "runtime main branch")
    result = parse_json(source["source-identities/runtime-merge-result.json"], "runtime merge result")
    if commit["sha"] != merge_sha or commit["tree"]["sha"] != CANDIDATES["c3"][1] or [x["sha"] for x in commit["parents"]] != [BASE, CANDIDATES["c3"][0]]:
        raise ArchiveError("actual runtime merge does not preserve the accepted candidate tree and ordered parents")
    if pr["number"] != 17 or pr["merged"] is not True or pr["merge_commit_sha"] != merge_sha or pr["head"]["sha"] != CANDIDATES["c3"][0]:
        raise ArchiveError("actual merged PR original disagrees with runtime identity")
    if branch["name"] != "main" or branch["commit"]["sha"] != merge_sha:
        raise ArchiveError("actual post-merge main branch original disagrees with runtime identity")
    if result.get("merged") is not True or result.get("sha", result.get("merge_commit_sha")) != merge_sha:
        raise ArchiveError("actual merge tool result disagrees with runtime identity")


def check_resource_zips(source: dict[str, bytes]) -> None:
    for candidate in CANDIDATES:
        for platform in ("ubuntu", "windows"):
            prefix = f"{candidate}-native/payment-resources-{platform}"
            expected = {"payment-resource-setup.json": source[prefix + "-setup.json"]}
            if candidate != "c1":
                expected["payment-resources.json"] = source[prefix + "-result.json"]
            with zipfile.ZipFile(io.BytesIO(source[prefix + ".zip"])) as archive:
                if sorted(archive.namelist()) != sorted(expected) or any(x.file_size > MAX_BYTES or x.is_dir() for x in archive.infolist()):
                    raise ArchiveError(f"resource ZIP has an unexpected member set: {prefix}")
                for name, raw in expected.items():
                    if archive.read(name) != raw:
                        raise ArchiveError(f"resource ZIP member differs from retained original: {prefix}/{name}")


def omitted_operator_records(source: dict[str, bytes]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for candidate in ("c2", "c3"):
        name = f"{candidate}-operator-download-observation.json"
        observed = parse_json(source[name], name)
        if candidate == "c2":
            rows = observed["files"]
        else:
            rows = [{
                "path": row["zip_path"], "bytes": row["zip_bytes"], "sha256": row["zip_sha256"],
                "manifest_path": row["manifest"]["path"], "manifest_bytes": row["manifest"]["bytes"],
                "manifest_sha256": row["manifest"]["sha256"], "artifact_id": row["artifact_id"],
            } for row in observed["artifacts"]]
        if len(rows) != 2:
            raise ArchiveError(f"incomplete operator download observation: {candidate}")
        artifact_path = f"{candidate}-native/artifacts-{35362925534 if candidate == 'c2' else 35363727265}.json"
        artifacts = parse_json(source[artifact_path], artifact_path)["artifacts"]
        for row in rows:
            if row["path"] not in OMITTED_PAYLOADS or not row["path"].startswith(f"payloads/{candidate}-"):
                raise ArchiveError("unapproved omitted operator payload path")
            verify_identity(source[row["manifest_path"]], {"bytes": row["manifest_bytes"], "sha256": row["manifest_sha256"]}, row["manifest_path"])
            platform = "Windows" if row["path"].endswith("-windows.zip") else "Linux"
            metadata = [item for item in artifacts if item["name"] == f"zevune-local-lab-{platform}"]
            if len(metadata) != 1 or metadata[0]["size_in_bytes"] != row["bytes"] or metadata[0]["digest"] != "sha256:" + row["sha256"] or ("artifact_id" in row and metadata[0]["id"] != row["artifact_id"]):
                raise ArchiveError(f"omitted ZIP observation does not match complete original artifact metadata: {row['path']}")
            result.append({
                "source_relative_to_scratch": row["path"], "bytes": row["bytes"], "sha256": row["sha256"],
                "artifact_id": metadata[0]["id"], "retained_artifact_metadata": f"{PREFIX}/{artifact_path}",
                "archived": False, "executed_by_collector": False,
                "scope": "Complete operator ZIP is deliberately not copied into the repository; exact manifest, Actions artifact metadata, author download observation and independent payload verification report are retained. The collector does not repeat or certify the independent payload audit.",
                "retained_manifest": f"{PREFIX}/{row['manifest_path']}",
                "download_observation": f"{PREFIX}/{name}",
                "independent_payload_verification": f"{PREFIX}/{candidate}-operator-independent-review.json",
            })
    if {r["source_relative_to_scratch"] for r in result} != OMITTED_PAYLOADS:
        raise ArchiveError("operator omission inventory is incomplete")
    return result


REFERENCE_PATTERN = re.compile(r"(?<![A-Za-z0-9_.-])(?:source-identities/|payloads/|carriers/)?(?:c[123]-[A-Za-z0-9_./-]+|design-[A-Za-z0-9_./-]+|native-[A-Za-z0-9_./-]+|rust-parser-[A-Za-z0-9_./-]+|audit_[A-Za-z0-9_./-]+|native_audit_[A-Za-z0-9_./-]+|finalize_[A-Za-z0-9_./-]+|runtime-[A-Za-z0-9_./-]+|base-git-commit|initial-main-branch)\.(?:md|json|log|patch|diff|py|zip)(?![A-Za-z0-9_.-])")


def reference_closure(spec: dict[str, Any], selected: dict[str, dict[str, str]], source: dict[str, bytes]) -> dict[str, Any]:
    by_name: dict[str, list[str]] = {}
    for rel in selected:
        by_name.setdefault(PurePosixPath(rel).name, []).append(rel)
    exceptions = spec.get("historical_reference_exceptions", {})
    edges: set[tuple[str, str, str]] = set()
    pins: set[tuple[str, str, int, str]] = set()
    markdown_pins: set[tuple[str, str, int | None, str]] = set()

    def resolve(ref: str, origin: str) -> list[str]:
        ref = ref.removeprefix(str(SCRATCH) + "/")
        if ref in selected:
            return [ref]
        if ref in OMITTED_PAYLOADS:
            edges.add((origin, ref, "explicit_operator_zip_omission"))
            return []
        if ref in exceptions:
            edges.add((origin, ref, "documented_historical_method_reference"))
            return []
        if ref in by_name:
            return by_name[ref]
        if (REPOSITORY / ref).is_file():
            edges.add((origin, ref, "repository_source_reference_not_duplicated"))
            return []
        raise ArchiveError(f"unresolved in-stage evidence reference in {origin}: {ref}")

    def walk(value: Any, origin: str) -> None:
        if isinstance(value, dict):
            for key in ("path", "file", "source_relative_to_scratch"):
                ref = value.get(key)
                if isinstance(ref, str) and "bytes" in value and "sha256" in value:
                    targets = [ref] if ref in selected else by_name.get(ref, [])
                    if len(targets) == 1:
                        target = targets[0]
                        verify_identity(source[target], {"bytes": value["bytes"], "sha256": value["sha256"]}, f"{origin} -> {target}")
                        pins.add((origin, target, value["bytes"], value["sha256"]))
            for item in value.values():
                walk(item, origin)
        elif isinstance(value, list):
            for item in value:
                walk(item, origin)

    for rel, row in selected.items():
        if not row["kind"].startswith(("reviewer_", "author_native_", "author_operator_", "author_formatter_")):
            continue
        text = source[rel].decode("utf-8")
        for match in REFERENCE_PATTERN.finditer(text):
            for target in resolve(match.group(), rel):
                edges.add((rel, target, "retained_stage_evidence"))
        if rel.endswith(".json"):
            walk(parse_json(source[rel], rel), rel)
        elif rel.endswith(".md"):
            for line in text.splitlines():
                matches = list(REFERENCE_PATTERN.finditer(line))
                for index, match in enumerate(matches):
                    ref = match.group()
                    targets = [ref] if ref in selected else by_name.get(ref, [])
                    if len(targets) != 1:
                        continue
                    suffix = line[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(line)]
                    declared_hashes = re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", suffix)
                    if len(declared_hashes) != 1:
                        continue
                    target = targets[0]
                    declared_hash = declared_hashes[0]
                    if digest(source[target]) != declared_hash:
                        raise ArchiveError(f"Markdown report's explicit file SHA-256 disagrees with retained bytes: {rel} -> {target}")
                    count = re.search(r"(?<![A-Za-z0-9])([0-9][0-9,]*)\s*(?:bytes|字节|B)(?![A-Za-z])", suffix)
                    if count is None:
                        count = re.search(r"^\s*`?\s*\|\s*([0-9][0-9,]*)\s*\|", suffix)
                    declared_bytes = int(count.group(1).replace(",", "")) if count else None
                    if declared_bytes is not None and len(source[target]) != declared_bytes:
                        raise ArchiveError(f"Markdown report's explicit file byte count disagrees with retained bytes: {rel} -> {target}")
                    markdown_pins.add((rel, target, declared_bytes, declared_hash))
    return {
        "scope": "Closure of explicit stage-evidence filename references in retained reviewer reports/derived records and author native/operator/formatter records, matching structured path/bytes/SHA pins and unambiguous Markdown filename/SHA/byte-count pins; repository source citations and artifact-internal generic member names are not claims of duplicated source files. Raw GitHub records, full job logs and helper source literals are not treated as evidence-reference catalogues.",
        "edges": [{"from": a, "to": b, "disposition": c} for a, b, c in sorted(edges)],
        "verified_structured_identity_pins": [{"from": a, "to": b, "bytes": c, "sha256": d} for a, b, c, d in sorted(pins)],
        "verified_markdown_identity_pins": [{"from": a, "to": b, "declared_bytes": c, "sha256": d} for a, b, c, d in sorted(markdown_pins, key=lambda row: (row[0], row[1], -1 if row[2] is None else row[2], row[3]))],
    }


def collection(lock: dict[str, Any], lock_raw: bytes, lock_name: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    spec, spec_raw = load_spec()
    selected = {row["path"]: row for row in spec["files"]}
    source = {rel: raw_file(SCRATCH / rel) for rel in selected}
    if source.get(SPEC_PATH.name) != spec_raw:
        raise ArchiveError("the fixed specification itself must be retained unchanged")
    for rel, expected in lock["frozen_files"].items():
        verify_identity(source[rel], expected, rel)
    native = expand_native(selected, source)
    validate_merge(lock, source)
    for rel, raw in source.items():
        if not rel.endswith(".zip"):
            reject_sensitive(raw, rel)
    check_resource_zips(source)
    omissions = omitted_operator_records(source)
    references = reference_closure(spec, selected, source)
    entries = [{**selected[rel], **identity(source[rel]), "source_absolute_at_capture": str(SCRATCH / rel), "target": f"{PREFIX}/{rel}"} for rel in sorted(selected)]
    snapshot = {
        "format": FREEZE_FORMAT,
        "scope": "author_explicit_byte_preserving_collection_not_independent_acceptance",
        "acceptance": "not_evaluated_by_collector",
        "source_scratch_at_capture": str(SCRATCH),
        "runtime_source": CANDIDATES["c3"][0], "runtime_tree": CANDIDATES["c3"][1],
        "runtime_merge_sha": lock["runtime_merge_sha"],
        "review_lock": {"path": lock_name, **identity(lock_raw), "confirmed_by": lock["confirmed_by"], "root_read_original_reports": lock["read_original_reports"]},
        "native_inventory": native,
        "entries": entries,
        "retained_file_count": len(entries),
        "retained_bytes": sum(e["bytes"] for e in entries),
        "representation_counts": dict(sorted(Counter(e["representation"] for e in entries).items())),
        "operator_archives_not_copied": omissions,
        "reference_closure": references,
        "intentional_exclusions": spec["intentional_exclusions"],
    }
    return snapshot, source


def install(path: Path, raw: bytes) -> None:
    components(path)
    if path.exists():
        if raw_file(path) != raw:
            raise ArchiveError(f"refusing to overwrite a differing output: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    components(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".package-evidence-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o644)
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if raw_file(path) != raw:
                raise ArchiveError(f"concurrent differing output appeared: {path}")
        if raw_file(path) != raw:
            raise ArchiveError(f"published output differs from original: {path}")
    finally:
        temporary_path.unlink(missing_ok=True)


def build(snapshot: dict[str, Any], source: dict[str, bytes], freeze_raw: bytes) -> dict[str, Any]:
    retained = {row["target"]: source[row["path"]] for row in snapshot["entries"]}
    retained[f"{PREFIX}/.gitattributes"] = ATTRIBUTES
    manifest = {**snapshot, "format": MANIFEST_FORMAT,
        "archive_state": "complete_frozen_inventory_not_acceptance",
        "manifest_scope": "This author-generated manifest does not hash itself; retained originals are copied byte for byte, including original BOM/CRLF. Original reports keep their historical verdicts and original absolute scratch references; each entry maps those paths to the repository archive.",
        "freeze_source": {"path": FREEZE_PATH.name, **identity(freeze_raw)},
        "configuration_not_counted_as_retained_source": [{"target": f"{PREFIX}/.gitattributes", "kind": "author_git_text_conversion_configuration", **identity(ATTRIBUTES)}],
    }
    retained[MANIFEST_TARGET] = json_bytes(manifest)
    evidence = OUTPUT / PREFIX
    components(evidence)
    if evidence.exists():
        actual = {str(path.relative_to(OUTPUT)) for path in evidence.rglob("*") if path.is_file() or path.is_symlink()}
        if not actual.issubset(retained):
            raise ArchiveError("archive output already contains files outside the frozen allowlist")
    for rel, raw in retained.items():
        target = OUTPUT / rel
        components(target)
        if target.exists() and raw_file(target) != raw:
            raise ArchiveError(f"preflight found a differing existing output: {rel}")
    for rel, raw in retained.items():
        install(OUTPUT / rel, raw)
    for rel, raw in retained.items():
        if raw_file(OUTPUT / rel) != raw:
            raise ArchiveError(f"final copied-byte comparison failed: {rel}")
    actual = {str(path.relative_to(OUTPUT)) for path in evidence.rglob("*") if path.is_file() or path.is_symlink()}
    if actual != {rel for rel in retained if rel.startswith(PREFIX + "/")}:
        raise ArchiveError("final archive path set differs from its frozen allowlist")
    return {"status": "ARCHIVE_COPIED_AND_BYTES_VERIFIED_NOT_ACCEPTANCE", "output": str(OUTPUT), "archive_file_count": len(retained), "retained_source_count": snapshot["retained_file_count"], "retained_source_bytes": snapshot["retained_bytes"], "manifest": {"path": str(OUTPUT / MANIFEST_TARGET), **identity(retained[MANIFEST_TARGET])}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "lock-template", "freeze", "verify", "build"))
    parser.add_argument("--review-lock", type=Path)
    parser.add_argument("--template-output", type=Path)
    args = parser.parse_args()
    spec, _ = load_spec()
    if args.mode == "inspect":
        missing = [row["path"] for row in spec["files"] if not (SCRATCH / row["path"]).is_file()]
        print(json.dumps({"status": "SPECIFICATION_ONLY_NOT_FROZEN", "fixed_paths": len(spec["files"]), "native_manifests": spec["native_manifests"], "native_expected_file_counts": {c: row[0] for c, row in NATIVE_COUNTS.items()}, "required_review_lock_paths": sorted(LOCKED_PATHS), "missing_fixed_files": missing, "repo_modified": False}, ensure_ascii=False, indent=2))
        return
    if args.mode == "lock-template":
        frozen: dict[str, Any] = {}
        missing: list[str] = []
        for rel in sorted(LOCKED_PATHS):
            if (SCRATCH / rel).is_file():
                frozen[rel] = identity(raw_file(SCRATCH / rel))
            else:
                missing.append(rel)
        template = {"format": LOCK_FORMAT, "confirmed_by": "REQUIRES_ROOT_CONFIRMATION", "runtime_merge_sha": None, "runtime_merge_tree": CANDIDATES["c3"][1], "read_original_reports": [], "frozen_files": frozen, "missing": missing}
        raw = json_bytes(template)
        if args.template_output:
            destination = args.template_output.absolute()
            if destination.parent != SCRATCH:
                raise ArchiveError("template output must stay directly in stage scratch")
            install(destination, raw)
            print(json.dumps({"status": "UNCONFIRMED_TEMPLATE_ONLY", "path": str(destination), **identity(raw), "missing": missing}, ensure_ascii=False, indent=2))
        else:
            print(raw.decode(), end="")
        return
    if not args.review_lock:
        raise ArchiveError("freeze/verify/build requires an explicit root-confirmed --review-lock")
    lock_path = args.review_lock.absolute()
    lock, lock_raw = load_lock(lock_path)
    snapshot, source = collection(lock, lock_raw, lock_path.name)
    fresh_raw = json_bytes(snapshot)
    if args.mode == "freeze":
        install(FREEZE_PATH, fresh_raw)
        print(json.dumps({"status": "SOURCE_SET_FROZEN_NOT_ACCEPTANCE", "path": str(FREEZE_PATH), **identity(fresh_raw), "retained_file_count": snapshot["retained_file_count"], "retained_bytes": snapshot["retained_bytes"], "native_inventory": snapshot["native_inventory"]}, ensure_ascii=False, indent=2))
        return
    freeze_raw = raw_file(FREEZE_PATH)
    if freeze_raw != fresh_raw:
        raise ArchiveError("current complete source inventory differs from the immutable freeze")
    if args.mode == "verify":
        print(json.dumps({"status": "ALL_FROZEN_INPUT_BYTES_AND_REFERENCES_VERIFIED_NOT_ACCEPTANCE", "retained_file_count": snapshot["retained_file_count"], "retained_bytes": snapshot["retained_bytes"]}, ensure_ascii=False, indent=2))
        return
    print(json.dumps(build(snapshot, source, freeze_raw), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ArchiveError, KeyError, TypeError, zipfile.BadZipFile, OSError) as error:
        print(f"EVIDENCE_ARCHIVE_BLOCKED: {error}", file=sys.stderr)
        raise SystemExit(2)
