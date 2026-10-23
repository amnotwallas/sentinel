# Milestone 4 task plan

Status: **M4-00 frozen and accepted; M4-01 not started**. The documentation base is
`b63c456148a626606dcc5568a3bae9d6a8fff3ff`. The exact contracts are in the
[M4 implementation packet](../implementation/milestone-4.md),
[ADR 0009](../architecture/ADRs/0009-deterministic-evaluation-and-baseline-bootstrap.md),
[ADR 0010](../architecture/ADRs/0010-baseline-api-persistence-and-provenance.md).

Follow [workflow.md](workflow.md). Each production slice starts only after its
dependency is integrated, in a fresh isolated worktree with a unique PostgreSQL
test database and reserved ports. The coordinator owns shared wiring, model
registration, migration allocation/chain, runtime OpenAPI, generated TypeScript,
shared fixtures, milestone documents, and integration. One writer owns each
file.

## Dependency order

```text
M4-00 contract acceptance
  -> M4-01 pure evaluator
  -> M4-02 persistence foundation
  -> M4-03 fenced orchestration and aggregation
  -> M4-04 baseline services
  -> M4-05 baseline/result API and typed contract
  -> M4-06 independent milestone acceptance
```

The sequence is intentionally serial. Parallelizing shared verdict, persistence,
or generated-contract work would increase merge and compatibility risk without a
meaningful independent seam.

## M4-00 — Accepted contract freeze

- **Objective:** Resolve all eight planning questions and produce one reviewable
  contract, ADR rationale, acceptance matrix, and implementation order.
- **Owned files:** ADRs 0009/0010, M4 implementation packet, this plan, and M4
  planning handoff status/link updates.
- **Acceptance:** Independent architecture, API, persistence, failure-recovery,
  and privacy review; no unresolved critical/important finding; valid links;
  documentation-only diff; `git diff --check`; no accepted ADR edited.
- **Current status:** Accepted by the repository owner on 2026-10-23; ADRs 0009
  and 0010 are accepted; no production slice is included.
- **Migration allocation (documentation-only):** M4-02 owns Alembic revision
  `0010_m4_evaluation_and_baselines`, parent `0009_attempt_response_outcomes`
  (`0009`). M4-00 creates no migration file.
- **Integration gate:** The accepted documentation commit must be integrated before
  M4-01 begins. No production slice may change this contract silently.

## M4-01 — Pure deterministic evaluator

- **Objective:** Implement assertions, selectors, versioned normalizers, bounded
  evidence, baseline comparison, and verdict aggregation as pure domain code.
- **Dependencies:** Accepted/integrated M4-00.
- **Owned areas:** `sentinel.regression` value types/services and focused unit
  tests only. No SQLAlchemy, FastAPI, worker, migration, or generated contract.
- **Acceptance:** `M4-EVAL-01` through `M4-EVAL-05`; no binary-float decision;
  deterministic order/canonical vectors; all verdict precedence combinations;
  no I/O or secret-bearing input.
- **Gate:** Ruff, strict mypy, focused regression tests, then backend unit suite.

## M4-02 — Persistence foundation and candidate pinning

- **Objective:** Persist pinned candidates, attempt verdicts, comparison/result
  rows, inherited execution result-contract versions, immutable baselines, and
  activation history with enforceable ownership and concurrency constraints.
- **Dependencies:** Integrated M4-01 domain values and the M4-00 allocation of
  Alembic revision `0010` on parent `0009`.
- **Owned areas:** Domain ports, SQLAlchemy rows/repositories, execution
  materialization pinning, one allocated Alembic migration, and PostgreSQL tests.
  Coordinator owns shared model/migration registration.
- **Acceptance:** `M4-DB-01` through `M4-DB-04` and `M4-RECOVERY-01`; sorted locks,
  one current activation, unique versions/source/ordinals, legacy preservation,
  in-flight version-0/replay inheritance, upgrade/downgrade/drift, and no target
  I/O while locked.
