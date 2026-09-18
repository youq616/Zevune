"""Reviewer-only parsing of complete native logs; no execution credit by itself."""
import hashlib
import json
import re

ANSI = re.compile(r"\x1b\[[0-9;]*m")
STAMP = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\S+Z ")
RESULT = re.compile(
    r"^test result: (\w+)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
    r"(\d+) measured; (\d+) filtered out; finished in ([\d.]+)s$")
RUNNING = re.compile(r"^\s*Running (?:(unittests) )?(.+?) \(target[/\\]release[/\\]deps[/\\].+\)$")
TEST = re.compile(r"^test (\S+) \.\.\. (.*)$")


def lines_from(raw):
    return [ANSI.sub("", STAMP.sub("", line))
            for line in raw.decode("utf-8").splitlines()]


def parse_rust(lines):
    # Cargo emits target announcements on stderr and harness results on stdout.
    # Either stream may arrive late, including an announcement after its result.
    # Each stream preserves its own order and Cargo runs harnesses sequentially.
    # Collect both streams, require equal counts, and pair by execution ordinal.
    # Every result still requires its own running count and exact named passes.
    announcements = []
    results = []
    passed_names = []
    pending_test = None
    totals = []
    funded_plans = []
    funded_complete = []
    for number, line in enumerate(lines, 1):
        match = RUNNING.fullmatch(line)
        if match:
            announcements.append({"kind": "unit" if match[1] else "integration",
                            "target": match[2].replace("\\", "/"),
                            "announcement_line": number})
            continue
        if line.strip().startswith("Doc-tests "):
            announcements.append({"kind": "doc", "target": line.strip()[10:],
                            "announcement_line": number})
            continue
        match = re.fullmatch(r"running (\d+) tests?", line)
        if match:
            totals.append(int(match[1]))
            continue
        match = TEST.fullmatch(line)
        if match:
            assert pending_test is None, (pending_test, line)
            if match[2] == "ok":
                passed_names.append(match[1])
            elif match[2] in ("FAILED", "ignored"):
                raise AssertionError("Unaccepted Rust case: " + line)
            else:
                # --nocapture permits public metric output before the eventual
                # standalone 'ok'. No test name is counted until that line.
                pending_test = match[1]
            continue
        if line == "ok" and pending_test is not None:
            passed_names.append(pending_test)
            pending_test = None
            continue
        match = RESULT.fullmatch(line)
        if match:
            assert pending_test is None, line
            target = {}
            assert match[1] == "ok"
            counts = [int(value) for value in match.group(2, 3, 4, 5, 6)]
            assert counts[1:] == [0, 0, 0, 0], line
            assert len(totals) == 1 and totals[0] == counts[0], (totals, line)
            assert len(passed_names) == counts[0], (len(passed_names), line)
            assert len(set(passed_names)) == len(passed_names)
            target.update({"passed": counts[0], "failed": counts[1],
                           "ignored": counts[2], "measured": counts[3],
                           "filtered": counts[4], "seconds": float(match[7]),
                           "result_line": number, "named_passes": passed_names})
            results.append(target)
            passed_names = []
            totals = []
            continue
        if line.startswith('{"cohort":'):
            funded_plans.append(json.loads(line))
        if line.startswith("FUNDED_COHORT_COMPLETE "):
            funded_complete.append(line.removeprefix("FUNDED_COHORT_COMPLETE "))
    assert pending_test is None and not passed_names and not totals
    assert len(announcements) == len(results), (len(announcements), len(results))
    completed = [{**announcement, **result}
                 for announcement, result in zip(announcements, results)]
    return {"harnesses": completed, "funded_plans": funded_plans,
            "funded_complete": funded_complete}


def identify(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "utf8_bom": raw.startswith(b"\xef\xbb\xbf"), "crlf_count": raw.count(b"\r\n")}
