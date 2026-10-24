from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import httpx
import pytest

from sentinel.api.app import create_app
from sentinel.api.executions import _attempt_detail
from sentinel.config import Settings
from sentinel.execution.attempts import AttemptRecord, TraceReferenceRecord
from sentinel.execution.creation import AttemptReadRecord, PostgresExecutionService
from sentinel.execution.domain import (
    AttemptState,
    DispatchCertainty,
    TransportOutcome,
)
from sentinel.regression.read_models import ComparisonRead, EvaluationRead, PromotionRead

NOW = datetime(2030, 1, 1, 12, 30, tzinfo=UTC)
EXECUTION_ID = UUID("00000000-0000-4000-8000-000000000006")
ITEM_ID = UUID("00000000-0000-4000-8000-000000000007")
ATTEMPT_ID = UUID("00000000-0000-4000-8000-000000000008")


def _attempt() -> AttemptRecord:
    return AttemptRecord(
        id=ATTEMPT_ID,
        execution_item_id=ITEM_ID,
        sequence=1,
        state=AttemptState.RESPONSE_RECEIVED,
        dispatch_certainty=DispatchCertainty.RESPONSE_RECEIVED,
        request_fingerprint="a" * 64,
        created_at=NOW,
        dispatch_recorded_at=NOW,
        response_recorded_at=NOW,
        finished_at=NOW,
        duration_ms=12,
        transport_outcome=TransportOutcome.RESPONSE_RECEIVED,
        preparation_error_code=None,
        redirect_rejection_code=None,
        replay_successor_id=None,
        primary_trace_id="b" * 32,
        client_span_id="c" * 16,
        included_in_verdict=True,
    )


class MemoryAttemptService:
    def __init__(self, trace_references: tuple[TraceReferenceRecord, ...] = ()) -> None:
        self.trace_references = trace_references

    def get_attempt(self, attempt_id: UUID) -> object:
        if attempt_id != ATTEMPT_ID:
            return None
        return type(
            "AttemptRead",
            (),
            {
                "execution_id": EXECUTION_ID,
                "attempt": _attempt(),
                "read_at": NOW,
                "artifact": type(
                    "Artifact",
                    (),
                    {
                        "attempt_id": ATTEMPT_ID,
                        "status_code": 200,
                        "headers": {"content-type": "application/json", "set-cookie": "[REDACTED]"},
                        "body_kind": "json",
                        "body_content": {"id": "synthetic"},
                        "source_bytes_captured": 18,
                        "truncated": False,
                        "redaction_unavailable": False,
                        "recorded_at": NOW,
                        "expires_at": NOW + timedelta(days=7),
                    },
                )(),
                "comparison": ComparisonRead(
                    state="not_requested",
                    baseline_activation_id=None,
                    baseline_id=None,
                    baseline_version=None,
                    policy_fingerprint=None,
                    checked_at=NOW,
                ),
                "evaluations": (
                    EvaluationRead(
                        id=ATTEMPT_ID,
                        ordinal=0,
                        kind="assertion",
                        rule_id=ATTEMPT_ID,
                        severity="required",
                        outcome="passed",
                        message_code="assertion_passed",
                        expected="synthetic",
                        actual="synthetic",
                        evidence_omitted=False,
                    ),
                ),
                "promotion": PromotionRead(True, (), ()),
                "trace_references": self.trace_references,
                "trace_references_truncated": False,
            },
        )()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(otlp_endpoint=None),
        database_probe=lambda: _ready(),
        tempo_probe=lambda: _not_ready(),
        execution_service=cast(PostgresExecutionService, MemoryAttemptService()),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client,
    ):
        yield client


async def _ready() -> bool:
    return True


async def _not_ready() -> bool:
    return False


