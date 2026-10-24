from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import httpx
import pytest

from sentinel.api.app import create_app
from sentinel.config import Settings
from sentinel.regression.baselines import (
    ActivationSummary,
    BaselineCreateResult,
    BaselinePage,
    BaselineScope,
    BaselineService,
    BaselineSummary,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)
TEST_CASE_ID = UUID("00000000-0000-4000-8000-000000000001")
ENVIRONMENT_ID = UUID("00000000-0000-4000-8000-000000000002")
BASELINE_ID = UUID("00000000-0000-4000-8000-000000000003")
ATTEMPT_ID = UUID("00000000-0000-4000-8000-000000000004")
EXECUTION_ID = UUID("00000000-0000-4000-8000-000000000005")
REVISION_ID = UUID("00000000-0000-4000-8000-000000000006")


def _baseline() -> BaselineSummary:
    return BaselineSummary(
        id=BASELINE_ID,
        test_case_id=TEST_CASE_ID,
        environment_id=ENVIRONMENT_ID,
        project_id=UUID("00000000-0000-4000-8000-000000000007"),
        version=1,
        source_attempt_id=ATTEMPT_ID,
        source_execution_id=EXECUTION_ID,
        source_test_case_revision_id=REVISION_ID,
        source_attempt_verdict="passed",
        source_finished_at=NOW,
        policy_fingerprint="a" * 64,
        created_at=NOW,
        reason=None,
        active=True,
        activated_at=NOW,
    )


def _activation() -> ActivationSummary:
    return ActivationSummary(
        id=UUID("00000000-0000-4000-8000-000000000008"),
        test_case_id=TEST_CASE_ID,
        environment_id=ENVIRONMENT_ID,
        project_id=_baseline().project_id,
        baseline_id=BASELINE_ID,
        baseline_version=1,
        activated_at=NOW,
        deactivated_at=None,
        reason=None,
    )


class MemoryBaselineService:
    def list_history(self, scope: BaselineScope, *, after: object, limit: int) -> BaselinePage:
        assert scope == BaselineScope(TEST_CASE_ID, ENVIRONMENT_ID)
        return BaselinePage(items=(_baseline(),), next_after=None, etag='"scope"')

    def promote(self, scope: BaselineScope, **_: object) -> BaselineCreateResult:
        assert scope == BaselineScope(TEST_CASE_ID, ENVIRONMENT_ID)
        return BaselineCreateResult(_baseline(), _activation(), '"scope-2"', True)

    def activate(self, scope: BaselineScope, **_: object) -> object:
        assert scope == BaselineScope(TEST_CASE_ID, ENVIRONMENT_ID)
        return type(
            "Activation", (), {"activation": _activation(), "etag": '"scope-2"', "created": True}
        )()


@pytest.fixture
async def baseline_client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(otlp_endpoint=None),
        baseline_service=cast(BaselineService, MemoryBaselineService()),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield client


def test_m4_routes_and_result_schemas_are_published() -> None:
    document = create_app(Settings(otlp_endpoint=None)).openapi()
    paths = document["paths"]
    assert set(paths["/api/v1/test-cases/{test_case_id}/baselines"]) == {"get", "post"}
    assert set(paths["/api/v1/test-cases/{test_case_id}/baseline-activations"]) == {"post"}
    assert "BaselineComparisonOutput" in document["components"]["schemas"]
    assert "EvaluationOutput" in document["components"]["schemas"]
    assert "baseline_comparison" in document["components"]["schemas"]["AttemptDetail"]["properties"]
    assert (
        "pinned_change_events" in document["components"]["schemas"]["ExecutionDetail"]["properties"]
    )


async def test_baseline_list_returns_scope_etag_and_links(
    baseline_client: httpx.AsyncClient,
) -> None:
    response = await baseline_client.get(
        f"/api/v1/test-cases/{TEST_CASE_ID}/baselines",
        params={"environment_id": str(ENVIRONMENT_ID)},
    )
    assert response.status_code == 200
    assert response.headers["etag"] == '"scope"'
    assert response.json()["items"][0]["links"] == {
        "source_attempt": f"/api/v1/attempts/{ATTEMPT_ID}",
        "test_case": f"/api/v1/test-cases/{TEST_CASE_ID}",
    }


async def test_baseline_commands_require_if_match(
    baseline_client: httpx.AsyncClient,
) -> None:
    response = await baseline_client.post(
        f"/api/v1/test-cases/{TEST_CASE_ID}/baseline-activations",
        json={
            "environment_id": str(ENVIRONMENT_ID),
            "baseline_id": str(BASELINE_ID),
            "reason": None,
        },
    )
    assert response.status_code == 428
    assert response.json()["code"] == "revision_precondition_required"


async def test_baseline_promotion_returns_result_and_etag(
    baseline_client: httpx.AsyncClient,
) -> None:
    response = await baseline_client.post(
        f"/api/v1/test-cases/{TEST_CASE_ID}/baselines",
        headers={"If-Match": '"scope"'},
        json={
            "environment_id": str(ENVIRONMENT_ID),
            "source_attempt_id": str(ATTEMPT_ID),
            "reason": None,
            "confirmation": "promote_selected_values",
            "acknowledged_warnings": [],
        },
    )
    assert response.status_code == 201
    assert response.headers["etag"] == '"scope-2"'
    assert response.json()["baseline"]["version"] == 1
