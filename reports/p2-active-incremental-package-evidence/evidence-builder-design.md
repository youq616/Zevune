# P2 incremental package evidence collection design

This document and the collector are author work by `/root/p2_package_evidence`.
They are not an independent review or a stage acceptance decision. The current
preparation does not modify the repository, freeze a candidate, merge a PR, or
publish files. The root task owns acceptance and the final documentation PR.

## Explicit admitted material

`evidence-spec.json` names every fixed input individually. The three immutable
`c1-native-original-manifest.json`, `c2-native-original-manifest.json`, and
`c3-native-original-manifest.json` supply their exact individual native paths,
bytes, and SHA-256 values. They admit 56, 62, and 62 files respectively. The
collector never selects an arbitrary file merely because it exists in scratch.

The fixed set includes both design reviews, all C1/C2/C3 code and storage reviews,
their scope files, explicitly cited remote response wrappers and decoded logs,
exact deltas, formatter reconstruction records, final native and non-Rust
reports, their structural and source scope records, retained resource and
operator audit records, immutable source identity captures, actual runtime merge
records, and selected analysis/capture/publication helper sources. Parser v1 is
preserved alongside v2 and the explicit v2 observation record. The original C1
initial observation remains an intermediate record. Early C2 funded library and
C3 bridge observations remain labelled as limited workflow observations; the
collector does not upgrade those observations to acceptance.

The source representations are explicit per file:

- GitHub API/log captures retain the exact UTF-8 bytes of the connector's decoded
  content, including original BOM/CRLF. They are not original HTTP wire captures.
- Reviewer response wrappers retain their original JSON bytes and the original
  decoded content string inside. These are selected only where the code reviewer
  actually cited that wrapper. Root's duplicative `carriers/` directory is not
  archived.
- The three storage reviewers' structured PR objects are labelled serialized
  connector structured objects, distinct from decoded API text.
- Reviewer MD reports are original authored responses. Scope, structural,
  reconstruction, resource, and payload audit JSONs are retained original files
  whose contents are independently authored derived observations.
- Resource ZIPs are full downloaded original ZIP bytes. The extracted setup and
  result JSONs are original member bytes. All six ZIP member sets are checked
  against the admitted exact extracted bytes before any archive is written.
- Helper source, author indexes, and collection specifications are labelled as
  authored helper/derived files, not independent review or CI output.

Every archive entry maps the original absolute scratch source path and its
relative name to `reports/p2-active-incremental-package-evidence/<relative>`.
Original reports are never rewritten to change their verdict, update their
absolute paths, or imply broader coverage. The generated adjacent original
manifest explains the mapping and each record's representation. It does not hash
itself. An additional `.gitattributes` containing `* -text` prevents Git text
conversion and is counted separately from retained source records.

## Exclusions and their practical limits

The four complete C2/C3 operator ZIPs and every executable payload remain outside
the repository evidence archive. The retained artifact API records identify
GitHub artifact IDs, sizes, and digests. The exact manifest members, root's
download observations, and the independent per-payload digest verification
reports are retained. The archive explicitly lists each omitted full ZIP with
its observed bytes/SHA-256 and says it was not copied. The collector does not
execute, re-sign, or independently re-audit any downloaded binary. A later
reader who needs the complete binary ZIP must obtain that separately; GitHub
artifact availability is not guaranteed indefinitely by this archive.

Upload JSONs containing duplicate full source text, progress records, PR-body and
documentation drafts, preliminary scope inventories, unreferenced partial
diagnostics, Python bytecode caches, and unrelated temporary files are excluded.
Earlier evidence directories and repository source/test/workflow files remain
bound to their immutable Git candidates and are not rewritten or duplicated.
An explicit historical method reference to `native_log_summary.py` is recorded
without claiming that older helper or older test execution belongs to this stage.

The reference check covers explicit stage-evidence filenames in the retained
reviewer reports/derived records and author native/operator/formatter records.
It resolves those to retained stage inputs or the explicit operator omission;
missing in-stage references stop collection. Structured entries containing a
retained path, byte count, and SHA-256 are checked against the actual full bytes.
Unambiguous Markdown filename/hash references, with byte counts where present,
are also checked directly against those full bytes.
Repository source citations and artifact-internal generic member names are not
treated as additional scratch evidence files. Raw job log text, API payloads,
and helper code literals are not treated as a reference catalogue. That limited
machine check is supplemented by the original reviewers' explicit attachment
lists and root's full reading of the original MD reports.

