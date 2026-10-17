# Milestone 3 execution and HTTP transport contract

Status: **FROZEN for implementation planning**. The repository owner approved
M3-00 on 2026-10-17. This packet was prepared from repository baseline
`75daa258eac7dd11d26c2e9ce4af945a74e5a41b` and does not authorize production
implementation, migrations, generated artifacts, a commit, or publication.

Normative inputs are [AGENTS.md](../../AGENTS.md), the [MVP](../MVP.md),
[roadmap](../ROADMAP.md), [architecture](../architecture/README.md), accepted ADRs
0001–0008, the accepted [M2 packet](milestone-2.md), and the
[M3 plan](../development/milestone-3-plan.md). ADR 0008 resolves the M2 transport
state and TLS-policy checkpoints without rewriting M2 history.

## 1. Scope

M3 delivers one test or ordered suite from asynchronous creation to durable,
bounded, redacted observations. It includes:

- atomic revision pinning, item materialization, job creation, and idempotency;
- execution, item, attempt, response artifact, and replay persistence;
- in-memory template and secret resolution;
- deterministic request fingerprinting;
- the safe HTTP adapter and target policy;
- attempt trace identity and the pre-I/O dispatch checkpoint;
- resumable fenced orchestration; and
- execution and attempt read APIs.

M3 does not implement assertion/baseline evaluation, baseline promotion, Tempo
reconciliation, authoring/results UI, schedules, notifications, proxy support,
mTLS, multi-tenancy, billing, AI analysis, Kubernetes, or another broker.

## 2. Compatibility rules inherited from M2

- Public routes remain under `/api/v1` and errors use the existing safe RFC 9457
  representation.
- `POST /api/v1/executions` accepts exactly one of `test_case_id` or `suite_id`
  plus `environment_id`.
- Creation pins immutable environment and test/suite revisions and materializes
  suite order in the same transaction as its job and optional idempotency record.
- Creation performs no secret lookup, DNS resolution, or target I/O and returns
  `202 Accepted` with `Location` before execution completes.
- `Idempotency-Key` is installation-scoped, visible ASCII, 1–128 bytes, hashed at
  rest, and retained for 24 hours. Equal key and canonical payload return the
  original execution; a different payload returns `409 idempotency_conflict`.
- An ordinary item has one configured dispatch. Recovery replay is the only
  automatic creation of another attempt.
- Request method, timeouts, redirect limit, response limit, replay consent,
  redaction, target policy, and secret-reference syntax remain those accepted in
  M2. Existing `verify_tls: false` definitions remain readable but are not
  executable.

M2's planned schemas were review inputs, not runtime contracts. The approved M3
changes below supersede only their explicitly open future-result vocabulary.
Historical M2 artifacts that say TLS opt-out needs M3 review remain unchanged by
this documentation-only freeze; ADR 0008 now supplies that decision. Runtime
schema descriptions and generated clients update only with an implemented M3
slice.

## 3. Closed vocabulary

### 3.1 Lifecycle enums

`ExecutionStatus`: `queued`, `running`, `completed`, `failed`.

`ItemStatus`: `pending`, `running`, `completed`, `indeterminate`, `failed`,
`skipped`.

`AttemptState`: `prepared`, `dispatching`, `response_received`,
`transport_failed`, `evaluated`, `replay_scheduled`, `indeterminate`, `failed`.

`DispatchCertainty`: `not_started`, `not_sent`, `possibly_sent`,
`response_received`. It is attempt-wide: `not_sent` proves no hop wrote HTTP
bytes; `possibly_sent` means the latest started hop may have written without a
response; `response_received` means a response head exists and no later hop has
an unresolved write.

`Verdict`: `passed`, `functional_regression`, `performance_warning`,
`observed_change`, `inconclusive`, `baseline_required`, `not_evaluated`.

`TransportOutcome`: `response_received`, `dns_failure`, `connect_timeout`,
`connection_failure`, `tls_failure`, `write_timeout`, `write_failure`,
`read_timeout`, `read_failure`, `total_timeout`, `target_denied`,
`redirect_denied`, `response_limit_exceeded`, `indeterminate`.

