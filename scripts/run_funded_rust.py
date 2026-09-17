"""Run every funded Rust test target in two disjoint CI cohorts.

This partitions TARGETS, never test names or cryptographic checks. Each process
uses the genuine crate and the same locked dependencies/features as the former
single cargo-test command. Unknown target policy fails instead of omitting it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any

MANIFEST = Path(__file__).resolve().parents[1] / "integration/orchard/Cargo.toml"
FEATURE = "local-funding-lab"
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,127}\Z")
COMMON = ("cargo", "test", "--locked", "--release", "--features", FEATURE)


def make_plan(metadata: dict[str, Any], manifest: Path, cohort: str) -> dict[str, Any]:
    """Validate this crate's target policy and produce an exhaustive partition.

    Cargo metadata is trusted local build input, not an imported execution plan.
    The checks make future examples/custom targets/feature changes explicit:
    they must not disappear silently when the CI pipeline is extended.
    """
    if (cohort not in ("library", "interfaces")
            or type(metadata.get("version")) is not int or metadata["version"] != 1):
        raise ValueError("unknown cohort or metadata version")
    packages = metadata.get("packages")
    if not isinstance(packages, list) or len(packages) != 1:
        raise ValueError("expected one no-deps workspace package")
    package = packages[0]
    if (not isinstance(package, dict)
            or package.get("name") != "zevune-orchard-lab"
            or not isinstance(package.get("manifest_path"), str)
            or Path(package["manifest_path"]).resolve() != manifest.resolve()
            or metadata.get("workspace_members") != [package.get("id")]):
        raise ValueError("unexpected workspace identity")
    targets = package.get("targets")
    if not isinstance(targets, list) or not 3 <= len(targets) <= 128:
        raise ValueError("invalid target inventory")
    inventory: dict[str, list[str]] = {"lib": [], "bin": [], "test": []}
    seen: set[tuple[str, str]] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("invalid target")
        kinds = target.get("kind")
        name = target.get("name")
        if (not isinstance(kinds, list) or len(kinds) != 1
                or not isinstance(kinds[0], str) or kinds[0] not in inventory
                or not isinstance(name, str) or NAME.fullmatch(name) is None
                or target.get("test") is not True):
            raise ValueError("unsupported or disabled test target; update cohort policy")
        kind = kinds[0]
        required = target.get("required-features", [])
        if (not isinstance(required, list)
                or any(value != FEATURE for value in required)):
            raise ValueError("target requires an unselected feature")
        if kind == "lib" and target.get("doctest") is not True:
            raise ValueError("library documentation tests must remain enabled")
        if (kind, name) in seen:
            raise ValueError("duplicate target")
        seen.add((kind, name))
        inventory[kind].append(name)
    if len(inventory["lib"]) != 1 or not inventory["bin"] or not inventory["test"]:
        raise ValueError("incomplete target inventory")
    for names in inventory.values():
        names.sort()
    if cohort == "library":
        commands = [list(COMMON) + ["--lib", "--", "--test-threads=1"]]
        selected = [("lib", inventory["lib"][0])]
    else:
        command = list(COMMON)
        selected = []
        for kind in ("bin", "test"):
            for name in inventory[kind]:
                command.extend(["--" + kind, name])
                selected.append((kind, name))
        command.extend(["--", "--test-threads=1"])
        commands = [command, list(COMMON) + ["--doc", "--", "--test-threads=1"]]
    return {"cohort": cohort, "test_targets": selected,
            "documentation_tests": cohort == "interfaces", "commands": commands}


def load_metadata(manifest: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["cargo", "metadata", "--manifest-path", str(manifest), "--no-deps",
         "--locked", "--format-version=1", "--features", FEATURE],
        cwd=manifest.parent, check=True, stdout=subprocess.PIPE, text=True,
    )
    metadata = json.loads(result.stdout)
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    return metadata


def execute(plan: dict[str, Any], manifest: Path) -> None:
    for command in plan["commands"]:
        print("RUN " + shlex.join(command), flush=True)
        # No shell, acceptance stub, skipped proof, or continue-on-error path.
        subprocess.run(command, cwd=manifest.parent, check=True)
    print("FUNDED_COHORT_COMPLETE " + plan["cohort"], flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort", choices=("library", "interfaces"))
    parser.add_argument("--plan-only", action="store_true",
                        help="print target selection, without claiming test execution")
    args = parser.parse_args(argv)
    try:
        plan = make_plan(load_metadata(MANIFEST), MANIFEST, args.cohort)
        print(json.dumps(plan, sort_keys=True), flush=True)
        if not args.plan_only:
            execute(plan, MANIFEST)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("FUNDED_COHORT_NOT_COMPLETED: " + type(error).__name__, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