async def test_attempt_detail_returns_redacted_observation(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/attempts/{ATTEMPT_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == str(EXECUTION_ID)
    assert body["execution_item_id"] == str(ITEM_ID)
    assert body["dispatch_certainty"] == "response_received"
    assert body["observation_state"] == "available"
    assert body["observation"]["body"] == '{"id":"synthetic"}'
    assert body["observation"]["headers"][1] == {
        "name": "set-cookie",
        "value": "[REDACTED]",
    }
    assert body["baseline_comparison"]["state"] == "not_requested"
    assert body["evaluations"][0]["ordinal"] == 0
    assert body["baseline_promotion"] == {
        "eligible": True,
        "warning_codes": [],
        "ineligibility_codes": [],
    }
    assert body["trace_references"] == []
    assert body["trace_references_truncated"] is False


def test_attempt_detail_returns_ordered_bounded_trace_evidence_and_safe_link() -> None:
    evidence = {
        "schema_version": 1,
        "primary_span_found": True,
        "trace_span_count": 2,
        "error_span_count": 0,
        "services": [{"name": "api", "version": None, "environment": None, "revision": None}],
        "deployments": [{"service": "api", "environment": None, "revision": None}],
        "linked_match_count": 1,
        "context_continuity": "connected",
        "comparison_anchor": {
            "reference_id": str(ATTEMPT_ID),
            "changed": [{"name": "api", "fields": ["version"]}],
        },
    }
    references = (
        TraceReferenceRecord(
            id=UUID("00000000-0000-4000-8000-000000000010"),
            relation="linked",
            trace_id="d" * 32,
            span_id=None,
            correlation_source="baggage_attribute_search",
            status="partial",
            first_checked_at=NOW,
            last_checked_at=NOW,
            deadline_at=NOW + timedelta(minutes=1),
            lookup_attempt_count=2,
            last_error_code="invalid_trace",
            evidence_json=evidence,
        ),
        TraceReferenceRecord(
            id=UUID("00000000-0000-4000-8000-000000000011"),
            relation="primary",
            trace_id="b" * 32,
            span_id="c" * 16,
            correlation_source="sentinel_context",
            status="available",
            first_checked_at=NOW,
            last_checked_at=NOW,
            deadline_at=NOW + timedelta(minutes=1),
            lookup_attempt_count=1,
            last_error_code=None,
            evidence_json=evidence,
        ),
    )
    record = AttemptReadRecord(
        execution_id=EXECUTION_ID,
        attempt=_attempt(),
        artifact=None,
        read_at=NOW,
        trace_references=references,
        trace_references_truncated=True,
    )

    detail = _attempt_detail(
        record, tempo_trace_url_template="https://grafana.example.test/traces/{trace_id}"
    )
    body = detail.model_dump(mode="json")

    assert [item["relation"] for item in body["trace_references"]] == ["primary", "linked"]
    assert body["trace_references"][0]["tempo_url"] == (
        f"https://grafana.example.test/traces/{'b' * 32}"
    )
    assert body["trace_references"][0]["first_checked_at"] == "2030-01-01T12:30:00.000000Z"
    assert body["trace_references"][1]["evidence"] == evidence
    assert body["trace_references_truncated"] is True
    assert "raw" not in detail.model_dump_json()


async def test_unknown_attempt_is_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/attempts/00000000-0000-4000-8000-000000000099")
    assert response.status_code == 404
    assert response.json() == {
        "type": "urn:sentinel:problem:resource_not_found",
        "title": "Request failed",
        "status": 404,
        "code": "resource_not_found",
    }


def test_expired_artifact_is_not_returned() -> None:
    attempt = _attempt()
    artifact = type(
        "Artifact",
        (),
        {
            "attempt_id": ATTEMPT_ID,
            "status_code": 200,
            "headers": {"authorization": "[REDACTED]"},
            "body_kind": "text",
            "body_content": "synthetic-secret-canary",
            "source_bytes_captured": 22,
            "truncated": False,
            "redaction_unavailable": False,
            "recorded_at": NOW - timedelta(days=8),
            "expires_at": NOW - timedelta(days=1),
        },
    )()
    detail = _attempt_detail(
        AttemptReadRecord(
            execution_id=EXECUTION_ID,
            attempt=attempt,
            artifact=artifact,
            read_at=NOW,
        )
    )
    assert detail.observation is None
    assert detail.observation_state == "expired"
    assert "synthetic-secret-canary" not in detail.model_dump_json()
