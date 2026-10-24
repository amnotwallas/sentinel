import base64
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from sentinel.config import Settings
from sentinel.telemetry.ports import (
    ContextContinuity,
    TraceErrorCode,
    TraceLookup,
    TraceLookupStatus,
)
from sentinel.telemetry.tempo import (
    MAX_RESPONSE_BYTES,
    MAX_SERVICES,
    TempoEndpointError,
    TempoLookupAdapter,
    TempoTLSConfigurationError,
    validate_tempo_url,
)

TRACE_ID = "a" * 32
SPAN_ID = "b" * 16
OTHER_SPAN_ID = "c" * 16


def payload(
    *, include_client: bool = True, extra: Sequence[dict[str, object]] | None = None
) -> dict[str, object]:
    spans: list[dict[str, object]] = [
        {"traceId": TRACE_ID, "spanId": OTHER_SPAN_ID, "status": {"code": 2}},
    ]
    if include_client:
        spans.insert(0, {"traceId": TRACE_ID, "spanId": SPAN_ID, "status": {"code": 1}})
    if extra:
        spans.extend(extra)
    return {
        "batches": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "z-api"}},
                        {"key": "service.version", "value": {"stringValue": "2"}},
                        {"key": "deployment.environment.name", "value": {"stringValue": "prod"}},
                    ]
                },
                "scopeSpans": [{"spans": spans}],
            },
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "a-api"}},
                        {"key": "service.version", "value": {"stringValue": "1"}},
                    ]
                },
                "scopeSpans": [{"spans": []}],
            },
        ]
    }


def adapter(transport: httpx.BaseTransport) -> TempoLookupAdapter:
    return TempoLookupAdapter("http://tempo:3200", transport=transport)


def lookup(adapter_instance: TempoLookupAdapter) -> TraceLookup:
    return adapter_instance.lookup(
        TRACE_ID,
        expected_span_id=SPAN_ID,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )


def test_direct_lookup_classifies_available_and_sorts_safe_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == f"/api/traces/{TRACE_ID}"
        return httpx.Response(200, json=payload())

    with adapter(httpx.MockTransport(handler)) as tempo:
        result = lookup(tempo)

    assert result.status is TraceLookupStatus.AVAILABLE
    assert result.error_code is None
    assert result.client_span_id == SPAN_ID
    assert result.trace_span_count == 2
    assert result.error_span_count == 1
    assert result.context_continuity is ContextContinuity.CONNECTED
    assert [service.name for service in result.services] == ["a-api", "z-api"]


def test_direct_lookup_decodes_tempo_otlp_base64_ids() -> None:
    document = payload()
    batches = document["batches"]
    assert isinstance(batches, list)
    for batch in batches:
        assert isinstance(batch, dict)
        scopes = batch["scopeSpans"]
        assert isinstance(scopes, list)
        for scope in scopes:
            assert isinstance(scope, dict)
            spans = scope["spans"]
            assert isinstance(spans, list)
            for span in spans:
                assert isinstance(span, dict)
                for key in ("traceId", "spanId"):
                    value = span[key]
                    assert isinstance(value, str)
                    span[key] = base64.b64encode(bytes.fromhex(value)).decode()

    with adapter(httpx.MockTransport(lambda _: httpx.Response(200, json=document))) as tempo:
        result = lookup(tempo)

    assert result.status is TraceLookupStatus.AVAILABLE
    assert result.client_span_id == SPAN_ID


def test_missing_and_partial_trace_are_distinct() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(TRACE_ID):
            return httpx.Response(200, json=payload(include_client=False))
        raise AssertionError("unexpected request")

    with adapter(httpx.MockTransport(handler)) as tempo:
        partial = lookup(tempo)
    assert partial.status is TraceLookupStatus.PARTIAL
    assert partial.error_code is None
    assert partial.context_continuity is ContextContinuity.BROKEN

    with adapter(httpx.MockTransport(lambda _: httpx.Response(404))) as tempo:
        missing = lookup(tempo)
    assert missing.status is TraceLookupStatus.MISSING
    assert missing.error_code is TraceErrorCode.NOT_FOUND


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(500), TraceErrorCode.UNAVAILABLE),
        (
            httpx.Response(302, headers={"location": "https://evil.invalid"}),
            TraceErrorCode.UNSUPPORTED,
        ),
        (httpx.Response(400), TraceErrorCode.BAD_RESPONSE),
    ],
)
def test_http_failures_are_closed_and_safe(response: httpx.Response, code: TraceErrorCode) -> None:
    with adapter(httpx.MockTransport(lambda _: response)) as tempo:
        result = lookup(tempo)
    assert result.status is TraceLookupStatus.TEMPO_UNAVAILABLE
    assert result.error_code is code
    assert result.response_size_bytes == 0


def test_malformed_json_never_exposes_payload() -> None:
    canary = "authorization-secret-canary"
    with adapter(
        httpx.MockTransport(lambda _: httpx.Response(200, content=f"{{{canary}"))
    ) as tempo:
        result = lookup(tempo)
    assert result.status is TraceLookupStatus.PARTIAL
    assert result.error_code is TraceErrorCode.INVALID_TRACE
    assert canary not in repr(result)


