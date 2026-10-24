# ADR 0011: Trace correlation and evidence contract

- Status: **Accepted**
- Date: 2026-10-23
- Extends: ADR 0002, ADR 0005, ADR 0006, ADR 0007, and ADR 0008

## Context

ADR 0005 accepts W3C propagation, one primary trace per dispatched attempt,
optional baggage-based linked traces, delayed ingestion, and verdict
independence. The accepted M4 implementation persists the primary trace and
client-span IDs before target I/O, but it does not yet persist correlation
state, query Tempo, or expose bounded trace evidence. This ADR freezes the
implementation-level contract needed to do that without changing accepted
execution, replay, regression, or privacy behavior.

This is the supporting M5-00 contract. It does not modify ADR 0005 in place and
is normative for M5 implementation slices after integration.

## Decision

### 1. TraceReference persistence and compatibility

M5-00 reserves Alembic revision `0011`, with `down_revision = "0010"`; the
coordinator confirmed that `0010` is the only current head. M5-01 will create
the migration that adds `trace_references`:

| Column | Contract |
| --- | --- |
| `id` | UUID primary key |
| `attempt_id` | UUID, `test_attempts.id`, `ON DELETE CASCADE` |
| `relation` | `primary` or `linked` |
| `trace_id` | 32 lowercase non-zero hexadecimal characters |
| `span_id` | 16 lowercase non-zero hexadecimal characters; required for `primary`, nullable for `linked` |
| `correlation_source` | `sentinel_context` for `primary`, `baggage_attribute_search` for `linked` |
| `status` | `pending`, `missing`, `available`, `partial`, `tempo_unavailable`, or `expired` |
| `first_checked_at`, `last_checked_at` | nullable UTC `timestamptz` |
| `deadline_at` | non-null UTC `timestamptz` |
| `lookup_attempt_count` | integer `0..7`; distinct from queue delivery and HTTP-attempt counts |
| `last_error_code` | nullable closed safe code, max 64 bytes |
| `evidence_schema_version` | non-null smallint, currently `1` |
| `evidence_json` | nullable bounded JSON object, canonical UTF-8 <= 65536 bytes |
| `created_at`, `updated_at` | non-null UTC `timestamptz` |

Constraints and indexes are:

- one primary reference per attempt (partial unique index on `attempt_id` where
  `relation = 'primary'`);
- linked references are unique by `(attempt_id, relation, trace_id)`;
- relation/source/span shape is enforced by checks;
- indexes support attempt-detail reads `(attempt_id, relation, created_at, id)`;
  due reconciliation `(status, deadline_at, updated_at)`; and trace lookup
  `(trace_id)`;
- evidence is an object with `schema_version = 1`, and the adapter rejects
  values that exceed the byte bound before persistence.

The existing `test_attempts.primary_trace_id` and `client_span_id` remain the
legacy canonical projection for M1-M4 and must equal the new primary reference
when one exists. Historical attempts are not backfilled, do not receive a
Tempo job, and read as `trace_references: []`; their legacy fields remain
unchanged. New dispatches create the primary reference in the same fenced
transaction as the existing checkpoint. No baseline row points to a trace
reference, and trace metadata is deleted with its attempt under the M7
retention/deletion policy.

### 2. Durable correlation work and atomic boundaries

M5 extends `jobs` with nullable `trace_reference_id`, a foreign key to
`trace_references.id` with `ON DELETE CASCADE`, while retaining
`subject_id -> executions.id` as the owning execution identity. A
`correlate_trace` row must have both the owning execution subject and a
primary trace-reference ID; execution jobs must have a null trace-reference
ID. A unique constraint on `trace_reference_id` for `kind = 'correlate_trace'`
prevents duplicate active or historical work. The lease carries the optional
reference ID; claiming, heartbeating, fencing, and delivery limits remain the
accepted ADR 0002 behavior.

The transaction boundaries are fixed:

1. The dispatch checkpoint writes the attempt IDs, legacy trace/span columns,
   and the `pending` primary reference before DNS or target I/O.
2. Every terminal attempt checkpoint (`response_received`, `transport_failed`,
   `replay_scheduled`, or `indeterminate`) sets the terminal-relative deadline
   and inserts the correlation job idempotently in the same transaction.
3. Preparation failure creates neither a reference nor a job.
4. A correlation handler has read-only Tempo and PostgreSQL capabilities. Its
   queue `start`/`complete` path must not call the existing execution-subject
   lifecycle transition or mark the execution complete; it cannot call the
   target adapter, create a replay, or alter any verdict.

### 3. Reconciliation window, retries, and terminal states

The default deadline is 60 seconds after the attempt's terminal timestamp. It
is one deployment setting, not a per-test input. The deterministic schedule is
an immediate lookup followed by delays of 1, 2, 4, 8, 16, and 28 seconds, for
at most seven lookups. The clock and scheduler are injectable; tests do not
sleep. Queue delivery count remains bounded by the existing job limit and is
separate from `lookup_attempt_count`. One claimed delivery runs the due
read-only lookup loop with lease heartbeats; it does not create one queue row per
scheduled lookup. A crash resumes from the persisted lookup counter on the next
delivery, while the existing delivery limit bounds crash recovery.

