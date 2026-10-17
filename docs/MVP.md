# Sentinel MVP

## Purpose

Sentinel is an open-source, self-hosted tool for deterministic API regression
testing with distributed-trace correlation. The MVP serves one operator running
Sentinel locally or on a trusted development network.

The MVP helps the operator answer:

1. **What broke?** Which required assertion or stable baseline value changed?
2. **Where did it fail?** Which observed spans contain errors or unexpected
   latency near the failed request?
3. **What changed before the failure?** Which Sentinel definition or baseline
   revision changed, and—when telemetry supplies it—which service version or
   deployment attribute differs from an earlier run?

Sentinel reports evidence. It does not infer or claim root cause.

## MVP user journey

1. The operator starts Sentinel, PostgreSQL, and Tempo with Docker Compose.
2. The operator creates a project and an environment containing a base URL and
   non-secret variables. Secrets are referenced by name and supplied out of band.
3. The operator creates a test case with an HTTP request, explicit assertions,
   stable comparison selectors, redaction rules, and optional performance limits.
4. The operator starts an execution for a test case or ordered suite.
5. The API durably enqueues the execution and returns its identifier without
   waiting for network calls.
6. A worker leases the job, resolves the request, creates an attempt and
   OpenTelemetry client context, persists dispatch intent, and sends the request.
7. Sentinel redacts and bounds captured data, evaluates assertions and baseline
   selectors, records a verdict, and correlates the attempt with Tempo.
8. The UI shows the verdict, deterministic evidence, relevant configuration
   changes, and trace availability without treating missing telemetry as a test
   failure.
9. The operator may promote an eligible successful attempt to a new immutable
   baseline version.

## Included scope

### Definition management

- One local Sentinel installation with projects as organizational containers.
- Environments with a base URL, non-secret variables, target allowlist settings,
  and secret references.
- HTTP test cases using `GET`, `HEAD`, `OPTIONS`, `POST`, `PUT`, `PATCH`, or
  `DELETE`.
- Immutable test-case revisions. Editing a case creates a revision rather than
  mutating prior execution inputs.
- Ordered suites. Suite execution is sequential in the MVP; the installation may
  execute different runs concurrently up to a global worker limit.
- A change record for test revisions, environment changes, suite revisions, and
  baseline activation.

### Request definition

- Base URL plus path, query parameters, headers, and optional JSON or text body.
- Template substitution for non-secret environment variables.
- Tagged secret references at header or JSON-body leaves, represented as
  `{ "$secret": "NAME" }`. Names match `[A-Z][A-Z0-9_]{0,63}` and resolve from
  `SENTINEL_SECRET_<NAME>` in the worker environment. Secret values may not be
  placed in URLs or query parameters because they are routinely exposed by
  infrastructure logs.
- Configurable connect/read/total timeout within deployment limits.
- Redirect following disabled by default and bounded when explicitly enabled;
  only `GET`, `HEAD`, and `OPTIONS` may follow in the MVP.
- HTTPS certificate-chain and hostname verification are mandatory. Existing
  definitions with `verify_tls: false` remain readable but are rejected before
  DNS or socket activity.
- A maximum captured response size; larger responses are truncated for storage
  and marked unevaluable for comparisons that need truncated content.

### Deterministic checks

- Required or advisory status-code assertions.
- Required or advisory header presence/equality assertions, with case-insensitive
  header names.
- Required or advisory JSON Pointer assertions for presence, absence, type, or
  exact JSON value.
- Opt-in exact text-body assertion for non-JSON responses.
- Baseline comparisons over explicitly selected JSON Pointers or an explicitly
  selected complete text body.
- Per-selector normalizers limited to deterministic built-ins documented in the
  stored policy, initially `none`, `sort_scalar_array`, and `round_decimal` with
  an explicit scale.
- Absolute duration thresholds expressed in integer milliseconds. Performance
  thresholds cannot produce a functional-regression verdict.

### Baseline management

- Create a baseline from an eligible, fully evaluated attempt.
- Baselines are immutable and numbered per test case and environment.
- Activating, replacing, or rolling back a baseline changes an activation pointer
  and records a change event; it does not alter a baseline version.
