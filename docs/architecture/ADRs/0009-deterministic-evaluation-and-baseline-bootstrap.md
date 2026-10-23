# ADR 0009: Deterministic evaluation and baseline bootstrap

- Status: Accepted
- Date: 2026-10-23
- Extends: ADR 0003 and ADR 0004

## Context

ADR 0003 defines explicit deterministic evaluation and verdict precedence. ADR
0004 defines immutable baselines and normally excludes `baseline_required`
attempts from promotion. Two details remain unresolved before Milestone 4 can
implement those decisions:

1. a test with required selectors and no compatible baseline evaluates to
   `baseline_required`, so ADR 0004's eligibility rule otherwise prevents the
   first baseline from ever being created; and
2. invalid normalizer input is an explicit evaluation error, but its effect on
   required and advisory verdicts is not defined.

The active baseline can also change while an execution is queued. Looking up the
current activation only when evaluation starts would make identical executions
depend on worker timing and would let a later read substitute evidence that was
never used.

## Decision

### Evaluation inputs and ordering

`sentinel.regression` remains a pure evaluator. Its complete inputs are the
pinned immutable test revision, the durable redacted response observation and
integer duration, and the immutable baseline candidate selected for the
execution item. It performs no database, network, secret, clock, UUID, or
telemetry operation.

Evaluation records are emitted in this order:

1. assertions in stored definition order;
2. baseline selectors in stored policy order; and
3. the optional performance threshold.

Only explicit rules are evaluated. No baseline lookup occurs when the policy has
no selectors. Exact text remains opt-in. Missing telemetry never participates.

### Baseline selection time

Each execution item pins the active `BaselineActivation` and its immutable
`Baseline`, if one exists, in the same transaction that materializes the
execution. The selection is scoped by the item's test-case identity and the
execution's environment identity. A suite creation locks its test-case identities
in ascending UUID order before reading these pointers.

The execution also pins result-contract version 1. Existing executions are
migrated as version 0 and finish under M3 semantics, including every replay
successor; they are never partially upgraded or evaluated by M4. Only a new
version-1 execution may pin baseline candidates and enter M4 evaluation. Item and
attempt rows inherit their execution's version, enforced relationally, and a
replay copies its predecessor's version.

The transaction records both nullable identifiers on the execution item. It
pins an active candidate even when its policy fingerprint is incompatible so
the later result can explain exactly what was inspected. No active candidate is
recorded as two null identifiers and remains missing for that execution; a later
promotion does not retrofit it.

Execution creation and baseline activation serialize on the same test-case row.
Consequently an execution observes either the activation before a concurrent
change or the activation after it, never a partially changed pointer. Evaluation
and API reads use only the pinned identifiers. Baseline activation never changes
a queued or completed verdict.

### Missing and incompatible baselines

With no selectors, baseline comparison is `not_requested`; no selector
evaluations are created and baseline state cannot affect the verdict.

With selectors and no compatible pinned baseline, every selector produces a
`not_evaluated` evaluation with `baseline_missing` or
`baseline_incompatible`. Selected current values are still extracted and
normalized when safe so that eligibility can be assessed, but they are not
classified as matches or changes.

- If any selector is required, the attempt verdict is `baseline_required` after
  higher-precedence inconclusive conditions are considered.
- If every selector is advisory, absent or incompatible baseline evidence does
  not change the verdict. Assertions and performance determine the verdict; a
  selector with no expected value is not an `observed_change`.

This rule does not reuse an incompatible baseline or infer an expected value.

### Invalid and unavailable inputs

An invalid normalizer input emits `unevaluable` with message code
`normalizer_input_invalid`. A required selector makes the functional verdict
`inconclusive`; an advisory selector remains visible but does not change the
verdict. It is not a regression or observed change because no valid comparison
occurred.

Missing, expired, truncated, or redaction-omitted content follows the same
required/advisory distinction. Required evidence that cannot be evaluated is
`inconclusive`; unavailable advisory evidence is recorded as `unevaluable` and
does not change the verdict. Sentinel never refetches, coerces, or substitutes an
unsafe value.

A rule is redaction-omitted when its JSON Pointer equals, contains, or is
contained by a configured redaction pointer, or when its header is fixed or
configured sensitive. It emits `content_redacted`; Sentinel never compares or
promotes the literal redaction placeholder. Rules outside those overlaps may use
the safely redacted document. Complete-text evaluation is unavailable whenever
the body was omitted by redaction.

Invalid JSON required by an explicit JSON assertion is different: it is an
observed response that fails that assertion. A required assertion therefore
produces `functional_regression`; an advisory assertion produces
`observed_change`. When JSON is needed only by selectors and cannot be parsed,
the selector is unevaluable under the preceding rules.

### Narrow bootstrap eligibility

ADR 0004's ordinary eligibility rules remain in force. This ADR makes one narrow
exception: an evaluated attempt whose `baseline_required` verdict is caused only
by a missing or incompatible baseline may be an explicit promotion source when
all of the following are true:

