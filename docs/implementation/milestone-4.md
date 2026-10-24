# Milestone 4 implementation contract

Status: **PASS**. M4-00 through M4-06 are complete at accepted implementation SHA
`8e280be334b8fa71044005ad6557a3b91f0dd828`. This packet was frozen from
documentation base `b63c456148a626606dcc5568a3bae9d6a8fff3ff`; independent
contract review passed with no unresolved critical or important finding, and the
repository owner accepted the packet and ADRs 0009/0010 on 2026-10-23. The frozen
contract remains normative historical authority for the implemented milestone.

## Implementation ledger

| Slice | Integrated commit | Accepted outcome |
| --- | --- | --- |
| M4-00 — Contract freeze | `2870b0a0c27a9d235c3834d75d7e84824b419e93` | Contract, ADR rationale, schema relationships, wire semantics, and acceptance matrix frozen. |
| M4-01 — Pure evaluator | `b9c99c646cac2b5611339ce5b1315a1f8bcf7ff7` | Deterministic evaluation engine and unit coverage integrated. |
| M4-02 — Persistence foundation | `ccdb31253d0f6c21fa81b16883e5d7faf1696807` | Migration `0010`, repositories, constraints, candidate pinning, and PostgreSQL concurrency coverage integrated. |
| M4-03 — Fenced evaluation | `b65fc2cbe95ec42742777603d1155f201377dfe8` | Fenced persistence, aggregation, crash recovery, and no-resend behavior integrated. |
| M4-04 — Baseline services | `3a21b82f1cd7c43129f75da3f4939969a2ff3c31` | Explicit promotion, activation, rollback, history, and safe change evidence integrated. |
| M4-05 — Result contracts | `c9c7fcb7d1df2b1ff201f1b9079ea936c2b60a8f` | Baseline/result APIs, OpenAPI, generated TypeScript, and typed client coverage integrated. |
| M4-06 — Acceptance | `8e280be334b8fa71044005ad6557a3b91f0dd828` | Independent review defect corrected; exact-SHA owner-supplied CI accepted. |

The M4-06 review found that a response with an `application/json` or `+json`
media type was left as text when no JSON redaction pointer was configured. That
prevented the evaluator from receiving the JSON representation required by JSON
assertions and selectors. The accepted implementation detects JSON media types
independently of configured redaction pointers and includes a focused regression
test. The repository owner supplied matching GitHub Actions results for the
accepted SHA: Backend and PostgreSQL `success`, Frontend and Contracts `success`,
Docker Compose `success`, 500/500 backend tests passed, and 12/12 frontend tests
passed. The run was not independently retrieved and no run URL or step logs were
supplied.

## 1. Authority and scope

This packet closes the eight questions in the
[M4 acceptance handoff](../development/milestone-4-handoff.md). It must be read with
the [MVP](../MVP.md), [roadmap](../ROADMAP.md),
[ADR 0003](../architecture/ADRs/0003-deterministic-regression-detection.md),
[ADR 0004](../architecture/ADRs/0004-immutable-baselines.md),
[ADR 0006](../architecture/ADRs/0006-security-privacy-retention.md),
[ADR 0009](../architecture/ADRs/0009-deterministic-evaluation-and-baseline-bootstrap.md),
[ADR 0010](../architecture/ADRs/0010-baseline-api-persistence-and-provenance.md).

The accepted M2 future result schemas are design history, not runtime contracts.
This packet preserves their bounds where possible and explicitly resolves their
open markers. Runtime OpenAPI and generated TypeScript remain unchanged until an
implementation slice lands.

M4 excludes authoring UI, imported baselines, automatic promotion, custom
scripts, statistical/AI comparison, telemetry verdict input, cleanup workers,
and M7 retention execution.

## 2. Frozen domain vocabulary

### Evaluation records

`EvaluationKind` is `assertion | baseline_selector | performance`.