`PreparationErrorCode`: `secret_missing`, `template_variable_missing`,
`target_policy_denied`, `request_invalid`, `tls_verification_required`,
`infrastructure_failure`.

`RedirectRejectionCode`: `method_not_allowed`, `location_missing`,
`location_invalid`, `scheme_denied`, `port_denied`, `target_denied`,
`redirect_limit_exceeded`.

All are lowercase closed enums. They never contain library exception types,
messages, URLs, header values, request bodies, or secret values.

### 3.2 State meaning

- `prepared`: immutable inputs are pinned and an attempt exists; no dispatch
  checkpoint has committed.
- `dispatching`: request fingerprint, trace ID, client span ID, and
  `possibly_sent` certainty are committed. Any recovery treats the target request
  as possibly sent.
- `response_received`: the accepted final HTTP response observation is redacted,
  bounded, and committed. Any HTTP status, including `4xx` and `5xx`, is a
  response.
- `transport_failed`: a terminal sanitized transport or redirect outcome is
  committed without an accepted final response. It is never resent automatically.
- `evaluated`: reserved for M4's completed deterministic evaluation.
- `replay_scheduled`: immutable ambiguous predecessor linked to a newly created
  attempt.
- `indeterminate`: ambiguity is terminal because replay is forbidden.
- `failed`: preparation or internal processing failed without an ambiguous target
  effect.

## 4. Attempt transitions

| From | To | Required durable action |
| --- | --- | --- |
| absent | `prepared` | Create next sequence with `not_started`; allocate no target result |
| `prepared` | `failed` | Store a safe preparation code; no destination network I/O |
| `prepared` | `dispatching` | Atomically store fingerprint, trace/span IDs, dispatch time, and `possibly_sent` under a live lease |
| `dispatching` | `response_received` | Atomically store accepted final bounded/redacted artifact, `response_received` outcome/certainty, duration, and response time |
| `dispatching` | `transport_failed` | Atomically store outcome, proven certainty, safe code/metadata, duration, and any permitted bounded evidence |
| `dispatching` | `replay_scheduled` | Atomically link immutable predecessor and create a fresh `prepared` successor when replay is permitted |
| `dispatching` | `indeterminate` | Record terminal ambiguity when replay is forbidden |
| `response_received` | `evaluated` | M4 only; no target request |
| `response_received` | `failed` | Unrecoverable internal post-response failure; no target request |

No other transition is valid. `transport_failed`, `replay_scheduled`,
`indeterminate`, and `failed` are terminal attempt states. A transition retries on
database serialization only before its transaction outcome becomes unknown; it
never repeats target I/O.

### 4.1 Item and execution aggregation in M3

- A preparation failure makes the item `failed` with verdict `not_evaluated`.
  It does not create an ambiguous side effect, so an ordered suite may continue.
- A known transport failure makes the item `completed` with verdict
  `inconclusive`, except a target-policy or TLS-policy rejection before target
  request transmission, which makes the item `failed`/`not_evaluated`.
- A non-replayable ambiguous attempt makes the item `indeterminate` and execution
  verdict `inconclusive`; remaining pending suite items become `skipped`.
- Successfully persisted response observations make the item `completed` with
  verdict `not_evaluated` until M4 owns assertions and baseline aggregation.
- An execution becomes `completed` when every item is terminal or skipped, even
  when its verdict is not `passed`. `failed` is reserved for exhausted durable job
  delivery or terminal Sentinel orchestration failure.
- Business outcomes normally finish the execution job as `succeeded`; `dead`
  means Sentinel could not finish its own orchestration.

## 5. Dispatch outcome matrix

