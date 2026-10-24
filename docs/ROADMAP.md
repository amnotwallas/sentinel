# Sentinel MVP Roadmap

## Purpose

This roadmap orders implementation so each milestone produces a reviewable,
tested capability while preserving the narrow scope in [`MVP.md`](MVP.md). It is
not a calendar commitment. A milestone is complete only when its exit criteria
pass in CI and the relevant documentation is current.

No milestone may introduce multi-tenancy, billing, AI behavior, Kubernetes,
scheduling, alerting, a dedicated message broker, a proprietary tracing protocol,
or other excluded features merely to prepare for hypothetical scale.

## Cross-cutting definition of done

Every milestone that changes production behavior must include:

- tests at the lowest useful layer plus PostgreSQL integration tests where state,
  locking, or JSONB is involved;
- typed Python and TypeScript interfaces with no unreviewed suppressions;
- Ruff, mypy, ESLint, Prettier, pytest, and Vitest checks relevant to the changed
  code;
- an Alembic migration for every schema change, tested both up and down where
  safe;
- structured, secret-safe logs and OpenTelemetry instrumentation at new process
  boundaries;
- OpenAPI updates and generated-client drift checks for API changes;
- documentation and an ADR for any decision that changes accepted architecture;
- exact verification commands and results in the change handoff.

Security, redaction, deterministic behavior, and recovery are built into each
milestone, not deferred to a final cleanup phase.

## Milestone 1: Repository foundation and durable work skeleton

Milestone 1 is complete. Native checks and Docker Desktop acceptance on macOS
are recorded in [the implementation ledger](implementation/milestone-1.md),
including full-stack health, actual in-flight worker recovery/fencing, and
PostgreSQL named-volume persistence across restart/replacement. The implementation
was committed and pushed to `amnotwallas/sentinel` on `main` as
`62635ea71566dc8e21118667a393ed944f6a0cce`. The user confirmed all GitHub Actions
backend, frontend, and Compose jobs passed. The run URL/logs were not independently
captured in this checkout; this CI status is user-reported.

