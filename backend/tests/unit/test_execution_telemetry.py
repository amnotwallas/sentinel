from __future__ import annotations

from uuid import UUID

from opentelemetry import baggage, trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from sentinel.execution.domain import DispatchCertainty, TransportOutcome
from sentinel.telemetry.execution import OpenTelemetryTraceLifecycle

EXECUTION_ID = UUID("70000000-0000-4000-8000-000000000001")
ATTEMPT_ID = UUID("70000000-0000-4000-8000-000000000002")


def lifecycle() -> tuple[OpenTelemetryTraceLifecycle, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OpenTelemetryTraceLifecycle(provider.get_tracer("sentinel.test")), exporter


def test_root_client_span_uses_actual_ids_and_preserves_vendor_baggage() -> None:
    traces, exporter = lifecycle()

    active = traces.start(
        execution_id=EXECUTION_ID,
        attempt_id=ATTEMPT_ID,
        method="GET",
        headers={"baggage": "vendor=value"},
    )

    trace_context = TraceContextTextMapPropagator().extract(active.headers)
    span_context = trace.get_current_span(trace_context).get_span_context()
    assert f"{span_context.trace_id:032x}" == active.trace_id
    assert f"{span_context.span_id:016x}" == active.span_id
    baggage_context = W3CBaggagePropagator().extract(active.headers)
    assert baggage.get_baggage("vendor", context=baggage_context) == "value"
    assert baggage.get_baggage("sentinel.execution.id", context=baggage_context) == str(
        EXECUTION_ID
    )
    assert baggage.get_baggage("sentinel.attempt.id", context=baggage_context) == str(ATTEMPT_ID)

    active.end(
        status_code=200,
        outcome=TransportOutcome.RESPONSE_RECEIVED,
        certainty=DispatchCertainty.RESPONSE_RECEIVED,
    )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].kind.name == "CLIENT"
    assert spans[0].parent is None
    assert spans[0].attributes == {
        "http.request.method": "GET",
        "http.response.status_code": 200,
        "sentinel.transport.outcome": "response_received",
        "sentinel.dispatch.certainty": "response_received",
    }


def test_each_attempt_is_a_distinct_root_span_and_end_is_idempotent() -> None:
    traces, exporter = lifecycle()
    first = traces.start(
        execution_id=EXECUTION_ID,
        attempt_id=ATTEMPT_ID,
        method="GET",
        headers={},
    )
    second = traces.start(
        execution_id=EXECUTION_ID,
        attempt_id=UUID("70000000-0000-4000-8000-000000000003"),
        method="GET",
        headers={},
    )

    first.end(status_code=None, outcome=None, certainty=None)
    first.end(status_code=None, outcome=None, certainty=None)
    second.end(status_code=None, outcome=None, certainty=None)

    assert first.trace_id != second.trace_id
    assert first.span_id != second.span_id
    assert len(exporter.get_finished_spans()) == 2