- Baselines store only redacted, normalized values selected by the comparison
  policy, plus fingerprints and provenance.
- Baseline promotion is always explicit. Sentinel never learns or auto-accepts a
  new baseline from repeated results.
- A baseline is incompatible when its comparison-policy fingerprint differs from
  the executing revision. Sentinel reports `baseline_required` rather than using
  an ambiguous comparison.

### Trace correlation

- One stable execution ID for the requested run.
- One new attempt ID for every dispatch checkpoint, representing one possible
  outbound request. It remains evidence even if a crash makes the actual send
  unknowable.
- One primary OpenTelemetry trace ID and client span ID generated and persisted
  before each dispatch.
- W3C `traceparent`, `tracestate`, and `baggage` propagation through the
  OpenTelemetry propagator.
- Standard baggage entries for `sentinel.execution.id` and
  `sentinel.attempt.id`. They contain opaque UUIDs and are correlation hints, not
  credentials or authorization inputs.
- Zero or more additional linked trace IDs when an instrumented application
  records the attempt baggage as searchable span attributes after breaking trace
  context. Linked traces are explicitly labeled as indirect correlation.
- Correlation states for pending, available, partial, missing, expired, and Tempo
  unavailable telemetry.
- Links from attempts to Tempo when a trace is available.

### Local UI

- Project/environment setup.
- Test-case and suite authoring.
- Execution start and execution history.
- Attempt details showing assertions, baseline comparison, performance warnings,
  transport/execution errors, and redacted response evidence.
- Baseline review and manual promotion.
- Trace status and navigation, including clear missing/partial telemetry messages.
- A change timeline limited to evidence known by Sentinel and supplied telemetry.

## Explicitly excluded

- Multi-user accounts, roles, organizations, or multi-tenancy.
- Billing, hosted control planes, or proprietary services.
- AI-generated tests, summaries, anomaly detection, or root-cause analysis.
- Test scheduling, alert delivery, incident management, or on-call integration.
- Browser, GraphQL-aware, gRPC, WebSocket, streaming, load, soak, or fuzz testing.
- Multi-step variable extraction and data-dependent workflow tests.
- Distributed test runners or horizontal worker autoscaling.
- Kubernetes deployment artifacts.
- Redis, RabbitMQ, Kafka, Celery, or another dedicated broker.
- A proprietary agent, SDK, collector, or tracing protocol.
- Full trace storage in PostgreSQL or a replacement trace viewer.
- Automatic baseline promotion or probabilistic response learning.
- Guaranteed discovery of traces that do not preserve trace context or searchable
  correlation baggage.

## Functional verdict model

Execution lifecycle and verdict are separate. Lifecycle answers whether work is
finished; verdict describes the observed API behavior.

| Verdict | Meaning |
| --- | --- |
| `passed` | All required functional checks passed and no higher-priority category applies. |
| `functional_regression` | A required assertion or required stable baseline selector failed. |
| `performance_warning` | Functional checks passed, but at least one duration threshold was exceeded. |
| `observed_change` | Functional checks passed, but an advisory assertion or selector changed. |
| `inconclusive` | Sentinel could not safely determine behavior, including an ambiguous non-replayable dispatch or required data truncated before evaluation. |
| `baseline_required` | The case requires a baseline and none compatible with its policy is active. |
| `not_evaluated` | Infrastructure failed before the execution could yield an API observation. |

Precedence is `inconclusive`, `baseline_required`, `functional_regression`,
`performance_warning`, `observed_change`, then `passed`. `not_evaluated` applies
only when no relevant API attempt reached evaluation. Transport failures are
shown separately from assertion failures and are `inconclusive` by default;
Sentinel does not guess whether the target or its own network caused them.

Trace status never changes this verdict.

## Execution and recovery semantics

PostgreSQL job delivery is **at least once with bounded acquisition attempts**.
It is not exactly once. A lease may expire after a worker crash, allowing another
worker to resume the execution. Durable checkpoints make orchestration
idempotent, but outbound HTTP effects cannot be made exactly once.

