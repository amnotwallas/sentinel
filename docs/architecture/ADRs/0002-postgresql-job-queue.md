# ADR 0002: PostgreSQL-backed job leasing

- Status: Accepted
- Date: 2026-10-09

## Context

Executions and trace reconciliation must survive API and worker restarts. The MVP
has low throughput, one installation, and PostgreSQL already in its required
topology. Adding Redis/RabbitMQ and Celery/RQ would add configuration, failure
modes, persistence semantics, and operations that are not required by the
acceptance criteria.

Worker recovery must not be confused with safe repetition of an HTTP request.
The queue can redeliver a handler, but it cannot provide exactly-once side effects
against an arbitrary target API.

## Decision

Store jobs in PostgreSQL and claim them with a short transaction using
`SELECT ... FOR UPDATE SKIP LOCKED`. A claim:

1. selects one `pending` job whose `available_at <= now()`, or one `leased` job
   whose lease expired;
2. rejects exhausted rows by moving them to `dead`;
3. sets `state = 'leased'`, `lease_owner`, a new random `lease_token`, and
   `lease_expires_at = now() + lease_duration`;
4. increments `delivery_count`;
5. commits before running the handler.

The initial operational defaults are:

- lease duration: 60 seconds;
- heartbeat interval: 15 seconds;
- maximum deliveries: 3;
- retry delays after the first and second failed delivery: 5 and 30 seconds;
- idle poll interval: up to 1 second with jitter and an optional PostgreSQL
  `LISTEN/NOTIFY` wake-up used only as an optimization.

Configuration may tune these values within validated bounds. Correctness never
depends on `NOTIFY`, because notifications are not durable.

### Lease ownership and fencing

Every claim receives a new opaque `lease_token`. Heartbeat, success, retry, and
dead-letter updates use compare-and-set predicates over job ID, `state = leased`,
owner, and token. A worker that cannot renew or confirm its lease must stop before
starting any new side effect. Its stale token cannot complete the job.

Application checkpoints also lock or compare the relevant execution/attempt
state. This makes a redelivered handler safe to resume or no-op. It does not make
an already-started network request exactly once.

### State transitions

- `pending -> leased`: atomic claim; increments `delivery_count`.
- `leased -> leased`: heartbeat extends the deadline using the fencing token.
- `leased -> succeeded`: handler reached a durable terminal application state.
- `leased -> pending`: retryable handler/infrastructure failure; clear lease,
  set the next `available_at`, and store a sanitized error code.
- expired `leased -> leased`: another worker reclaims with a new token and count.
- `leased/pending -> dead`: the next delivery would exceed `max_deliveries`, or
  the handler reports a non-retryable internal failure.

`succeeded` and `dead` are terminal. Business outcomes such as a failed assertion,
blocked target, or non-replayable ambiguous request are handled durably by the
execution state machine and normally finish the job as `succeeded`; `dead` means
Sentinel could not finish its own orchestration.

### Delivery guarantee

The queue provides **at-least-once handler delivery, bounded by
`max_deliveries`**, while PostgreSQL and a worker are available. It provides:

- no exactly-once handler execution;
- no exactly-once outbound HTTP effect;
- no guarantee that every job succeeds, because exhausted jobs become `dead`;
- durable creation when a job is inserted in the same transaction as its
  execution;
- durable recovery after lease expiration;
- per-job ordering only through application state, not broker partitions.

Operators can requeue a dead job only through an explicit future administrative
operation. Such an operation is not required in the MVP UI. Direct SQL requeue is
not a supported normal workflow.

### Separation from request replay

The job handler reads durable `TestAttempt` state before acting:

- before `dispatching`, it may continue preparation;
- at `response_received`, it resumes evaluation without another request;
- at `evaluated`, it advances/no-ops;
- at `dispatching`, it treats the request as possibly sent and applies the test
  revision's replay policy.

Only `GET`, `HEAD`, and `OPTIONS` replay by default. Other methods require an
explicit unsafe-replay opt-in. Every replay creates a new attempt, trace ID, and
span ID; the ambiguous predecessor becomes `replay_scheduled` and links to its
successor. Otherwise the attempt becomes `indeterminate` and the execution
becomes `inconclusive`.

Queue delivery count and HTTP attempt sequence are therefore intentionally
different fields. A handler may be delivered more than once without issuing any
additional HTTP request.

## Schema and query requirements

The `jobs` table includes `id`, `kind`, `subject_id`, `state`, `available_at`,
`lease_owner`, `lease_token`, `lease_expires_at`, `delivery_count`,
`max_deliveries`, `last_error_code`, `created_at`, and `finished_at`.

The runnable-job index begins with state and availability/lease deadline. Claim
queries must be covered by PostgreSQL integration tests with two concurrent
connections. Error fields contain stable codes and bounded sanitized summaries,
not exception dumps, request data, or secrets.

## Alternatives considered

### In-memory/FastAPI background jobs

They lose work on restart and cannot coordinate API and worker processes.

### Celery or RQ with Redis/RabbitMQ

They provide mature worker features but add a required service and a second
durability model. Current load and routing needs do not justify them.

### PostgreSQL advisory locks only

Advisory locks do not by themselves retain job state, delivery history, retry
deadlines, or terminal failures. Durable rows are simpler to inspect and recover.

## Limitations

- Polling and frequent row updates create database load and table/index churn.
- Long transactions or poor vacuum behavior can degrade claim latency.
- PostgreSQL is a shared failure domain: database outage stops both API writes and
  job progress.
- There is no broker-native priority, routing, consumer-group, replay, or lag
  tooling.
- `SKIP LOCKED` optimizes concurrency but does not guarantee strict FIFO fairness.
- Large backlogs compete with product queries unless indexes, batching, and
  retention remain disciplined.

## Conditions for a dedicated broker

A broker is justified only after measurement shows one or more of these sustained
conditions and PostgreSQL/index/query tuning is insufficient:

- claim latency or queue polling materially consumes the database capacity needed
  for product reads/writes;
- backlog age violates the execution-start objective under expected load;
- workers must scale independently across hosts/regions with routing or priority
  requirements PostgreSQL cannot meet cleanly;
- the product needs high-volume fan-out, scheduled delivery, consumer groups, or
  broker-native dead-letter/replay operations;
- database maintenance or failover coupling creates unacceptable execution
  availability.

Introducing a broker requires a new ADR, an outbox or equivalent atomic publish
design, explicit delivery semantics, operational documentation, and evidence that
the added service is preferable to the measured PostgreSQL bottleneck.

## Consequences

- The MVP has no additional required infrastructure.
- Queue state and failure history are locally inspectable with the rest of the
  execution record.
- Handlers must be resumable and idempotent at durable checkpoints.
- Lease/fencing tests are critical because a framework does not provide them.
- This decision is deliberately reversible at the application-service boundary.
