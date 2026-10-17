# ADR 0008: HTTP dispatch outcomes and TLS policy

- Status: Accepted
- Date: 2026-10-17
- Extends: ADR 0007

## Context

ADR 0007 establishes a conservative dispatch checkpoint, replay policy, target
validation, and secure transport defaults. The Milestone 2 planning contract
intentionally left two Milestone 3 compatibility decisions open:

1. the durable attempt transition for a transport failure that produces no final
   HTTP response; and
2. the runtime policy for a stored request definition with `verify_tls: false`.

Milestone 3 also needs exact rules for redirect evidence, proof that a request was
not sent, and DNS-pinned TLS connections. These rules must preserve at-least-once
job delivery without turning it into an exactly-once HTTP claim.

The accepted repository uses HTTPX 0.28.1 and httpcore 1.0.9. HTTPX's stock
transport does not expose a public constructor option that separates the TCP dial
address from the request authority and TLS server name. The locked stack does,
however, pass an explicit `sni_hostname` request extension to the TLS layer, and
the lower connection layer accepts an injectable network backend. A local
synthetic TLS proof confirmed that the current stack can dial a numeric address,
send the original `Host` authority, validate the certificate against the original
hostname through SNI, and reject a hostname mismatch.

That feasibility evidence is version-specific. It is not permission to let the
general-purpose client resolve the hostname again after Sentinel validates it, to
reuse a connection across distinct validated origins, or to depend on an
undeclared transitive API without review.

## Decision

### Attempt states and dispatch certainty

Add `transport_failed` to the attempt state vocabulary:

```text
prepared
  |-- failed
  `-- dispatching
        |-- response_received --> evaluated
        |-- transport_failed
        |-- replay_scheduled --> new prepared attempt
        `-- indeterminate
```

`transport_failed` means the worker durably recorded a bounded, sanitized
transport or redirect-policy outcome but did not durably record an accepted final
response. It is terminal for target dispatch and is never recovered by resending.

Every attempt also records `DispatchCertainty`:

- `not_started`: no durable dispatch checkpoint exists and destination network
  work has not begun;
- `not_sent`: the owning worker positively proved that no HTTP request bytes for
  any hop in this attempt were handed to a connected peer;
- `possibly_sent`: the latest started hop may have transmitted request bytes and
  has no confirmed response head, even if an earlier redirect response exists;
- `response_received`: at least one complete HTTP response head was received and
  no later hop entered an uncertain write state.

The `dispatching` transaction stores `possibly_sent` before DNS or other
destination network activity. This is the fail-closed recovery value. A later
fenced terminal transaction may replace it with `not_sent` or
`response_received` only from positive phase evidence.

`DispatchCertainty.response_received` is evidence about the network exchange. It
does not imply `AttemptState.response_received`. The latter is reserved for a
durably recorded, accepted final response. For example, an accepted initial `3xx`
response followed by a rejected redirect target is `transport_failed` with
certainty `response_received`.

Certainty is attempt-wide across a redirect chain. Once a hop has returned a
response, a later DNS/connect/TLS failure before any later write keeps certainty
`response_received`, not `not_sent`. A later write timeout/failure or response
wait failure changes it to `possibly_sent`. A later response restores
`response_received`. Thus `not_sent` is possible only before any hop in the
attempt has transmitted HTTP bytes.

### Transport outcome vocabulary

The bounded `TransportOutcome` vocabulary is:

- `response_received`;
- `dns_failure`;
- `connect_timeout`;
- `connection_failure`;
- `tls_failure`;
- `write_timeout`;
- `write_failure`;
- `read_timeout`;
- `read_failure`;
- `total_timeout`;
- `target_denied`;
- `redirect_denied`;
- `response_limit_exceeded`; and
- `indeterminate`.

`connection_failure` is limited to connection establishment before HTTP request
transmission. Write and response-read failures use their distinct values. A total
timeout uses the current transport phase to choose certainty; an unknown phase is
always `possibly_sent`.

No raw exception class or message becomes an outcome, log field, span attribute,
database value, or API response.

### Proof required for `not_sent`

After the `dispatching` checkpoint, `not_sent` may be recorded only while the
worker still owns an unexpired fenced lease and one of these controlled phases
completed without entering request transmission:

- DNS resolution failed;
- resolved-address or redirect-target policy rejected the destination before a
  connection attempt;
- TCP connection establishment failed or timed out before a stream was returned;
- the TLS handshake or certificate/hostname verification failed before HTTP data,
  with TLS early data disabled; or
- the adapter rejected an approved static transport policy before invoking its
  send operation.

