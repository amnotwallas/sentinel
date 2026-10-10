# ADR 0006: Secret handling, redaction, and retention

- Status: Accepted
- Date: 2026-10-09

## Context

API tests often use authorization headers and sensitive request/response fields.
Test failures, structured logs, traces, and database artifacts are common leakage
paths. The MVP is single-user, but it may still reach privileged local services
and store sensitive observations.

A full secret manager, user/role model, or field-level database encryption would
expand the MVP significantly. The design instead minimizes what Sentinel stores
and makes the deployment boundary explicit.

## Decision

### Secrets

- Secret values are supplied through process or mounted-secret environment
  variables and resolved only in worker memory.
- Persisted definitions contain tagged references such as
  `{ "$secret": "API_TOKEN" }`, never the resolved value. Names match
  `[A-Z][A-Z0-9_]{0,63}` and resolve from `SENTINEL_SECRET_<NAME>`.
- Secret references may appear in header values and JSON-body leaves. They are
  prohibited in URLs and query parameters.
- Request fingerprints use a constant placeholder and reference name, not the
  secret value.
- Missing secret references fail preparation before dispatch with a stable,
  non-sensitive error code.
- The API never provides an endpoint to read or enumerate secret values.

Sentinel cannot reliably detect an arbitrary secret typed as a literal. The UI
and documentation require references for sensitive values, and known credential
headers receive warnings/rejection when configured as unprotected literals.

### Logging and telemetry

Sentinel never logs complete request or response objects or request bodies.
Structured logs use IDs, state transitions, safe target metadata, durations, and
stable error codes. OpenTelemetry spans follow the same rule.

The following headers are always redacted case-insensitively:
`Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`, and
common variants configured by the deployment. Operators may add header names and
JSON Pointers. Fixed protections cannot be disabled by a test definition.

### Persistence redaction

Redaction occurs before an observation enters PostgreSQL, an API response, a log,
an evaluation record, or a test snapshot. If content cannot be parsed enough to
apply configured field redaction, Sentinel omits the entire body and records
`redaction_unavailable`; it does not persist an unsafe fallback.

Responses are streamed into a bounded capture. Sentinel does not buffer an
unbounded body before applying limits. Baselines store only selected, normalized,
redacted values.

### Access boundary

Docker Compose binds the frontend and API to loopback by default. A configured
non-loopback bind requires a static bearer token from an environment variable.
The API compares it in constant time and never stores or logs it. CORS permits
only configured frontend origins.

This is not multi-user identity or authorization. Operators exposing Sentinel to
an untrusted network must place it behind an appropriate authenticating reverse
proxy; formal reverse-proxy integration is outside the MVP.

### Retention

Defaults are:

- redacted response artifacts: 7 days;
- execution, attempt, and evaluation metadata: 30 days;
- example Tempo traces: 7 days;
- definitions, change events, and baseline versions: until explicit project
  deletion.

A daily, idempotent, chunked maintenance job applies retention. Baseline values
are independent of response artifacts. Cleanup records counts and error codes,
not deleted content.

### Data at rest and backups

Sentinel does not implement application-level database encryption or backup in
the MVP. Operators are responsible for disk/database encryption, backup access,
and secure deletion appropriate to their deployment. Documentation must warn that
non-secret literal request bodies and redacted response evidence are stored in
PostgreSQL.

## Alternatives considered

### Store encrypted secrets in PostgreSQL

This requires key generation, rotation, backup/recovery, and UI lifecycle. Using
operator-managed environment/mounted secrets keeps Sentinel out of that business
for the MVP.

### Persist raw data and redact on read

This leaves secrets in the database, backups, and internal failure paths. Redact
before persistence instead.

### No authentication in all local deployments

Loopback-only defaults are reasonable, but accidental non-loopback exposure needs
a hard guard. Requiring a token on remote bind provides a minimal safety boundary.

### Retain everything until manual deletion

This increases breach impact and disk growth without helping normal regression
work. Short artifact retention plus durable baseline values is sufficient.

## Consequences

- Some debugging detail is intentionally unavailable after redaction or expiry.
- Secret rotation occurs outside Sentinel and takes effect on the next dispatch.
- Users must correctly label sensitive JSON paths and avoid literal secrets.
- The MVP bearer token is unsuitable for shared/team deployments.
- Privacy tests must inspect logs, traces, database records, and API errors, not
  only response rendering.
