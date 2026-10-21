# Durable work operations

## Scope

Sentinel uses the PostgreSQL queue from ADR 0002 for the internal probe and real
execution jobs. The API atomically persists an execution, its pinned immutable
inputs, materialized items, optional idempotency record, and queue job. The worker
then prepares and dispatches bounded HTTP requests, records fenced attempts and
redacted observations, and resumes from durable checkpoints after interruption.

The internal probe remains a deployment smoke tool and sends no target request.
Assertion/baseline evaluation and Tempo reconciliation are not implemented yet;
successful M3 observations therefore remain `not_evaluated` until Milestone 4.

## Transaction and dependency boundaries

- `execution.domain` owns states, transition validation, lease identity, and stable
  failure codes, with no framework imports.
- `execution.ports.JobStore` defines persistence operations; `WorkService` is the
  application interface consumed by the worker and internal probe CLI.
- `persistence.queue.PostgresJobStore` implements the port. It owns one session
  and one short transaction per operation and rolls back on exceptions.
- `execution.orchestration.ExecutionOrchestrator` owns recovery and dispatch
  decisions. `persistence.orchestration.PostgresOrchestrationStore` checkpoints
  attempts and results with the live job fence.
- Queue insertion and its execution envelope commit in one transaction.
- Claim commits before handler invocation. No database transaction remains open
  across handler work or heartbeat waiting.
- Request preparation and every durable checkpoint use short transactions. DNS,
  TLS, and target HTTP I/O run with no database transaction open.
- The worker commits `dispatching` with `possibly_sent`, request fingerprint,
  trace ID, and client span ID before DNS resolution or socket activity.
- Start, completion, retry, and failure first lock/validate the owned job. Subject
  transitions then lock the execution, always in that order.
- Terminal job/execution writes commit atomically. There is no detached subject
  update that can survive a failed job checkpoint.

Lease ownership predicates require job ID, `leased` state, owner ID, and the
current random fencing token. The adapter reads PostgreSQL `clock_timestamp()`
after acquiring the lock and rejects already expired ownership, even before
another worker reclaims the job. Row locking keeps each validated transition
exclusive until commit. Worker clocks are not used for production lease decisions.

## Job lifecycle

```text
pending -> leased -> succeeded
             |
             +-> pending (retry at available_at)
             +-> dead (terminal internal failure or delivery exhaustion)
expired leased -> leased (new token, new owner, incremented delivery count)
```

The claim uses `FOR UPDATE SKIP LOCKED` so another claimant skips a row already
locked by a concurrent transaction. It orders by availability/creation/ID as a
best-effort order; strict FIFO fairness is not guaranteed. Each claim processes
at most 100 exhausted rows before returning to avoid unbounded cleanup work.

Defaults:

| Setting | Default | Bounds |
| --- | --- | --- |
| `SENTINEL_LEASE_SECONDS` | 60 seconds | 5–300 |
| `SENTINEL_HEARTBEAT_SECONDS` | 15 seconds | 0.1–60; less than half the lease |
| `SENTINEL_MAX_DELIVERIES` | 3 | 1–3 |
| `SENTINEL_POLL_SECONDS` | 1 second | 0.05–1; idle jitter is 80–100% |

Infrastructure retry delays are 5 seconds after delivery 1 and 30 seconds after
delivery 2. A third failed delivery becomes `dead`. An abandoned final delivery
becomes `dead` when the next claimant discovers its expired lease. Thus dead-job
cleanup requires a running worker; no independent reaper service is necessary.

Each heartbeat extends expiry relative to PostgreSQL time. Stale tokens cannot
renew, start, complete, retry, or fail the job. Terminal jobs cannot be reclaimed.
Transitions are validated in domain code; database constraints additionally
enforce states, delivery limits, terminal timestamps, and lease-field shape.

## Delivery and failure guarantees

Handler delivery is at least once, bounded by the maximum delivery count. It is
not exactly once and success is not guaranteed. A random fencing token prevents
an old owner from committing queue/application checkpoints after takeover.
The delivery budget is consumed at claim time, including a crash before handler
invocation. Repeated crashes can therefore exhaust a job without a completed
handler invocation; delivery counters are not successful-run counters.

