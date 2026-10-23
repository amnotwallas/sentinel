# Milestone 4 planning handoff

Status: **M4-00 frozen and accepted; M4-01 not started**.
Milestones 1, 2, and 3 are accepted; the accepted M3 implementation remains
`a41670b5c9da5410d0bd50d4ceaca495d23998bf`, and the published documentation
base for M4-00 is `b63c456148a626606dcc5568a3bae9d6a8fff3ff`.
This handoff preserves the inputs and questions supplied to M4-00. Their accepted
resolutions are in the [M4 implementation packet](../implementation/milestone-4.md),
[task plan](milestone-4-plan.md),
[ADR 0009](../architecture/ADRs/0009-deterministic-evaluation-and-baseline-bootstrap.md),
[ADR 0010](../architecture/ADRs/0010-baseline-api-persistence-and-provenance.md).
Those documents freeze the M4-00 contract and allocate the next migration in
documentation only; they do not change runtime compatibility surfaces or
authorize production changes.

## Normative inputs

- [AGENTS.md](../../AGENTS.md), the [MVP](../MVP.md), the
  [Milestone 4 roadmap scope](../ROADMAP.md#milestone-4-deterministic-evaluation-and-baseline-management),
  and the [architecture](../architecture/README.md) define product and module
  boundaries.
- [ADR 0003](../architecture/ADRs/0003-deterministic-regression-detection.md)
  fixes explicit deterministic evaluation, normalizers, verdict precedence, and
  explainable bounded evidence.
- [ADR 0004](../architecture/ADRs/0004-immutable-baselines.md) fixes baseline
  scope, immutability, eligibility, compatibility, activation history, and
  retention behavior.
- [ADR 0006](../architecture/ADRs/0006-security-privacy-retention.md) requires
  redaction before persistence and limits baselines to selected normalized
  redacted values.
- The accepted [Milestone 2 packet](../implementation/milestone-2.md) and planned
  OpenAPI/fixtures are historical design inputs. Their future `Evaluation` and
  `BaselineComparison` components explicitly retain M4 open decisions and are not
  implemented routes or automatically accepted wire contracts.
- The accepted [Milestone 3 packet](../implementation/milestone-3.md) supplies
  durable observations, attempt/replay identity, execution aggregation seams,
  and the `response_received -> evaluated` lifecycle boundary that M4 must fill.
- Use the [development workflow](workflow.md) for ownership/isolation and the
  [quality gates](quality-gates.md) for candidate evidence.

## Current implementation boundary

M2 already validates and stores immutable assertion/comparison documents and a
canonical SHA-256 policy fingerprint. The accepted v1 rule documents include
required/advisory assertions, JSON or complete-text selectors, the `none`,
`sort_scalar_array`, and `round_decimal` normalizers, and an optional integer
duration threshold.

M3 persists redacted bounded observations and pins the exact test-case revision
for every execution item. `TestAttempt` already has an `evaluated` state and an
`included_in_verdict` flag; replay predecessors are excluded when a successor is
created. Execution and item rows already carry the accepted verdict vocabulary,
but attempt verdicts are not persisted and attempt API reads return `null`.
Today a durable attempt remains in `response_received`; its item and eventual
execution complete with `not_evaluated`, and the job succeeds because the
evaluator, evaluation records, baseline rows, and baseline APIs do not exist.
Runtime OpenAPI exposes only implemented M3 fields; it must not grow until an M4
slice implements and tests the corresponding behavior.

## Accepted M4 requirements

### 1. Evaluation responsibility

- `sentinel.regression` owns pure assertion/selector evaluation, deterministic
  normalization, bounded evidence, and verdict classification. It remains free
  of FastAPI, SQLAlchemy, HTTPX, Tempo, and worker entry points.
- Execution orchestration supplies the immutable revision, persisted redacted
  observation, duration, and the selected immutable baseline candidate through
  explicit ports. The worker invokes an application service; it does not contain
  comparison rules.
- Lifecycle and verdict remain separate. Trace availability is never an evaluator
  input and may not rewrite a functional verdict.
- Only the attempt marked `included_in_verdict` participates after replay. No
  evaluation may resend, refetch, or recover missing target content.

### 2. Assertions and deterministic comparison

- Evaluate only explicit status, header, JSON Pointer, exact text, selector, and
  duration rules from the pinned immutable test revision. Unselected fields are
  ignored and exact body comparison is opt-in.
- Header names compare case-insensitively. JSON Pointer presence distinguishes an
  absent value from JSON `null`; booleans are not numbers; array order matters
  unless an accepted normalizer changes it; object key order does not.
- Numeric evaluation uses exact decimal/integer semantics, never binary floating
  point. `round_decimal` uses the stored scale and half-even mode.
- `sort_scalar_array` accepts only homogeneous arrays of one JSON scalar type and
  rejects mixed or nested values. Normalizer input errors are explicit and are
  never coerced.
- Evaluation records retain stable rule identity, kind, severity, outcome,
  message code, and bounded redacted expected/actual evidence sufficient to
  explain the result.

### 3. Verdict semantics

- Accepted precedence is `inconclusive`, `baseline_required`,
  `functional_regression`, `performance_warning`, `observed_change`, then
  `passed`.
- `not_evaluated` applies only when platform infrastructure prevents every
  relevant API observation from reaching evaluation.
- Missing, truncated, expired, or redaction-omitted content required by a rule
  cannot fabricate equality; required unavailable evidence is inconclusive.
- Required assertion/selector mismatch is a functional regression. Advisory
  mismatch is an observed change. A duration breach is advisory and cannot
  produce a functional regression.
- Transport uncertainty remains distinct from application behavior and follows
  the accepted M3 mapping; M4 must not relabel it as an assertion failure.

### 4. Baseline lifecycle

- Baselines are scoped to test-case and environment identities and receive a
  monotonically increasing version within that scope.
- A baseline version is immutable. It stores the source attempt and test-case
  revision, exact policy fingerprint, selected normalized redacted values,
  creation time, and optional operator reason.
- Promotion is explicit. Creating a baseline from an eligible attempt creates a
  new version and activates it; Sentinel never auto-promotes repeated results.
- Activation is append-only history. Replacing or rolling back closes the prior
  active row and inserts a new activation in one transaction; no baseline row is
  edited. At most one activation is current for a test-case/environment scope.
- A baseline may be compared only when its policy fingerprint matches exactly;
  Sentinel never partially compares or guesses compatibility. A required missing
  or incompatible baseline produces `baseline_required`. M4-00 must settle the
  advisory-only case identified below.
- A request-only revision whose comparison-policy fingerprint is unchanged may
  use the active compatible baseline while retaining both revision provenances.

### 5. Eligibility, associations, and retention

- Promotion requires an `evaluated` source attempt, all required explicit
  assertions passing, every selected value captured/evaluated, no selected
  evidence lost to truncation/redaction fallback, matching scope/fingerprint,
  and canonical representability.
- `observed_change` and `performance_warning` attempts may be eligible when all
  required functional checks pass. `functional_regression`, `inconclusive`,
  `baseline_required`, and `not_evaluated` attempts are ineligible under the
  accepted ADR.
- Evaluation and baseline-comparison records must preserve the actual immutable
  baseline candidate used; later activation changes may not rewrite history or
  change a completed verdict.
- Execution reads link the immutable revision, baseline candidate, and relevant
  definition/baseline change events using bounded deterministic ordering. This is
  evidence only and is never labeled as a root cause.
- Baseline activation emits the accepted append-only `baseline_activated` change
  event without sensitive or free-form selected values in its summary.
- Baseline values survive response-artifact expiry and must not depend on retained
  source-execution details; provenance identifiers and minimal metadata remain.
  Definition and baseline versions remain until explicit project deletion.
  Operational execution-metadata cleanup remains M7 scope unless M4-00 explicitly
  transfers it.

### 6. API and privacy boundaries

- The MVP requires list, create/promote, and activate/rollback endpoints under
  `/api/v1/test-cases/{test_case_id}`. Immutable baseline versions have no
  in-place update endpoint.
- Promotion/activation validate scope, eligibility, compatibility, and
  concurrency in application services, not only at the API boundary. Stable
  RFC 9457 problems must not echo sensitive evidence.
- Redaction occurs before evaluation records, baselines, API responses, logs, or
  test snapshots. Baselines store only selected normalized redacted values, never
  full response bodies, fixed-sensitive headers, resolved secrets, or raw request
  objects.
- The optional operator reason is bounded persistent metadata: validate it at the
  boundary, never place it in logs or change-event summaries, and make its
  retention-until-project-deletion behavior explicit to the operator.
- Selected baseline values and evaluation expected/actual evidence can still
  contain sensitive business data when an operator selects a field that the
  redaction policy does not cover. API/UI documentation must state their response
  visibility and retention: evaluation metadata follows the accepted 30-day
  default, while baseline versions remain until project deletion. Sentinel does
  not infer sensitive fields or silently expand redaction rules.
- Expected/actual evidence and result collections remain bounded. Evidence that
  cannot be included safely is omitted explicitly rather than replaced with an
  unsafe fallback.

## Persistence and migration implications

M4 requires relational identities and lifecycle state for evaluation records,
immutable baseline versions, and activation history. JSONB is appropriate only
for versioned selected values and bounded redacted evidence, not for hiding scope,
foreign keys, versions, activation state, or provenance.

The M4-00 contract must define the exact tables, constraints, deletion behavior,
candidate association, indexes, and transaction locks before the coordinator
allocates migrations. At minimum, PostgreSQL must enforce baseline ownership,
unique monotonic versions per test-case/environment scope, immutable provenance,
one current activation per scope, ordered evaluation records, and associations to
the attempt and baseline actually evaluated. Compatibility is enforced atomically
by the application service and by database constraints only where the frozen
representation can express it; M4-00 chooses the exact mechanism.
Migration acceptance must include visible upgrade/downgrade SQL, `head -> base ->
head`, Alembic drift checks, preservation of accepted M1-M3 data, and concurrent
promotion/activation tests against a dedicated disposable PostgreSQL database.

## Required acceptance coverage

M4 acceptance must include:

1. every assertion kind at required and advisory severity, including absent versus
   JSON-null behavior, case-insensitive headers, invalid JSON, and opt-in text;
2. `none`, homogeneous scalar-array sorting, exact decimal half-even rounding,
   and explicit mixed/nested/wrong-type normalizer failures;
3. unselected volatility, object key order, numeric precision, array-order, and
   exact-body-default tests;
4. all seven verdict categories and precedence combinations at attempt, item,
   execution, and ordered-suite aggregation levels;
5. truncated, expired, missing, and redaction-omitted required/advisory evidence
   without unsafe fallback or secret leakage;
6. replay chains proving that only the included successor contributes;
7. first creation, repeated promotion, compatible rollback, incompatible
   activation rejection, and immutable history;
8. concurrent promotion/activation proving unique versions and one current
   activation without lost updates;
9. policy-compatible request-only revisions, required-selector policy changes
   that yield `baseline_required`, and advisory-only changes that follow the
   explicit M4-00 decision rather than reusing an incompatible baseline;
10. source-artifact expiry without baseline value loss, plus schema/FK proof that
    baselines do not depend on retained source-execution details;
11. stable problem responses, bounded read payloads, OpenAPI/generated-client
    drift, relevant definition/baseline change evidence, and synthetic-canary
    inspection of baseline and evaluation values across database, API, logs, and
    spans;
12. migration SQL/up/down/drift, full PostgreSQL tests, and a Compose journey from
    execution through evaluation, explicit promotion, later comparison, and
    rollback.

## Questions resolved by M4-00

These were unresolved when this handoff was accepted. The accepted M4-00 packet
supplies the answers below and keeps this list as the review checklist. Each item
is traceable to executable acceptance criteria before M4 creates compatibility
surfaces:

1. **First-baseline bootstrap:** ADR 0004 requires an evaluated eligible attempt
   and declares `baseline_required` attempts ineligible, while the MVP needs an
   explicit path to create the first baseline. Define the bootstrap evaluation,
   verdict, confirmation, and eligibility contract without weakening required
   assertions or silently auto-accepting selected values. Also define missing and
   incompatible behavior for policies with no selectors or only advisory
   selectors.
2. **Baseline candidate selection time:** decide whether an execution pins the
   active baseline during creation, item acquisition, or evaluation. Persist the
   actual immutable candidate and define concurrent activation behavior; a later
   API read may never substitute the current pointer.
3. **Invalid normalizer result:** accepted docs require an explicit evaluation
   error but do not decide its final verdict mapping. Freeze required/advisory
   behavior and aggregation without silently classifying it as either a regression
   or infrastructure failure.
4. **Runtime wire contract:** freeze create/list/activate request and response
   bodies, pagination/order, operator-reason bounds, confirmation/warning fields,
   ETag/`If-Match` scope, the test revision/fingerprint against which activation
   compatibility is checked, and exact problem mappings. The MVP route inventory
   and M2 future components do not settle these details.
5. **Evaluation persistence shape:** freeze evaluation ordering/identity,
   attempt verdict and baseline-comparison persistence, evidence caps, nullable
   and migration/backfill behavior, and whether performance uses a synthetic rule
   identity. Pre-M4 completed rows remain historical records and may not be
   automatically re-evaluated against a later baseline. M2's future `Evaluation`/
   `BaselineComparison` shapes are proposals with explicit open-decision markers.
6. **Aggregation transaction boundary:** define the fenced atomic transition from
   `response_received` to `evaluated`, item/execution aggregation, and recovery
   after evaluation persistence but before job completion. It must preserve M3's
   no-resend recovery guarantee.
7. **Deletion provenance:** ADR 0004 requires minimal provenance after source
   execution detail deletion, but project deletion and later M7 retention must
   agree on exact foreign-key/deletion behavior.
8. **Execution change evidence:** freeze which definition/baseline events are
   relevant to an execution, their bounded order, retained identifiers, and API
   shape. The current execution API returns an empty collection and the roadmap
   requires a real association rather than an inferred root-cause claim.

If resolving any item changes accepted architecture rather than closing an
unspecified wire/transaction detail, stop and add or supersede an ADR before
implementation. Do not edit accepted ADR history.

## Accepted implementation slices

The sequence is deliberately mostly serial because the evaluator, persistence,
worker transition, and public contract share compatibility decisions.

### M4-00 — Contract freeze and acceptance matrix

- Resolve every open decision above; freeze domain vocabulary, transactions,
  wire shapes, evidence bounds, schema relationships, and named acceptance cases.
- Produce the reviewed implementation packet and planned schema/fixtures without
  registering routes or allocating production migrations prematurely.
- **Dependency:** accepted M3 SHA `a41670b`.

### M4-01 — Pure deterministic evaluator

- Implement assertion evaluation, JSON Pointer handling, versioned normalizers,
  selected-value comparison, bounded evidence, and pure verdict aggregation under
  `sentinel.regression`.
- Use existing validated immutable definition documents and `Decimal`; add no
  dependency unless M4-00 demonstrates the standard library and installed stack
  are insufficient.
- **Dependency:** M4-00 frozen semantics. No database or API work.

### M4-02 — Evaluation and baseline persistence foundation

- Add the allocated Alembic revision `0010` on parent `0009`, domain ports,
  PostgreSQL repositories, constraints, indexes, and transaction tests for
  attempt verdicts, the actual baseline-comparison candidate/result, ordered
  evaluation records, immutable baselines, and activation history. Freeze
  nullable/backfill handling for M3 rows without retroactive evaluation.
- Prove concurrent version allocation/activation, downgrade/re-upgrade, accepted
  M1-M3 data preservation, and actual-candidate association.
- **Dependency:** M4-00 schema and transaction contract; consumes M4-01 value
  types without importing framework/ORM concerns into the domain.

### M4-03 — Fenced execution evaluation and aggregation

- Connect durable response observations and the pinned baseline candidate to the
  evaluator, persist the attempt verdict/comparison/evaluations atomically under
  the live job fence, transition attempts to `evaluated`, and aggregate
  item/execution verdicts.
- Recovery after every new checkpoint must resume without target resend or result
  duplication; replay predecessors remain excluded.
- **Dependency:** integrated M4-01 and M4-02.

### M4-04 — Baseline application services

- Implement explicit create/promote, list/history, and activate/rollback flows,
  including eligibility, fingerprint compatibility, optimistic concurrency,
  append-only change evidence, and stable safe problems.
- Keep transport routes, runtime OpenAPI, and generated clients unchanged; this
  slice owns no M6 authoring UI and does not auto-promote.
- **Dependency:** evaluated-attempt and persistence contracts from M4-03.

### M4-05 — Baseline/result contract and typed-client handoff

- Publish baseline command/history routes together with implemented evaluation/
  baseline fields, update execution and attempt reads with persisted verdict/
  comparison data, complete pinned change anchors, and bounded contextual
  definition/baseline change evidence, regenerate runtime OpenAPI and TypeScript
  once under coordinator ownership, and add frontend client-consumption tests.
- Reconcile only the approved parts of M2's future schemas; preserve historical
  planned artifacts unless M4-00 explicitly supersedes them with a new planned
  contract.
- **Dependency:** integrated M4-03 and M4-04. No product UI.

### M4-06 — Independent acceptance and milestone integration

- Independently verify the accepted M4 matrix, privacy sinks, concurrency,
  migration round trips, contract drift, PostgreSQL suite, and full Compose
  evaluation/promotion/rollback journey on one exact integrated candidate.
- Record exact candidate identity, local evidence, review findings/resolution,
  and—after separately authorized publication—remote CI for that exact SHA.
- **Dependency:** M4-01 through M4-05 integrated; no unresolved security or
  compatibility finding.

## Ownership and readiness

The coordinator owns M4-00, shared model registration, migration allocation and
chain, API/worker composition, shared fixtures, generated contracts, milestone
documentation, integration, and final evidence. One backend writer should own
each sequential domain/persistence/application slice; frontend work begins only
after the coordinator publishes the implemented generated contract. Independent
QA/security review is read-only unless assigned exclusive acceptance files.

The M4-00 candidate prepared from documentation base `b63c456` passed independent
contract review with no unresolved critical or important finding. The repository
owner accepted ADRs 0009 and 0010 and the implementation packet on 2026-10-23.
M4-02 is allocated Alembic revision `0010_m4_evaluation_and_baselines`, parent
`0009_attempt_response_outcomes` (`0009`); this is documentation-only and creates
no migration file. Per-slice databases, ports, and production authorization are
allocated when each implementation slice begins.
