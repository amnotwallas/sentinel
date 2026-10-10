# ADR 0004: Immutable, versioned baseline management

- Status: Accepted
- Date: 2026-10-09

## Context

A baseline is trusted expected behavior. Overwriting it in place destroys the
evidence needed to explain why a later result changed. Automatically promoting a
recent response can also normalize a regression, especially when responses have
volatile or sensitive fields.

Baselines must remain compatible with the comparison policy that selected and
normalized their values. They must not retain a full unredacted response merely
for convenience.

## Decision

Baseline versions are immutable and scoped by test case and environment. A
baseline stores:

- a monotonically increasing version within that scope;
- the source attempt and test-case revision;
- the canonical comparison-policy fingerprint;
- only the selected, normalized, redacted expected values;
- creation timestamp and optional operator reason.

The current baseline is represented by an append-only `BaselineActivation`
history. Activation closes the previous row and inserts a new active row in one
transaction. Rollback means activating an older compatible version; no baseline
row is edited.

### Eligibility

The application service accepts a source attempt only when:

- it reached `evaluated`;
- required explicit assertions passed;
- every selected value needed by the policy was captured and evaluated;
- response truncation or redaction fallback did not remove selected evidence;
- the test revision and policy fingerprint match the requested baseline scope;
- selected values can be represented by canonical JSON.

A source attempt may have an `observed_change` or `performance_warning` verdict
if all required functional checks pass; the API must show those warnings during
confirmation. `functional_regression`, `inconclusive`, `baseline_required`, and
`not_evaluated` attempts are ineligible.

Promotion is an explicit API/UI action. Sentinel never auto-promotes based on a
passing run, frequency, or repeated identical observations.

### Compatibility

An execution compares only with an active baseline whose fingerprint equals the
test revision's comparison-policy fingerprint. A mismatch yields
`baseline_required`; Sentinel does not partially match or guess compatibility.

A test revision that changes only request metadata but preserves the exact
canonical comparison policy may use the active baseline. The execution and UI
still show that the request revision changed since baseline creation.

### Deletion and retention

Ordinary response-artifact expiration does not delete baseline values because
they are copied into the immutable baseline after redaction and normalization.
Definition and baseline versions remain until explicit project deletion.
Deleting a source execution does not invalidate the baseline; its provenance ID
and minimal metadata remain available even if detailed artifacts expire.

## Alternatives considered

### Mutable single snapshot

Simple storage, but it erases history and makes rollback/audit impossible.

### Automatic promotion after a passing run

Convenient, but it can silently accept behavior that an incomplete assertion set
failed to protect.

### Store the full response as the baseline

This retains unnecessary volatile and sensitive data and encourages whole-body
comparison. Selected values are sufficient and safer.

### Baseline per test revision only

This forces promotion after harmless request metadata changes. Fingerprint
compatibility is more precise while revision provenance remains visible.

## Consequences

- Baseline history is auditable and reversible.
- Storage grows with promotions but each row is bounded to selected values.
- Policy changes deliberately require review and a new compatible baseline.
- Activation requires a transaction and uniqueness constraint ensuring one active
  baseline per test case/environment.
- The UI must distinguish creating a version from activating an existing one.