- **Gate:** Focused unit/PostgreSQL concurrency tests, reviewed migration SQL,
  migration round trip, backend full gate.

## M4-03 — Fenced evaluation and aggregation

- **Objective:** Connect durable M3 observations and pinned candidates to the
  pure evaluator, atomically persist results, and advance item/execution state.
- **Dependencies:** Integrated M4-01 and M4-02.
- **Owned areas:** Execution application service, worker invocation/composition,
  aggregation repositories, and crash/replay tests. It does not own baseline API
  or generated clients.
- **Acceptance:** `M4-RECOVERY-02`, `M4-RECOVERY-03`, all attempt/item/execution
  verdict categories, ordered-suite stop/aggregation behavior, stale-fence
  rejection, one result set, and no resend/refetch after response durability.
  `M4-RECOVERY-04` covers max delivery after a durable response; version-0
  executions and replays retain M3 aggregation.
- **Gate:** Focused state/recovery tests with injected time, UUIDs, and failures;
  PostgreSQL two-worker tests; backend full gate.

## M4-04 — Baseline services

- **Objective:** Implement promotion, immutable version creation, activation,
  rollback, history, warning confirmation, and scope concurrency behind explicit
  application ports.
- **Dependencies:** Integrated M4-03 results and M4-02 persistence.
- **Owned areas:** Baseline application service/ports/repositories,
  change-event writes, and domain/PostgreSQL tests. No FastAPI route, runtime
  OpenAPI change, generated client, or product UI.
- **Acceptance:** `M4-BASELINE-01` and `M4-BASELINE-02`; exact command result and
  ETag value semantics through service ports, retry no-op, immutable reasons,
  privacy/retention rules, and transaction rollback.
- **Gate:** Focused domain/PostgreSQL concurrency tests and backend full gate;
  runtime/generated contracts remain byte-for-byte unchanged.

## M4-05 — Baseline/result API, change evidence, and typed handoff

- **Objective:** Publish list/promote/activate commands together with implemented
  evaluation/baseline reads, promotion assessment, complete pinned change
  anchors, and bounded contextual evidence; regenerate clients once.
- **Dependencies:** Integrated M4-03 and M4-04.
- **Owned areas:** Baseline transport schemas/routes/API tests, stable problems,
  attempt/execution read repositories and routes, runtime OpenAPI, generated
  TypeScript, client-consumption tests, and contract reconciliation. Coordinator
  exclusively owns generated artifacts.
- **Acceptance:** All of `M4-API-01`, `M4-API-02`, and `M4-CHANGE-01`; exact
  result/error/legacy projections, status/body/ETag/order/bounds, later-event
  exclusion, safe provenance, generated compilation, and no causal wording.
- **Gate:** Backend contract/full tests, frontend lint/type/Vitest/build, runtime
  and generated drift checks.

## M4-06 — Independent acceptance and milestone integration

- **Objective:** Verify the exact integrated candidate against the complete M4
  contract and roadmap, including failure recovery and privacy sinks.
- **Dependencies:** M4-01 through M4-05 integrated with no unresolved review
  finding.
- **Owned areas:** Independently assigned acceptance files/worktree/database and
  coordinator-owned final documentation. Reviewer remains read-only unless
  exclusive files are assigned.
- **Acceptance:** Every named matrix case, `M4-PRIVACY-01`,
  `M4-RETENTION-01`, and `M4-E2E-01`; migration up/down/drift, complete
  PostgreSQL gate, runtime/generated contract gate, and full Compose journey.
- **Evidence:** Exact candidate SHA or uncommitted fingerprint, command/count
  report, migration SQL, review findings/resolutions, Compose identity, and only
  after authorized publication exact-SHA remote CI evidence.

## Release rules

Passing a slice does not authorize commit, push, merge, remote changes, or the
next slice. No production slice may silently change an accepted M4 contract; a
material change requires an ADR that supersedes rather than rewrites accepted
history. `make check-fast` never substitutes for the PostgreSQL, migration,
contract, privacy, or Compose gates assigned above.