| Checkpoint or event | State | Certainty | Outcome | Retry/recovery |
| --- | --- | --- | --- | --- |
| Missing secret/template or invalid static request | `failed` | `not_started` | null | Fix definition/environment and start a new execution |
| `verify_tls: false` | `failed` | `not_started` | null | `tls_verification_required`; no DNS/socket activity |
| DNS failure | `transport_failed` | `not_sent` | `dns_failure` | No automatic retry |
| Resolved destination denied | `transport_failed` | `not_sent` | `target_denied` | No connection to denied address |
| TCP connect timeout | `transport_failed` | `not_sent` | `connect_timeout` | No automatic retry |
| Other TCP establishment failure | `transport_failed` | `not_sent` | `connection_failure` | No automatic retry |
| TLS chain/hostname/handshake failure | `transport_failed` | `not_sent` | `tls_failure` | No automatic retry; early data disabled |
| Request write timeout/failure | `transport_failed` | `possibly_sent` | `write_timeout`/`write_failure` | No automatic retry |
| Timeout before response head | `transport_failed` | `possibly_sent` | `read_timeout` or `total_timeout` | No automatic retry |
| Connection loss before response head | `transport_failed` | `possibly_sent` | `read_failure` | No automatic retry |
| Response head received, body read later fails | `transport_failed` | `response_received` | `read_timeout`/`read_failure` | Persist only safely redacted bounded evidence; no refetch |
| Complete HTTP response, including `4xx`/`5xx` | `response_received` | `response_received` | `response_received` | Continue locally; never retry status |
| Capture limit reached | `response_received` | `response_received` | `response_limit_exceeded` | Set `truncated`; no refetch |
| Redirect disabled and `3xx` received | `response_received` | `response_received` | `response_received` | Treat `3xx` as final response |
| Enabled redirect hop rejected | `transport_failed` | `response_received` | `redirect_denied` | Preserve sanitized `3xx` evidence; never dispatch rejected hop |
| Approved later hop fails in DNS/connect/TLS before write | `transport_failed` | `response_received` | phase-specific outcome | Earlier `3xx` is confirmed; no later request was written |
| Approved later hop fails after write may begin | `transport_failed` | `possibly_sent` | phase-specific write/read/total outcome | No automatic retry; safe-method recovery rules remain conservative |
| Worker stops before dispatch commit | absent or `prepared` | `not_started` | null | Re-delivery resumes preparation |
| Crash/lease loss after dispatch commit | remains `dispatching` | `possibly_sent` | null | New delivery applies replay policy |
| Response/outcome commit result unknown | remains as observed from database | never inferred from memory | existing durable value | Read state; do not blindly repeat write or request |

`not_sent` requires the positive proof in ADR 0008. An ambiguous exception,
cancellation, lost lease, worker death, or uncertain database commit can never
downgrade `possibly_sent`. After any redirect response, a later pre-write failure
cannot make the attempt `not_sent`; an unresolved later write overrides earlier
response evidence to `possibly_sent`.

## 6. Redirect contract

- Redirect following defaults to false and the configured maximum is at most
  three followed hops.
- Only `GET`, `HEAD`, and `OPTIONS` may follow a redirect. Unsafe replay consent
  does not authorize unsafe redirect following.
- Redirect status is limited to `301`, `302`, `303`, `307`, and `308`. The safe
  method is preserved except that `303` maps `GET`/`OPTIONS` to `GET` and retains
  `HEAD`; a followed hop carries no request body or content headers.
- HTTPS-to-HTTP redirects are denied. Origin equality is normalized scheme, IDNA
  hostname, and effective port.
- A redirect chain is part of one configured attempt. It does not increment HTTP
  attempt sequence and is not queue replay.
- Each proposed hop is parsed, normalized, checked for userinfo/scheme/port,
  resolved, checked against every address and allow/deny rule, and assigned a
  validated dial address before connection.
- A denied hop receives no TCP connection, TLS handshake, or HTTP request.
- Cross-origin hops remove `Authorization`, `Proxy-Authorization`, `Cookie`,
  `X-API-Key`, deployment-configured credential headers, and every header value
  derived from a secret reference. `Proxy-Authorization` is never sent.
- The adapter owns `Host`; user definitions cannot override it.
- Rejected-hop observations store the received `3xx` status and safe bounded
  headers. `Location` is replaced with `[REDACTED]`; its query, fragment, userinfo,
  and raw value never enter persistence, logs, spans, API errors, or snapshots.
- An accepted intermediate response is not a separate `ResponseArtifact`. A
  crash before the next/final response checkpoint leaves `dispatching` and is
  recovered conservatively.

## 7. TLS, DNS, and connection contract

### 7.1 TLS

- HTTPS always verifies the certificate chain and canonical hostname.
- TLS minimum version is 1.2.
- TLS early data/0-RTT and client certificates are disabled/unsupported.
- Stored `verify_tls: false` is readable but fails preparation with
  `tls_verification_required` before DNS or socket I/O. It is not coerced.
