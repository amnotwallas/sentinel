from datetime import UTC, datetime
from uuid import UUID

import httpx

from sentinel.telemetry.tempo import MAX_LINKED_TRACES, TempoLookupAdapter

ATTEMPT_ID = UUID("11111111-1111-4111-8111-111111111111")
START = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
END = datetime(2026, 10, 23, 12, 1, tzinfo=UTC)


def search_payload() -> dict[str, object]:
    return {
        "traces": [
            {
                "traceID": "B" * 32,
                "spanSets": [
                    {
                        "spans": [
                            {
                                "attributes": [
                                    {"key": "service.name", "value": {"stringValue": "z-api"}},
                                    {"key": "service.version", "value": {"stringValue": "2"}},
                                    {
                                        "key": "deployment.revision",
                                        "value": {"stringValue": "rev-2"},
                                    },
                                ]
                            }
                        ]
                    }
                ],
            },
            {"traceID": "a" * 32, "spanSets": []},
            {"traceID": "a" * 32, "spanSets": []},
        ]
    }


def test_search_attempt_queries_exact_baggage_and_returns_safe_sorted_matches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/search"
        assert request.url.params["tags"] == f"sentinel.attempt.id={ATTEMPT_ID}"
        assert request.url.params["start"] == str(int(START.timestamp()))
        assert request.url.params["end"] == str(int(END.timestamp()))
        assert request.url.params["limit"] == str(MAX_LINKED_TRACES)
        return httpx.Response(200, json=search_payload())

    with TempoLookupAdapter(
        "http://tempo:3200", transport=httpx.MockTransport(handler), clock=lambda: START
    ) as tempo:
        results = tempo.search_attempt(ATTEMPT_ID, start_at=START, end_at=END, limit=99)

    assert [item.trace_id for item in results] == ["a" * 32, "b" * 32]
    assert results[1].services[0].name == "z-api"
    assert results[1].services[0].revision == "rev-2"


def test_search_malformed_response_is_empty_and_does_not_expose_payload() -> None:
    canary = "authorization-secret-canary"
    response = {"traces": [{"traceID": canary, "payload": canary}]}
    with TempoLookupAdapter(
        "http://tempo:3200",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)),
        clock=lambda: START,
    ) as tempo:
        results = tempo.search_attempt(ATTEMPT_ID, start_at=START, end_at=END, limit=16)

    assert results == ()
    assert canary not in repr(results)


def test_search_is_bounded_and_ignores_unapproved_attributes() -> None:
    canary = "authorization-secret-canary"
    traces = [
        {
            "traceID": f"{index + 1:032x}",
            "spanSets": [
                {
                    "spans": [
                        {
                            "attributes": [
                                {
                                    "key": "service.name",
                                    "value": {"stringValue": f"service-{index:02d}"},
                                },
                                {"key": "http.url", "value": {"stringValue": canary}},
                                {"key": "db.statement", "value": {"stringValue": canary}},
                            ]
                        }
                    ]
                }
            ],
        }
        for index in range(20)
    ]
    with TempoLookupAdapter(
        "http://tempo:3200",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"traces": traces})),
        clock=lambda: START,
    ) as tempo:
        results = tempo.search_attempt(ATTEMPT_ID, start_at=START, end_at=END, limit=99)

    assert len(results) == MAX_LINKED_TRACES
    assert [item.trace_id for item in results] == [f"{index + 1:032x}" for index in range(16)]
    assert canary not in repr(results)
