from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sentinel.telemetry.ports import TraceLookupStatus
from sentinel.telemetry.tempo import TempoLookupAdapter


def test_tempo_lookup_span_uses_only_safe_bounded_attributes() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with TempoLookupAdapter(
        "http://tempo:3200",
        transport=httpx.MockTransport(handler),
        tracer=provider.get_tracer("sentinel.test"),
    ) as tempo:
        result = tempo.lookup(
            "a" * 32,
            expected_span_id="b" * 16,
            deadline=datetime.now(UTC) + timedelta(seconds=10),
        )

    assert result.status is TraceLookupStatus.MISSING
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "sentinel.tempo.lookup"
    assert spans[0].attributes == {
        "sentinel.outcome": "missing",
        "sentinel.error_code": "not_found",
        "sentinel.response.size": 0,
    }


def test_tempo_search_span_excludes_query_and_response_payloads() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with TempoLookupAdapter(
        "http://tempo:3200",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"traces": []})),
        tracer=provider.get_tracer("sentinel.test"),
    ) as tempo:
        assert (
            tempo.search_attempt(
                UUID("11111111-1111-4111-8111-111111111111"),
                start_at=datetime(2030, 1, 1, tzinfo=UTC),
                end_at=datetime(2030, 1, 1, 0, 1, tzinfo=UTC),
                limit=16,
            )
            == ()
        )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "sentinel.tempo.search"
    assert spans[0].attributes == {"sentinel.outcome": "empty", "sentinel.response.size": 13}