def test_oversized_response_is_bounded() -> None:
    content = b"{" + b"x" * MAX_RESPONSE_BYTES
    with adapter(httpx.MockTransport(lambda _: httpx.Response(200, content=content))) as tempo:
        result = lookup(tempo)
    assert result.status is TraceLookupStatus.PARTIAL
    assert result.error_code is TraceErrorCode.OVERSIZED_RESPONSE
    assert result.trace_span_count == 0


def test_invalid_trace_response_and_span_limit_are_partial() -> None:
    invalid = {"batches": [{"scopeSpans": [{"spans": [{"traceId": "bad"}]}]}]}
    with adapter(httpx.MockTransport(lambda _: httpx.Response(200, json=invalid))) as tempo:
        result = lookup(tempo)
    assert result.status is TraceLookupStatus.PARTIAL
    assert result.error_code is TraceErrorCode.INVALID_TRACE

    many: list[dict[str, object]] = [
        {"traceId": TRACE_ID, "spanId": f"{index + 1:016x}"} for index in range(257)
    ]
    with adapter(
        httpx.MockTransport(lambda _: httpx.Response(200, json=payload(extra=many)))
    ) as tempo:
        result = lookup(tempo)
    assert result.error_code is TraceErrorCode.OVERSIZED_RESPONSE
    assert result.trace_span_count == 256


def test_service_evidence_is_bounded_and_sorted() -> None:
    document = payload()
    batches = document["batches"]
    assert isinstance(batches, list)
    for index in range(MAX_SERVICES + 1):
        batches.append(
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": f"service-{index:02d}"},
                        }
                    ]
                },
                "scopeSpans": [{"spans": []}],
            }
        )
    with adapter(httpx.MockTransport(lambda _: httpx.Response(200, json=document))) as tempo:
        result = lookup(tempo)
    assert result.error_code is TraceErrorCode.OVERSIZED_RESPONSE
    assert len(result.services) == MAX_SERVICES
    assert [service.name for service in result.services] == sorted(
        service.name for service in result.services
    )


def test_timeout_and_transport_errors_do_not_include_exception_text() -> None:
    canary = "socket-secret-canary"

    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(canary)

    with adapter(httpx.MockTransport(timeout)) as tempo:
        result = lookup(tempo)
    assert result.status is TraceLookupStatus.TEMPO_UNAVAILABLE
    assert result.error_code is TraceErrorCode.TIMEOUT
    assert canary not in repr(result)

    with adapter(
        httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ConnectError(canary)))
    ) as tempo:
        result = lookup(tempo)
    assert result.error_code is TraceErrorCode.TRANSPORT_ERROR
    assert canary not in repr(result)


def test_expired_adapter_deadline_is_not_sent() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=payload())

    with adapter(httpx.MockTransport(handler)) as tempo:
        result = tempo.lookup(
            TRACE_ID,
            expected_span_id=SPAN_ID,
            deadline=datetime.now(UTC) - timedelta(seconds=1),
        )
    assert not called
    assert result.error_code is TraceErrorCode.TIMEOUT


def test_tls_and_endpoint_validation() -> None:
    for value in ("ftp://tempo:3200", "http://user:pass@tempo:3200", "http://tempo:3200/?token=x"):
        with pytest.raises(TempoEndpointError):
            validate_tempo_url(value)
    with pytest.raises(TempoTLSConfigurationError):
        TempoLookupAdapter("https://tempo:3200", verify=False)
    assert validate_tempo_url("https://tempo:3200/") == "https://tempo:3200"


def test_settings_validate_internal_tempo_endpoint() -> None:
    with pytest.raises(ValidationError):
        Settings(tempo_url="http://tempo:3200/?secret=canary")


def test_search_capability_is_opt_in_and_cached() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/search/tags"
        assert request.url.query == b"scope=span"
        return httpx.Response(200, json={"scopes": ["span"]})

    with adapter(httpx.MockTransport(handler)) as tempo:
        assert tempo.search_supported()
        assert tempo.search_supported()
    assert calls == 1


def test_untrusted_attributes_are_not_returned_as_evidence() -> None:
    canary = "authorization-secret-canary"
    document = payload()
    batches = document["batches"]
    assert isinstance(batches, list)
    batch = batches[0]
    assert isinstance(batch, dict)
    resource = batch["resource"]
    assert isinstance(resource, dict)
    attributes = resource["attributes"]
    assert isinstance(attributes, list)
    attributes.extend(
        [
            {"key": "http.url", "value": {"stringValue": canary}},
            {"key": "db.statement", "value": {"stringValue": canary}},
            {"key": "Authorization", "value": {"stringValue": canary}},
        ]
    )
    with adapter(httpx.MockTransport(lambda _: httpx.Response(200, json=document))) as tempo:
        result = lookup(tempo)
    assert canary not in repr(result)