`Severity` is `required | advisory`; performance is always advisory.

`EvaluationOutcome` is `passed | failed | unevaluable | not_evaluated`.

The closed `message_code` vocabulary is:

- success: `assertion_passed`, `selected_value_match`,
  `duration_within_threshold`;
- assertion mismatch: `status_mismatch`, `header_missing`,
  `header_mismatch`, `json_missing`, `json_unexpected`,
  `json_type_mismatch`, `json_value_mismatch`, `text_mismatch`, `invalid_json`;
- selector result: `selected_value_mismatch`, `normalizer_input_invalid`,
  `baseline_missing`, `baseline_incompatible`;
- availability: `content_missing`, `content_expired`, `content_truncated`,
  `content_redacted`; and
- performance/lifecycle: `duration_exceeded`, `not_evaluated`.

There is no arbitrary message or captured exception. `expected` and `actual` are
JSON values or null, with `evidence_omitted` distinguishing actual JSON null from
absent evidence.

### Baseline comparison

The persisted states are `not_requested | missing | incompatible | compatible`.
Attempt reads may additionally project `pending` before evaluation or
`not_evaluated` after a terminal platform evaluation failure. Neither projection
is stored as a completed comparison.

- `not_requested`: no selectors; all candidate reference fields null and
  `checked_at` nonnull after successful evaluation.
- `missing`: selectors exist but no activation was pinned; reference fields null,
  `checked_at` nonnull.
- `incompatible`: pinned activation/baseline/version/fingerprint and
  `checked_at` nonnull.
- `compatible`: the same reference fields are nonnull; individual selectors may
  still pass, fail, or be unevaluable.
- `pending` and `not_evaluated`: all reference/check fields null; the attempt
  state distinguishes work still eligible for evaluation from terminal failure.

### Verdict calculation

Attempt verdict precedence remains:

1. `inconclusive`;
2. `baseline_required`;
3. `functional_regression`;
4. `performance_warning`;
5. `observed_change`;
6. `passed`.

`not_evaluated` is used only when no relevant target observation reached
evaluation. An included attempt supplies its verdict to the existing item,
ordered-suite, and execution aggregation; replay predecessors with
`included_in_verdict=false` never contribute.

| Condition | Evaluation | Verdict contribution |
| --- | --- | --- |
| Required assertion mismatch | `failed` | `functional_regression` |
| Advisory assertion mismatch | `failed` | `observed_change` |
| Required selector mismatch | `failed` | `functional_regression` |
| Advisory selector mismatch | `failed` | `observed_change` |
| Required selector missing/incompatible baseline | `not_evaluated` | `baseline_required` |
| Advisory selector missing/incompatible baseline | `not_evaluated` | none |
| Required invalid normalizer/unavailable content | `unevaluable` | `inconclusive` |
| Advisory invalid normalizer/unavailable content | `unevaluable` | none |
| Duration exceeded | `failed`, advisory | `performance_warning` |

Higher rows do not override the documented precedence. For example, an
inconclusive required selector plus a failed assertion remains inconclusive.

## 3. Deterministic evaluator contract

Inputs are immutable test definition data, the redacted observation, integer
duration milliseconds, and the pinned baseline candidate. Outputs are values;
the evaluator has no I/O.

- Header names compare case-insensitively after accepted normalization.
- RFC 6901 presence distinguishes absence from JSON null.
- Booleans are never numeric. JSON numbers parse and compare with `Decimal` or
  integer semantics; non-finite values are invalid.
- Object member order is ignored; array order remains significant unless
  `sort_scalar_array` applies.
- `sort_scalar_array` accepts only a homogeneous array of one JSON scalar type;
  null, boolean, number, and string are different types. Nested or mixed arrays
  are invalid.
- `round_decimal` accepts only a JSON number, uses the stored scale, and rounds
  half-even. It never converts through binary float.
- A selected value is normalized before canonical comparison and before it can
  become baseline content.
