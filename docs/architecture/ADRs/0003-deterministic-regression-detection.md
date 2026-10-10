# ADR 0003: Explicit deterministic regression classification

- Status: Accepted
- Date: 2026-10-09

## Context

API responses commonly contain timestamps, generated IDs, ordering differences,
tokens, and environment-specific values. Whole-body snapshot comparison creates
noise and trains operators to ignore failures. Conversely, automatically learning
volatile fields can hide important changes and makes a result difficult to
reproduce.

Performance degradation, advisory response changes, target transport failures,
and missing telemetry are materially different from a functional regression.

## Decision

Evaluate only explicit rules stored in an immutable test revision:

- status-code assertions;
- header presence/equality assertions;
- RFC 6901 JSON Pointer presence, absence, type, or exact-value assertions;
- opt-in exact text-body assertions;
- baseline selectors for explicitly chosen JSON Pointers or the complete text
  body;
- absolute performance thresholds in integer milliseconds.

Each functional assertion/selector has severity `required` or `advisory`.
Unselected JSON fields are ignored. Exact body comparison is off by default.
Sentinel does not infer volatility or stability from previous responses.

### Deterministic normalization

Selectors default to no normalization. The MVP permits only named, versioned,
deterministic normalizers:

- `none`;
- `sort_scalar_array`, which sorts an array only when every member is the same
  JSON scalar type;
- `round_decimal(scale)`, which parses a JSON number without binary floating-point
  comparison and rounds using the documented decimal mode.

Invalid normalizer input is an evaluation error; it is never silently coerced.
Canonical policy serialization and SHA-256 produce a policy fingerprint used to
detect baseline compatibility.

### Verdict classification

Lifecycle state is separate from verdict. The ordered verdict precedence is:

1. `inconclusive` for ambiguous dispatch, uncertain transport, or unavailable
   content required for evaluation;
2. `baseline_required` for a required missing/incompatible baseline;
3. `functional_regression` for a failed required assertion or selector;
4. `performance_warning` when functional checks pass but a duration threshold
   fails;
5. `observed_change` for advisory mismatches;
6. `passed` when all evaluated checks pass.

`not_evaluated` applies when platform infrastructure fails before any relevant API
observation. Trace availability is not an input to this function.

Evaluation records store a stable rule ID, kind, severity, outcome, message code,
and bounded redacted expected/actual values so the verdict is explainable.

## Alternatives considered

### Whole-response snapshots by default

Easy to implement, but volatile values create false regressions and encourage
unsafe blanket update behavior.

### Ignore common volatile field names automatically

Names such as `id`, `time`, or `version` can be business-critical. Silent ignore
rules hide behavior and vary across APIs.

### Statistical or AI anomaly detection

These approaches are probabilistic, need more observations, and violate the MVP's
deterministic/no-AI constraints.

### User-supplied scripts

Scripts are expressive but create a code-execution sandbox, nondeterminism, and a
larger security surface. Named comparison primitives are sufficient for the MVP.

## Consequences

- Initial setup requires the operator to choose meaningful stable fields.
- Results are reproducible and each regression cites a configured rule.
- Volatile data does not create noise unless explicitly selected.
- The MVP comparison language is intentionally limited; new comparator semantics
  require versioning, tests, and an ADR when they change classification behavior.
- Transport uncertainty remains visible without being mislabeled as an
  application regression.