- every required explicit assertion passed;
- every configured selector was safely extracted and normalized;
- every selected value passed redaction without rule overlap, is canonically
  representable, and is within the frozen per-value and aggregate baseline
  limits;
- no selected evidence was lost to truncation, expiry, or redaction fallback;
- the test-case/environment scope and policy fingerprint match the requested new
  version; and
- the operator supplies the exact required confirmation contract.

This exception applies both to a first baseline and to replacement after a
policy change. It does not make an attempt eligible after a required assertion
failure, transport uncertainty, invalid normalizer input, unavailable selected
content, or any other inconclusive condition. Policies with no selectors cannot
create baselines because there are no selected values to preserve.

Promotion remains manual. Sentinel never promotes merely because values were
captured, repeated, or advisory-only. `observed_change` and
`performance_warning` retain ADR 0004's existing conditional eligibility.

### Recovery and aggregation boundary

After a response is durable, the worker loads one immutable evaluation snapshot
under its live job fence, releases the database transaction, and computes the
pure result. A second fenced transaction atomically writes the baseline
comparison, ordered evaluations, attempt verdict, `evaluated` state, item
aggregation, and any resulting execution progress.

A crash before that commit recomputes from the same durable inputs and pinned
candidate without resending the request. After an unknown commit result, a
worker rereads the attempt: `evaluated` resumes job completion, while
`response_received` recomputes. Database uniqueness prevents duplicate result
sets. A stale lease holder cannot commit evaluation or aggregation.

A platform failure after a relevant response was durably observed yields
`inconclusive` when the failure can be committed safely. `not_evaluated` remains
reserved for the absence of every relevant API observation. Recovery never
rewrites a transport outcome or replays a target request merely to evaluate it.

If bounded job delivery is exhausted after a response is durable, a final
fenced transaction records a stable `platform_evaluation_failure`, moves the
attempt to `failed` with verdict `inconclusive`, marks the item failed with the
same verdict, skips unsent later suite items, aggregates the execution as failed,
and then marks the job dead. It stores no partial evaluation set and never
resends the target request. Lease loss or unknown commit outcome is reread before
this terminal action.

## Security and failure implications

- Evaluation uses only already-redacted persisted content. It never resolves
  secrets or logs evidence values.
- Required invalid or unavailable inputs fail closed as inconclusive rather than
  fabricating equality or an application regression.
- Pinning at creation prevents a concurrent operator action from silently
  changing expected values after a run is queued.
- Bootstrap is explicit and auditable, but it can bless incorrect selected
  values if the operator chooses weak assertions. Confirmation must expose this
  risk without echoing sensitive values in logs or problems.
- Locks are held only for local materialization/activation transactions, never
  across target I/O or evaluation computation.

## Executable acceptance criteria

1. An execution created before and after a concurrent activation deterministically
   pins the old or new activation; no execution has a mixed pair of identifiers.
2. Later activation does not change the candidate, evaluations, or verdict of a
   queued or completed execution.
3. No selectors produces `not_requested` and no selector records.
4. Required missing/incompatible baseline produces `baseline_required`; an
   advisory-only missing/incompatible baseline does not produce
   `baseline_required` or `observed_change`.
5. Required invalid normalizer input produces `unevaluable` and
   `inconclusive`; advisory invalid input is visible and does not alter the
   verdict.
6. Invalid JSON assertion behavior is distinct from selector parsing failure.
7. The narrow bootstrap candidate is eligible only when every listed condition
   holds and explicit confirmation succeeds; no automatic promotion occurs.
8. Process termination before, during, and after the fenced result transaction
   produces one result set and no additional outbound request.
9. Lease loss prevents result/aggregation writes by the stale worker.
10. Replay predecessors remain visible but only the attempt marked
    `included_in_verdict` contributes to item and execution aggregation.
11. Maximum delivery after a durable response produces the defined failed/
    inconclusive terminal result, one dead job, no partial results, and no target
    resend.
12. A version-0 queued or in-progress execution and every replay successor finish
    with M3 behavior after upgrade; only a newly created version-1 execution can
    persist M4 evaluation results.

## Alternatives considered

### Look up the baseline at evaluation time

This shortens execution creation but makes results depend on queue timing and
weakens auditability.

### Treat every missing advisory baseline as an observed change

There is no expected value to differ from, so this would manufacture a change.

### Treat invalid normalization as a functional regression

The comparator failed to produce a valid value; blaming the target would be
misleading. Required failure therefore remains inconclusive.

### Import a first baseline or auto-promote the first response

An import contract adds a new trust boundary, while auto-promotion can silently
accept faulty behavior. Explicit promotion from a constrained evaluated attempt
uses the existing evidence and audit model.

## Consequences

- Execution materialization gains nullable pinned baseline identifiers and a
  short test-case lock.
- A narrowly defined `baseline_required` attempt can bootstrap or replace a
  baseline, superseding only ADR 0004's blanket exclusion for that case.
- Advisory-only policies can execute usefully before promotion without claiming
  a comparison occurred.
- Evaluation is repeatable after crashes because all decision inputs are durable
  and immutable.