Before network I/O, the worker persists an attempt in `dispatching`, including
its request fingerprint, trace ID, and client span ID. The commit intentionally
precedes DNS resolution and sending and records dispatch certainty as
`possibly_sent`. If the worker later recovers an attempt still in `dispatching`,
Sentinel cannot distinguish “not sent” from “sent but response not recorded.” A
live fenced worker may record `not_sent` only from positive pre-write phase proof;
an ambiguous exception, cancellation, lost lease, process death, or uncertain
database commit never downgrades `possibly_sent`.

- `GET`, `HEAD`, and `OPTIONS` are replayable by default.
- Other methods are not replayed unless the test revision explicitly sets
  `allow_unsafe_replay: true`. The UI and API must describe the possible duplicate
  side effect before accepting that setting.
- A replay creates a new attempt. It never reuses the ambiguous attempt ID or
  trace context.
- An ambiguous non-replayable attempt becomes `indeterminate`, and its execution
  becomes `inconclusive`. Operator-triggered execution of a new run remains
  available.
- Queue retries recover orchestration failures; they do not themselves authorize
  an HTTP replay.
- A known DNS, connection, TLS, write, read, timeout, or redirect failure becomes
  a durable `transport_failed` attempt and is not automatically resent. HTTP
  `4xx` and `5xx` statuses are responses, not transport failures.
- A received `3xx` is the final response when redirect following is disabled. If
  following is enabled and a proposed safe-method hop is rejected, the received
  `3xx` remains sanitized evidence, the attempt becomes `transport_failed` with
  `response_received` certainty, and no connection is made to the rejected hop.

Job leases, expiration, retry limits, and failure transitions are specified in
`docs/architecture/ADRs/0002-postgresql-job-queue.md`.

## What instrumented applications must provide

For direct trace correlation, the application under test must:

1. Extract incoming W3C Trace Context with an OpenTelemetry-compatible
   propagator and make it the server span parent.
2. Propagate W3C context on downstream calls.
3. Export spans to the same Tempo deployment Sentinel is configured to query, or
   to a collector that forwards to it.
4. Set a stable `service.name` resource attribute.
5. Use clocks sufficiently synchronized for useful timelines.

Recommended, but not required:

- Preserve W3C Baggage and copy `sentinel.execution.id` and
  `sentinel.attempt.id` to searchable span attributes. This permits indirect
  correlation if trace context is broken.
- Set `service.version`, `deployment.environment.name`, and a deployment or
  source-revision attribute. Sentinel may display differences as evidence but
  must not label them as causes.
- Record exceptions and set span error status according to OpenTelemetry semantic
  conventions.

If any item is absent, Sentinel still evaluates the API response. It reports the
trace as missing, delayed, or partial and states which evidence is unavailable.

## API acceptance contract

All endpoints are under `/api/v1`, use JSON unless noted, expose UUID identifiers,
and return RFC 9457 `application/problem+json` on errors.

| Method and path | Purpose |
| --- | --- |
| `GET /health/live` | Process liveness without dependency checks. |
| `GET /health/ready` | Readiness including PostgreSQL; Tempo degradation is reported but does not make the API unready. |
| `GET /api/v1/projects` | List projects. |
| `POST /api/v1/projects` | Create a project. |
| `GET /api/v1/projects/{project_id}` | Read a project. |
| `GET /api/v1/projects/{project_id}/environments` | List environments. |
| `POST /api/v1/projects/{project_id}/environments` | Create an environment without secret values. |
| `GET /api/v1/environments/{environment_id}` | Read an environment and its active revision. |
| `PATCH /api/v1/environments/{environment_id}` | Update environment metadata and create a change record. |
| `GET /api/v1/projects/{project_id}/test-cases` | List test cases. |
| `POST /api/v1/projects/{project_id}/test-cases` | Create a case and revision 1. |
| `GET /api/v1/test-cases/{test_case_id}` | Read a case and its active revision. |
| `PUT /api/v1/test-cases/{test_case_id}` | Create and activate a new immutable revision. |
| `GET /api/v1/test-cases/{test_case_id}/revisions` | List revision history. |
| `GET /api/v1/projects/{project_id}/suites` | List suites. |
| `POST /api/v1/projects/{project_id}/suites` | Create an ordered suite. |
| `GET /api/v1/suites/{suite_id}` | Read a suite and its active revision. |
| `PUT /api/v1/suites/{suite_id}` | Create and activate a suite revision. |
| `POST /api/v1/executions` | Queue one test case or suite against one environment. |
| `GET /api/v1/executions/{execution_id}` | Read lifecycle, verdict, attempts, and change evidence. |
| `GET /api/v1/executions` | List filterable execution history. |
| `GET /api/v1/attempts/{attempt_id}` | Read redacted observation, evaluations, and trace references. |
| `POST /api/v1/test-cases/{test_case_id}/baselines` | Create and activate a baseline from an eligible attempt. |
| `POST /api/v1/test-cases/{test_case_id}/baseline-activations` | Activate an existing compatible baseline version. |
| `GET /api/v1/test-cases/{test_case_id}/baselines` | List immutable baseline history. |

