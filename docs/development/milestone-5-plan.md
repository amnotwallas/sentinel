# Milestone 5 task plan

Status: **M5-00 contract freeze accepted; M5-01+ planning only**.
Base for the contract-freeze worktree: `18bee847789e83527d6eb48fe6667b40b9f628a3`.
M5-01+ slices require the accepted M5-00 contract plus a workflow packet naming
their own worktree, database, ports, owner, and write set.

## M5-00 — contract freeze (this worktree)

**Objective:** turn accepted M1-M4 architecture into an owner-reviewable trace
correlation contract without changing runtime behavior.

**Deliverables:** accepted ADR 0011, implementation contract, this plan, and a
resolution record in the M5 handoff. Verify one Alembic head, existing Tempo
image/configuration, queue FK seam, legacy attempt fields, API detail shape,
privacy boundaries, and all documentation links.

**Exit:** ADR 0011 and the resolution record are accepted; no new production
file, migration, API route, generated artifact, or CI change exists.

## M5-01 — relational references and durable correlation work

**Objective:** persist primary/linked references and one durable read-only
correlation job.

**Coordinator-owned allocation:** migration `0011` with parent `0010` is reserved
by M5-00 documentation; shared ORM registration and the migration file remain
M5-01 implementation work.

**Tests:** migration upgrade/downgrade/drift, legacy M1-M4 rows, primary and
linked constraints, unique job, atomic dispatch/terminal enqueue, concurrent
claims, stale lease fence, correlation completion that leaves execution status
unchanged, and deletion cascade shape. Because the current worker calls
`start` before every handler, this slice must give `correlate_trace` an explicit
non-execution start/complete path rather than relying on a handler convention.

**Forbidden:** Tempo HTTP, target HTTP, API response changes, backfills,
verdict changes, or a second queue.

## M5-02 — direct Tempo adapter

**Objective:** implement the explicit adapter port for direct trace-ID lookup.

**Tests:** valid trace/client span, not found, malformed/oversized JSON,
timeout, TLS failure, redirect rejection, HTTP 5xx, capability probe,
response-size and safe-error assertions. Use mocked HTTP transport; no live CI
or external Tempo dependency.

**Forbidden:** persistence of raw payloads, synchronous API lookup, linked
search fallback, or target-request behavior.

## M5-03 — reconciliation service and delayed arrival

**Objective:** reconcile a primary reference under the injected clock and
bounded schedule.

**Tests:** every state transition, deadline boundary, delayed arrival, outage
exhaustion, crash before/after lookup/persist, lease reclaim, idempotent retry,
monotonic counters/timestamps, and proof that no target adapter is reachable.

**Forbidden:** rewriting attempt/item/execution verdicts or automatically
replaying an ambiguous target attempt.

## M5-04 — linked traces and bounded evidence

**Objective:** add optional exact baggage search and derived service/deployment
evidence.

**Tests:** disabled/unsupported capability, exact attempt attribute, zero/one/
many matches, duplicate/primary filtering, 16-result deterministic ordering,
bounded evidence, comparison-anchor scope, retention expiry, and privacy canaries.

**Forbidden:** timestamp/service-name inference, parent-child claims for linked
traces, raw spans, bodies, headers, SQL, URLs, or root-cause language.

## M5-05 — additive attempt contract and safe instrumentation

**Objective:** expose stored references/evidence and add the frozen safe spans.

**Tests:** OpenAPI schema and generated TypeScript drift, legacy/pending/terminal
ordering, safe link template validation, no synchronous Tempo call, API problem
shape, and attribute allowlist checks across API/worker/PostgreSQL/target/Tempo.

**Forbidden:** M6 trace UI, a refresh route, browser access to the internal Tempo
URL, auto-instrumentation with unsafe capture, or breaking existing response
fields.

## M5-06 — independent acceptance and integration

**Objective:** validate one exact integrated candidate and record evidence.

**Required gates:** migration round trip and drift, focused backend/privacy/
concurrency tests, frontend contract tests, Compose delayed-ingestion trace
journey, Tempo outage/restart, and exact generated-contract check. Do not claim
PASS from documentation or inspection alone.

**Exit:** owner-approved contract, independent review findings resolved, all
required gates pass on one candidate, and separately authorized CI evidence is
recorded for that exact SHA.

## Cross-slice ownership and handoff

The coordinator owns shared files, migration allocation, model registration,
API/generated contract regeneration, root wiring, and integration evidence.
Every slice handoff names its base SHA, absolute worktree, allowed files,
database/ports, focused commands/results, privacy findings, and remaining
decisions. No M5 slice modifies accepted ADRs; a material architecture change
requires a new ADR and owner acceptance.