An exception name alone is not proof. Once the adapter invokes request writing,
any write timeout, write failure, cancellation, or unknown error is
`possibly_sent`, even if a byte counter reports zero. Lease loss, worker
cancellation, process death, database commit uncertainty, and failure to persist
the terminal result never justify downgrading `possibly_sent`. They leave the
durable attempt at `dispatching` for normal conservative recovery.

### Retry and recovery

There is no same-attempt retry of DNS, connection, TLS, write, read, timeout, HTTP
status, or redirect failure. A known `not_sent` outcome also receives no automatic
retry. Starting another ordinary execution is an explicit operator action.

Recovery of a durable `dispatching` attempt follows ADR 0007:

- `GET`, `HEAD`, and `OPTIONS` may create a new attempt;
- `POST`, `PUT`, `PATCH`, and `DELETE` require the pinned revision's explicit
  unsafe-replay consent;
- every replay has new attempt, trace, and client-span identifiers; and
- otherwise the attempt and item become `indeterminate` and the execution becomes
  `inconclusive`.

Recovery of `response_received` or `transport_failed` never sends another HTTP
request. Queue delivery count, HTTP attempt sequence, and trace-correlation retry
count remain separate.

### Redirect responses and rejected hops

A redirect chain belongs to the configured attempt; a redirect hop is not a
replay and does not create another `TestAttempt`. The configured attempt's
checkpoint precedes every hop in that chain. Each actual hop may have subordinate
telemetry, but it does not replace the attempt's persisted primary trace and span
identity.

When `follow_redirects` is false, a complete `3xx` response is the accepted final
response. It records:

- `AttemptState.response_received`;
- `DispatchCertainty.response_received`; and
- `TransportOutcome.response_received`.

When redirects are enabled, only `GET`, `HEAD`, and `OPTIONS` may follow. Before
dispatching a proposed hop, the adapter must:

1. resolve the `Location` reference against the current URL;
2. reject missing, malformed, userinfo-bearing, unsupported-scheme, or
   prohibited-port destinations;
3. enforce the maximum of three followed hops;
4. resolve DNS and validate every usable address, with explicit deny taking
   precedence;
5. select only a validated address for the connection; and
6. construct the next request after applying the cross-origin credential rules.

Only status `301`, `302`, `303`, `307`, and `308` participates in redirect
following. `301`, `302`, `307`, and `308` preserve the safe method. `303` changes
`GET` or `OPTIONS` to `GET` and keeps `HEAD` as `HEAD`. A followed hop never
forwards a request body or its content headers. An HTTPS-to-HTTP downgrade is
`scheme_denied`. Origin equality uses normalized scheme, IDNA hostname, and
effective port.

No TCP connection, TLS handshake, or HTTP request is made to a rejected hop. DNS
resolution may occur solely to determine that the hop is prohibited.

If a hop is rejected after a `3xx` was received, the attempt records:

- `AttemptState.transport_failed`;
- `DispatchCertainty.response_received`;
- `TransportOutcome.redirect_denied`;
- the received `3xx` status and bounded redacted headers as the observation; and
- one stable redirect rejection code.

If an approved later hop fails, its transport outcome remains phase-specific.
DNS/connect/TLS failure keeps attempt certainty `response_received` because the
earlier hop already returned and no later request was written. Write/read/total
failure before a later response uses `possibly_sent`. These failures are not
`redirect_denied` because the hop passed redirect policy.

The closed redirect rejection codes are `method_not_allowed`, `location_missing`,
`location_invalid`, `scheme_denied`, `port_denied`, `target_denied`, and
`redirect_limit_exceeded`. The raw `Location` value, URL query, fragment, and
userinfo are not persisted or logged. The persisted observation replaces the
`Location` value with `[REDACTED]`; bounded safe scheme, normalized hostname, and
effective port may be recorded separately only when they pass the common safe
target-metadata policy.

If a redirect is approved, its intermediate response is transient transport
evidence. Only the accepted final response becomes the ordinary response artifact.
A crash between hops leaves the attempt at `dispatching`, so recovery remains
conservative.

Cross-origin redirect construction removes all fixed credential headers and every
header whose value was derived from a secret reference. `Proxy-Authorization` is
never forwarded. User-defined `Host` is already prohibited; the adapter owns the
authority header.

### TLS and trust policy

HTTPS target requests require certificate-chain verification and hostname
verification. TLS 1.2 is the minimum. TLS early data/0-RTT and client
certificates are not supported in the MVP.

M2 definitions containing `verify_tls: false` remain readable for compatibility,
but they are not executable. Preparation fails before DNS, connection, or target
network activity with the stable code `tls_verification_required`. Sentinel does
not silently coerce the stored value to `true`.