- Default platform trust is extended, not replaced, by one optional
  deployment-wide PEM CA bundle. `SENTINEL_TARGET_CA_BUNDLE` is an optional
  absolute mounted-file path; unset means default roots only.
- The bundle is worker configuration, not a test/environment field. Startup
  validates readability and certificate content and loads it additively; invalid
  configuration fails worker readiness without exposing the path.

### 7.2 Proxy and retry behavior

- Target clients use `trust_env=false`, no explicit proxy, and library retries
  set to zero.
- Proxy and target-CA environment variables do not affect target requests.
- Any future proxy or mTLS support requires a new accepted security decision.

### 7.3 DNS pinning

Static URL validation occurs before dispatch. DNS resolution and all destination
network activity occur after the durable `dispatching` checkpoint.

For each initial destination and redirect hop:

1. resolve all addresses through an injected resolver;
2. canonicalize IPv4/IPv6 forms;
3. apply deployment and environment allow/deny policy to every usable address;
4. fail closed if any address is prohibited unless the accepted exact exception
   applies, with explicit deny winning;
5. select one permitted address deterministically;
6. connect the socket to that address without another DNS lookup; and
7. retain the original canonical hostname/effective port for HTTP authority,
   TLS SNI, and certificate hostname verification.

Target connection pooling is disabled for the MVP. The transport is scoped to one
dispatch/hop so a connection cannot cross an origin or outlive its validation.
HTTP/2 is not required for M3; enabling it later must preserve authority and pool
partitioning.

The locked HTTPX 0.28.1/httpcore 1.0.9 stack can satisfy this with a narrow
version-coupled transport wrapper. The ordinary HTTPX transport constructor alone
does not express separate dial and verification hosts. M3-03 begins with the
executable feasibility cases in §12.4. Failure requires an explicit dependency or
architecture review; fallback hostname re-resolution is prohibited.

## 8. Fencing and transaction boundaries

Every application checkpoint uses database time and verifies, in the same short
transaction:

- job ID;
- `state = leased`;
- expected owner;
- expected opaque lease token;
- `lease_expires_at > clock_timestamp()`; and
- expected execution/item/attempt state under a row lock or compare-and-set.

The following are atomic boundaries:

1. execution, materialized items, execution job, and optional idempotency record;
2. attempt creation in `prepared`;
3. `prepared → dispatching` with fingerprint and trace/span identity;
4. response artifact plus `response_received` checkpoint;
5. transport outcome/evidence plus `transport_failed` checkpoint;
6. predecessor `replay_scheduled` plus successor `prepared` and replay link;
7. non-replayable `indeterminate` plus item/execution aggregation and suite skips;
8. terminal item/execution aggregation plus job success where possible.

No transaction remains open across secret resolution, DNS, TLS, target HTTP I/O,
response streaming, or redaction. A stale worker discards in-memory results and
cannot commit them.

## 9. Persistence contract

### 9.1 Entities

`Execution` adds the accepted project/environment/source revision pins, source
type, status, verdict, and timestamps to the M1 execution envelope.

`ExecutionItem` stores execution, zero-based ordinal, exact test-case revision,
status, verdict, and timestamps. `(execution_id, ordinal)` is unique.

`TestAttempt` stores item, positive sequence, state, dispatch certainty, request
fingerprint, dispatch/response/finish times, duration, transport outcome, safe
preparation/redirect code, replay successor, verdict participation, primary trace
ID, and client span ID. `(execution_item_id, sequence)` is unique. Replay links
cannot self-reference or form chains that disagree with sequence order.

`ResponseArtifact` stores at most one bounded redacted observation for an attempt:
status, redacted headers, body kind/content, source bytes captured, truncation,
redaction-unavailable flag, record time, and expiry. It may belong to
`response_received`, or to `transport_failed` only when certainty is
`response_received` and the outcome is `redirect_denied`, `read_timeout`, or
`read_failure`.

`IdempotencyRecord` stores key hash, canonical request hash, execution ID, and
expiry. Raw keys are never persisted.

### 9.2 Required database constraints

