"""OpenTelemetry adapter for one root HTTP client span per execution attempt."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from opentelemetry import baggage, trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.context import Context
from opentelemetry.trace import Span, SpanKind, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from sentinel.execution.domain import DispatchCertainty, TransportOutcome


@dataclass(slots=True)
class _OpenTelemetryDispatchTrace:
    _span: Span
    trace_id: str
    span_id: str
    headers: Mapping[str, str]
    _ended: bool = False

    def end(
        self,
        *,
        status_code: int | None,
        outcome: TransportOutcome | None,
        certainty: DispatchCertainty | None,
    ) -> None:
        if self._ended:
            return
        if status_code is not None:
            self._span.set_attribute("http.response.status_code", status_code)
        if outcome is not None:
            self._span.set_attribute("sentinel.transport.outcome", outcome.value)
        if certainty is not None:
            self._span.set_attribute("sentinel.dispatch.certainty", certainty.value)
        self._ended = True
        self._span.end()


class OpenTelemetryTraceLifecycle:
    """Create/inject a new root span while retaining validated vendor baggage."""

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer
        self._trace_context = TraceContextTextMapPropagator()
        self._baggage = W3CBaggagePropagator()

    def start(
        self,
        *,
        execution_id: UUID,
        attempt_id: UUID,
        method: str,
        headers: Mapping[str, str],
    ) -> _OpenTelemetryDispatchTrace:
        existing_baggage = next(
            (value for name, value in headers.items() if name.lower() == "baggage"), None
        )
        baggage_context = (
            self._baggage.extract({"baggage": existing_baggage})
            if existing_baggage is not None
            else Context()
        )
        baggage_context = baggage.set_baggage(
            "sentinel.execution.id", str(execution_id), context=baggage_context
        )
        baggage_context = baggage.set_baggage(
            "sentinel.attempt.id", str(attempt_id), context=baggage_context
        )
        normalized_method = method.upper()
        span = self._tracer.start_span(
            f"HTTP {normalized_method}", context=Context(), kind=SpanKind.CLIENT
        )
        span.set_attribute("http.request.method", normalized_method)
        span_context = span.get_span_context()
        dispatch_context = trace.set_span_in_context(span, baggage_context)
        carrier = {
            name: value
            for name, value in headers.items()
            if name.lower() not in {"traceparent", "tracestate", "baggage"}
        }
        self._trace_context.inject(carrier, context=dispatch_context)
        self._baggage.inject(carrier, context=dispatch_context)
        return _OpenTelemetryDispatchTrace(
            span,
            f"{span_context.trace_id:032x}",
            f"{span_context.span_id:016x}",
            carrier,
        )