The worker starts a heartbeat task independently of handler work. Heartbeat
failure cancels the handler and leaves the lease for recovery. SIGINT/SIGTERM
cancels active work and stops claiming new jobs. Cancellation is cooperative:
handlers must await and stop when cancelled; a detached thread or remote effect
cannot be undone by cancelling an asyncio task. The execution handler can produce
an outbound HTTP effect, so recovery consults the durable attempt state and
dispatch certainty instead of assuming cancellation prevented the request.

The database adapter converts operational driver errors to a sanitized
`InfrastructureFailure`. Handler infrastructure failures are eligible for bounded
retry; unknown-handler and unexpected handler errors are terminal. If the database
cannot record the retry or terminal result, the lease expires and recovery reads
durable state. Raw exception messages are not logged or stored.

Polling is authoritative and no `LISTEN/NOTIFY` optimization is implemented.
Therefore notification loss cannot hide queued work.

Queue redelivery alone never authorizes HTTP replay. Recovery before the dispatch
checkpoint resumes without sending an extra request. A stored response or known
transport failure resumes without resend. An ambiguous safe request creates a new
attempt; an ambiguous unsafe request becomes `indeterminate` unless its immutable
definition explicitly permits replay. Every replay receives new attempt, trace,
and client span identifiers. See ADRs 0007 and 0008 for the complete matrix.

## Health and observability

- `/health/live`: always returns process liveness without dependency checks.
- `/health/ready`: returns `200` only if PostgreSQL is accessible and the database
  is at the deployed Alembic head; returns `503` otherwise.
- Tempo `/ready` is checked with a 1-second timeout and reported as
  `available`/`unavailable`; it does not determine API readiness.
- Worker health uses a process-owned `/tmp/sentinel-worker-health` marker updated
  after successful queue polling or lease heartbeat. Startup clears stale markers;
  shutdown removes the marker. The check tolerates three heartbeat intervals.

JSON log events include job IDs and fixed event names. They exclude tokens,
database URLs, exception dumps, requests, and bodies. API request and worker
handler boundaries emit OpenTelemetry spans. An optional OTLP/HTTP exporter
sends to Tempo; native runs without `SENTINEL_OTLP_ENDPOINT` create SDK spans with
no exporter. Each dispatched attempt creates a W3C client context and injects
Sentinel correlation baggage. Export failure does not determine job results.
Tempo lookup, delayed-ingestion handling, linked-trace discovery, and correlation
status remain in Milestone 5.

## Recovery and inspection

Restart the worker to resume expired jobs. The normal workflow does not reset dead
rows or edit delivery counters. Inspect with read-only SQL:

```sql
SELECT id, kind, state, delivery_count, max_deliveries,
       available_at, lease_expires_at, last_error_code
FROM jobs
ORDER BY created_at DESC
LIMIT 50;
```

Worker process IDs are ephemeral UUIDs, not operating-system PIDs or user IDs.
Fencing tokens are internal ownership evidence and should not be shared.

## Accepted limitations

- One active handler runs per worker process. The MVP does not provide distributed
  runners or horizontal autoscaling.
- Polling, row churn, and vacuum/index maintenance share PostgreSQL capacity with
  product queries.
- Database downtime pauses new work and invalidates unconfirmed active ownership.
- Queue and execution history are not cleaned up yet; retention is Milestone 7.
- `jobs.subject_id` references executions. New job subject types need an explicit
  migration when introduced.
- Functional assertion/baseline verdicts and trace correlation are not available
  until Milestones 4 and 5.
- A full Compose run requires Docker. Native PostgreSQL tests do not prove image
  builds or container health checks; CI covers that independent acceptance path.

Broker migration conditions remain those in ADR 0002: measured queue/database
capacity contention, unacceptable backlog age, routing/priority/fan-out needs, or
availability coupling that tuning cannot resolve.
