# Security status

**NOT AUDITED. NO REAL FUNDS. NO REAL ZERO-KNOWLEDGE BACKEND. NO CONSENSUS.**

This is an in-memory, local-only specification scaffold. Its executable refuses all payments. It cannot provide anonymity, correct issuance, asset custody, durable storage, network finality or censorship resistance.

Test-only checksums are deliberately forgeable. No `*_test.go` file is a payment verification implementation. The SHA-256 tree and fixed ciphertext size are provisional modeling tools, not a final shielded protocol. The engine's full-state cloning is not production storage.

No protocol-wide viewing key, wallet seed, administrator key or actual user secrets are included. Absence of these in a scaffold does NOT establish the security of a future wallet/network.

Do not add a bypass flag or an always-successful verifier to make demonstrations run. Production acceptance requires genuine proofs, domain binding, authenticated ownership, ranges/conservation, output correctness and a protocol-specific security review.

The current API only listens on a numeric loopback address. It has no authentication or TLS and MUST NOT be exposed through a public reverse proxy. The local-only restriction is not a substitute for production API security.

Private security reporting channel and response process are not configured. Do not post secrets in public issues. The repository is publicly visible. Configure an owner-approved private reporting channel before a public testnet or any funds-related use.

Mainnet deployment and accepting funds are blocked until all release gates in docs/ROADMAP.md have been explicitly reviewed. There is no promise of absolute anonymity or immunity from investigation or regulation.
