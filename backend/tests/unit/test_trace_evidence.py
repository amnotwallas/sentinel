from uuid import UUID

from sentinel.telemetry.evidence import build_comparison_anchor, build_trace_evidence
from sentinel.telemetry.ports import (
    ContextContinuity,
    ServiceEvidence,
    TraceLookup,
    TraceLookupStatus,
)


def lookup() -> TraceLookup:
    return TraceLookup(
        trace_id="a" * 32,
        client_span_id="b" * 16,
        status=TraceLookupStatus.AVAILABLE,
        error_code=None,
        trace_span_count=4,
        error_span_count=1,
        services=(
            ServiceEvidence("z-api", version="2", environment="prod", revision="r2"),
            ServiceEvidence("a-api", version="1"),
        ),
        context_continuity=ContextContinuity.CONNECTED,
        response_size_bytes=128,
    )


def test_trace_evidence_is_allowlisted_sorted_and_separates_deployments() -> None:
    evidence = build_trace_evidence(lookup(), linked_match_count=2, comparison_anchor=None)

    assert evidence == {
        "schema_version": 1,
        "primary_span_found": True,
        "trace_span_count": 4,
        "error_span_count": 1,
        "services": [
            {"name": "a-api", "version": "1", "environment": None, "revision": None},
            {"name": "z-api", "version": "2", "environment": "prod", "revision": "r2"},
        ],
        "deployments": [{"service": "z-api", "environment": "prod", "revision": "r2"}],
        "linked_match_count": 2,
        "context_continuity": "connected",
        "comparison_anchor": None,
    }


def test_comparison_anchor_records_only_changed_keys() -> None:
    previous = {
        "services": [
            {"name": "a-api", "version": "1", "environment": "prod", "revision": "r1"},
            {"name": "old-api", "version": "1", "environment": None, "revision": None},
        ]
    }
    anchor = build_comparison_anchor(
        UUID("22222222-2222-4222-8222-222222222222"),
        previous,
        (
            ServiceEvidence("a-api", version="2", environment="prod", revision="r1"),
            ServiceEvidence("new-api", version="1"),
        ),
    )

    assert anchor == {
        "reference_id": "22222222-2222-4222-8222-222222222222",
        "changed": [
            {"name": "a-api", "fields": ["version"]},
            {"name": "new-api", "fields": ["name"]},
            {"name": "old-api", "fields": ["name"]},
        ],
    }
