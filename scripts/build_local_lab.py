#!/usr/bin/env python3
"""Build a create-only local NO-FUNDS bundle. No compiler installs or node launches.

Compilers and locked dependencies must already be available. Only tracked,
clean source is accepted. Checksums detect damage; they are not code signatures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def checked_output(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def manifest_for(folder: Path, commit: str, versions: dict[str, str]) -> dict:
    files = []
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Bundle must contain regular files only")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files.append({"name": path.name, "size": path.stat().st_size,
                      "sha256": digest.hexdigest()})
    return {"format": "zevune-local-bundle-1", "source_commit": commit,
            "real_funds_allowed": False, "public_network_supported": False,
            "network_anonymity_implemented": False,
            "scope": "single_machine_fixed_validator_test_lab",
            "toolchains": versions, "files": files}


def build(destination: Path) -> dict:
    root = Path(__file__).resolve().parent.parent
    commit = checked_output(["git", "rev-parse", "HEAD"], root)
    if len(commit) != 40 or checked_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], root
    ):
        raise ValueError("Build requires an exact clean tracked commit")
    versions = {"go": checked_output(["go", "version"], root),
                "rust": checked_output(["rustc", "--version"], root / "integration/orchard")}
    if not versions["go"].startswith("go version go1.27.1 ") or not versions["rust"].startswith("rustc 1.98.1 "):
        raise ValueError("Pinned Go 1.27.1 and Rust 1.98.1 are required")
    destination = destination.absolute()
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    suffix = ".exe" if os.name == "nt" else ""
    env = os.environ.copy()
    env.update({"GOTOOLCHAIN": "local", "CARGO_BUILD_JOBS": "2"})
    subprocess.run(["go", "build", "-mod=readonly", "-trimpath", "-o",
                    str(destination / ("zevune-network" + suffix)), "./cmd/zevune-network"],
                   cwd=root / "integration/cometbft", env=env, check=True)
    subprocess.run(["cargo", "build", "--locked", "--release", "--features", "local-funding-lab",
                    "--bin", "zevune-pool-worker", "--bin", "zevune-wallet-local"],
                   cwd=root / "integration/orchard", env=env, check=True)
    for name in ("zevune-pool-worker", "zevune-wallet-local"):
        shutil.copy2(root / "integration/orchard/target/release" / (name + suffix), destination)
    shutil.copy2(root / "scripts/zevune_wallet.py", destination)
    shutil.copy2(root / "docs/LOCAL_NETWORK_OPERATOR.zh-CN.md", destination)
    if checked_output(["git", "status", "--porcelain", "--untracked-files=no"], root):
        raise ValueError("Build changed tracked source or a dependency lock")
    result = manifest_for(destination, commit, versions)
    with (destination / "BUNDLE-MANIFEST.json").open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=True, indent=2)
        file.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.output)
        print(json.dumps({"built": True, "source_commit": result["source_commit"],
                          "real_funds_allowed": False}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Build not completed. Existing files were not replaced; a new partial directory may remain. No install, launch or automatic repair was performed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
