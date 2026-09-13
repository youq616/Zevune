# Contributor / coding-agent instructions

This is a NO-FUNDS local scaffold. Preserve these invariants:

- Do not claim that hidden fields, hashes, test checksums or stubs are zero-knowledge privacy.
- Do not add an executable mock verifier, `skip-proof`, `always-valid`, admin key, master view key, trusted witness service or silent fallback to transparent transfers.
- Do not implement novel cryptography without an explicit, reviewed protocol design and genuine test vectors.
- Keep accepting doubles ONLY in `*_test.go`.
- Run `go test ./...`, `go vet ./...`, and race tests where supported. Fuzz the binary decoder.
- Every state-affecting rule must be deterministic; every rejected block must leave state unchanged.
- No private keys, view keys, seeds, payment plaintext, tokens or real wallet data in code/logs/reports.
- Never call process health, a preflight result, an app hash or a local ApplyBlock result "finality".
- Keep public metadata, performance costs, incomplete milestones and failures explicit.
- Updating source is not permission to deploy, publish publicly, add paid infrastructure or transfer value.
- Consult docs/PROOF_CONTRACT.md and docs/ARCHITECTURE.zh-CN.md before adapting a real backend.

## Stage acceptance and independent review

Owner requirement (2026-09-14): every development stage requires an independent
coding-agent review before it is marked accepted or merged into `main`.

- Keep each stage on the existing development branch and open a PR against its
  actual base. Freeze the candidate commit and record the base/head/tree IDs.
- The reviewer must be a separate agent task/session that did not write the
  candidate. Author self-review, a second test run, a CI job, and a checklist do
  not constitute an independent agent review.
- Give the reviewer the diff, relevant callers, tests, invariants and known
  limitations. Read the returned findings; fix blockers, rerun regression and
  request re-review of the changed commit. Preserve reviewer/task links and scope.
- No review response, unavailable reviewer access, stale review, or a reaction
  emoji alone means REVIEW PENDING, not approval. Do not advance `main` or claim
  stage completion while this condition holds. Do not fabricate reviewer output.
- CI success and agent review do not replace a specialist external security audit.
  This is a development-process rule, not a claim that GitHub branch protection
  has been configured or that repository administrators cannot bypass it.

## Code Review Rules

### State and storage safety

Rejected candidates must not alter committed state, journal bytes, wallet
reservations or pending commit slots. Recheck constraints at commit; preflight
and authorization-cache hits are never reusable spend permissions. Capacity
accounting must include the actual record framing, not just transaction bytes.

### Scope and compatibility

Retain genuine Orchard verification, legacy decoding and no-funds boundaries.
Do not silently delete/reinterpret data, raise a protocol/storage limit, expose
private worker interfaces, introduce viewing backdoors, or label a test-only
failure injection as a production capability. Report untested platform and
real-disk/power-loss conditions explicitly.
