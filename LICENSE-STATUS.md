# License decision pending

The project owner has not selected an open-source license. The existing GitHub repository is public; public visibility is not an explicit license grant. No license is assigned on the owner's behalf in this change.

The original root Go scaffold uses the Go standard library. The repository now also includes a CometBFT integration and a Rust Orchard integration with third-party dependencies recorded in [go.mod](integration/cometbft/go.mod), [go.sum](integration/cometbft/go.sum), [Cargo.toml](integration/orchard/Cargo.toml) and [Cargo.lock](integration/orchard/Cargo.lock). It is no longer accurate to describe the entire project as standard-library-only.

Two upstream public Merkle empty-root vectors are incorporated in the Rust tests; their source and included terms are recorded in [integration/orchard/NOTICE.md](integration/orchard/NOTICE.md). That notice covers the identified material and does not select a license for the rest of Zevune. The repository also provides [an offline crate-notice inventory tool](scripts/audit_crate_notices.py); its existence is not evidence that the actual dependency inventory or distribution review is complete. Those completion flags remain false in [PROJECT_STATUS.json](PROJECT_STATUS.json).

Any later reuse or fork must retain applicable upstream licenses/notices and undergo a compatibility review. This factual inventory correction does not grant a project license or authorize distribution of a release.
