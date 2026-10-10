# ADR 0005: OpenTelemetry trace correlation

- Status: Accepted
- Date: 2026-10-09

## Context

Sentinel must connect an API test observation to distributed traces without a
proprietary protocol. Trace ingestion is asynchronous; applications may sample,
drop, delay, or break context; and one logical execution may issue multiple
requests. Trace evidence must remain useful without becoming a prerequisite for
functional evaluation.

The identifiers involved serve different purposes and must not be conflated:
execution and attempt IDs are Sentinel workflow identities, while trace and span
IDs are OpenTelemetry identities.

## Decision

Use the OpenTelemetry SDK and W3C Trace Context/Baggage propagators.

For each possible outbound dispatch:

1. Create a new attempt UUID.
2. Start a new root HTTP client span using the OpenTelemetry API. It is separate
   from Sentinel's internal job-processing trace; the internal span may link to
   it rather than parent it.
3. Read the generated 128-bit trace ID and 64-bit span ID.
4. Persist the attempt in `dispatching`, the primary `TraceReference`, trace ID,
   client span ID, and request fingerprint in a committed transaction.
5. Inject the span context as W3C `traceparent`/`tracestate` and inject W3C
   `baggage` entries `sentinel.execution.id` and `sentinel.attempt.id`.
6. Perform the request and end/export the span with OpenTelemetry HTTP semantic
   attributes, excluding secrets and bodies.

Starting a new root per attempt makes the primary trace identity unambiguous.
Every replay creates a new attempt, root span, trace ID, and span ID. One execution
therefore maps to one or more attempts and traces; a suite normally has many.

User definitions may carry unrelated W3C baggage, subject to size/security
validation, but may not set `traceparent`, `tracestate`, or Sentinel-owned baggage
keys. Sentinel owns these values for the dispatch.

### Correlation model

Every dispatched attempt has one primary trace reference with
`correlation_source = sentinel_context`. It may have zero or more linked trace
references.

`TraceReference.status` is one of `pending`, `missing`, `available`, `partial`,
`tempo_unavailable`, or `expired`. `pending`, `missing`, `partial`, and
`tempo_unavailable` may be revisited before the lookup deadline; `available` and
`expired` are terminal for that reconciliation window.

The primary lookup uses the known trace ID and validates whether the stored client
span is present:

- trace and client span present: `available`;
- trace exists but expected spans/context are incomplete: `partial`;
- no result before deadline: initially `missing`, eventually `expired`;
- Tempo query fails: `tempo_unavailable`, retryable until the deadline.

If the target breaks trace context but copies Sentinel's standard baggage values
into indexed span attributes, an optional Tempo search may find one or more other
trace IDs. These become `linked` references with
`correlation_source = baggage_attribute_search`. This is indirect evidence. The
UI must not draw a parent/child edge or claim completeness unless trace data
proves it.

Attribute search is best-effort because Tempo configurations differ. Direct
known-ID lookup is the MVP's required correlation path.

### Delayed ingestion

Trace reconciliation runs as a job separate from functional evaluation. It uses
bounded backoff until a configurable deadline (default 60 seconds after the
attempt becomes terminal). The functional result is immediately available. A
later successful lookup updates correlation state without rewriting the attempt
verdict.

After the deadline, missing primary telemetry becomes `expired`. A manual page
refresh may verify that previously available trace content has aged out of Tempo,
but persisted identifiers and correlation provenance remain.

### Application obligations

Direct end-to-end correlation requires the tested application to:

- extract W3C Trace Context and parent its server span correctly;
- propagate context downstream;
- export OpenTelemetry spans to the Tempo path Sentinel queries;
- provide stable `service.name` resource attributes.

For linked-trace discovery, it must also preserve W3C Baggage and deliberately
copy the Sentinel baggage values to searchable span attributes. OpenTelemetry
does not automatically turn baggage into span attributes.

`service.version`, deployment environment, and source/deployment revision
attributes are recommended. Sentinel may compare and display them as “changed
before this result” evidence, never as proven cause.

## Privacy constraints

- IDs are opaque UUIDs with no user or secret content.
- Baggage is treated as untrusted by applications and must never authorize a
  request.
- Request/response bodies, authorization data, secret values, full URLs with
  sensitive query values, and cookies are prohibited from span attributes/events.
- Sentinel records only IDs, status, timing, safe route/host metadata, and bounded
  error codes in its own spans.

## Alternatives considered

### Custom correlation headers or proprietary agent

This would create a Sentinel-specific protocol and violate interoperability
requirements. W3C Trace Context and Baggage already provide the needed transport.

### One trace for an entire suite

It makes a suite visually cohesive but couples unrelated target requests and
complicates replay identity, long trace duration, and sampling. Execution ID
already provides suite-level grouping.

### Query Tempo synchronously before completing a test

This couples verdict latency and availability to asynchronous telemetry ingestion.
Correlation must converge independently.

### Infer related traces from timestamps/service names

This creates false correlations under concurrency. Sentinel shows no link without
an exact trace ID or exact attempt baggage attribute.

## Consequences

- Sentinel interoperates with standard OpenTelemetry instrumentation.
- Missing or partial telemetry is an expected state rather than a test failure.
- The worker must explicitly create/inject the client span so IDs can be persisted
  before network I/O.
- Multiple traces are represented rather than collapsed.
- Baggage-based recovery is optional and depends on application and Tempo indexing
  configuration.
- Trace data can support investigation but cannot by itself establish root cause.
