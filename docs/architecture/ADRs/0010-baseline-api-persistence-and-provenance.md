# ADR 0010: Baseline API, persistence, and provenance

- Status: Accepted
- Date: 2026-10-23
- Extends: ADR 0004 and ADR 0006

## Context

The MVP requires immutable baseline history, explicit promotion and rollback,
ordered explainable evaluations, and relevant change evidence. Existing accepted
ADRs do not define the runtime wire contract, relational associations, evidence
bounds, optimistic concurrency scope, or behavior after future execution-detail
deletion. Those choices must be deterministic and enforceable before migrations
or public schemas are created.

## Decision

### Relational result model

Milestone 4 adds a result-contract version to executions and inherited copies on
items/attempts, an optional attempt verdict, one baseline-comparison row per
successfully evaluated M4 attempt, and zero to 257 ordered evaluation rows.
Pre-M4 executions and all later attempts/replays belonging to them remain version
0, keep their accepted M3 result behavior, and are never backfilled or
re-evaluated against a later baseline. Only executions created after M4
activation use version 1 and baseline pinning.

An evaluation has a unique `(attempt_id, ordinal)`, a generated UUID, kind,
nullable rule ID only for performance, severity, closed outcome and message-code
vocabularies, nullable redacted expected/actual JSON values, and an explicit
`evidence_omitted` flag. Expected and actual values are each limited to 4096
canonical UTF-8 bytes. An oversized value is omitted in full, never truncated to
a misleading prefix.

The baseline-comparison row records `not_requested`, `missing`, `incompatible`,
or `compatible`, the pinned activation/baseline/version/fingerprint fields
permitted by that state, and the check time. `pending` before evaluation and
`not_evaluated` after a terminal platform evaluation failure are transport/API
projections with null reference/check fields; neither is a durable completed
comparison row.

### Immutable baselines and activation history

A baseline is unique by `(test_case_id, environment_id, version)` and globally by
source attempt UUID. It stores versioned selected-value document schema 1,
the exact comparison-policy fingerprint, source attempt/execution/test-revision
identifiers and minimal source verdict/timestamp, creation time, and optional
operator reason. Each selected normalized value is at most 4096 canonical bytes;
the complete canonical document is at most 1048576 bytes and contains at most
128 entries in selector order.

Versions are allocated while holding the test-case row lock. Activation closes
the current row and inserts a new row in the same transaction. A partial unique
index permits at most one row with no `deactivated_at` for each test-case and
environment scope. The service rechecks baseline ownership and exact policy
compatibility against the current active test-case revision under the lock.

Baseline and activation rows are immutable apart from closing the prior
activation with `deactivated_at`. Rollback is a new activation. No endpoint
updates or deletes a baseline version.

### Provenance and later deletion

Baseline source attempt and execution UUIDs are retained scalar provenance, not
foreign keys whose deletion would cascade or block the future M7 execution
retention policy. The source test-case revision, test case, environment, and
project remain relational references because accepted definitions and baselines
survive until explicit project deletion. Project deletion removes the complete
owned baseline history through explicit scoped cascade behavior.

Source attempt UUID is globally unique in baseline history. One attempt belongs
to exactly one test-case/environment execution scope and can create at most one
immutable baseline, even if an application-service validation regresses.

Evaluation/comparison rows follow execution metadata's accepted 30-day default;
response artifacts retain their separate seven-day default. M4 adds no cleanup
job. M7 owns operational deletion and must preserve retained baseline provenance
scalars while removing eligible execution details. Baseline values, reasons,
and activation history remain until project deletion.

### Baseline wire contract

The only MVP routes are:

- `GET /api/v1/test-cases/{test_case_id}/baselines`;
- `POST /api/v1/test-cases/{test_case_id}/baselines`; and
- `POST /api/v1/test-cases/{test_case_id}/baseline-activations`.

The list requires `environment_id`, accepts the standard `limit` (1..100,
default 50) and opaque cursor, and sorts ascending by `(version, id)`. Its closed
response is `{items, next_cursor}`. Cursors bind resource kind, test-case scope,
environment filter, and the last version/ID using the accepted v1 cursor rules.
History summaries exclude selected values and carry bounded provenance, reason,
fingerprint, activation state, and timestamps.