Milestone 2 is complete with status **PASS**. The accepted implementation is
`6b83adf0b8c9d9dcb0bba668a9e15d8ff0b4d715` on `main`. The independent M2-08
review passed locally with 235 backend tests, including the real-PostgreSQL
integration suite, plus migration round trips, contract validation, security
checks, nine frontend tests, and full Compose verification. The repository owner
supplied the final remote evidence: the `checks` push workflow on `main` concluded
`success` in 1 minute 28 seconds at
[GitHub Actions run 38971960329](https://github.com/amnotwallas/sentinel/actions/runs/38971960329),
with frontend Vitest reporting 2 files and 9 tests passed. This supplied evidence
was accepted without independently retrieving GitHub Actions. It establishes the
overall workflow conclusion; individual backend and Compose job conclusions were
not separately supplied or recorded. The detailed acceptance mapping is in the
[Milestone 2 implementation ledger](implementation/milestone-2.md), and the
transition is in the
[Milestone 3 handoff](development/milestone-3-handoff.md). Milestone 3 is complete
with status **PASS** at accepted implementation SHA
`a41670b5c9da5410d0bd50d4ceaca495d23998bf`. Milestone 4 is complete with
status **PASS** at accepted implementation SHA
`8e280be334b8fa71044005ad6557a3b91f0dd828`. M4-00 through M4-06 are complete.
The repository owner supplied matching exact-SHA GitHub Actions evidence:
Backend and PostgreSQL, Frontend and Contracts, and Docker Compose all concluded
`success`, with 500/500 backend and 12/12 frontend tests passing. This evidence
was accepted without independently retrieving GitHub Actions. The
[Milestone 4 acceptance handoff](development/milestone-4-handoff.md) records the
independent review, its corrected JSON response-classification defect, and the
accepted evidence. Milestone 5 is now complete with status **PASS**; its
implementation, acceptance evidence, and M6 transition are recorded in the
[Milestone 5 contract handoff](development/milestone-5-handoff.md).

### Goal

Establish a runnable, testable monorepo and prove the API/worker/PostgreSQL
process boundary and job-leasing semantics before implementing target HTTP calls.

### Deliverables

- Python 3.12 backend package with `api` and `worker` entry points, shared typed
  configuration, and module directories from the architecture document.
- React/TypeScript/Vite shell with strict TypeScript and a generated/typed API
  client boundary.
- Docker Compose services for frontend, API, worker, PostgreSQL, and Tempo with
  loopback-only public bindings.
- FastAPI liveness/readiness endpoints and RFC 9457 error foundation.
- SQLAlchemy/Alembic setup with initial `jobs` and minimal execution-envelope
  tables required to test ownership and terminal failure.
- PostgreSQL job repository with atomic `SKIP LOCKED` claim, lease token fencing,
  heartbeat, expiration reclaim, bounded backoff, `succeeded`, and `dead` states.
- A worker handler registry and deterministic clock/UUID abstractions. The only
  initial handler may be an internal test/probe handler; it is not a public
  product feature.
- CI jobs for backend lint/type/test, frontend lint/type/test, migration checks,
  and Docker Compose configuration validation.

### Required tests

- Two workers cannot own the same unexpired lease.
- A stale lease token cannot heartbeat or complete a reclaimed job.
- Expired leases are reclaimed and increment delivery count.
- Retry backoff uses the documented schedule and the third failed delivery becomes
  terminal `dead`.
- `LISTEN/NOTIFY` loss does not prevent polling from discovering work.
- API restart does not lose a committed job; worker restart permits recovery.
- Tempo unavailability is reported as degraded readiness detail but does not make
  the API unable to manage definitions/jobs.
- Default Compose ports are not bound to all interfaces.

### Exit criteria

- A fresh checkout can run documented setup, migrations, and Compose services.
- A test inserts a job transactionally, observes a worker lease/heartbeat, and
  reaches `succeeded` without an in-memory queue.
- Crash/reclaim and delivery-exhaustion integration tests pass against PostgreSQL,
  without sleeps or SQLite.
- No target HTTP execution, definition UI, or comparison behavior has been added.

This is the recommended first implementation milestone. It retires the highest
foundational risk—the custom durable lease/fencing behavior—without prematurely
building product features on an unreliable worker substrate.

## Milestone 2: Versioned catalog and definition API

### Goal

Create reproducible, immutable inputs for later executions.

### Deliverables

- `Project`, `Environment`, `EnvironmentRevision`, `TestCase`,
  `TestCaseRevision`, `Suite`, `SuiteRevision`, `SuiteRevisionItem`, and
  `ChangeEvent` persistence and domain models.
- Canonical validation for request, assertion, comparison, redaction, and target
  policy documents.
- Secret-reference syntax validation without secret-resolution endpoints.
- Project/environment/test/suite endpoints from the MVP API contract.
- Strong ETag/`If-Match` behavior for mutable metadata/activation pointers.
- OpenAPI schemas and generated frontend client types.

### Required tests

- Editing creates an immutable monotonically versioned revision.
- Concurrent stale `If-Match` update returns `412` and cannot overwrite the active
  pointer.
- A suite revision pins exact test-case revision IDs and preserves order.
- Canonical comparison-policy serialization produces the same SHA-256 fingerprint
  across dictionary insertion orders.
- Secret values are rejected in known credential headers when supplied as
  unprotected literals, and secret references are never resolved by API reads.
- User-supplied trace headers and Sentinel-owned baggage keys are rejected.

### Exit criteria

- All definition workflows function through the API with durable change history.
- An execution can later pin all required immutable revisions without reading a
  mutable document.
- No outbound request is sent yet.

## Milestone 3: Safe execution lifecycle and HTTP adapter

Milestone 3 is complete with status **PASS** at accepted implementation SHA
`a41670b5c9da5410d0bd50d4ceaca495d23998bf`. The repository owner accepted
[ADR 0008](architecture/ADRs/0008-http-dispatch-outcomes-and-tls-policy.md) and
the frozen [Milestone 3 implementation contract](implementation/milestone-3.md)
on 2026-10-17. M3-00 through M3-06 are integrated on `main`. The implementation
provides
atomic execution creation, protected attempt persistence, a DNS-pinned HTTP
adapter, fenced worker orchestration/recovery, and execution/attempt read APIs.
M3-06 independent acceptance completed on 2026-10-21, including the process-crash,
recovery, replay, fencing, TLS, redirect, SSRF, privacy, migration, contract, and
Compose evidence recorded in the
[acceptance handoff](development/milestone-3-handoff.md). The repository owner
supplied exact-SHA GitHub Actions evidence for `a41670b`: workflow `checks` and
its Backend and PostgreSQL, Frontend and Contracts, and Docker Compose jobs all
concluded `success`. The report was accepted without independently retrieving
GitHub Actions; its supplied and unavailable details are recorded in the handoff.

### Goal

Execute one test or ordered suite safely, with crash recovery and redacted bounded
observations, before implementing baseline comparisons.

### Deliverables

- `Execution`, `ExecutionItem`, `TestAttempt`, `ResponseArtifact`, and execution
  idempotency records.
- `POST /api/v1/executions` with atomic revision pinning, materialization, job
  creation, optional 24-hour `Idempotency-Key`, and `202` response.
- Execution/item/attempt state machines and resumable job handler.
- In-memory secret resolution, template expansion, request fingerprinting, and
  fixed/configured redaction.
- Target-policy adapter with DNS/address validation, redirect-hop validation,
  DNS-pinned connections, mandatory certificate/hostname verification, additive
  deployment CA trust, timeouts, response streaming/capture limits, and bounded
  concurrency. Target requests inherit no proxy and use no library retry.
- Durable `transport_failed` outcomes and `DispatchCertainty` that distinguish
  positive `not_sent` proof, possible transmission, and observed responses without
  weakening conservative crash recovery.
- Attempt root client span created and IDs checkpointed before dispatch. Full
  Tempo reconciliation waits for Milestone 5.
- Read endpoints for executions and attempt observations.

### Required tests

- Revision changes after queueing do not affect a pinned execution.
- Repeated identical idempotency key/payload returns the same execution; a
  different payload returns `409`.
- Recovery before dispatch continues without an extra request.
- Recovery from `response_received` evaluates/resumes without resending.
- Recovery from `transport_failed` never resends, and `not_sent` is recorded only
  from positive pre-write phase evidence under a live fenced lease.
- An ambiguous `POST`, `PUT`, `PATCH`, or `DELETE` becomes
  `indeterminate`/`inconclusive` by default.
- An ambiguous `GET`, `HEAD`, or `OPTIONS` creates a new attempt with new trace and
  span IDs.
- Explicit unsafe replay is versioned and produces a new attempt.
- Job redelivery without an ambiguous dispatch can no-op and does not imply an
  HTTP retry.
- DNS rebinding/private-address, cross-origin redirect credentials, TLS, timeout,
  oversized body, invalid secret, and redaction fallback scenarios are safe.
- A rejected redirect hop receives no TCP/TLS/HTTP connection; its received `3xx`
  evidence, certainty, rejection code, and redacted Location remain consistent.
- Selected-IP dialing retains the original HTTP authority and TLS SNI/hostname;
  hostname mismatch, proxy inheritance, transport retry, and cross-origin
  connection reuse are rejected by executable local tests.
- Stored `verify_tls: false` remains readable but fails before DNS/socket activity.
- Logs, spans, database records, API errors, and test output contain no resolved
  secrets or fixed sensitive headers.

### Exit criteria

- A single test and ordered suite run from API request to durable redacted
  observation.
- Worker termination at every durable checkpoint has a deterministic recovery
  result.
- The implementation makes no exactly-once claim and never auto-retries a
  potentially non-idempotent ambiguous request.
- The locked HTTP transport passes the DNS-pinning/SNI feasibility gate, and any
  future transport dependency upgrade must requalify that behavior.

## Milestone 4: Deterministic evaluation and baseline management

Status: **PASS**. M4-00 through M4-06 are complete at accepted implementation SHA
`8e280be334b8fa71044005ad6557a3b91f0dd828`. The frozen decisions and executable
acceptance criteria remain in the
[implementation packet](implementation/milestone-4.md), the completed dependency
ledger is in the [task plan](development/milestone-4-plan.md), and evidence is in
the [acceptance handoff](development/milestone-4-handoff.md). The independent
M4-06 review found that JSON responses without configured redaction pointers were
classified as text; the accepted SHA classifies `application/json` and `+json`
responses as JSON and includes a regression test. Exact-SHA owner-supplied CI
passed all three jobs with 500/500 backend and 12/12 frontend tests.

### Goal

Classify functional regressions, advisory changes, and performance warnings with
explainable evidence and immutable baseline history.

### Deliverables

- Assertion/selector domain types, deterministic normalizers, and evaluation
  records.
- Verdict aggregation with the exact precedence in `MVP.md`.
- `Baseline` and `BaselineActivation` persistence and services.
- Baseline list, create/promote, and activate/rollback endpoints.
- Eligibility and policy-fingerprint compatibility enforcement.
- Change evidence linking executions to relevant definition/baseline changes.

### Required tests

- Unselected volatile fields do not change required comparison results.
- Required, advisory, performance, baseline-required, inconclusive, and
  not-evaluated cases produce their specified distinct verdicts.
- Integer/decimal comparisons do not depend on binary floating-point behavior.
- Invalid normalizer inputs fail explicitly without coercion.
- Exact body comparison never occurs by default.
- Promotion creates a version and activation history without mutating old rows.
- An incompatible fingerprint cannot be activated or compared.
- Baseline values remain usable after source response-artifact expiry.

### Exit criteria

- API-level acceptance tests demonstrate every verdict category.
- A result explains the exact configured rule and bounded redacted evidence.
- No baseline changes without explicit operator action.

## Milestone 5: Trace correlation and evidence

Status: **PASS — complete** at accepted implementation SHA
`18d72162c26575778ab94556d0f85c2c76ecc75d`. The [Milestone 5 contract
handoff](development/milestone-5-handoff.md), [implementation
contract](implementation/milestone-5.md), [task plan](development/milestone-5-plan.md),
and accepted [ADR 0011](architecture/ADRs/0011-trace-correlation-and-evidence-contract.md)
remain authoritative. All M5 slices and the independent M5-06 acceptance gate
are complete.

The owner confirmed exact-SHA GitHub Actions success for Backend and PostgreSQL,
Frontend and Contracts, and Docker Compose, with 551/551 backend tests and
12/12 frontend tests passing. The final disposable Compose journey used real
Tempo 2.9.0 OTLP ingestion and indexed `sentinel.attempt.id` search through
the actual correlation worker; the linked reference persisted without changing
the functional verdict. The M5 handoff records the timing, persistence,
privacy, and controlled-indexing evidence.

### Goal

Make direct trace correlation reliable and missing/partial telemetry graceful.

### Deliverables

- OpenTelemetry instrumentation for Sentinel API, worker, PostgreSQL, target HTTP,
  and Tempo client boundaries.
- W3C Trace Context and Baggage injection with protected Sentinel keys.
- `TraceReference` persistence and separate `correlate_trace` jobs.
- Direct Tempo lookup by trace ID, expected-client-span validation, bounded
  delayed-ingestion retries, and correlation state API.
- Optional capability-gated baggage-attribute search for indirect linked traces.
- Safe Tempo UI links and service/deployment attribute change evidence.
- Example instrumented target used only by integration/end-to-end tests.

### Required tests

- Injected `traceparent` contains the persisted primary trace and client span IDs.
- One suite execution maps to multiple attempts/traces without identity collapse.
- Replay produces distinct trace context.
- Delayed ingestion moves `missing` to `available` without changing verdict.
- Missing, sampled-out, partial, expired, linked-only, multiple-linked, and
  Tempo-unavailable cases are distinguished.
- Attribute search disabled/unsupported does not break direct correlation.
- Telemetry contains no secrets, protected headers, or bodies.
- Service version differences are labeled evidence, not root cause.

### Exit criteria

- A Compose acceptance run follows an API request into an instrumented test
  service and opens the matching Tempo trace.
- Stopping Tempo leaves execution and regression behavior fully functional.
- Broken propagation produces an honest partial/missing explanation.

## Milestone 6: MVP user interface

### Goal

Expose the complete supported workflow without adding backend features.

The preparation boundary and unresolved interaction decisions are recorded in
the [Milestone 6 UI handoff](development/milestone-6-handoff.md). It does not
authorize implementation.

### Deliverables

- Project/environment setup and versioned test/suite authoring.
- Execution start, polling, filtering, and history.
- Attempt detail with lifecycle, verdict, assertions, selected baseline diffs,
  performance warnings, transport outcomes, and truncation/redaction notices.
- Baseline eligibility review, explicit promotion confirmation, history, and
  compatible rollback.
- Trace states, direct/indirect provenance, Tempo links, and missing/partial
  explanations.
- Definition/baseline/deployment evidence timeline using only backend-provided
  facts.
- Keyboard-accessible controls, focus management, semantic status text, and
  non-color-only verdict indicators.

### Required tests

- Components render every lifecycle, verdict, and trace state from typed fixtures.
- Unsafe replay and baseline promotion require explicit, unambiguous confirmation.
- Secrets never round-trip into form responses.
- Polling stops on terminal execution state while trace reconciliation can update
  independently.
- Accessibility checks cover the main author-run-investigate-promote workflow.

### Exit criteria

- A user can complete the full MVP journey from the browser.
- The UI does not invent classification or causal language absent from the API.
- Frontend and OpenAPI types have no drift.

## Milestone 7: Retention, hardening, and release candidate

### Goal

Prove the entire documented contract under failure and package a supportable
self-hosted MVP.

### Deliverables

- Idempotent, chunked retention job and operator-configurable bounded policies.
- Remote-bind bearer-token guard, CORS restrictions, and startup validation.
- Operational documentation for configuration, secret injection, private target
  allowlists, backup responsibility, upgrades, and Tempo retention.
- Database indexes verified against representative query plans and bounded test
  history.
- End-to-end failure matrix and Compose smoke test.
- Open-source license, contribution guide, security reporting policy, and release
  notes.

### Required tests

- Retention removes artifacts at 7 days and metadata at 30 days while preserving
  active baseline values and immutable definition history.
- Cleanup can restart mid-batch without corrupting references.
- Non-loopback startup without a bearer token fails closed.
- API/worker/PostgreSQL/Tempo restarts yield the documented outcomes.
- A full privacy test scans logs, spans, API payloads, and PostgreSQL artifacts for
  canary secrets.
- Fresh-install and supported-upgrade Compose acceptance runs pass.

### Exit criteria

- Every acceptance criterion in `MVP.md` maps to a passing automated test or a
  repeatable documented acceptance step.
- Known limitations and recovery procedures are published.
- No excluded MVP feature or extra required infrastructure has entered the
  release.

## Post-MVP decision backlog

These are evaluation triggers, not committed features:

- scheduling and notifications;
- richer protocol support;
- team authentication/authorization;
- dedicated broker adoption after ADR 0002's measured thresholds are met;
- distributed workers after security and queue semantics are redesigned;
- additional deterministic comparison primitives based on user evidence.

Each item requires its own product decision, threat/scope review, and ADR where
appropriate. None should shape MVP infrastructure prematurely.