- Exact text evaluates only when `exact_text_body=true`; no implicit body
  snapshot exists.
- A JSON rule overlapping a configured redaction pointer in either direction,
  or a header rule naming a fixed/configured sensitive header, is
  `content_redacted`. Required rules are inconclusive; advisory rules are
  unevaluable and verdict-neutral. The literal `[REDACTED]` is never compared or
  promoted. A safely redacted document remains usable for non-overlapping rules.

Records follow definition order: at most 128 assertions, then at most 128 JSON
selectors or one complete-text selector, then at most one performance record.
The overall accepted bound remains 257.

Expected and actual evidence is redacted before the evaluator receives it. Each
canonical encoded value is at most 4096 UTF-8 bytes. A larger value may still be
used transiently to classify a comparison, but its record stores null with
`evidence_omitted=true`, and an attempt containing such a selected value is not a
promotion candidate. No prefix is retained.

## 4. Baseline bootstrap and eligibility

No selectors means comparison `not_requested` and baseline promotion
ineligible. With selectors, the evaluator safely extracts and normalizes current
values even when the pinned candidate is missing or incompatible, but never
compares them to invented expected values.

The ordinary ADR 0004 rules apply. The only exception permits a
`baseline_required` source when that verdict is caused solely by missing or
incompatible baseline state and:

1. all required assertions passed;
2. all selectors produced safe canonical values of at most 4096 bytes each;
3. the ordered selected-values document is at most 1048576 canonical bytes;
4. no selected value was missing, expired, truncated, redaction-omitted, or
   invalid for its normalizer;
5. source scope and policy fingerprint match the command and current test
   revision; and
6. command confirmation exactly acknowledges the derived warnings.

The derived warning set is sorted in this order:
`missing_baseline`, `incompatible_baseline`, `observed_change`,
`performance_warning`. At most one of the first two can appear. Empty warnings
are represented by an empty array, not null. The literal confirmation is always
required, including for a clean passing candidate.

Stable ineligibility codes exposed by promotion assessment are:
`no_selectors`, `attempt_not_evaluated`, `attempt_not_included`,
`required_functional_check_failed`, `evaluation_inconclusive`,
`selected_value_unavailable`, `selected_value_too_large`,
`policy_mismatch`, and `scope_mismatch`. They reveal no value or secret.

## 5. Planned relational contract

The relational contract below is frozen. M4-00 allocates the next migration in
documentation only: M4-02 owns Alembic revision `0010_m4_evaluation_and_baselines`
with parent revision `0009_attempt_response_outcomes` (`0009`). No migration
file is created until M4-02 implementation begins.

### Existing-table additions

- `executions.result_contract_version` small integer, with pre-M4 rows set to 0
  and new executions defaulting to 1
- `execution_items.result_contract_version` inherited from the execution
- `execution_items.baseline_activation_id UUID NULL`
- `execution_items.baseline_id UUID NULL`
- `test_attempts.result_contract_version` inherited from the execution item
- `test_attempts.verdict` nullable accepted verdict enum
- `test_attempts.evaluation_error_code` nullable closed value
  `platform_evaluation_failure`

The baseline columns are both null or both nonnull. A composite foreign key from
the pair to activation/baseline association prevents mismatched identities.
Application services also verify test-case/environment scope because it spans
the parent execution row.

Composite keys/FKs make every item inherit its execution version and every
attempt inherit its item version. Existing execution/item/attempt rows migrate
to 0. A replay successor copies its predecessor's version. Version-0 executions
never gain baseline pins and continue the accepted M3 response/
`not_evaluated` behavior after upgrade; only a version-1 execution can enter M4
evaluation.