- Lifecycle, certainty, outcome, and error-code values are checked enums.
- `dispatching` and later dispatch states require fingerprint, trace ID, span ID,
  and dispatch time.
- `response_received` requires response artifact, response time,
  `DispatchCertainty.response_received`, and matching outcome.
- `transport_failed` requires a transport outcome other than ordinary
  `response_received`; its certainty must agree with the outcome matrix.
- `prepared` and preparation `failed` use `not_started`.
- `replay_scheduled` requires one successor; the successor begins with fresh
  identifiers and sequence.
- Secret-bearing request documents are never copied into jobs or result rows.
- History and recovery indexes follow the access paths in the architecture.

## 10. API contract

M3 implements the accepted endpoints:

- `POST /api/v1/executions`;
- `GET /api/v1/executions`;
- `GET /api/v1/executions/{execution_id}`; and
- `GET /api/v1/attempts/{attempt_id}`.

The M2 planned request/list/detail envelopes and bounds remain accepted. M3 adds
these exact attempt fields:

- `dispatch_certainty: DispatchCertainty` — required, never null;
- `transport_outcome: TransportOutcome | null`;
- `preparation_error_code: PreparationErrorCode | null`; and
- `redirect_rejection_code: RedirectRejectionCode | null`.

The API never returns a resolved outbound request, raw redirect location, selected
secret value, peer certificate details, socket/library exception, job lease token,
or idempotency key/hash.

Execution-time preparation, policy, transport, and redirect failures are durable
attempt results. They are not retroactive HTTP errors from the asynchronous
creation endpoint.

Runtime OpenAPI and generated client artifacts change only with the slice that
implements these routes and fields. This design packet is not a generated
contract.

## 11. Error and evidence safety

- Redaction occurs before persistence and before structured logging.
- Fixed credential headers and configured sensitive fields remain redacted.
- `Location` is fixed-sensitive for rejected redirect evidence.
- If configured JSON redaction cannot be safely applied, the entire body is
  omitted and `redaction_unavailable=true`.
- Partial bodies from read failure may be stored only if bounded and fully
  redacted; otherwise the body is omitted. Status and already validated/redacted
  headers may remain.
- TLS errors use `tls_failure` or `tls_verification_required`; certificate
  subject/issuer/SAN details and filesystem paths are not returned.
- Logs and spans contain IDs, state, stable codes, bounded duration, and approved
  safe target metadata only.

## 12. Named acceptance cases

### 12.1 State, replay, and fencing

- `M3-STATE-001`: every allowed transition succeeds and every unlisted transition
  fails without mutation.
- `M3-STATE-002`: crash before dispatch commit resumes without a request.
- `M3-STATE-003`: response checkpoint recovery performs no request.
- `M3-STATE-004`: transport-failure recovery performs no request.
- `M3-REPLAY-001`: ambiguous `GET`/`HEAD`/`OPTIONS` creates a linked successor
  with new attempt, trace, and span IDs.
- `M3-REPLAY-002`: ambiguous unsafe method without consent becomes
  `indeterminate`/`inconclusive` and skips remaining suite items.
- `M3-REPLAY-003`: accepted unsafe replay consent creates one fresh successor.
- `M3-FENCE-001`: wrong owner/token, replaced token, and expired lease cannot
  checkpoint dispatch, response, outcome, replay, or completion.
- `M3-FENCE-002`: lease loss during target I/O leaves durable certainty
  `possibly_sent`; the stale worker stores nothing.
- `M3-FENCE-003`: concurrent recovery creates at most one successor.

### 12.2 Transport classification

- `M3-OUTCOME-001`: DNS, target denial, TCP failure, and TLS failure record
  `not_sent` only from controlled pre-write phases.
- `M3-OUTCOME-002`: write failure/timeout records `possibly_sent` even when the
  transport reports zero bytes.
- `M3-OUTCOME-003`: read timeout/loss before headers records `possibly_sent`.
- `M3-OUTCOME-004`: read failure after response head records
  `response_received` certainty with safe bounded evidence.
- `M3-OUTCOME-005`: cancellation, lease loss, unknown exception, and commit
  uncertainty never downgrade `possibly_sent`.
