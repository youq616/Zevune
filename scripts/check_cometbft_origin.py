#!/usr/bin/env python3
"""Verify the explicit local CometBFT lifetime patch; never fetch or patch code."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

from source_snapshot import _check_path

MODULE = "github.com/cometbft/cometbft"
VERSION = "v0.38.26"
ORIGIN_COMMIT = "94d77f9f51a72e2b7d832798859f6222f08028f8"
BASELINE_MANIFEST_SHA = "82d320cf1c701ea282ae928d4f91c1c0c6b7213004349796d8a042c453f28955"
MODULE_H1 = "h1:MIPYgOSvyyiN1jo3SZljKy4ZXqs896aQnj3pQFfUmaE="
MOD_H1 = "h1:mDrAs+NMp7gc2ExoTE2/S6lDMespxaEc2Nd2BvDbbmM="
VENDOR = Path("integration/cometbft/third_party/cometbft-v0.38.26")
PROVENANCE = Path("integration/cometbft/third_party/cometbft-origin")
RUNTIME_PATCH = "consensus/reactor.go"
NEW_TESTS = frozenset(("consensus/reactor_shutdown_test.go", "node/node_shutdown_order_test.go", "p2p/conn/send_shutdown_bound_test.go"))
HEX = re.compile(r"[0-9a-f]{64}\Z")

class OriginError(ValueError):
    pass

def require(value: bool, label: str) -> None:
    if not value:
        raise OriginError(label)

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def hash1(entries: dict[str, str]) -> str:
    summary = "".join(f"{entries[name]}  {name}\n" for name in sorted(entries))
    return "h1:" + base64.b64encode(hashlib.sha256(summary.encode()).digest()).decode()

def pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_metadata_key")
        result[key] = value
    return result

def load(path: Path):
    require(path.stat().st_size <= 1024 * 1024, "oversize_metadata")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs_no_duplicates)

def regular(path: Path) -> None:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), "nonregular_source")
    require(not (getattr(info, "st_file_attributes", 0) & 0x400), "source_reparse_point")
    if os.name != "nt":
        require(not (info.st_mode & 0o111), "unexpected_executable_source")

def verify_files(root: Path) -> dict:
    root = root.resolve(strict=True)
    vendor, provenance = root / VENDOR, root / PROVENANCE
    for target in (VENDOR, PROVENANCE):
        parent = root
        for part in target.parts:
            parent = parent / part
            info = parent.lstat()
            require(stat.S_ISDIR(info.st_mode) and not parent.is_symlink() and not (getattr(info, "st_file_attributes", 0) & 0x400), "invalid_dependency_directory")
    for name in ("complete-upstream-manifest.json", "retained-manifest.json", "omitted-docs-manifest.json", "origin.json", "patch.json", "lifetime.patch"):
        regular(provenance / name)
    require(digest((provenance / "complete-upstream-manifest.json").read_bytes()) == BASELINE_MANIFEST_SHA, "origin_manifest_digest_mismatch")
    original = load(provenance / "complete-upstream-manifest.json")
    require(isinstance(original, list) and len(original) == 1409, "invalid_origin_inventory")
    baseline, spellings, paths = {}, {}, set()
    for item in original:
        require(isinstance(item, dict) and set(item) == {"path", "size", "sha256", "archive_mode", "retain"}, "invalid_origin_entry")
        name = item["path"]
        require(isinstance(name, str) and name not in baseline, "duplicate_origin_path")
        _check_path(name, spellings, paths)
        require(type(item["size"]) is int and 0 <= item["size"] <= 64 * 1024 * 1024, "invalid_origin_size")
        require(isinstance(item["sha256"], str) and bool(HEX.fullmatch(item["sha256"])), "invalid_origin_digest")
        require(item["archive_mode"] == "0o0" and item["retain"] == (not name.startswith("docs/")), "invalid_origin_partition")
        baseline[name] = item
    require(hash1({f"{MODULE}@{VERSION}/{p}": x["sha256"] for p, x in baseline.items()}) == MODULE_H1, "origin_hash_mismatch")
    require(hash1({"go.mod": baseline["go.mod"]["sha256"]}) == MOD_H1, "origin_module_hash_mismatch")
    retained = [x for x in original if x["retain"]]
    omitted = [x for x in original if not x["retain"]]
    require(len(retained) == 1019 and len(omitted) == 390, "origin_partition_count")
    require(load(provenance / "retained-manifest.json") == retained and load(provenance / "omitted-docs-manifest.json") == omitted, "origin_partition_mismatch")
    origin = load(provenance / "origin.json")
    require(origin == {"module": MODULE, "version": VERSION, "git_commit": ORIGIN_COMMIT, "tag_object": "2228c7101a00994a14811e15cd8795c7e70713c2", "module_h1": MODULE_H1, "go_mod_h1": MOD_H1, "zip_sha256": "3d0996fbaa4b13bc940807b157f93f4e362296c7e5e5ecc6c734ed27e04b4f13", "source_url": "https://github.com/cometbft/cometbft", "materialized_git_mode": "100644"}, "origin_identity_mismatch")
    patch = load(provenance / "patch.json")
    require(set(patch) == {"runtime", "added_tests", "patch_sha256"} and set(patch["runtime"]) == {RUNTIME_PATCH} and set(patch["added_tests"]) == NEW_TESTS, "unapproved_patch_scope")
    changed = dict(patch["runtime"], **patch["added_tests"])
    require(all(isinstance(h, str) and HEX.fullmatch(h) for h in changed.values()), "invalid_patch_digest")
    raw_patch = (provenance / "lifetime.patch").read_bytes()
    require(len(raw_patch) <= 512 * 1024 and digest(raw_patch) == patch["patch_sha256"], "patch_digest_mismatch")
    expected = {x["path"] for x in retained} | NEW_TESTS
    found, spellings, paths = set(), {}, set()
    for current, dirs, files in os.walk(vendor, followlinks=False):
        for directory in dirs:
            p = Path(current) / directory
            info = p.lstat()
            require(stat.S_ISDIR(info.st_mode) and not p.is_symlink() and not (getattr(info, "st_file_attributes", 0) & 0x400), "invalid_source_directory")
        for name in files:
            p = Path(current) / name
            rel = p.relative_to(vendor).as_posix()
            _check_path(rel, spellings, paths)
            regular(p)
            require(rel in expected, "extra_dependency_source")
            found.add(rel)
            want = changed.get(rel, baseline.get(rel, {}).get("sha256"))
            require(digest(p.read_bytes()) == want, "dependency_source_digest_mismatch")
    require(found == expected, "missing_dependency_source")
    # Reverse exactly the reviewed patch in disposable files and bind every
    # original runtime byte to the complete h1-anchored origin manifest.
    with tempfile.TemporaryDirectory(prefix="zevune-cometbft-origin-") as tmp:
        staged = Path(tmp)
        for rel in changed:
            p = staged / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(vendor / rel, p)
        # This disposable directory has no repository attributes. Keep reverse
        # application byte-exact even when the host enables Windows CRLF output.
        git_apply = ["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "apply"]
        result = subprocess.run([*git_apply, "--reverse", "--check", "--whitespace=error", "-"], input=raw_patch, cwd=staged, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        require(result.returncode == 0, "patch_reverse_check_failed")
        result = subprocess.run([*git_apply, "--reverse", "--whitespace=error", "-"], input=raw_patch, cwd=staged, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        require(result.returncode == 0, "patch_reverse_failed")
        require(digest((staged / RUNTIME_PATCH).read_bytes()) == baseline[RUNTIME_PATCH]["sha256"], "patched_origin_mismatch")
        require(all(not (staged / rel).exists() for rel in NEW_TESTS), "added_test_reverse_mismatch")
        require({p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file() or p.is_symlink()} == {RUNTIME_PATCH}, "unlisted_reverse_patch_file")
        regular(staged / RUNTIME_PATCH)
    return {"module": MODULE, "version": VERSION, "origin": ORIGIN_COMMIT, "retained_origin_files": 1019, "added_test_files": 3, "runtime_patch_files": 1}

def verify_build_selection(root: Path) -> dict:
    root = root.resolve(strict=True)
    result = verify_files(root)
    env = os.environ.copy()
    # Matches the supported isolated builder. Do not inherit a workspace,
    # modfile or compiler overlay from outside the captured source tree.
    env.update(GOWORK="off", GOFLAGS="")
    cwd = root / "integration/cometbft"
    def output(*args):
        return subprocess.check_output(["go", *args], cwd=cwd, env=env, text=True, stderr=subprocess.PIPE, timeout=60).strip()
    require(Path(output("env", "GOMOD")).resolve(strict=True) == (cwd / "go.mod").resolve(strict=True), "unexpected_integration_module")
    selected = json.loads(output("list", "-mod=readonly", "-m", "-json", MODULE))
    require(selected.get("Version") == VERSION, "unexpected_dependency_version")
    require(Path(selected["Replace"]["Dir"]).resolve(strict=True) == (root / VENDOR).resolve(strict=True), "unexpected_dependency_replacement")
    package = json.loads(output("list", "-mod=readonly", "-json", MODULE + "/consensus"))
    require(Path(package["Dir"]).resolve(strict=True) == (root / VENDOR / "consensus").resolve(strict=True), "unexpected_consensus_source")
    result["compiler_source_selection"] = "captured_local_replacement"
    return result

if __name__ == "__main__":
    try:
        print(json.dumps(verify_build_selection(Path(__file__).resolve().parent.parent), sort_keys=True))
    except (OriginError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        raise SystemExit("CometBFT origin/build qualification failed: " + type(error).__name__ + ": " + str(error))