For result-contract version 1, checks require an `evaluated` attempt to have a
nonnull verdict, recorded response, `response_received` certainty, and transport
outcome `response_received` or `response_limit_exceeded`. A post-response
terminal evaluation failure is instead state `failed`, verdict `inconclusive`,
and `platform_evaluation_failure`. That error code is forbidden on every other
shape. Other version-1 states have null attempt verdict. Version 0 preserves
historical rows without asserting M4 result completeness.

### `baseline_comparisons`

One row per successfully evaluated version-1 attempt: `attempt_id`
primary/foreign key; state;
nullable activation ID, baseline ID, version, and policy fingerprint;
`checked_at`; and state-dependent checks. Deleting its owning attempt deletes the
comparison. It is not a baseline-retention dependency.

A deferred PostgreSQL constraint trigger enforces at transaction end that every
version-1 `evaluated` attempt has exactly one comparison row and that comparison
or evaluation children cannot remain attached to any other attempt state. This
reverse cardinality is not claimed from child-side foreign keys alone.

### `evaluations`

`id UUID` primary key; `attempt_id` foreign key; `ordinal` 0..256; kind;
nullable `rule_id`; severity; outcome; message code; nullable JSONB expected and
actual; `evidence_omitted`; created time. Unique `(attempt_id, ordinal)` preserves
deterministic order. `rule_id` is null only for performance. Deleting the owning
attempt deletes evaluations.

### `baselines`

`id UUID` primary key; test-case, environment, and project ownership; positive
version; source attempt and execution UUID scalar provenance; source test-case
revision foreign key; source attempt verdict and finished timestamp; policy
fingerprint; selected-values schema version and JSONB document; nullable reason;
created timestamp.

Unique constraints cover `(test_case_id, environment_id, version)` and globally
unique nonnull `source_attempt_id`. Composite ownership
constraints/FKs prevent cross-project test-case/environment/revision references.
The selected document is closed schema version 1:

```json
{
  "schema_version": 1,
  "values": [
    {"rule_id": "uuid", "value": "any JSON value"}
  ]
}
```

Entries are in selector order and rule IDs are unique. Application validation
enforces canonical per-value/document byte limits before insert.

### `baseline_activations`

`id UUID` primary key; test-case, environment, project, baseline IDs; activated
timestamp; nullable deactivated timestamp; nullable reason under the common
1..500 UTF-8-byte rule. A composite FK proves the baseline belongs to the same
scope. Unique `(id, baseline_id)` supports the execution-item pair reference. A
partial unique index on `(test_case_id, environment_id)` where `deactivated_at IS
NULL` enforces one current activation. Timestamps satisfy deactivated greater
than or equal to activated.

Indexes support baseline history `(test_case_id, environment_id, version, id)`,
current activation by scope, source-attempt retry lookup, evaluation order, and
attempt result reads. Exact PostgreSQL SQL, downgrade order, constraint names,
and migration ID are coordinator-owned in M4-02.

Legacy M1-M3 data is not recalculated. New nullable columns remain null and
existing item/execution verdicts retain their historical meaning.

## 6. Transaction and recovery contract

### Execution materialization

Version-1 execution creation locks participating test-case rows in ascending UUID
order, pins the current activation/baseline pair for each item, and commits it
with all existing immutable revision pins and the job. Version-0 executions
already present during upgrade keep null candidate pins. Creation does not run
evaluation or target I/O.

### Evaluation

1. Under a live job fence, read the durable response, definition, pinned
   candidate, and existing result status as one immutable snapshot.
2. End the database transaction.
3. Compute the pure evaluation.
4. In one new live-fence transaction, insert comparison/evaluations, set attempt
   verdict/state, update the item, and advance execution aggregation.
5. Complete the job using the existing M3 recovery path.

Unique rows make recomputation idempotent. On unknown commit, reread before any
action. `evaluated` resumes downstream completion; `response_received`
recomputes. No path sends or refetches the target request.

