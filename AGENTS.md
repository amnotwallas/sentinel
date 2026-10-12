# Sentinel Engineering Guide

This file applies to the entire repository. More specific `AGENTS.md` files may
add local rules but must not weaken the architecture, safety, privacy, or test
requirements documented here.

## Development collaboration

Follow `docs/development/workflow.md` for task ownership, isolated worktrees,
handoffs, and integration. Use one writer per file; the coordinator owns shared
wiring, migration allocation, and generated contracts unless ownership is
explicitly transferred. Worktrees also require separate test databases and
reserved runtime ports. Read-only review may share a checkout.

Repository workflows live in `.agents/skills/`: `sentinel-feature`,
`sentinel-quality-gate`, `sentinel-security-review`, and `sentinel-pr-prepare`.
Use `docs/development/quality-gates.md` for local commands. `make check-fast`
does not replace PostgreSQL/migration, full Compose, or required CI gates.
Successful checks do not grant commit, push, merge, or remote-setting permission.
Use `docs/implementation/milestone-2.md` and its planned schema for M2 contracts;
runtime generated artifacts describe implemented routes only.

## Product boundaries

Sentinel is an open-source, self-hosted API reliability and distributed tracing
platform. The MVP is a single-user, local-first modular monolith. It answers:

1. What broke?
2. Where did it fail?
3. What changed before the failure?

Do not add multi-tenancy, billing, AI analysis, Kubernetes, a proprietary
tracing protocol, a dedicated message broker, or other infrastructure unless an
accepted ADR and an updated MVP explicitly require it. Never describe an
observed trace or configuration change as a root cause without sufficient
evidence.

The normative product and architecture documents are:

- `docs/MVP.md`
- `docs/architecture/README.md`
- Accepted ADRs in `docs/architecture/ADRs/`
- `docs/ROADMAP.md`

If code and documentation conflict, stop and resolve the conflict. Material
architecture changes require an ADR before implementation.

## Intended repository layout

- `backend/`: Python 3.12 FastAPI API, worker, domain modules, migrations, and
  backend tests.
- `frontend/`: React, TypeScript, and Vite application and tests.
- `infra/`: Docker Compose and local configuration for PostgreSQL and Tempo.
- `docs/`: product scope, architecture, ADRs, operations, and roadmap.
- `.github/workflows/`: continuous integration.

Do not create production code outside these boundaries without documenting why.

## Backend boundaries

The backend is one deployable codebase with two process entry points: `api` and
`worker`. Preserve these module responsibilities:

- `sentinel.catalog`: projects, environments, test cases, immutable revisions,
  suites, and change records.
- `sentinel.execution`: execution and attempt state machines, job orchestration,
  request preparation, and result recording.
- `sentinel.regression`: assertions, comparison policies, immutable baselines,
  diffs, and verdict classification.
- `sentinel.telemetry`: OpenTelemetry context creation, correlation records, and
  Tempo queries.
- `sentinel.security`: target validation, secret resolution, redaction, and
  retention policies.
- `sentinel.api`: FastAPI transport, request/response schemas, and dependency
  wiring. It contains no domain decisions.
- `sentinel.worker`: queue polling, lease heartbeats, and application-service
  invocation. It contains no comparison or HTTP semantics.
- `sentinel.persistence`: SQLAlchemy models, repositories, units of work, and
  Alembic integration.

Domain code must not import FastAPI, SQLAlchemy, HTTPX, Tempo clients, or worker
entry points. Application services depend on explicit ports; adapters implement
those ports. The API and worker may compose modules but may not bypass their
public application services.

## Queue and request-safety invariants

- PostgreSQL job delivery is at least once and bounded, never exactly once.
- A recovered job lease is not permission to repeat an outbound API request.
- Persist an attempt in `dispatching` before network I/O.
- After an ambiguous crash window, automatically replay only `GET`, `HEAD`, and
  `OPTIONS`, or a test explicitly configured to allow replay.
- Every actual replay creates a new attempt ID, trace ID, and client span ID.
- Potentially non-idempotent ambiguous attempts end as `indeterminate`; they
  require operator review and are not silently retried.
- Queue retry counters, HTTP attempt counters, and trace-correlation retries are
  separate concepts and must remain separate in code, schemas, metrics, and UI.

## Regression invariants

- Exact response-body comparison is opt-in.
- Compare only explicit assertions and baseline selectors. Unselected fields are
  ignored rather than guessed to be volatile or stable.
- Baseline versions are immutable. Promotion creates a new version and changes
  an activation pointer; it never overwrites history.
- A performance threshold breach is a warning, not a functional regression.
- An observed but non-required difference is a change, not a regression.
- Missing or incomplete telemetry cannot change a functional test verdict.
- Transport uncertainty and unsafe replay conditions produce an inconclusive
  outcome, not a fabricated application failure.

## Trace invariants

- Use W3C Trace Context and Baggage through OpenTelemetry APIs. Do not invent a
  proprietary tracing protocol.
- Generate and persist correlation identifiers before dispatch.
- An execution contains one or more attempts; each dispatched attempt has one
  primary trace and client span and may have additional linked traces.
- Preserve the execution ID, attempt ID, trace ID, and client span ID as distinct
  fields. Never overload one as another.
