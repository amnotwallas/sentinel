# ADR 0007: Conservative outbound execution safety

- Status: Accepted
- Date: 2026-10-09

## Context

Sentinel sends operator-defined HTTP requests from a networked worker. This
creates two independent risks:

1. repeating a request after a crash may duplicate a target side effect;
2. arbitrary URLs and redirects can reach internal, loopback, link-local, or
   cloud-metadata services.

HTTP method idempotency is not sufficient proof that a particular target is safe,
and exactly-once delivery cannot be guaranteed across a database and remote HTTP
server.

## Decision

### Dispatch checkpoint

The worker prepares and validates a request, creates its trace context, and
commits a `dispatching` attempt before any network I/O. This creates a deliberate
ambiguity window: after a crash, the request may or may not have reached the
target. Sentinel chooses possible false-positive uncertainty over hidden duplicate
side effects.

### Replay policy

- `GET`, `HEAD`, and `OPTIONS` are replayable by default.
- `POST`, `PUT`, `PATCH`, and `DELETE` are not replayed after an ambiguous
  dispatch by default, even though some are specified as idempotent by HTTP.
- A test revision may set `allow_unsafe_replay: true`. The API and UI must require
  explicit acknowledgement that duplicate target effects are possible.
- A target-supported idempotency header may be part of the test request, but
  Sentinel does not assume or verify its semantics. The operator may then choose
  unsafe replay knowingly.
- Every replay creates a new attempt and OpenTelemetry context. The old attempt
  remains immutable as `replay_scheduled`, links to its successor, and is
  identifiable as ambiguous.
- Without replay permission, recovery marks the attempt `indeterminate`, the item
  `indeterminate`, and the execution `inconclusive`. It does not create another
  request automatically.

Ordinary test execution sends each configured case once. The MVP does not retry
HTTP status codes, connection errors, or timeouts within an attempt. Starting a
new execution is an explicit operator action.

### Target policy

By default, the worker permits `http` and `https` schemes but blocks resolved
loopback, private, link-local, multicast, unspecified, and known cloud-metadata
destinations. Operators may explicitly allow exact hostnames and CIDRs required
for local/private API testing.

For every initial URL and redirect hop, the HTTP adapter:

1. parses and normalizes the URL and rejects credentials in userinfo;
2. rejects prohibited schemes and ports from deployment policy;
3. resolves all addresses;
4. rejects the destination if any usable address is blocked and not allowlisted;
5. connects only under a strategy that prevents resolution from changing to an
   unvalidated address;
6. repeats validation for redirects.

Redirects are disabled by default. When enabled, they are limited to three and
may not forward authorization/cookie headers across origins.

### Resource limits

- TLS verification is on by default.
- Default total timeout is 30 seconds; deployment maximum is 120 seconds.
- Default stored response-body limit is 256 KiB; deployment maximum is 1 MiB.
- Concurrency is globally bounded by worker configuration.
- Streaming, upgrades, WebSockets, and unbounded downloads are unsupported.
- Unsupported content required by a comparison produces an explicit
  inconclusive/evaluation result rather than an unsafe fallback.

## Alternatives considered

### Retry every failed or interrupted request

This improves apparent reliability but can duplicate payments, writes, or deletes
and violates the product's evidence-first behavior.

### Treat all RFC-defined idempotent methods as automatically replayable

Real APIs may implement `PUT` or `DELETE` with non-repeatable side effects. The
smaller default set is conservative; operators can opt in per immutable revision.

### Check URL text without resolved addresses

This is vulnerable to DNS rebinding and alternate address representations.

### Allow private networks by default because Sentinel is self-hosted

Private targets are common, but default access turns any UI/API compromise into a
broad SSRF primitive. Explicit deployment allowlists make the trust boundary
visible.

## Consequences

- Recovery may produce `inconclusive` even if the request never left the worker.
- Operators testing private services must configure an allowlist.
- The HTTP adapter needs careful DNS/connection integration and security tests.
- Some target-supported safe retries require explicit operator configuration.
- Sentinel makes no exactly-once claim and preserves the evidence needed to
  explain why it stopped.