If delivery is exhausted or a non-retryable evaluator failure occurs after a
durable response, the queue/execution finalizer performs one live-fence
transaction: it stores `platform_evaluation_failure`, attempt `failed` with
`inconclusive`, item `failed` with `inconclusive`, skips later unsent suite
items, aggregates the execution as failed, and marks the job dead. No comparison
or evaluation children remain. Unknown commit outcome is reread; no response is
refetched and no target request is resent.

### Promotion and activation

Both commands parse and scope-bind a valid ETag, lock the test-case row, and
recompute current scope state. Promotion first reconciles an exact same-source,
same-request retry; that non-mutating case may return the existing result and
current ETag even when the state digest is stale. Same-source changed immutable
input returns `resource_conflict` at that same step, before digest comparison.
Every other command compares the current precondition before revalidating
ownership/compatibility. Promotion also revalidates the source assessment from
persisted results. All baseline/version/activation/change-event writes commit
atomically. No network I/O, secret resolution, or response-artifact fetch occurs
while locked.

The ETag is a quoted strong token with resource kind and scope plus a SHA-256
digest of canonical `{latest_version,current_activation_id}`. Clients treat it
as opaque. Every successful new version or activation changes it.

## 7. Frozen API contract

All bodies are closed and all fields below are required unless marked nullable.
UUIDs, timestamps, fingerprints, body limits, problem envelopes, and cursor
syntax reuse the accepted M2 conventions.

### Result-detail additions

M4 extends the existing `AttemptSummary.verdict`; all other existing summary
fields retain their runtime shapes. Version-0 attempts keep a null attempt
verdict. A version-1 successfully evaluated attempt returns its persisted
verdict; terminal post-response evaluation failure returns `inconclusive`.

`BaselineComparisonOutput` is a closed object with all fields required:

- `state`: `not_requested | pending | not_evaluated | missing | incompatible |
  compatible`;
- `baseline_activation_id: UUID|null`;
- `baseline_id: UUID|null`;
- `baseline_version: integer|null` (nonnull values are at least 1);
- `policy_fingerprint: SHA256|null`; and
- `checked_at: Timestamp|null`.

`not_requested` has null references and a nonnull check time after successful
evaluation. `missing` has null references and a nonnull check time.
`incompatible` and `compatible` have every reference/check field nonnull.
`pending` is used only for a version-1 attempt that may still evaluate;
`not_evaluated` covers version 0, pre-observation terminal attempts, and terminal
platform evaluation failure. Both projections have all reference/check fields
null.

`EvaluationOutput` is closed and contains:

- `id: UUID`, `ordinal: integer 0..256`;
- `kind: assertion | baseline_selector | performance`;
- `rule_id: UUID|null`, null only for performance;
- `severity: required | advisory`;
- `outcome: passed | failed | unevaluable | not_evaluated`;
- `message_code` from the closed vocabulary in section 2;
- `expected: JSONValue|null`, `actual: JSONValue|null`; and
- `evidence_omitted: boolean`.

Evaluations are sorted by ordinal, contain at most 257 entries, and obey the
state/message/severity rules in sections 2 and 3. JSON null evidence is
distinguished from omitted evidence by `evidence_omitted` and the message code.

`AttemptDetail` adds four required fields:

- `baseline_comparison: BaselineComparisonOutput`;
- `evaluations: EvaluationOutput[]` with maximum 257;
- `evaluation_error_code: null | platform_evaluation_failure`; and
- `baseline_promotion: {eligible:boolean, warning_codes:PromotionWarning[],
  ineligibility_codes:PromotionIneligibility[]}`.

Version-0 detail projects `not_evaluated`, an empty evaluation list, null error,
and ineligibility `attempt_not_evaluated`. A version-1 attempt before evaluation
projects `pending`, empty evaluations, null error, and the same ineligibility. A
terminal post-response evaluation failure projects `not_evaluated`, empty
evaluations, `platform_evaluation_failure`, and `evaluation_inconclusive`.
Successfully evaluated attempts return only persisted comparison/evaluation
data and null error.

