# Milestone 5 implementation contract

Status: **M5-00 contract freeze accepted**.
This packet freezes M5-00 only. It authorizes no M5-01+ production code,
migration, worker, API, frontend, generated artifact, CI, or runtime rollout. It
turns the accepted architecture and [ADR 0011](../architecture/ADRs/0011-trace-correlation-and-evidence-contract.md)
into independently testable slices.

## Scope and invariants

M5 makes trace evidence converge asynchronously without making telemetry a
prerequisite for functional execution. It preserves the accepted M1-M4
identities, state machines, replay rules, regression precedence, baseline
history, redaction, queue leasing, and API versioning.

The implementation must preserve these invariants:

- every dispatched attempt has one primary `TraceReference` with the same trace
  and client-span IDs already checkpointed on the attempt;
- every replay has new attempt/trace/span identities and never reuses a
  predecessor's correlation job;
- one primary correlation job is durable and idempotent; linked references are
  bounded and deduplicated;
- Tempo lookup, delay, outage, sampling, malformed payloads, and retention do
  not change an execution, evaluation, baseline, or verdict;
- every correlation write is fenced and safe under at-least-once delivery;
- no raw trace payload, secret, protected header, body, unsafe URL, SQL text,
  SQL parameter, or exception text crosses an approved persistence/log/span/API
  sink.

## Frozen interfaces

### Domain port

The telemetry application service should depend on a domain port, not HTTPX or
Tempo types:

```text
TraceLookupPort.lookup(trace_id, *, expected_span_id, deadline) -> TraceLookup
TraceLookupPort.search_attempt(attempt_id, *, start_at, end_at, limit) -> tuple[LinkedTrace, ...]
```

`TraceLookup` carries only validated IDs, safe counts, service/deployment
identities, context-continuity classification, and a closed error code. The
worker receives no target-dispatch capability. Time, UUID generation, response
parsing, capability detection, and scheduling are injected.

### Persistence and job contract

Use `trace_references` and the nullable `jobs.trace_reference_id` contract in
[ADR 0011](../architecture/ADRs/0011-trace-correlation-and-evidence-contract.md).
M5-00 reserves migration `0011` with parent `0010`, confirmed as the current
single head; this is documentation-only and creates no migration file. The
dispatch checkpoint creates the primary row; the first terminal attempt
checkpoint inserts one idempotent `correlate_trace` job. Reclaimed work may
repeat a read-only lookup but cannot send HTTP or replay a target request. The
queue handler must bypass execution `start`/`complete` lifecycle transitions for
this kind; correlating a trace cannot mark an execution running or completed.

### State and timing contract

The default 60-second terminal-relative window uses the injected clock. Lookups
are scheduled at `0, 1, 3, 7, 15, 31, 59` seconds after the first eligible
lookup. One claimed delivery runs the bounded read-only loop with heartbeats;
it does not enqueue one job per lookup, and a crash resumes from the persisted
lookup counter. `available` and `expired` are terminal for this window. `missing`,
`partial`, and `tempo_unavailable` may be retried; an outage at the deadline
remains `tempo_unavailable`, while no trace at the deadline becomes `expired`.
Queue delivery and lookup counters are separate.

### Tempo and linked-search contract

The adapter uses the pinned Tempo 2.9.0 direct endpoint `/api/traces/{trace_id}`
and capability-gated `/api/search` tags lookup, with the limits and safe error
vocabulary in ADR 0011. Linked search is opt-in, exact on
`sentinel.attempt.id`, capped at 16 results, sorted by trace ID, and never a
prerequisite for direct correlation.

### API contract

Attempt detail gains additive `trace_references`, ordered primary then linked,
bounded to 17. Existing legacy trace fields remain. Each reference includes
identity, relation/source, state, timestamps/deadline, lookup count, safe error,
bounded evidence, and an optional validated operator link. API reads never query
Tempo. M5 does not add a refresh route.

## Slice packets

| Slice | Owned outcome | Required files/interfaces | Independent gate |
| --- | --- | --- | --- |
| M5-00 | Accepted contract, ADR, implementation packet, task plan | `docs/architecture/ADRs/0011-*`, `docs/implementation/milestone-5.md`, `docs/development/milestone-5-plan.md`, handoff | Links; contradiction review; no runtime changes |
| M5-01 | TraceReference model/repository and durable correlate job | `backend/src/sentinel/telemetry/`, persistence model/repository, allocated `backend/migrations/versions/0011_*`, focused PostgreSQL tests | Upgrade/downgrade/drift; constraints; atomic enqueue; concurrent claim/fence |
| M5-02 | Bounded Tempo lookup adapter | telemetry adapter/port and focused HTTP tests | direct lookup, limits, TLS/redirect, malformed/outage codes, no raw payload |
| M5-03 | Fenced reconciliation and delayed arrival | telemetry application service, worker handler, injected scheduler/clock, tests | delayed arrival, deadline, crash windows, at-least-once, no target capability |
| M5-04 | Optional linked traces and bounded change evidence | search adapter, evidence normalizer/repository, tests | capability gate, exact attribute, 16-result bound, deterministic dedupe/order |
| M5-05 | Attempt API, links, instrumentation, and typed handoff | attempt schemas/router, OpenAPI/TypeScript generated artifacts, API/telemetry tests | additive contract, legacy projection, no synchronous Tempo, privacy sinks |
| M5-06 | Integrated acceptance | named acceptance tests, Compose evidence, implementation record | exact candidate; PostgreSQL, backend, contracts, Compose; verdict independence |

The coordinator owns migration numbering, shared model registration, API
contract regeneration, root wiring, and integrated evidence. Each slice gets a
separate worktree, disposable PostgreSQL database, reserved ports, explicit
write set, and a handoff containing exact base SHA and test results.

## Acceptance matrix

The following cases are mandatory before M5 can be marked PASS:

1. W3C `traceparent` IDs, primary persistence, and target export match exactly;
2. delayed ingestion converges through each state using an injected clock;
3. direct trace present/client span present is `available`;
4. trace present/client span missing or malformed is `partial`;
5. not found at deadline is `expired`, while outage at deadline is
   `tempo_unavailable`;
6. concurrent/reclaimed delivery creates no duplicate references or jobs and
   stale leases cannot write;
7. linked search is disabled/unsupported safely and exact baggage matches are
   deduplicated, bounded, sorted, and labeled indirect;
8. attempt reads expose bounded state/evidence and perform no Tempo call;
9. malformed, oversized, redirected, timed-out, and TLS-invalid Tempo responses
   produce only closed safe errors;
10. Tempo stopping leaves execution, evaluation, baseline, readiness, and
    definition behavior functional;
11. retention/deletion tests prove reference cascade boundaries without baseline
    history mutation; and
12. API, worker, PostgreSQL, target HTTP, and Tempo spans pass privacy canaries.

## Explicit non-goals and implementation prerequisites

M5 does not implement a trace UI, a new tracing protocol, a full trace store,
root-cause inference, guaranteed recovery after broken propagation, M7 cleanup,
or refresh behavior beyond stored API reads. M5-01 requires an isolated task
packet, migration implementation and review, focused PostgreSQL/adapter/privacy
tests, and coordinator integration. Any change to accepted ADR 0005, public
endpoint inventory, persisted revision documents, or verdict rules requires a
new ADR and re-planning.
