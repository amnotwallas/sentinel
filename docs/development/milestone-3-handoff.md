# Milestone 3 acceptance handoff

Status: **PASS**. M3-00 through M3-06 are complete on `main` at accepted
implementation SHA `a41670b5c9da5410d0bd50d4ceaca495d23998bf`. M3-06 local
acceptance completed on 2026-10-21 from base
`76ed18c9d816650af1c0d9b4fad0381a6cdedd70` and was integrated through acceptance
commit `4b4193ad50f39d4e174a82dd769e0194b17da8cb`. Milestone 2 remains
accepted with status **PASS** at
`6b83adf0b8c9d9dcb0bba668a9e15d8ff0b4d715`; its historical record is unchanged.

The repository owner previously supplied remote evidence for base SHA `76ed18c`:
workflow `checks` concluded `success`; Backend and PostgreSQL, Frontend and
Contracts, and Docker Compose all passed. Reported counts were 247 non-integration
backend tests, 152 PostgreSQL integration tests, 399 aggregate backend tests in
31.21 seconds, and 10 frontend Vitest tests. This report was not independently
retrieved and is historical pre-acceptance evidence, not the final M3 acceptance
evidence below.

## Normative inputs

- [AGENTS.md](../../AGENTS.md), [MVP](../MVP.md), the
  [Milestone 3 roadmap scope](../ROADMAP.md#milestone-3-safe-execution-lifecycle-and-http-adapter),
  [architecture](../architecture/README.md), and accepted ADRs remain authoritative.
- ADR 0002 governs PostgreSQL at-least-once job delivery and lease fencing; ADR
  0005 governs per-attempt OpenTelemetry identity; ADR 0006 governs secrets,
  redaction, and persistence; ADR 0007 governs dispatch checkpoints, replay, target
  validation, redirects, TLS, timeouts, capture limits, and bounded concurrency.
  [ADR 0008](../architecture/ADRs/0008-http-dispatch-outcomes-and-tls-policy.md)
  extends ADR 0007 with the frozen transport-failure, certainty, redirect, TLS,
  trust, proxy, and DNS-pinning rules.
- The frozen [Milestone 3 implementation packet](../implementation/milestone-3.md)
  and [task plan](milestone-3-plan.md) control M3 compatibility surfaces and slice
  ownership.
- The [Milestone 2 implementation packet](../implementation/milestone-2.md) and
  planned OpenAPI/fixtures remain historical review inputs. Runtime OpenAPI and
  generated TypeScript now describe the implemented M3 routes.
- Use the [development workflow](workflow.md) for ownership and isolation and the
  [quality gates](quality-gates.md) for verification evidence.

## Integrated implementation

- M1 provides the durable PostgreSQL job queue, bounded delivery, lease heartbeat,
  expiration recovery, and stale-token fencing.
- M2 provides immutable project/environment/test/suite inputs, exact suite revision
  pins, canonical request policies, secret references, strong ETags, change
  history, active OpenAPI generation, and typed frontend client consumption.
- M3-01 through M3-05 provide execution creation and reads, attempt persistence,
  in-memory secret resolution, redacted bounded observations, safe target HTTP
  dispatch, conservative recovery, and generated client contracts.
- Assertion/baseline evaluation, Tempo reconciliation, and the product UI remain
  outside the implemented runtime and belong to later milestones.

## Milestone 3 outcome and boundaries

Milestone 3 executes one test or ordered suite from `POST /api/v1/executions`
to a durable, bounded, redacted observation while preserving deterministic crash
recovery. It includes execution/idempotency persistence, revision pinning, request
preparation, in-memory secret resolution, the safe HTTP adapter, attempt trace
identity/checkpointing, resumable orchestration, and execution/attempt reads.

It does not include baseline comparison/promotion (M4), Tempo reconciliation and
linked-trace discovery (M5), authoring/results UI (M6), scheduling, notifications,
multi-tenancy, billing, AI analysis, Kubernetes, or a dedicated broker. Missing
telemetry must not alter functional execution outcomes.

## Resolved M3-00 contracts

1. A known durable transport/redirect failure uses terminal attempt state
   `transport_failed`. `DispatchCertainty` distinguishes `not_started`, positively
   proven `not_sent`, `possibly_sent`, and `response_received`.
2. The `dispatching` checkpoint commits `possibly_sent` before DNS. Only positive
   controlled pre-write phase evidence under a live fenced lease may record
   `not_sent`; exceptions, cancellation, lease loss, process death, or uncertain
   commit do not.
3. A received `3xx` is an accepted response when redirects are disabled. When an
   enabled safe-method redirect hop is rejected, the attempt is
   `transport_failed`/`redirect_denied` with `response_received` certainty, the
   preceding response is sanitized evidence, and no connection reaches the
   rejected hop.
4. HTTPS verification is mandatory with TLS 1.2 or newer. Existing
   `verify_tls: false` definitions stay readable but fail before DNS/socket I/O.
   Trust is default roots plus an optional deployment-wide additive CA bundle;
   proxy inheritance, mTLS, early data, insecure mode, and target pooling are out
   of MVP scope.
5. The integrated HTTPX/httpcore adapter dials a selected IP while retaining the
   original authority and SNI/hostname verification through a narrow
   version-qualified seam. M3-06 independently requalified this behavior;
   dependency upgrades require the same gate and may not fall back to hostname
   re-resolution.
6. Execution, item, attempt, artifact, idempotency, and job transaction boundaries
   are frozen in the M3 packet. Queue delivery, attempt sequence, redirect hops,
   and trace retries remain distinct.
7. First-required-baseline bootstrap and baseline-selection timing remain M4
   decisions. M3 does not invent baseline semantics.

A material change to these contracts requires an ADR/product update before
implementation. Runtime OpenAPI and generated clients are published only with
implemented slices.

## Accepted delivery sequence

The accepted integrated sequence was:

1. **M3-00 — Freeze execution contracts and recovery cases.** Integrated at
   `3a83e26`. ADR 0008, the M3 packet, named acceptance cases, transaction
   boundaries, and migration reservations are documented.
2. **M3-01 — Atomic execution creation and immutable materialization.** Integrated
   at `a12744c`. Persist
   executions/items/idempotency records, pin all source revisions in one
   transaction, enqueue atomically, and add POST/list/detail contracts without
   dispatching a target request.
3. **M3-02 — Request preparation and protected observations.** Integrated at
   `26f92c2`. Add template
   expansion, in-memory secret resolution, request fingerprinting, bounded capture,
   and redaction-before-persistence with synthetic canary coverage.
4. **M3-03 — Safe HTTP adapter.** Integrated at `becbc55`. The locked-stack selected-IP,
   authority, SNI, hostname, retry/proxy, and connection-isolation feasibility
   gate; then enforce DNS/address and redirect-hop validation, credential stripping
   across origins, TLS policy, timeout/size limits, streaming, and bounded
   concurrency through explicit ports.
5. **M3-04 — Resumable dispatch and recovery.** Integrated at `4264e63`. Persist
   `dispatching` before I/O,
   create per-attempt trace/span identity, checkpoint responses, separate job
   redelivery from HTTP replay, and implement conservative ambiguous recovery.
6. **M3-05 — Execution and attempt reads plus typed client handoff.** Integrated at
   `95a3a86`. Publish only
   implemented runtime schemas, regenerate artifacts once under coordinator
   ownership, and verify bounded redacted outputs.
7. **M3-06 — Independent acceptance and milestone integration.** **Complete.**
   Single tests and ordered suites, checkpoint
   termination, ambiguity/replay, target-policy attacks, privacy sinks,
   PostgreSQL/migration/contract gates, and full Compose passed locally. The
   acceptance candidate was integrated and exact-candidate CI passed.

## Ownership and verification handoff

- The coordinator owns shared API/worker wiring, model registration, migration
  allocation and chain, fixture cleanup, generated OpenAPI/client artifacts,
  milestone documentation, integration, and final evidence.
- Start with one backend writer for the transaction/state-machine critical path.
  Split request preparation and the HTTP adapter only after their ports, shared
  types, and write sets are frozen. A security/QA reviewer is read-only unless
  assigned exclusive acceptance files.
- Use fresh isolated worktrees from the accepted base, separate disposable
  `_test` databases, and reserved ports. Do not reuse another task's worktree or
  runtime as evidence for an M3 candidate.
- Apply test-driven development to every production slice. Run focused tests,
  backend/frontend/contract gates as applicable, real PostgreSQL and migration
  round trips for persistence, security review for request/secret/network paths,
  and the task-owned full Compose gate at integration.
- M3 PASS required the exact integrated candidate identity, complete local
  evidence, independent review resolution, and remote CI evidence under the
  workflow rules. Those requirements are satisfied at `a41670b`; test success
  does not grant future commit, push, merge, or remote-setting permission.

## M3-06 local acceptance evidence — 2026-10-21

- **Candidate isolation:** branch `test/m3-06-acceptance` in a dedicated worktree
  from base `76ed18c9d816650af1c0d9b4fad0381a6cdedd70`, with disposable database
  `sentinel_m3_acceptance_test` and isolated Compose project
  `sentinel-m3-06-76ed18c`.
- **Acceptance gap closed:** 39 focused tests use local synthetic TLS peers and
  deterministic adapters to cover additive trust, untrusted/expired/hostname
  certificate rejection, original Host and SNI with selected-IP dialing, fresh
  connections, TLS policy, the locked httpcore seam, conservative transport
  classifications, 3xx rules, redirect denial, and alternate loopback/metadata
  address forms. All 39 passed in 9.40 seconds after the final fixture update.
- **Fast and contract gates:** `make check-fast` passed Ruff lint/format, strict
  mypy, 286 non-integration backend tests, ESLint, Prettier, TypeScript, 10 Vitest
  tests, the production frontend build, runtime OpenAPI/generated TypeScript drift,
  the planned contract inventory (16 operations, 121 schemas, 74 fixture cases),
  and repository tooling checks. `make check-compose-config` confirmed loopback
  public bindings.
- **PostgreSQL and migrations:** Alembic reported no pending model operations; all
  438 backend tests passed against PostgreSQL in 31.30 seconds. Offline upgrade and
  downgrade SQL was generated and reviewed, and the disposable database completed
  `head -> base -> head`; `alembic check` passed and the final revision was `0009
  (head)`.
- **Compose:** the packaged API migration, image build, health-gated startup,
  worker smoke, and frontend liveness probe passed. With Tempo stopped, API
  readiness remained `ready`, PostgreSQL remained `available`, and Tempo was
  reported `unavailable` as required.
- **Security/privacy review:** no production code or public contract changed. The
  only private key is deliberately public, synthetic, test-only material paired
  with the local TLS fixture; no credential or production data was added. The
  exercised denial paths do not echo rejected redirect locations.
- **Publication:** acceptance commit `4b4193a` was merged to `main` as
  `a41670b5c9da5410d0bd50d4ceaca495d23998bf`.

## Exact-candidate GitHub Actions evidence

The repository owner supplied matching evidence for workflow `checks`, branch/ref
`main`, and exact commit `a41670b5c9da5410d0bd50d4ceaca495d23998bf`:

- workflow conclusion: `success`;
- Backend and PostgreSQL job: `success`;
- Frontend and Contracts job: `success`;
- Docker Compose job: `success`;
- backend unit/contract pytest: 286/286 passed, 0 failed, 0 skipped;
- PostgreSQL integration pytest: 152/152 passed, 0 failed, 0 skipped;
- aggregate backend pytest: 438/438 passed, 0 failed, 0 skipped in 41.18 seconds;
- frontend Vitest: 10/10 passed, 0 failed, 0 skipped.

The report covers Ruff lint/format, strict mypy, migrations, schema drift,
PostgreSQL-backed tests, OpenAPI/generated TypeScript drift, ESLint, Prettier,
TypeScript, Vitest, the production frontend build, Compose configuration and
binding checks, packaged migration, startup, worker smoke, and Tempo-outage
readiness. Planned-contract validation and repository-tooling checks were not
configured in this workflow; they passed in the local M3-06 `make check-fast`
evidence above. No run URL/ID, attempt number, per-step log URL, workflow duration,
or frontend duration unit was supplied. Per instruction, this record accepts the
owner-supplied exact-SHA evidence without attempting credentialed retrieval.

## Next action

Proceed to the [Milestone 4 planning handoff](milestone-4-handoff.md). M4-00 must
freeze its unresolved evaluation, baseline-selection, persistence, and wire
contracts before production implementation begins.