`ExecutionDetail` adds required `pinned_change_events: ChangeEventOutput[]` with
maximum 202 and no truncation flag. Existing `change_evidence` remains maximum
128 with required `change_evidence_truncated`. Both use the existing closed
`ChangeEventOutput` schema.

Encoded AttemptDetail and ExecutionDetail responses remain at most 8388608 UTF-8
bytes. Execution serialization preserves all pinned anchors, then applies the
existing attempt-summary and contextual-evidence truncation flags to stay within
the cap. Baseline history pages remain at most 1048576 bytes and never return an
empty continuation page when a valid next summary can fit. A valid AttemptDetail
at the accepted maxima must fit without dropping an evaluation; contract tests
prove that bound before publication.

### Baseline summary and page

`BaselineSummary`:

- `id`, `test_case_id`, `environment_id`, `version`;
- `source_attempt_id`, `source_execution_id`, `source_test_case_revision_id`,
  `source_attempt_verdict`, `source_finished_at`;
- `policy_fingerprint`, `created_at`, `reason` nullable;
- `active` boolean, `activated_at` nullable and equal to the current activation
  time only when active (otherwise null); and
- links containing the source attempt and owning test case. A retained source
  link may later resolve to 404 without changing baseline provenance.

`BaselineActivationSummary` contains `id`, `test_case_id`, `environment_id`,
`baseline_id`, `baseline_version`, `activated_at`, nullable `deactivated_at`, and
nullable `reason`.

`BaselineCreateResult` is
`{baseline: BaselineSummary, activation: BaselineActivationSummary}`.

`BaselinePage` is `{items: BaselineSummary[], next_cursor: string|null}`.
Selected values are not returned by history pages.

`GET /api/v1/test-cases/{test_case_id}/baselines` requires `environment_id` and
accepts `limit`/`cursor`. It returns 200, a page, and the current scope `ETag`.
Ordering is ascending `(version,id)`; a cursor binds both scope identities and
the environment filter. Concurrent inserts have the accepted keyset limitation;
the ETag is not a page snapshot.

### Promotion assessment

Attempt detail adds:

```json
{
  "baseline_promotion": {
    "eligible": true,
    "warning_codes": ["missing_baseline"],
    "ineligibility_codes": []
  }
}
```

Arrays are sorted closed enums, max four warnings and max nine ineligibility
codes. The command always revalidates this projection.

### Promote/create

`POST /api/v1/test-cases/{test_case_id}/baselines` requires `If-Match` and:

```json
{
  "environment_id": "uuid",
  "source_attempt_id": "uuid",
  "reason": null,
  "confirmation": "promote_selected_values",
  "acknowledged_warnings": ["missing_baseline"]
}
```

Reason is null or 1..500 UTF-8 bytes with control characters rejected.
Acknowledgements must exactly equal the current derived sorted set. Success is
201 with `BaselineCreateResult` and new `ETag`. After the scope is locked, an
exact same-source request whose ETag is structurally valid and bound to this
scope returns the original `BaselineCreateResult` with 200/current `ETag` before
the stale state digest is considered; it performs no write or reactivation. A
same-source request changing reason or any other immutable request field returns
`resource_conflict` before state-digest comparison. Promotion reason is stored
only on the baseline; the automatically created activation reason is null. No
`Location` is returned because no detail route exists.

### Activate/rollback

`POST /api/v1/test-cases/{test_case_id}/baseline-activations` requires
`If-Match` and `{environment_id: UUID, baseline_id: UUID, reason: string|null}`.
Reason has the common optional 1..500 UTF-8-byte/control-character rules. A new
activation returns 201 with `BaselineActivationSummary` and new `ETag`.
Already-current activation is 200/no-op with its current activation summary and
unchanged ETag; it does not replace the retained reason.

### Problems