Retained helper sources preserve how the original observations were produced.
Some helpers refer to the original scratch/repository paths or external Git
objects. They are not a promise that every audit can be replayed without those
inputs, that all original tool calls can be regenerated, or that the omitted
operator ZIPs are contained in the archive.

## Root-confirmed lock and actual merge identity

Only root may confirm that the original reports have been read and frozen. The
collector requires the following exact JSON shape, directly in this stage
scratch directory:

```json
{
  "format": "zevune-active-incremental-package-review-lock-1",
  "confirmed_by": "/root",
  "runtime_merge_sha": "the actual 40-character runtime merge commit",
  "runtime_merge_tree": "21de343c12bc27cb1022ffd7ebd451abe0e61f29",
  "read_original_reports": ["the exact 15 original MD paths"],
  "frozen_files": {
    "one of the exact 29 required paths": {
      "bytes": 123,
      "sha256": "64 lowercase hexadecimal characters"
    }
  }
}
```

The 15 MD paths are `design-review.md`, `design-storage-review.md`,
`native-expectation.md`, and the C1/C2/C3 `code-review.md`, `storage-review.md`,
`native-review.md`, and `native-nonrust-review.md` variants. In addition to those
15 MDs, the lock requires the six formal native/non-Rust JSON files, the three
native collection manifests, and these five actual merge records:

- `source-identities/runtime-merge-result.json`
- `source-identities/runtime-merged-pr.json`
- `source-identities/runtime-git-commit.json`
- `source-identities/runtime-main-branch.json`
- `source-identities/runtime-merge-receipt.json`

The collector verifies all C1/C2/C3 immutable Git commit/tree identities and
their ordered parent chain; each synthetic checkout has `[stage base, candidate]`
parents and the exact candidate tree. The actual runtime merge must have
`[2cc87a2207d502ac5cfe00ea52e525c1516917e5,
cb0804e7c921a456cbbafab313b3a4a4501b8f5e]` as ordered parents and the C3 tree.
Actual merged PR 17, merge-result, and captured post-merge main-branch originals
must agree. There is no inferred future merge or synthetic-checkout-as-main
substitution.

## Commands and copy boundaries

Run from `/workspace/scratch/1753b04c9dbb/zevune-p2-incremental-package`:

```sh
python prepare_package_evidence.py inspect
python prepare_package_evidence.py lock-template --template-output evidence-review-lock-template.json
```

The template has `confirmed_by: REQUIRES_ROOT_CONFIRMATION`, an empty report-read
list, and a `missing` field. It cannot satisfy the review lock. Root should create
a separate final lock after the report readback and actual merge; the template
is not silently converted to confirmation by the collector.

Once root supplies the final lock and explicitly authorizes collection:

```sh
python prepare_package_evidence.py freeze --review-lock evidence-review-lock.json
python prepare_package_evidence.py verify --review-lock evidence-review-lock.json
python prepare_package_evidence.py build --review-lock evidence-review-lock.json
```

Freeze records every selected input's exact bytes/SHA-256, representation,
reference closure, intentional omissions, and root lock identity in the
create-only `evidence-freeze.json`. All fixed files and all native originals must
exist, all required lock hashes must match, all native pages must be complete and
terminal for the exact candidate, and no unexpected file may exist inside a
native evidence directory. C1's single skipped zero-step growth placeholder
correctly has no log. The collector never treats a job's zero tests or existence
as test execution credit.

Build fully revalidates that snapshot before writing. It accepts only bounded
regular files with no symlinked path components and detects changes during
reads. It rejects signed/credential-bearing URLs, unmasked token-shaped values,
private-key markers, and non-UTF-8 content outside the six explicitly admitted
JSON-only resource ZIPs. File content is never redacted or reformatted to pass a
gate. Any refusal requires examining the particular source and scope.

The build output stays entirely under `scratch/handoff-draft/reports/`. Existing
different output bytes, additional files within this stage evidence directory,
or any post-freeze input change stop the operation. Publication uses create-only
atomic file creation and verifies every output byte again. Existing repository
reports are untouched. Root then copies these prepared new artifacts alongside
the root-authored validation/CI/merge indexes into the separate documentation
candidate and obtains its own independent review and native checks.

The archive build neither grants the root declaration independent review status
nor evaluates stage acceptance. C1 and C2 rejection reports and C3's exact
review-time scope remain separate historical originals.
