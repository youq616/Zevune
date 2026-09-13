# Local payment preparation timing (P7 measurement foundation)

Scope: NO-FUNDS laboratory diagnostics, not a throughput result or a completed
P7 acceptance gate. The actual local wallet backend returns a `local_timing`
object after a successful `prepare`. No remote telemetry endpoint is added.

`format` is `zevune-prepare-timing-1`, `scope` is
`local_prepare_not_finality`, and `unit` is `microseconds`. `valid` is a Boolean.
The fixed `stages` object contains five non-overlapping measurements:

| Stage | Included work |
|---|---|
| `setup_and_sync` | Handler entry, public intent/genesis checks, wallet open/decrypt, reference-journal replay, wallet scan and any saved checkpoint |
| `intent_preflight` | Owned-file and spend-policy preflight; no proving-key construction |
| `prover_parameters` | Construction of public proving parameters in this CLI process |
| `prove_sign_verify_persist` | Repeated authoritative state checks, construction, proof, signatures, local validation, and durable encrypted reservation/outbox save |
| `export` | Create-only signed-transaction export and file synchronization |

`total` covers handler entry through completed export. Request decoding, password
entry, Python process launch, response serialization, network broadcast, consensus,
receiver scan and independent finality verification are **not** included. Do not
call this an end-to-end payment or compare it directly with the 5-second p95 target.
The proving/signing/persistence stage is intentionally combined until finer
instrumentation can be added without changing cryptographic or storage APIs.

Measurements use `std::time::Instant` and checked elapsed durations. A backwards
clock observation, missing/extra stage or unrepresentable duration produces
`valid:false` and null for every duration. A clock failure never changes an
already saved transaction into an invalid spend or triggers a retry. Zero is a
possible sub-microsecond rounded duration; it is not used as a missing-data marker.
For valid samples the sum of rounded stages can be below rounded total by at most
four microseconds. Frontend/schema tests enforce this distinction.

The timer exists only in the local CLI. It is not included in any transaction,
signature digest, proof input, wallet journal, consensus state or fee decision.
It contains no address, domain, transaction identifier, amount, password, seed,
view key or absolute timestamp. The normal operation response separately retains
its existing wallet information, which must not be copied into public reports.
`pending` retrieves old signed bytes and emits no new preparation measurement.
Failed prepares emit no success measurement; any benchmark must separately count
attempts, failures and timeouts rather than selecting only these success records.

The Python/Rust interoperability runner records exactly one ephemeral local
sample, validates its schema, and checks that a restored outbox yields identical
signed bytes without a second measurement. It is not a statistical benchmark.
Public reporting of test timings is separate from ordinary wallet use; the wallet
itself does not store or upload a performance history.

The funded multi-process integration driver now obtains an encoded, domain-bound
recipient from the receiving wallet, decodes it, rejects foreign-domain and LAB1
recipient variants without changing the sender receipt/outbox, and calls the
checked recipient preparation API for the real A-to-B-to-C payments. These tests
still use four local processes and valueless test allocations, not a public or
anonymous network. Existing proof and node rejection tests remain required.

Upstream timing semantics: https://doc.rust-lang.org/std/time/struct.Instant.html .
Operating-system, virtualization, suspend and clock behavior remain measurement
limitations; no timer can certify finality or the accuracy of a compromised host.