- 404 `resource_not_found`: unknown or inaccessible resource;
- 409 `baseline_ineligible`: source cannot safely become a baseline;
- 409 `baseline_incompatible`: target version fingerprint differs from the
  current active test revision;
- 409 `baseline_confirmation_required`: literal or exact warning set absent or
  stale;
- 409 `resource_conflict`: same source attempt reused with changed immutable
  promotion input;
- 412 `revision_conflict`: valid stale/other-scope ETag;
- 428 `revision_precondition_required`: missing `If-Match`;
- 422 `validation_failed`: body/query/header syntax, bounds, cursor, weak,
  wildcard, or multiple ETags.

Unknown, cross-project, or same-project resources outside the requested
test-case/environment scope are 404 `resource_not_found`. A structurally valid
ETag bound to another scope is 412. Problems use fixed titles and never include
dynamic detail. Unsupported media, body size, authentication, and internal
errors retain existing mappings.

## 8. Change relevance and retention

`pinned_change_events` contains the complete deduplicated events establishing
the pinned environment/source/suite/test revisions and every pinned activation.
It is ordered ascending `(created_at,id)`, never truncated, and bounded to 202
by the 100-item execution limit.

A revision anchor is only the creation/revision event whose `after_ref` equals
the pinned revision and whose `before_ref` differs from `after_ref`; metadata-only
events reusing the same revision remain contextual. A pinned activation anchor
matches exact `after_ref=baseline_activation_id`.

The existing `change_evidence` remains contextual with upper bound
`execution.created_at`; later events never appear. For each item with a baseline,
it includes safe events for the same environment, source, test case, baseline, or
activation scope in `(baseline.source_finished_at, execution.created_at]`, after
deduplicating pinned anchors. The query reads the newest 129, retains the newest
128, sets truncation from the extra row, and returns them ascending.

For `baseline_activated`, `subject_id` is the baseline ID, `before_ref` is the
prior activation ID or null, and `after_ref` is the new activation ID. The event
summary never contains reason, selected value, request/response content, or a
causal claim.

Evaluation/comparison metadata follows the existing 30-day execution-metadata
default and response artifacts the seven-day default. Baselines and activation
history persist until project deletion. M4 implements schema compatibility but
no retention worker; M7 must delete execution metadata without cascading to or
being blocked by baseline scalar provenance.

## 9. Security and privacy acceptance

- Use only persisted redacted observations; never resolve a secret during
  evaluation or promotion.
- Do not log baseline reason, selected/expected/actual values, request bodies,
  response bodies, raw cursor/ETag, or eligibility internals.
- API documentation warns that selected business data may persist in baselines
  until project deletion even though raw artifacts expire sooner.
- Problems, change events, metrics, and spans contain only stable codes and
  identifiers approved by existing safe-metadata policy.
- Synthetic fixed-sensitive, configured-redaction, and unrecognized business
  canaries are inspected across database, API, logs, spans, problems, cursors,
  and generated snapshots. The business canary may appear only in the explicitly
  selected authorized value surfaces.

## 10. Acceptance matrix

### Pure evaluation

- `M4-EVAL-01`: every assertion kind, severity, absent/null, header-case, invalid
  JSON, and exact-text opt-in.
- `M4-EVAL-02`: all normalizers, decimal precision/half-even, scalar types,
  mixed/nested/wrong-type rejection, object/array ordering.
- `M4-EVAL-03`: all verdicts and precedence combinations, including advisory
  unevaluable and advisory-only missing baselines.
- `M4-EVAL-04`: evidence ordering, IDs, caps, omission, and 257 maximum.
- `M4-EVAL-05`: equal/ancestor/descendant JSON redaction overlap, sensitive
  headers, and redaction placeholders are unevaluable and never comparable or
  promotable.

### Persistence and concurrency

- `M4-DB-01`: migration SQL, upgrade/downgrade/re-upgrade, drift, and preservation
  of M1-M3 history.
