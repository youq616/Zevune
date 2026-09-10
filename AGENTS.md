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