- Treat delayed ingestion, sampling, context breaks, and partial spans as normal
  correlation states. Never fail a functional test because Tempo is unavailable.

## Security and privacy

- Never log or persist resolved secrets, `Authorization`, `Proxy-Authorization`,
  `Cookie`, `Set-Cookie`, API keys, session tokens, or unredacted sensitive
  bodies.
- Secret values come from process or mounted-secret environment variables.
  Definitions store references only.
- Redact before persistence and before structured logging. Tests must cover both.
- Bind public ports to loopback by default. Non-loopback API binding requires an
  operator-supplied bearer token.
- Validate outbound targets after DNS resolution. Private, loopback, link-local,
  metadata, and operator-denied destinations are blocked unless explicitly
  allowlisted. Redirect following is off by default.
- Enforce request timeouts, response-size limits, bounded concurrency, and TLS
  verification by default.
- Use synthetic data in fixtures and documentation. Never commit real tokens,
  production payloads, trace exports, or database dumps.

## Python conventions

- Target Python 3.12 and use modern type annotations.
- Use Pydantic v2 at transport and configuration boundaries and SQLAlchemy 2.x
  for persistence.
- Keep domain types independent from ORM and API schemas.
- Use UUIDs for public identifiers, UTC-aware `datetime`, PostgreSQL
  `timestamptz`, lowercase snake-case enum values, and explicit state-transition
  methods.
- Use `Decimal` or integer milliseconds where precision matters; do not compare
  floating-point durations for deterministic decisions.
- Return RFC 9457 `application/problem+json` errors from HTTP APIs. Error bodies
  must be stable, documented, and free of secrets.
- Use structured logging with event names and identifiers. Do not log complete
  request or response objects.
- Keep functions and modules focused. Prefer explicit dependencies over module
  globals and import-time side effects.
- Format and lint with Ruff and type-check with mypy in strict mode. Do not
  suppress a check without a local explanation.

## TypeScript conventions

- Enable TypeScript strict mode; do not use `any` to bypass an API mismatch.
- Generate or derive API client types from the versioned OpenAPI document.
- Organize UI code by feature (`catalog`, `executions`, `baselines`, `traces`),
  with shared primitives under `src/shared`.
- Keep server state in a query/cache layer and local presentation state in
  components. Do not duplicate backend state machines in ad hoc strings.
- Meet keyboard-navigation, focus, semantic HTML, and contrast requirements.
- Format with Prettier, lint with ESLint, and test behavior with Vitest and React
  Testing Library.

## Database and migrations

- Every schema change requires an Alembic migration and a downgrade unless the
  ADR for that change explicitly explains why downgrade is unsafe.
- Migrations must be deterministic, reviewed SQL must be visible, and destructive
  data migrations require a backup/rollback note.
- Transactions own state transitions. Use row locks or compare-and-set updates
  where concurrency matters.
- Add indexes from demonstrated access patterns, including runnable-job claims,
  execution history, active baselines, and trace lookups.
- JSONB is for versioned request/comparison documents and redacted artifacts,
  not for hiding relational identities or lifecycle state.
- Tests must run against PostgreSQL. SQLite is not a substitute for queue,
  locking, JSONB, or migration tests.

## Testing and verification

Use test-driven development for production changes:

1. Add a failing test for the behavior or invariant.
2. Confirm it fails for the expected reason.
3. Add the smallest implementation that satisfies it.
4. Run focused tests, then the relevant suite.

Required test layers:

- Unit tests for state machines, comparison rules, normalization, redaction, and
  policy validation.
- PostgreSQL integration tests for repositories, migrations, leasing, expiration,
  concurrent claims, retry exhaustion, and retention.
- HTTP adapter tests for timeout, size limit, TLS, redirect, DNS, and ambiguous
  dispatch behavior.
- API contract tests for OpenAPI schemas, problem responses, and idempotency keys.
- Tempo/OpenTelemetry integration tests for propagation and missing, delayed,
  partial, and multiple traces.
- Frontend component tests and a minimal Docker Compose end-to-end smoke test.

Time, UUID generation, DNS resolution, HTTP transport, and telemetry lookup must
be injectable in tests. Do not use sleeps to test leases or delayed ingestion.

Before declaring work complete, run the linters, type checks, migrations, focused
tests, and the relevant full suite. Report the exact commands and results. Do not
claim success based only on code inspection.

## API and compatibility

- Version public endpoints under `/api/v1`.
- Treat persisted revision documents, OpenAPI schemas, queue payloads, and enum
  values as compatibility surfaces.
- Additive response changes are preferred. Breaking API or persisted-document
  changes require a migration plan and ADR.
- Validate all untrusted inputs at the boundary and enforce domain invariants
  again in application services.

## Documentation expectations

- Update `docs/MVP.md` when acceptance criteria or exclusions change.
- Update `docs/architecture/README.md` when module boundaries, flows, or data
  relationships change.
- Add or supersede an ADR for consequential decisions; do not rewrite accepted
  history to make a later choice appear original.
- Update `docs/ROADMAP.md` when milestone scope or exit criteria change.
- Document assumptions, operational limits, privacy consequences, and failure
  behavior. Prefer precise claims over aspirational language.