- `M4-DB-02`: ownership/FK/check/unique/index enforcement and immutable rows.
- `M4-DB-03`: concurrent version allocation and activation with one current row.
- `M4-DB-04`: legacy/in-flight executions, items, attempts, and replay successors
  remain version 0 with M3 behavior; no partial upgrade or retroactive
  evaluation.

### Orchestration and recovery

- `M4-RECOVERY-01`: pinned old/new candidate across concurrent activation.
- `M4-RECOVERY-02`: termination at snapshot, compute, result commit, aggregation,
  and job completion yields one result set and no resend.
- `M4-RECOVERY-03`: stale fence rejected; replay predecessor excluded.
- `M4-RECOVERY-04`: max delivery after durable response performs the final
  failed/inconclusive transaction, leaves no partial result, and never resends.

### Baseline and API

- `M4-BASELINE-01`: first bootstrap, replacement, clean promotion,
  warning-bearing promotion, exact retry versus changed-input 409 precedence,
  null initial-activation reason, later activation reason, rollback, and
  immutable history.
- `M4-BASELINE-02`: every ineligibility, incompatible current revision, reason
  bound, exact confirmation, and selected-value/document bound.
- `M4-API-01`: exact result/baseline schemas, legacy/in-flight/error projections,
  list pagination/order/ETag, wrong-scope handling, response caps, and all safe
  problem mappings.
- `M4-API-02`: runtime OpenAPI/generated TypeScript drift only after implemented
  routes land; bounded encoded responses.

### Privacy, retention, and evidence

- `M4-PRIVACY-01`: synthetic canaries across every persistence and observability
  sink.
- `M4-RETENTION-01`: artifact expiry leaves baseline usable; simulated future
  source-detail deletion preserves provenance.
- `M4-CHANGE-01`: complete deduplicated pinned anchors, exact activation-event
  identity, introduction-only revision anchor selection, contextual newest-128
  bound, ascending presentation, truncation, and no later/sensitive/causal event.
- `M4-E2E-01`: Compose journey executes, evaluates, promotes explicitly,
  compares a later run, activates an older compatible version, and explains each
  result without Tempo dependency.

## 11. Contract and acceptance status

No technical contract question from the planning handoff remains open in the
accepted M4 contract. Independent contract review found no unresolved critical or
important issue; the repository owner accepted ADRs 0009 and 0010 and the packet
on 2026-10-23. M4-02 implemented the allocated revision
`0010_m4_evaluation_and_baselines` on parent `0009`. M4-01 through M4-05 then
implemented the frozen contract, and M4-06 independently reviewed the integrated
candidate. The JSON classification defect found in that review was corrected and
covered before exact-SHA CI passed at `8e280be`.

Accepted evidence preserves the named matrix in section 10:

- deterministic evaluator and verdict coverage, including JSON null/absence,
  normalizer failures, numeric precision, redaction overlap, and bounded evidence;
- PostgreSQL migration, ownership, cardinality, candidate-pinning, activation,
  concurrent promotion, rollback, and legacy-row behavior;
- recovery from response/evaluation checkpoints, stale-fence rejection, replay
  exclusion, atomic aggregation, and no target resend after durable observation;
- explicit baseline bootstrap, compatibility, history, retention independence,
  safe problems, API schemas, generated-client drift, and contextual change
  evidence;
- synthetic privacy-canary inspection across persistence, API, logs, spans, and
  snapshots; and
- the Compose execution/evaluation/promotion/comparison/rollback journey.

M4 intentionally does not implement Tempo reconciliation (M5), the product UI
(M6), or retention execution (M7). Evaluation metadata retains the accepted
30-day policy and response artifacts the seven-day policy, but M7 still owns the
idempotent chunked cleanup job, restart recovery, representative query-plan/index
evidence, full cross-sink privacy scan, operational retention documentation, and
proof that cleanup preserves immutable baseline values and provenance.
