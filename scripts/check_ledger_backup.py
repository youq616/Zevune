#!/usr/bin/env python3
"""Build the original backend and a tracked Rust fixture in an isolated snapshot.

The fixture creates a backup set with the actual CLI and real recovery binary, then spends
from the recovered ledger. No test wallet, transaction or fixture is uploaded.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

from source_snapshot import export_build_source


def main():
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(["git", "--no-replace-objects", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    with tempfile.TemporaryDirectory(prefix="zevune-backup-native-") as temporary:
        source = Path(temporary) / "source"
        export_build_source(root, commit, source)
        manifest = source / "integration/orchard/Cargo.toml"
        fixture = source / "scripts/fixtures/ledger_backup_cli.rs"
        target = source / "integration/orchard/tests/ledger_backup_cli.rs"
        if target.exists():
            raise RuntimeError("fixture_target_already_exists")
        # Only this exact tracked fixture is added to the isolated TEST build;
        # original production source/dependencies are not changed or rewritten.
        shutil.copyfile(fixture, target)
        environment = os.environ.copy()
        environment.update(ZEVUNE_CHAIN_PYTHON=sys.executable, RAYON_NUM_THREADS="2", CARGO_BUILD_JOBS="2",
                           CARGO_TARGET_DIR=str(Path(temporary)/"target"))
        subprocess.run(["cargo", "+1.98.1", "test", "--manifest-path", str(manifest), "--locked", "--release",
                        "--features", "local-funding-lab", "--test", "ledger_backup_cli", "--", "--test-threads=1"],
                       cwd=source, env=environment, check=True, timeout=900)
    subprocess.run(["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"], cwd=root, check=True)
    print("Exact-source native ledger backup-set lifecycle completed; no validator readiness granted.")


if __name__ == "__main__":
    main()