Every list response returns a strong opaque baseline-scope `ETag` representing
the test-case/environment pair, current activation (or none), and latest
allocated version. Unlike ordinary identity lists, this header exists to obtain
the precondition for the two baseline commands; it is not a cross-page snapshot
or cache-validation promise.

Create/promote accepts the closed body:

```json
{
  "environment_id": "uuid",
  "source_attempt_id": "uuid",
  "reason": "optional string or null",
  "confirmation": "promote_selected_values",
  "acknowledged_warnings": ["missing_baseline"]
}
```

`reason` is null or 1..500 UTF-8 bytes after rejecting control characters; it is
preserved exactly, never logged, and never copied to change-event summaries.
`acknowledged_warnings` is a sorted, duplicate-free array containing exactly the
closed warnings derived from the source: `missing_baseline`,
`incompatible_baseline`, `observed_change`, and `performance_warning`. A client
obtains the same safe warning set from the attempt's promotion assessment. Any
missing, extra, stale, or unsorted acknowledgement fails without mutation.

Create normally requires the current scope `If-Match`, rechecks eligibility and policy
compatibility, inserts the next immutable version, activates it, and emits one
safe `baseline_activated` change event in one transaction. It returns 201 with
the created baseline and activation summaries, current `ETag`, and no `Location`
because the MVP intentionally has no single-baseline route.

For retry reconciliation, the service first parses and scope-binds the strong
token, then locks the test-case row and looks for the same source attempt before
comparing the token's state digest. If the complete immutable request matches the
original promotion, it returns the existing baseline/original activation with
200 and the current `ETag`, without writing or reactivating anything. Same-source
changed immutable input returns 409 `resource_conflict` before state-digest
comparison, even when that digest is stale. A token bound to another scope is
412. A source or baseline belonging to another test-case/environment resource
scope is indistinguishable from missing and returns 404.

Activate/rollback accepts the closed body
`{environment_id, baseline_id, reason}` and requires the current scope
`If-Match`. The nullable reason has the same 1..500 UTF-8 byte, control-character,
logging, and retention rules as a baseline reason. The service validates
ownership and compatibility against the current active test revision, then
atomically closes/inserts activation and emits the safe event. A new activation
returns 201 with `BaselineActivationSummary` and the new scope `ETag`.
Activating the already-current version with a matching precondition is an
idempotent 200 returning its current activation summary; it creates no duplicate
activation or event and does not replace its reason.

Promotion reason belongs to the immutable baseline. The initial activation
created by promotion always has null reason. Reasons supplied to later activation
commands belong only to those activation rows.

`If-Match` accepts exactly one strong token. Missing is 428
`revision_precondition_required`; malformed, weak, wildcard, or multiple values
are 422 `validation_failed`; a valid stale or other-scope value is 412
`revision_conflict`. Safe RFC 9457 command failures add:

- 409 `baseline_ineligible`;
- 409 `baseline_incompatible`; and
- 409 `baseline_confirmation_required`.

Same-source promotion with changed immutable input uses the existing 409
`resource_conflict`.

Unknown, cross-project, and same-project resources outside the requested
test-case/environment scope remain indistinguishable as 404
`resource_not_found`. Only an ETag token bound to another scope is 412. Problems
never echo evidence, reason, selector value, submitted ETag, or internal
eligibility detail.

### Result reads and relevant change evidence

Attempt detail exposes the persisted comparison and ordered evaluations plus a
closed promotion assessment: eligibility boolean, exact warning codes, and safe
ineligibility codes without selected values. This is advisory output; the command
revalidates everything transactionally.

Execution detail separates complete immutable-input anchors from contextual
history. `pinned_change_events` contains every distinct event establishing the
pinned environment/source/suite/test revisions and every pinned baseline
activation. It is deduplicated and ordered by `(created_at,id)`, never truncated,
and structurally bounded to 202 events by the 100-item execution maximum.
The revision anchor is the creation/revision event whose `after_ref` equals the
pinned revision and whose `before_ref` differs from `after_ref`; metadata-only
events that reuse the same revision are contextual, not additional anchors.