- `M3-OUTCOME-006`: `4xx` and `5xx` record an accepted response and never trigger
  automatic retry.
- `M3-OUTCOME-007`: capture overflow records a truncated response and never
  refetches.

### 12.3 Redirects and SSRF

- `M3-REDIRECT-001`: with redirects disabled, `3xx` is the final response.
- `M3-REDIRECT-002`: approved safe-method redirect revalidates and pins every hop.
- `M3-REDIRECT-003`: unsafe-method redirect is rejected before the hop.
- `M3-REDIRECT-004`: malformed/missing Location, scheme/port denial, address
  denial, and limit exhaustion record the exact safe rejection code.
- `M3-REDIRECT-005`: rejected hop receives no TCP/TLS/HTTP connection and stores
  sanitized `3xx` evidence with redacted Location.
- `M3-REDIRECT-006`: cross-origin redirect strips every fixed credential and
  secret-derived header.
- `M3-REDIRECT-007`: after an earlier `3xx`, a later pre-write failure preserves
  `response_received` certainty, while an unresolved later write records
  `possibly_sent`; neither case records attempt-wide `not_sent`.
- `M3-REDIRECT-008`: only the five accepted redirect statuses are followed;
  method conversion, body removal, origin comparison, and HTTPS downgrade denial
  match §6 exactly.
- `M3-SSRF-001`: mixed allowed/blocked DNS results fail closed; explicit deny wins.
- `M3-SSRF-002`: alternate IPv4/IPv6 forms and metadata destinations are blocked.
- `M3-SSRF-003`: the connected peer is one validated address and no second DNS
  resolution changes it.

### 12.4 TLS and current-stack feasibility

- `M3-TLS-001`: valid public/default trust succeeds with hostname verification.
- `M3-TLS-002`: untrusted, expired, and hostname-mismatched certificates fail.
- `M3-TLS-003`: additive deployment CA succeeds without replacing default roots.
- `M3-TLS-004`: unreadable/invalid configured CA makes worker readiness fail.
- `M3-TLS-005`: `verify_tls: false` fails before resolver or socket invocation.
- `M3-TLS-006`: TLS below 1.2 and TLS early data are unavailable.
- `M3-TLS-007`: environment proxy variables do not affect the target path.
- `M3-TLS-008`: a synthetic peer proves selected-IP dialing, original Host
  authority, original-host SNI, and original-host certificate verification.
- `M3-TLS-009`: connection pooling/reuse cannot cross a validation decision.
- `M3-TLS-010`: dependency upgrades rerun `M3-TLS-008` and `M3-TLS-009`.

### 12.5 Privacy, API, and persistence

- `M3-PRIV-001`: synthetic secrets are absent from database, logs, spans, API
  output, problems, and test failures.
- `M3-PRIV-002`: redaction failure omits the body rather than storing fallback.
- `M3-API-001`: creation is atomic, asynchronous, and pins immutable revisions.
- `M3-API-002`: equal idempotency key/payload returns the original execution;
  different payload returns `409`.
- `M3-API-003`: read responses are bounded and contain the exact frozen enum and
  certainty fields.
- `M3-DB-001`: migration upgrade/downgrade and reviewed SQL preserve accepted M1
  and M2 data.
- `M3-E2E-001`: one case and ordered suite reach durable redacted observations.
- `M3-E2E-002`: termination at every checkpoint produces the documented recovery
  result without sleeps.

Time, UUIDs, DNS, target transport, lease state, and telemetry are injectable.
PostgreSQL—not SQLite—backs persistence and concurrency acceptance.

## 13. Frozen assumptions and deferred decisions

The following are explicit M3 limits, not inferred future guarantees:

- no outbound proxy, mTLS, per-environment CA store, or insecure TLS mode;
- no HTTP/2 acceptance requirement;
- no target connection pooling;
- no automatic target retry outside accepted ambiguous recovery;
- redirect chains remain within one configured attempt;
- M4 owns evaluation and baseline semantics; and
- M5 owns Tempo reconciliation and linked-trace discovery.

The exact internal implementation of the narrow pinned transport wrapper remains
an implementation choice only if it passes every frozen network/TLS acceptance
case without a new dependency or contract change. Otherwise M3-03 stops for
owner review.
