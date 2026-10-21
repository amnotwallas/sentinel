# Milestone 3 task plan

Milestone 3 contract design was frozen by the repository owner as M3-00 on
2026-10-17 from baseline `75daa258eac7dd11d26c2e9ce4af945a74e5a41b`.
M3-01 through M3-05 are integrated on `main`, ending at
`95a3a86812876c9fa0b0730f4316e836a868684a`. M3-06 independent acceptance is the
only remaining task before a Milestone 3 **PASS** decision.

Scope and exit criteria come from the
[roadmap](../ROADMAP.md#milestone-3-safe-execution-lifecycle-and-http-adapter).
The exact lifecycle, TLS, redirect, API, persistence, and acceptance contracts are
in the [M3 implementation packet](../implementation/milestone-3.md) and
[ADR 0008](../architecture/ADRs/0008-http-dispatch-outcomes-and-tls-policy.md).
This plan records implementation order and status; it does not authorize
Milestone 4 or change the frozen M3 contract.

## Frozen prerequisites

- `transport_failed`, `DispatchCertainty`, phase-specific transport outcomes, and
  conservative recovery are accepted.
- DNS resolution occurs after the durable `dispatching` checkpoint.
- `not_sent` requires positive phase proof under an owned live lease; ambiguous
  exceptions, cancellation, lease loss, process death, and commit uncertainty
  remain `possibly_sent`.
- HTTPS requires chain and hostname verification with TLS 1.2 or newer.
- Existing `verify_tls: false` definitions remain readable but fail preparation
  before DNS/socket I/O.
- Trust is default roots plus one optional deployment-wide additive CA bundle.
- Target requests inherit no proxy settings, use no library retry, and use no
  mTLS or TLS early data.
- Only `GET`, `HEAD`, and `OPTIONS` follow redirects. Every hop is revalidated and
  cross-origin credentials/secret-derived headers are removed.
- The integrated HTTP adapter satisfies selected-IP dialing plus original-host
  authority/SNI under its locked version. The seam is version-coupled, so M3-06
  and future dependency upgrades must re-run the feasibility gate.
- Queue deliveries, HTTP attempt sequences, redirect hops, and trace retries are
  distinct. A redirect chain remains within one configured attempt.
- M4 owns evaluation and baseline semantics; M5 owns Tempo reconciliation.

## Ownership rules

Follow [workflow.md](workflow.md). Each authorized slice starts from an exact
integrated SHA in a fresh worktree, uses a unique `_test` database and reserved
ports, and assigns one writer per file.

The coordinator owns:

- shared API/worker composition;
- persistence model registration and migration-chain integration;
- migration allocation;
- runtime OpenAPI and generated client artifacts;
- shared fixtures and contract gates;
- milestone documentation and final integration.

Backend slice owners may change only their assigned domain, service, adapter,
persistence, API, migration, and focused-test paths. Security/QA review is
read-only unless given exclusive acceptance files. Generated artifacts are never
edited concurrently with backend schemas.

Integrated migrations:

- `0007_execution_materialization`: expand the M1 execution envelope and add
  execution items plus idempotency records for M3-01;
- `0008_attempt_observations`: add attempts, replay links, dispatch certainty,
  response artifacts, constraints, and indexes for M3-02/M3-04.
- `0009_attempt_response_outcomes`: add durable response/transport outcome fields
  and constraints required by M3-03/M3-04.

## M3-00 — Contract freeze

- **Objective:** Close the transport-failure, certainty, redirect, TLS/trust,
  proxy, DNS-pinning, transaction, and acceptance contracts.
- **Owned files:** ADR 0008, M3 implementation packet, this plan, roadmap,
  architecture, MVP, and M3 handoff.
- **Acceptance:** All three owner-requested clarifications are explicit; ADR 0007
  is extended rather than rewritten; M2 history is unchanged; docs have no
  unresolved state/TLS contradiction; no production or generated file changes.
- **Status:** Integrated at `3a83e26`.

## M3-01 — Atomic execution creation and immutable materialization

- **Status:** Integrated at `a12744c`.

- **Objective:** Create one test or ordered suite execution without target I/O.
- **Dependencies:** Published M3-00 documentation and explicit implementation
  authorization.
- **Owned areas:** Execution/item/idempotency domain and repositories, execution
  creation service, allocated `0007` migration, POST/list/detail API schemas and
  tests. Coordinator owns shared wiring and generated artifacts.
- **Contract:** In one transaction, validate ownership, pin active immutable
  environment and source revisions, materialize exact suite item order, create
  the execution job, and claim/store the optional 24-hour idempotency record.
- **Acceptance:** Atomic rollback, immutable pinning after later edits, concurrent
  idempotency serialization, equal-key replay, different-payload `409`, bounded
  list/detail responses, and proof that creation invokes no resolver, secret
  source, or target transport.
- **Tests:** Domain/API tests, real PostgreSQL constraints/concurrency, migration
  SQL and upgrade/downgrade/data-preservation, contract drift after coordinator
  generation, backend full gate, and applicable frontend compile tests.
- **Out of scope:** Attempts, secret resolution, HTTP adapter, dispatch/replay,
  evaluation, and UI.

## M3-02 — Preparation and protected observation persistence

- **Status:** Integrated at `26f92c2`.

- **Objective:** Add the frozen attempt lifecycle, in-memory request preparation,
  deterministic fingerprints, and bounded redaction without sending HTTP.
- **Dependencies:** Integrated M3-01 and frozen adapter ports.
- **Owned areas:** Attempt/observation domain and repositories, template/secret
  adapters, fingerprinting, redaction, allocated `0008` migration, focused unit
  and PostgreSQL tests.
- **Contract:** Secret values exist only in worker memory; fingerprints retain
  reference identity but not values; `prepared → failed/dispatching` and terminal
  outcome writes are fenced; observations are redacted before persistence.
- **Acceptance:** All legal/illegal transitions, database constraints, missing
  secret/template failures, `verify_tls: false` pre-network rejection, response
  cap/redaction fallback, synthetic canary sink inspection, and stale-token
  rejection.
- **Tests:** Pure domain/security tests, real PostgreSQL concurrency and migration
  round trips, safe logs/problems, and backend full gate.
- **Out of scope:** Actual DNS/TLS/HTTP and recovery-driven replay.

## M3-03 — Safe HTTP adapter

- **Status:** Integrated at `becbc55`.

- **Objective:** Produce one bounded transport result through an explicit port,
  with DNS pinning, verified TLS, redirect safety, and no hidden retry/proxy path.
- **Dependencies:** M3-02 types/ports and passing feasibility gate below.
- **Owned areas:** HTTP adapter and resolver/trust configuration, adapter-focused
  tests and synthetic local target fixtures. It does not own worker orchestration
  or generated contracts.
- **Feasibility gate before feature code:** With locked HTTPX/httpcore, prove
  selected-IP peer connection, original Host authority, original-host SNI and
  certificate validation, hostname-mismatch rejection, zero proxy/retry behavior,
  and connection isolation. Failure stops the slice for owner review.
- **Contract:** Static validation before checkpoint; resolver invoked only after
  checkpoint by its caller; validate all addresses; connect only to a selected
  validated IP; TLS 1.2+; default roots plus additive CA; no pooling, proxy, mTLS,
  early data, or insecure mode; safe-method redirects only; sanitize Location and
  credentials; stream to bounded capture.
- **Acceptance:** Every `M3-OUTCOME`, `M3-REDIRECT`, `M3-SSRF`, and `M3-TLS` case
  in the implementation packet, using injected DNS/time/transport and local
  synthetic peers without sleeps or external network dependence.
- **Out of scope:** Queue recovery, item aggregation, runtime API publication.

## M3-04 — Fenced dispatch orchestration and recovery

- **Status:** Integrated at `4264e63`.

- **Objective:** Connect durable job delivery to prepared attempts and the HTTP
  adapter without conflating redelivery with replay.
- **Dependencies:** Integrated M3-02 and M3-03.
- **Owned areas:** Execution application service, worker handler, heartbeat-aware
  cancellation, atomic replay/terminal aggregation, and integration tests.
- **Contract:** Persist `dispatching` with `possibly_sent`, fingerprint, trace ID,
  and span ID before DNS; keep database transactions out of network I/O; persist
  response/outcome only under the live fence; apply exact recovery matrix.
- **Acceptance:** Termination at every checkpoint; safe/default and explicitly
  unsafe replay; distinct attempt/trace/span identities; response/transport
  recovery without resend; one successor under concurrent reclaim; stale workers
  cannot write; remaining suite items skipped only after terminal ambiguity.
- **Tests:** Unit state/recovery tests, real PostgreSQL two-worker and lease-expiry
  cases with injected time, HTTP adapter integration, and backend full gate.

## M3-05 — Execution and attempt reads plus typed contract handoff

- **Status:** Integrated at `95a3a86`.

- **Objective:** Publish only implemented execution/result contracts and prove
  bounded redacted consumption.
- **Dependencies:** Integrated M3-01 through M3-04.
- **Owned areas:** Read repositories/services/routes and API contract tests.
  Coordinator exclusively owns runtime OpenAPI, planned/runtime reconciliation,
  and generated TypeScript.
- **Contract:** Exact frozen enums and fields, ordered/bounded attempts and items,
  safe observation expiry, no resolved request/raw Location/lease token/error
  detail, and stable RFC 9457 problems.
- **Acceptance:** Read/list filters and cursors, response byte bounds, expired
  artifact behavior, generated-client compilation, runtime/generated drift, and
  synthetic secret absence.
- **Tests:** Backend unit/integration/contract gates, frontend type/Vitest gates,
  and coordinator-owned regeneration verification.

## M3-06 — Independent acceptance and milestone integration

- **Status:** Pending.

- **Objective:** Establish the exact integrated M3 candidate and independently
  verify every roadmap and frozen-contract criterion.
- **Dependencies:** All slices integrated; no unresolved security/review finding.
- **Owned areas:** Exclusively assigned acceptance files and coordinator-owned
  integration/docs. Reviewer does not edit production files unless ownership is
  transferred.
- **Acceptance:** Single test and ordered suite end-to-end; crash at every durable
  checkpoint; replay/ambiguity; pinned revision inputs; target-policy attacks;
  TLS/trust/redirect/proxy cases; privacy sinks; response bounds; PostgreSQL and
  migration gates; runtime/generated contracts; full Compose.
- **Evidence:** Exact candidate SHA or uncommitted fingerprint, commands/counts,
  migration SQL/up/down, security findings/resolutions, Compose identity, and—only
  after separately authorized publication—remote workflow URL and actual job
  evidence.

## Verification policy

Every production slice follows test-driven development and the commands in
[quality-gates.md](quality-gates.md). `make check-fast` is not PostgreSQL,
migration, full Compose, or remote CI evidence. Database tests use disposable,
slice-owned PostgreSQL databases; network tests use local synthetic services and
reserved ports. No test relies on sleep for lease or ingestion timing.

Successful checks never authorize commit, push, merge, remote settings, or the
next milestone. M3 PASS requires an integrated candidate, independent acceptance,
full local evidence, and the required remote workflow evidence for that exact SHA.

## Next action

Run M3-06 against the integrated M3-05 candidate. Do not start M4 until the
independent review, PostgreSQL/migration/contract gates, full Compose acceptance,
and required remote CI evidence establish a Milestone 3 **PASS**.