`POST /api/v1/executions` accepts exactly one of `test_case_id` and `suite_id`,
plus `environment_id`. It accepts an optional `Idempotency-Key` header scoped to
the installation for 24 hours. Repeating the same key and payload returns the
original execution; repeating the key with a different payload returns `409`.
The response is `202 Accepted` with the execution resource and `Location` header.

Creation and update requests use optimistic concurrency through an `ETag` and
`If-Match` on mutable activation/metadata resources. Immutable revisions and
baselines do not support in-place update.

## Acceptance criteria

The MVP is complete only when all criteria below are demonstrated in automated
tests or the documented Docker Compose acceptance run.

### Installation and boundaries

- A fresh checkout starts the frontend, API, worker, PostgreSQL, and Tempo using
  documented Docker Compose commands and no other required infrastructure.
- The API and worker use the same backend package but run as separate processes.
- Data survives API or worker restart.
- Default host bindings are loopback-only.

### Definition and execution

- An operator can create an environment, test case, and suite from the UI and
  API without persisting resolved secrets.
- Starting an execution returns `202` before its HTTP request completes.
- A worker claims a runnable job exclusively while another worker skips it.
- A suite executes its cases in stored order and records a distinct attempt for
  every configured case dispatch or recovery replay. A bounded redirect chain is
  part of that configured attempt and is not a replay.
- Timeouts, DNS/TLS failures, oversized responses, invalid JSON, and target-policy
  rejection produce explicit, redacted outcomes rather than worker crashes.

### Worker reliability and safety

- A worker heartbeats an active lease and another worker cannot claim it before
  expiration.
- An expired lease is reclaimable and orchestration resumes from durable state.
- Retryable infrastructure errors use bounded backoff; exhaustion moves the job
  to `dead` and the execution to `failed`/`not_evaluated` when no observation
  exists.
- Recovery before dispatch may continue without creating a duplicate request.
- Recovery of an ambiguous `POST`, `PUT`, `PATCH`, or `DELETE` does not send
  another request by default; it records `indeterminate`/`inconclusive`.
- Recovery of an ambiguous default-replayable request creates a new attempt and
  distinct trace identifiers.
- Tests demonstrate that lease recovery and HTTP replay policy are independent.
- Recovery from a durable `response_received` or `transport_failed` state does
  not send another target request.

### Regression and baselines

- Two responses differing only in unselected fields produce the same required
  comparison result.
- A required stable value mismatch produces `functional_regression` with expected
  and redacted actual evidence.
- An advisory difference produces `observed_change`, not a regression.
- A duration threshold breach with passing functional checks produces
  `performance_warning`.
- Exact body comparison happens only when explicitly configured.
- Baseline creation is manual, versioned, attributable to a source attempt, and
  cannot mutate an older version.
- A policy fingerprint mismatch produces `baseline_required`.

### Trace correlation

- The stored primary trace ID matches the `traceparent` injected into the tested
  request, and the stored client span ID identifies the Sentinel HTTP client span.