The worker uses the platform/default CA roots plus an optional deployment-wide
additive PEM CA bundle selected by `SENTINEL_TARGET_CA_BUNDLE`. The value is an
absolute mounted-file path; unset means default roots only. The worker validates
readability and certificate content at startup and adds the bundle to, rather
than replacing, default trust. An unreadable or invalid configured bundle makes
worker readiness fail closed without returning the path. Test definitions and
environment revisions cannot supply inline CA material, filesystem paths,
per-environment trust stores, or client certificates.

Target clients set `trust_env=false`, configure no proxy, and use zero library
transport retries. `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, and
environment-provided target CA overrides do not affect outbound target requests.

### DNS-pinned connection architecture

The security contract is expressed by an adapter port, not by HTTPX internals:

- DNS resolution occurs after the durable `dispatching` checkpoint;
- every returned address is normalized and evaluated;
- any prohibited usable address rejects the destination unless the accepted
  allowlist applies, and explicit deny always wins;
- the socket connects to one selected validated address without a second hostname
  resolution;
- the HTTP authority and TLS SNI/hostname verification continue to use the
  canonical original hostname; and
- redirects repeat the process with a fresh destination decision.

For the locked HTTPX/httpcore versions, M3 may implement this through a narrowly
owned transport wrapper that dials the selected IP while supplying the original
authority and `sni_hostname`. Target connection pooling is disabled in the MVP so
that a connection cannot cross logical origins or outlive the resolution and
policy decision that authorized it. HTTP/2 is not an M3 acceptance requirement;
any later protocol enablement must preserve the same authority, SNI, pinning, and
pool-partition guarantees.

The transport seam is version-coupled and must remain isolated from domain and
application code. Before M3-03 implementation, an executable local feasibility
test must prove with the locked packages that:

- the peer socket uses the selected IP;
- the request authority remains the original host and effective port;
- SNI and certificate hostname verification use the original hostname;
- a hostname mismatch is rejected;
- no library retry or proxy path changes the destination; and
- connection reuse cannot cross a validation decision.

An HTTP dependency upgrade must rerun these tests. If the locked seam cannot meet
them, implementation stops for an explicit dependency or architecture decision;
it must not fall back to validate-then-resolve behavior. Direct use of a transitive
httpcore API also requires explicit dependency ownership rather than an undeclared
import.

### Fenced outcome persistence

Every dispatch, response, transport-failure, redirect-denial, replay, and terminal
item checkpoint verifies the job ID, leased state, owner, fencing token, and
unexpired lease using database time in the same transaction that locks or
compare-and-sets the attempt. A stale worker cannot persist a response or failure.

If a response was observed but the worker cannot prove lease ownership or commit
the result, the in-memory evidence is discarded and the durable state remains
`dispatching`. This can produce an inconclusive result or a safe-method replay;
it cannot authorize a stale write.

## Alternatives considered

### Reuse `response_received` for transport failures

This would claim a response exists when none does and makes recovery rules
ambiguous. A distinct terminal state preserves the accepted meaning.

### Use an exception class to infer `not_sent`

Library exception types may cover more than one phase and cancellation can race
with socket activity. Phase-owned positive proof is safer.

### Persist every redirect response as another attempt

Redirects are bounded behavior of one configured dispatch, not queue recovery or
operator-requested re-execution. Creating attempts per hop would overload replay
semantics and require a second attempt-link contract. Intermediate hop evidence is
instead bounded within the adapter, with rejected-hop evidence preserved on the
configured attempt.

### Permit `verify_tls: false` behind a deployment flag

This expands configuration and makes credential-bearing requests vulnerable to
active interception. An additive CA bundle supports private trust without
disabling authentication.

### Use per-environment CA material or client certificates

This requires new persisted secret/configuration surfaces and lifecycle policy.
It is outside the MVP.

### Let HTTPX resolve again after validation

This reintroduces DNS rebinding and cannot prove the connected peer was validated.

### Inherit deployment proxies

A proxy can become the real peer, bypass address pinning, and observe credentials.
Proxy support requires a separate architecture and threat-model decision.

## Consequences

- Known transport failures are durable and distinct from unresolved crash
  ambiguity.
- Some requests become inconclusive even when they probably did not leave the
  worker; this is the accepted fail-closed tradeoff.
- Self-signed/private PKI targets require an operator-installed CA bundle rather
  than insecure TLS.
- Corporate outbound proxies and mTLS-only targets are unsupported in the MVP.
- Target connection pooling is sacrificed for a simpler, auditable DNS-pinning
  boundary.
- The adapter has a version-sensitive HTTP transport seam and mandatory
  requalification tests.
- No new package is required by this decision. A future direct httpcore dependency
  or different transport library requires explicit review.