The existing `change_evidence` field remains contextual. For an item with a
baseline, candidates are safe events affecting the same environment, source,
test case, or baseline scope after the baseline source attempt finished and no
later than execution creation. Events already returned as pinned anchors are
deduplicated from this collection. The query selects the newest 129, returns the
newest 128 in ascending `(created_at,id)` order, and sets
`change_evidence_truncated` from the extra row. Events after execution creation
are excluded.

A `baseline_activated` event uses `subject_type=baseline`,
`subject_id=baseline_id`, `before_ref=prior_activation_id` or null, and
`after_ref=new_activation_id`. This makes the exact pinned activation event
addressable without exposing reason or values. All summaries use only the
accepted fixed vocabulary. Evidence is never labeled as a cause.

### Privacy

All stored and returned values are redacted before evaluation. Fixed-sensitive
headers, resolved secrets, full request objects, and raw response bodies are
never baseline content. Values selected by an operator may still contain
business-sensitive data not covered by configured redaction. API/UI text must
state that evaluation evidence is normally retained with execution metadata and
baseline values/reasons persist until project deletion.

Neither selected values nor reason appear in structured logs, spans, problem
bodies, list cursor payloads, or change-event summaries. Synthetic canary tests
inspect each sink.

## Failure and concurrency implications

- Test-case row locking plus a scope ETag makes concurrent promotion/activation
  have one winner and one stale precondition without an additional mutable scope
  entity.
- Database uniqueness rejects duplicate versions, duplicate source promotion,
  duplicate result ordinals, and multiple current activations even if service
  validation regresses.
- A failed command transaction leaves no baseline, activation, or change event.
- A source retry cannot silently reactivate a historical version.
- Retained scalar provenance avoids preventing later execution cleanup, at the
  cost that detailed source reads may eventually return 404.

## Executable acceptance criteria

1. Migrations preserve all M1-M3 rows, leave legacy attempt verdicts null, and
   pass `head -> base -> head` plus drift checks.
2. Database constraints enforce every cardinality, ownership, unique-version,
   unique-source, ordinal, and single-current-activation invariant.
3. Two concurrent commands using one ETag yield one commit and one 412; no lost
   update, duplicate version, duplicate activation, or duplicate event occurs.
4. Create and activate enforce exact bodies, pagination/order, reason limits,
   warning acknowledgement, scope, compatibility, and safe problem mappings.
5. Same-source create retry is non-mutating and never reactivates after a later
   command.
6. Evaluation values above the evidence cap are omitted completely and cannot be
   promoted; all collections and encoded responses respect their byte/count
   bounds.
7. Pre-M4 rows remain readable with null attempt verdict and accepted historical
   `not_evaluated` results.
8. Source artifact expiry does not change an existing baseline; simulated future
   execution-detail deletion leaves baseline provenance and values usable.
9. Pinned change events contain every distinct exact revision/activation anchor;
   contextual change evidence includes only the defined subjects and time
   window, is stable and bounded, excludes later events and sensitive text, and
   is never presented as root cause.
10. Synthetic secrets and business-data canaries are absent from logs, spans,
    problems, cursors, and change summaries; only explicitly selected redacted
    values appear in authorized result/baseline responses.

## Alternatives considered

### Mutable baseline scope row

It could provide a natural state version, but adds a lifecycle entity solely for
locking. Existing test-case row locks plus relational uniqueness can enforce the
same MVP contract with less schema.

### Cascade source-attempt foreign keys

They make joins convenient but conflict with the accepted requirement that a
baseline survive deletion of source execution detail.

### Return selected values in baseline history

This increases privacy exposure and response size. Attempt evidence and the
immutable baseline used by comparisons provide the value-level review surface;
history remains provenance-focused.

### Offset pagination or unbounded change history

Both diverge from accepted bounded keyset contracts and become unstable or
expensive as history grows.

## Consequences

- Runtime contracts gain scope-specific ETags and three stable baseline problem
  codes only when their implementation slice lands.
- Promotion is retry-safe without adding an idempotency-key system.
- Baseline provenance stays meaningful after ordinary artifact or future
  execution-detail deletion.
- Operators must understand that explicitly selected values and reasons have
  longer retention than ordinary response artifacts.