- A suite execution maps one execution ID to all case attempts while each replay
  receives a new attempt ID and primary trace.
- A complete trace becomes navigable after delayed Tempo ingestion without
  blocking the functional verdict.
- Sampled-out, missing, broken-context, partial, multiple, and Tempo-unavailable
  cases show distinct correlation status and do not change the functional result.
- Indirectly linked traces identify their correlation source and are not presented
  as definitive children of the primary trace.

### Security, privacy, and retention

- Authorization and cookie headers are redacted in logs, API responses, stored
  artifacts, and test failure output.
- Resolved secret values never appear in PostgreSQL or OpenTelemetry attributes.
- Sensitive JSON paths configured by the operator are redacted before storage.
- Target validation rejects blocked address classes after DNS resolution and on
  every redirect hop.
- The socket connects only to a validated resolved address while HTTP authority,
  TLS SNI, and certificate hostname verification retain the original hostname.
- Rejected redirect hops receive no target connection. Cross-origin redirects
  remove fixed credentials and every secret-derived header.
- Target HTTP clients inherit no proxy configuration and perform no library-level
  retry.
- Response capture limits and concurrency limits are enforced.
- Cleanup removes expired artifacts and execution metadata according to policy
  while preserving active baseline values and definition history.

## Security and retention defaults

- API/frontend bind: `127.0.0.1` only.
- Non-loopback API binding: requires an operator-supplied bearer token from an
  environment variable; Sentinel does not store the token.
- TLS certificate-chain and hostname verification: required for HTTPS; minimum
  TLS 1.2, with no insecure opt-out, TLS early data, or client certificate in the
  MVP.
- Target trust: default roots plus one optional deployment-wide additive PEM CA
  bundle selected by `SENTINEL_TARGET_CA_BUNDLE` and validated by the worker at
  startup.
- Target proxy inheritance and target connection pooling: disabled.
- Redirects: disabled.
- Private, loopback, link-local, multicast, unspecified, and cloud-metadata
  targets: denied unless an exact hostname or CIDR is operator-allowlisted.
- Maximum redirects when enabled: 3, with target validation at every hop.
- Redirect methods when enabled: `GET`, `HEAD`, and `OPTIONS` only.
- Default total request timeout: 30 seconds; deployment maximum: 120 seconds.
- Default stored response-body limit: 256 KiB; deployment maximum: 1 MiB.
- Default worker HTTP concurrency: 4; configurable from 1 through 32.
- Execution/attempt/evaluation metadata retention: 30 days.
- Redacted response artifact retention: 7 days.
- Tempo trace retention in the example deployment: 7 days.
- Test definitions, change records, and baseline versions: retained until the
  containing project is explicitly deleted.

Retention values are configurable within documented bounds. Cleanup must not
delete a response artifact referenced by an active baseline; baseline values are
stored separately so ordinary artifact expiration remains safe.

## Assumptions and limitations

- The operator controls both Sentinel and the target authorization credentials.
- Target APIs fit bounded request/response semantics; streaming is unsupported.
- API effects cannot be exactly once. The conservative crash window may classify
  a request as indeterminate even when it was never sent.
- Corporate outbound proxies, mTLS-only targets, per-environment CA stores, and
  insecure TLS endpoints are unsupported in the MVP.
- The locked HTTP transport uses a version-qualified adapter seam to dial a
  validated IP while preserving original-host authority, SNI, and hostname
  verification. Transport dependency upgrades require requalification.
- PostgreSQL polling is adequate for the MVP's low throughput but is not a
  general-purpose message broker.
- Tempo search capabilities and attribute indexing vary. Direct trace-ID lookup
  is authoritative; baggage-based discovery is best-effort.
- Sampling may remove spans, and context propagation may be broken by target
  services. Sentinel cannot reconstruct evidence that was never exported.
- Wall-clock latency includes the tested HTTP interaction as observed by the
  Sentinel worker; it is not a substitute for load testing or service-level
  latency metrics.
- Deployment attributes are supplied by instrumented applications and may be
  absent or inaccurate.
- Local bearer-token support is a safety boundary, not a complete identity and
  access management system.