Before the deadline, `missing`, `partial`, and `tempo_unavailable` may return
to `pending` for another lookup. A found trace plus the expected stored client
span is `available`. A trace without that span, or a malformed/incomplete
response that still proves some trace evidence, is `partial`. A not-found
lookup is `missing` while the window is open and becomes `expired` only when the
deadline passes with no trace. A Tempo outage stays `tempo_unavailable` when the
window ends in outage; it is not relabeled as missing or expired. If a job
reaches queue-delivery exhaustion before any lookup completes, the reference is
`tempo_unavailable` with `correlation_delivery_exhausted`; otherwise its safe
error code is recorded and it keeps the last truthful state. None of these
transitions changes a functional verdict.

### 4. Tempo adapter and capability detection

The adapter uses the pinned Compose Tempo `2.9.0` HTTP API: direct lookup is
`GET /api/traces/{trace_id}` and optional search is `GET /api/search` with an
exact indexed baggage attribute. The protocol is verified again when the image
changes; M5 does not silently switch API versions. The official API surface is
documented by [Grafana Tempo's HTTP API reference](https://grafana.com/docs/enterprise-traces/latest/api_docs/).

The adapter has connect/read/write/total timeout limits of 1/2/1/2 seconds,
rejects redirects, verifies TLS by default, caps each response at 1 MiB, and
accepts only valid JSON with the required trace/span identity fields. It emits
closed safe error codes: `not_found`, `unavailable`, `timeout`,
`bad_response`, `oversized_response`, `unsupported`, `transport_error`, and
`invalid_trace`. Raw response bodies, URLs with sensitive query data, and
exception text never cross the telemetry port.

Direct lookup is required even when search is unavailable. Search capability is
probed once per adapter lifetime with `GET /api/search/tags?scope=span`; an
unsupported or failed probe disables only linked discovery and is not a
correlation failure.

### 5. Available versus partial

`available` requires the response to identify the requested trace, contain the
exact stored client span ID, and pass span-ID and trace-ID validation. It does
not require downstream target spans: absent downstream spans are recorded as
unknown evidence rather than treated as a functional failure. `partial` means
the trace exists but the expected client span is absent, the trace payload is
malformed/incomplete, or context continuity cannot be validated. A not-found
response remains `missing`/`expired`, and a transport/service failure remains
`tempo_unavailable`.

### 6. Linked traces and deterministic bounds

Linked discovery is disabled by default and is enabled only by an operator
setting. The only query is the exact `sentinel.attempt.id=<UUID>` baggage
attribute; execution ID, time, service name, or proximity cannot create a link.
The query window is the attempt dispatch time through its correlation deadline,
the result count is capped at 16, and each response is capped at 1 MiB. Results
are deduplicated, exclude the primary trace, and are ordered by lowercase trace
ID. Search results carry `relation=linked` and indirect provenance. A search
that is disabled, unsupported, malformed, or empty leaves direct correlation
unchanged and creates no guessed reference.

### 7. Bounded evidence and comparison anchors

Evidence is schema version 1 and contains only derived, allowlisted fields:
`primary_span_found`, `trace_span_count` (<=256), `error_span_count` (<=256),
`services` (<=32 sorted entries with bounded `service.name`, `service.version`,
deployment-environment, and source/deployment-revision strings),
`linked_match_count`, `context_continuity` (`connected`, `broken`, or
`unknown`), and an optional comparison anchor. No body, header, URL, SQL,
resource instance ID, arbitrary attribute, event, or raw span payload is stored.

The comparison anchor is the most recent `available` primary reference from the
same test-case/environment and the same pinned revision IDs, excluding replay
predecessors and attempts not included in the verdict. It records only bounded
changed service/deployment keys. It is evidence of change before a result, not
a baseline, verdict input, or root-cause claim. If no compatible reference
exists, the anchor is null.

### 8. Additive API and navigation

`GET /api/v1/attempts/{attempt_id}` gains an additive `trace_references` array,
ordered primary first and then linked trace ID, capped at 17. Each item exposes
the persisted IDs, relation, source, state, timestamps, deadline, lookup count,
safe error code, and bounded derived evidence. Existing nullable legacy
`primary_trace_id` and `client_span_id` fields remain. API reads use stored data
only and never call Tempo synchronously. M5 adds no refresh route; a later
refresh action, if required, must be a separate accepted contract and may only
reconcile stored references. This keeps ADR 0005's optional page-refresh
capability available for a later accepted read-side action without inventing an
M5 route or making an API read depend on Tempo.

The internal `SENTINEL_TEMPO_URL` is never emitted to browsers. An optional
operator-only `SENTINEL_TEMPO_TRACE_URL_TEMPLATE` may contain exactly one
`{trace_id}` placeholder, must be an absolute `http`/`https` URL without user
info, and is validated at configuration load. The API emits a link only after
substituting a validated lowercase trace ID; without the template it emits
`null`. No arbitrary Tempo response data is used to build a link.

### 9. Instrumentation, retention, and safety

M5 adds manual safe spans named `sentinel.api.request`, `sentinel.job.claim`,
`sentinel.job.handle`, `sentinel.trace.reconcile`, `sentinel.db.operation`,
`sentinel.tempo.lookup`, and `sentinel.tempo.search`. Attributes are limited to
route templates, method, status, operation kind, job kind, delivery/lookup
counts, bounded outcome/error codes, duration, and response size. SQL text and
parameters, headers, URLs, bodies, exceptions, and resolved secrets are never
captured. Existing target HTTP span identity and parenting remain unchanged.

Trace references and derived evidence follow the accepted attempt/metadata
retention boundary and cascade with attempt deletion; Tempo's seven-day local
retention remains independent. M7 owns cleanup execution, project-deletion
workflow, restartability, and the release-wide privacy scan. M5 must not add a
second trace store or a deletion policy that rewrites baseline history.

## Decision review matrix

The following matrix makes the review obligations explicit; the named tests are
the M5-01 through M5-06 acceptance cases, not implementation authorization.

| Decision | M1-M4 compatibility | Security/failure boundary | Recovery/concurrency guarantee | Required proof | Material alternative rejected |
| --- | --- | --- | --- | --- | --- |
| References/schema | Legacy IDs and rows remain readable; no backfill | Bounded IDs/evidence, cascade only with attempts | Unique primary and linked dedupe | PostgreSQL constraints, round trip, legacy fixtures | Separate trace store |
| Correlation job | One existing queue and execution owner | Correlator cannot target-dispatch | Atomic enqueue, lease fencing, one job/reference | FK, enqueue crash window, concurrent claim | Trace-ID `subject_id` or second queue |
| Retry/deadline | Verdict path remains immediate | Closed outage/expiry states | Injected clock, persisted counter, bounded delivery | State table at every deadline boundary | Synchronous lookup or unbounded retry |
| Tempo protocol | Pinned Compose image and direct-ID authority | TLS, timeout, redirect, size, safe errors | Adapter retries are read-only and bounded | Mocked HTTP matrix and capability probe | Unbounded/raw client or API call |
| Available/partial | Existing client span remains identity anchor | Invalid payload never becomes a verdict | Idempotent monotonic state updates | Present/missing/malformed span fixtures | Trace-ID-only availability |
| Linked discovery | Optional; direct path works alone | Exact baggage only; no inference | Stable dedupe/order under duplicate search | Disabled/unsupported/0/1/many cases | Time/service-name correlation |
| Evidence/anchor | Baselines and verdicts never consume it | Allowlist, byte/cardinality caps | Deterministic sorting and revision-scoped anchor | Canonical JSON/privacy canaries | Full trace persistence or causal claims |
| Attempt API | Additive; legacy fields stay | Safe codes/links only | Stored read has no external side effect | OpenAPI/generated types/no-Tempo-call test | Breaking field replacement |
| Navigation | Internal URL stays private | Validated operator template only | Missing template returns null | Config validation and link sink scan | Echo internal URL or Tempo response |
| Instrumentation | Existing target span unchanged | No SQL/headers/URLs/bodies/exceptions | Stable names and bounded attributes | Span allowlist and secret canaries | Unsafe auto-instrumentation |
| Retention/M7 | Baseline history unaffected | No full traces or secret evidence | Idempotent future cascade boundary | Expiry/project-delete shape tests | M5 cleanup worker or baseline cascade |

## Compatibility and alternatives

These choices are additive to M1-M4: old attempt rows, legacy fields, execution
state machines, queue delivery semantics, baseline IDs, and verdict precedence
remain valid. The main alternative was a separate correlation-job table or a
trace-ID job subject; both would weaken the existing execution ownership/FK and
create a second leasing path. The chosen nullable reference FK keeps one queue
and makes ownership explicit. A synchronous Tempo query, unbounded trace JSON,
timestamp-only linking, and auto-instrumentation with raw capture were rejected
for availability, privacy, and concurrency reasons.

## Required acceptance evidence

M5-01 through M5-05 must provide PostgreSQL migration round trips, unique and
concurrent reference/job tests, adapter timeout/TLS/size/error tests, injected
clock delayed-arrival tests, crash/fence/idempotency tests, API/OpenAPI and
TypeScript drift checks, instrumentation privacy canaries, and a Compose trace
journey with Tempo stopped and restarted. Every test must prove that no
correlation state changes an execution, evaluation, baseline, or verdict.

## Implementation boundary

The owner-approved contract covers the migration number/shape, queue FK and
atomic boundaries, exact retry schedule and outage terminal state, pinned Tempo
wire protocol and limits, available/partial rule, linked-search flag and
bounds, evidence allowlist/anchor, additive API and no-refresh decision, URL
template, instrumentation names/attributes, and M7 retention handoff. M5-01
still requires its own task packet, isolated worktree, migration implementation,
focused tests, and integration review; this ADR does not implement it.
