# Milestone 5 contract handoff

Status: **M5-00 contract freeze accepted; M5-01+ implementation planning only**.
Milestone 4 is accepted with status **PASS** at implementation SHA
`8e280be334b8fa71044005ad6557a3b91f0dd828`. This handoff records the accepted
M5 contract and the implemented seams that M5-01 may build on. It authorizes no
M5-01+ production code, migration execution, worker, API, frontend, generated
artifact, CI, or runtime rollout.

## Authority and scope

- [AGENTS.md](../../AGENTS.md), the [MVP](../MVP.md), the
  [Milestone 5 roadmap scope](../ROADMAP.md#milestone-5-trace-correlation-and-evidence),
  the [architecture](../architecture/README.md), and accepted ADRs remain
  authoritative.
- [ADR 0005](../architecture/ADRs/0005-opentelemetry-trace-correlation.md)
  fixes the identity, propagation, direct-correlation, delayed-ingestion,
  optional linked-search, privacy, and verdict-independence requirements.
- [ADR 0006](../architecture/ADRs/0006-security-privacy-retention.md) prohibits
  secrets, protected headers, bodies, and unsafe error detail in spans,
  persistence, logs, problems, and test artifacts.
- [ADR 0002](../architecture/ADRs/0002-postgresql-job-queue.md) governs
  at-least-once delivery and lease fencing.
  [ADR 0007](../architecture/ADRs/0007-outbound-execution-safety.md) and
  [ADR 0008](../architecture/ADRs/0008-http-dispatch-outcomes-and-tls-policy.md)
  govern the dispatch checkpoint, replay identity, and target-request boundary.
- The accepted [M3 implementation packet](../implementation/milestone-3.md)
  supplies per-attempt trace/span creation and persistence before target I/O.
  The accepted [M4 packet](../implementation/milestone-4.md) supplies functional
  verdicts that telemetry must never rewrite.
- Use the [development workflow](workflow.md) for ownership and isolation and the
  [quality gates](quality-gates.md) for candidate evidence.

M5 includes trace-reference persistence, asynchronous Tempo reconciliation,
bounded trace evidence, public attempt correlation state, safe navigation links,
and the remaining required process-boundary instrumentation. It excludes the M6
trace UI, a replacement trace viewer, full trace storage in PostgreSQL,
proprietary headers or agents, guaranteed discovery after broken propagation,
root-cause claims, and the M7 retention worker.

## Implemented starting point

The accepted M4 repository already provides these seams:

- `OpenTelemetryTraceLifecycle` creates a new root client span for every attempt,
  preserves validated unrelated baggage, injects W3C `traceparent` and baggage,
  and overwrites protected trace-context headers.
- The dispatch checkpoint atomically stores the request fingerprint, 32-character
  lowercase primary trace ID, 16-character client span ID, and
  `possibly_sent` certainty before DNS or target network I/O. Replay creates a
  fresh attempt, trace ID, and span ID.
- `test_attempts` stores `primary_trace_id` and `client_span_id`; its state checks
  require them from `dispatching` onward. Attempt summary/detail responses expose
  those two nullable identifiers.
- Worker job handling has an internal `worker.handle` span. Both API and worker
  create OTLP-capable providers with fixed `service.name` resources; the target
  request span records method, response status, transport outcome, and dispatch
  certainty using a closed safe attribute set.
- Definition validation rejects user-supplied `traceparent`, `tracestate`, and
  Sentinel-owned baggage keys while preserving validated unrelated baggage.
- Compose runs Tempo 2.9.0 with OTLP/HTTP ingestion, local storage, seven-day
  block retention, loopback-published HTTP/OTLP ports, and a readiness probe.
  `SENTINEL_TEMPO_URL` is the internal query/readiness base and
  `SENTINEL_OTLP_ENDPOINT` is the export endpoint.
- API readiness reports Tempo as `available` or `unavailable` without making the
  API unready. Functional execution and M4 regression classification have no
  Tempo dependency.

The following M5 capabilities do not yet exist:

- no `trace_references` persistence or correlation-state repository;
- no `correlate_trace` job, deadline, lookup-attempt counter, or reconciliation
  application service;
- no Tempo query adapter or bounded response parser;
- no persisted linked traces, service/deployment evidence, or Tempo navigation
  links;
- no trace-reference fields in `AttemptDetail`, runtime OpenAPI, or generated
  TypeScript; and
- no accepted instrumentation implementation for FastAPI requests, SQLAlchemy
  calls, or Tempo queries. Merely constructing an API tracer provider does not
  instrument those boundaries.

One schema constraint requires explicit M5 treatment: `jobs.subject_id` currently
has a foreign key to `executions.id`, and the job store assumes every job subject
is an execution. A `correlate_trace` job cannot safely use a trace-reference ID
without an M5-00 persistence decision and migration.

## Accepted M5 requirements

### Identity and propagation

- Execution ID, execution-item ID, attempt ID, trace ID, and client span ID remain
  distinct identities. One suite may have many attempts and traces.
- Every possible replay uses a new attempt ID, trace ID, and client span ID. The
  predecessor remains immutable evidence.
- Every dispatched attempt has exactly one primary correlation reference with
  `relation=primary` and `correlation_source=sentinel_context`; an attempt may
  have zero or more linked references.
- The persisted primary IDs must match the client span and injected
  `traceparent`. User definitions cannot replace Sentinel-owned context.

### Direct Tempo correlation

- Direct lookup by the known primary trace ID is required and authoritative.
- The reconciler validates the stored client span ID rather than accepting a
  trace-ID match alone.
- Accepted correlation vocabulary is `pending`, `missing`, `available`,
  `partial`, `tempo_unavailable`, and `expired`.
- Missing, sampled-out, partial, context-broken, expired, linked-only,
  multiple-linked, and Tempo-unavailable cases remain distinguishable.
- Attribute search is optional and capability-gated. Disabling or lacking search
  support cannot weaken direct trace-ID correlation.

### Delayed arrival and independence

- Reconciliation is separate durable work with bounded backoff until a
  configurable deadline whose accepted default is 60 seconds after the attempt
  becomes terminal.
- `pending`, `missing`, `partial`, and `tempo_unavailable` may be rechecked before
  the deadline. A delayed trace may move to `available` without rewriting the
  attempt, item, or execution verdict.
- Tempo latency, outage, malformed data, sampling, missing spans, and retention
  expiry never block execution completion or change a functional result.
- API reads return stored correlation state; they do not synchronously query
  Tempo.

### Evidence and privacy

- Sentinel stores correlation metadata and bounded derived evidence, not full
  trace payloads or a second trace store.
- Request/response bodies, authorization data, cookies, secret values, full URLs
  with sensitive query values, raw Tempo errors, and unbounded span attributes or
  events are prohibited from persistence, logs, spans, API responses, and test
  snapshots.
- Only exact attempt baggage attributes may support indirect discovery. Time,
  service name, or proximity alone cannot create a link under concurrency.
- Linked traces are labeled indirect and are not drawn as parent/child unless
  trace data proves that relationship.
- Service/deployment/version differences are evidence that changed before a
  result, never a root-cause claim.
- Persisted identifiers and provenance may outlive Tempo data. Tempo trace
  retention remains independent from PostgreSQL retention.

### Recovery and idempotency

- PostgreSQL job delivery remains at least once and fenced. A reclaimed
  reconciliation lease permits another read-only Tempo lookup, never a target
  request or replay.
- Queue delivery count, target HTTP attempt count, and trace lookup count remain
  separate fields and concepts.
- Duplicate delivery or a crash between Tempo lookup and persistence must not
  create duplicate primary/linked references, regress terminal evidence, alter a
  verdict, or enqueue an unbounded retry chain.
- Time, IDs, Tempo responses, capability detection, and retry scheduling must be
  injectable. Tests use no sleeps.

## M5-00 resolution record

The [M5 implementation contract](../implementation/milestone-5.md),
[M5 task plan](milestone-5-plan.md), and [ADR 0011](../architecture/ADRs/0011-trace-correlation-and-evidence-contract.md)
record the eleven approved decisions as one implementation contract. The
contract is internally consistent with M1-M4 and is accepted for M5 planning;
implementation still requires the slice-specific workflow gates below.
Accepted ADR 0005 is not edited in place. The detailed checklist below remains
the audit trail for each question.

| Decision | Accepted resolution | Status |
| --- | --- | --- |
| Relational shape and migration | `trace_references` revision `0011` after `0010`; one primary, deduplicated linked rows, bounded JSON evidence, legacy fields preserved, no historical backfill | Accepted contract; implementation pending |
| Queue subject and atomic enqueue | Keep execution `subject_id`; add nullable reference FK and unique `correlate_trace` row; create reference at dispatch and enqueue atomically at terminal checkpoint | Accepted contract; implementation pending |
| Retry and exhaustion | 60-second terminal-relative deadline; `0,1,3,7,15,31,59` lookup seconds; outage remains `tempo_unavailable`, no trace at deadline becomes `expired` | Accepted contract; implementation pending |
| Tempo wire protocol | Pinned Tempo 2.9.0 direct `/api/traces/{trace_id}`, optional tags search, bounded HTTP/TLS/size limits and closed errors | Accepted contract; implementation pending |
| Available versus partial | Client span present and valid is `available`; trace without it or malformed/incomplete evidence is `partial`; downstream absence is unknown evidence | Accepted contract; implementation pending |
| Linked discovery | Opt-in exact `sentinel.attempt.id`, capability-gated, max 16, deterministic ID ordering, indirect provenance only | Accepted contract; implementation pending |
| Persisted evidence | Versioned 64 KiB allowlist, max 32 services/256 spans and same revision-scoped comparison anchor; no raw trace | Accepted contract; implementation pending |
| Public API | Additive attempt-detail array, primary first and max 17, legacy fields retained, stored reads only, no M5 refresh route | Accepted contract; implementation pending |
| Navigation URL | Internal URL never emitted; optional validated `{trace_id}` operator template, otherwise null | Accepted contract; implementation pending |
| Instrumentation | Manual safe spans with closed attributes; no SQL/headers/URLs/bodies/exceptions/secrets | Accepted contract; implementation pending |
| Retention handoff | References/evidence follow attempt metadata and cascade; Tempo retention independent; M7 owns cleanup/deletion/privacy scans | Accepted contract; implementation pending |

Any future change that affects an accepted architectural invariant requires an
amended contract/new ADR before implementation.

## Decision checklist (accepted contract)

Each item below is retained as the original review prompt; its accepted answer is
recorded in the linked ADR sections and summarized in the resolution table.

1. **Relational shape and migration.** Freeze `trace_references` columns,
   constraints, indexes, ownership, deletion behavior, primary cardinality,
   linked-reference uniqueness, timestamp/error fields, and any bounded evidence
   tables or columns. Allocate the post-`0010` migration only after confirming the
   current single head. Decide whether the existing attempt ID columns remain the
   canonical primary identity, are constrained to the primary reference, or are
   safely migrated without duplication, including whether historical M3/M4
   dispatched attempts receive references or an explicit legacy projection.
2. **Queue subject model and enqueue transaction.** Choose an enforceable FK model
   for `correlate_trace` work; the current execution-only `jobs.subject_id` cannot
   reference a trace row. Freeze when the primary reference is created, when the
   reconciliation job is enqueued after terminal attempt state, how ambiguous and
   replay-predecessor attempts participate, and how the job observes the 60-second
   terminal-relative deadline.
3. **Retry schedule and exhaustion semantics.** Define the exact backoff,
   lookup-attempt bound, job-delivery behavior, deadline calculation, clock
   source, and final states. In particular, settle whether `partial` remains
   `partial` after deadline, whether an outage at deadline remains
   `tempo_unavailable`, and the only transition that produces `expired`.
4. **Tempo read protocol.** Freeze the Tempo HTTP endpoint/version used for direct
   trace lookup, timeout/TLS/response-size limits, response validation, error-code
   vocabulary, capability detection, and compatibility with the pinned Compose
   image. Raw Tempo payloads and errors must not cross the adapter port.
5. **Available versus partial.** Define the minimum validated span graph. ADR 0005
   requires the expected client span and treats incomplete expected context as
   partial, and the accepted M5-00 contract states whether a client span alone is `available`, which
   downstream/server evidence is expected, and how malformed, duplicate, or
   truncated span sets classify.
6. **Linked discovery.** Freeze the opt-in configuration, exact indexed attribute
   names for the two Sentinel baggage values, query limits, pagination/bounds,
   deduplication, multiple-match ordering, provenance, and unsupported-capability
   behavior. No timestamp/service-name fallback is permitted.
7. **Persisted trace evidence.** Decide the allowlisted service/resource/span
   fields, evidence cardinality and byte caps, deterministic ordering, freshness,
   and comparison anchor for service-version/deployment change evidence. Decide
   what survives Tempo expiry without storing full traces or inventing causal
   language.
8. **Public API shape.** Freeze the additive `AttemptDetail` trace-reference and
   evidence schemas, ordering and bounds, pending/legacy projections, link
   presence, and problem behavior. Decide whether MVP needs only the existing
   `GET /api/v1/attempts/{attempt_id}` or an additional refresh command; the
   endpoint inventory currently promises trace references on attempt detail and
   does not approve another route.
9. **Tempo navigation URL.** The internal `tempo_url` may not be browser-reachable.
   Freeze a separate optional operator-facing base URL or document why one base is
   sufficient, plus safe URL construction, validation, and behavior when no UI
   URL is configured. Never echo arbitrary Tempo query data into a link.
10. **Instrumentation boundary.** Freeze the minimum API, worker, PostgreSQL,
    target HTTP, and Tempo client spans; propagation/parenting; stable names;
    closed safe attributes; exception/status behavior; and whether installed
    libraries suffice. Avoid auto-instrumentation that captures SQL parameters,
    headers, URLs, or bodies unless its safety is executable and explicit.
11. **Retention handoff.** Define M5 schema compatibility with the accepted
    30-day attempt/metadata policy and seven-day Tempo policy. M5 may expose expiry
    states and safe provenance, but M7 retains ownership of cleanup execution,
    restartability, project deletion behavior, and release-wide privacy scans.

## Implementation slices

This ordering is recorded in the [M5 task plan](milestone-5-plan.md). It remains
implementation planning until each slice passes its workflow gate.

### M5-00 — Contract freeze and acceptance matrix — accepted

- Accepted state transitions, schema/FKs, queue subject model, retry/deadline
  semantics, Tempo adapter port, evidence bounds, API shapes, configuration, and
  named acceptance cases.
- Reconcile ADR 0005's available/partial/deadline wording without rewriting it.
  Add or supersede an ADR only if the decision changes accepted architecture.
- Produced the reviewed implementation packet and task plan. No migration,
  route, generated artifact, or production adapter was created in this slice.

### M5-01 — Trace-reference and durable-work persistence

- Implement the allocated migration, domain values/ports, primary and linked
  reference repositories, correlation-state transition rules, indexes, and the
  chosen job-subject FK model.
- Atomically create the primary reference with dispatch identity and enqueue or
  schedule reconciliation at the frozen terminal boundary.
- Prove legacy M1-M4 preservation, unique primary identity, linked deduplication,
  concurrent claims, stale fencing, upgrade/downgrade/drift, and bounded retry
  metadata against PostgreSQL.

### M5-02 — Direct Tempo lookup adapter

- Implement direct trace-ID lookup behind an explicit telemetry port using the
  frozen Tempo protocol, limits, timeouts, TLS policy, and safe error codes.
- Parse only the allowlisted fields needed to validate the expected client span
  and derive bounded evidence. Reject malformed or oversized responses without
  persisting raw payloads.
- Instrument the Tempo client with the frozen safe span contract.

### M5-03 — Fenced reconciliation and delayed arrival

- Implement the `correlate_trace` application service and worker handler with
  injected clock/scheduler, deadline-aware backoff, idempotent state writes, and
  no target-dispatch capability.
- Cover crash windows before lookup, after lookup, and after persistence;
  concurrent/reclaimed delivery; delayed `missing`/`partial` convergence; outage
  exhaustion; and verdict immutability.

### M5-04 — Optional linked traces and bounded change evidence

- Add capability-gated exact baggage-attribute search, linked-reference
  deduplication and ordering, indirect provenance, and multiple-match handling.
- Persist only the frozen allowlisted service/deployment evidence. Direct lookup
  remains complete when search is disabled or unsupported.

### M5-05 — Attempt API, navigation links, instrumentation, and typed handoff

- Publish stored correlation state and bounded evidence through the frozen
  attempt-detail shape, add safe Tempo links, and regenerate runtime OpenAPI and
  TypeScript once under coordinator ownership.
- Complete the accepted API, worker, PostgreSQL, target HTTP, and Tempo client
  instrumentation boundaries without adding product UI.
- Add backend contract tests and frontend typed-client consumption tests; M6 owns
  rendering and interaction.

### M5-06 — Independent acceptance and milestone integration

- Independently verify the complete M5 matrix on one exact integrated candidate,
  including delayed ingestion, Tempo outage, recovery/concurrency, privacy sinks,
  migration round trips, generated-contract drift, and the Compose trace journey.
- Record exact candidate identity, commands/counts, migration SQL, Tempo/Compose
  identity, review findings and resolutions, and separately authorized exact-SHA
  remote CI evidence.

## Required test and acceptance coverage

M5-00 should turn the following into executable named cases:

1. persisted primary trace/span IDs exactly match the injected `traceparent` and
   exported client span, including preserved unrelated baggage and rejected
   Sentinel-owned input;
2. one suite maps to multiple attempts/traces and every replay has distinct
   attempt/trace/span identities without collapsing its predecessor;
3. direct lookup distinguishes present trace plus expected client span, trace
   without that span, malformed/oversized response, not found, sampled out,
   retention expiry, and Tempo transport/service failure;
4. delayed arrival follows every accepted state transition before and at the
   deadline using an injected clock and deterministic scheduler, with no sleeps;
5. at-least-once and concurrent reconciliation produce one primary reference,
   deduplicated linked references, monotonic timestamps/counters, bounded jobs,
   and no stale-fence write;
6. crashes at every lookup/persist/complete checkpoint resume idempotently and
   never dispatch or replay a target request;
7. disabled/unsupported attribute search leaves direct correlation functional;
   exact attempt baggage may return zero, one, or multiple deterministically
   ordered indirect references without inferred parentage;
8. attempt reads expose every status, legacy/pending projections, bounded evidence,
   safe provenance and links, stable ordering, and no synchronous Tempo call;
9. stopping Tempo leaves execution, evaluation, baseline, and API readiness
   behavior functional while correlation records the frozen outage state;
10. synthetic canaries are absent from PostgreSQL, logs, spans, metrics, API
    payloads, problems, Tempo queries/links, generated fixtures, and failures;
11. API, worker, PostgreSQL, target HTTP, and Tempo client spans use only the
    frozen names/attributes and do not capture SQL parameters, headers, URLs,
    bodies, exception text, or resolved secrets; and
12. Compose sends one request to an instrumented synthetic target, observes the
    matching primary trace after delayed ingestion, validates the client span,
    exposes a safe Tempo link, then proves the same functional result with Tempo
    stopped.

Migration acceptance includes visible upgrade/downgrade SQL, `head -> base ->
head`, Alembic drift, preservation of accepted M1-M4 rows, one-head proof, and
concurrent job/reference tests in a dedicated disposable PostgreSQL database.
Contract acceptance includes runtime OpenAPI/generated TypeScript drift and typed
frontend consumption; it does not require an M6 UI.

## M5 exit criteria

- Each dispatched attempt has one durable primary correlation reference whose
  identity matches injected W3C context.
- Direct known-ID reconciliation converges after delayed ingestion and reports
  missing, partial, expired, and outage states honestly.
- Optional linked discovery is capability-gated, exact, bounded, and labeled
  indirect; direct lookup does not depend on it.
- Attempt reads expose stored bounded trace evidence and safe navigation without
  querying Tempo synchronously or changing a functional verdict.
- Stopping Tempo leaves execution, evaluation, baseline, and definition behavior
  fully functional.
- Privacy checks establish that no secret, protected header, body, unsafe URL,
  SQL parameter, or raw Tempo payload crossed an approved sink.
- PostgreSQL/migration, backend, frontend/contract, and full Compose acceptance
  pass on one exact candidate, followed by matching exact-SHA CI after separately
  authorized publication.

## Readiness for M5-00

This handoff is based on accepted M4 SHA
`8e280be334b8fa71044005ad6557a3b91f0dd828`. Once this documentation-only closure
is integrated, M5-00 is complete at the resulting documentation commit.
Production implementation readiness is intentionally **not** granted: M5-01
requires its own task packet and gates. M5-00 preserves one writer per file,
coordinator ownership of migration allocation and generated contracts, separate
disposable databases and ports, and independent
architecture/API/persistence/recovery/privacy review.

No M5-01+ production work, migration implementation, runtime API, worker,
frontend, generated artifact, or CI change is authorized by this handoff.
