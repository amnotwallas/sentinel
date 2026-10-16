from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sentinel.catalog.environments import EnvironmentService
from sentinel.catalog.projects import ProjectService
from sentinel.catalog.suites import SuiteService
from sentinel.catalog.test_cases import TestCaseService as CaseService
from sentinel.persistence.catalog.unit_of_work import PostgresCatalogUnitOfWork
from sentinel.persistence.models import (
    ChangeEventRow,
    EnvironmentRevisionRow,
    EnvironmentRow,
    ProjectRow,
    SuiteRevisionItemRow,
    SuiteRevisionRow,
    SuiteRow,
    TestCaseRevisionRow,
    TestCaseRow,
)
from sentinel.security.definition_policy import (
    validate_environment_document,
    validate_test_definition,
)

pytestmark = pytest.mark.integration

NOW = datetime(2030, 1, 1, tzinfo=UTC)
PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")
ENVIRONMENT_ID = UUID("10000000-0000-4000-8000-000000000010")
ENVIRONMENT_REVISION_1_ID = UUID("10000000-0000-4000-8000-000000000011")
ENVIRONMENT_REVISION_2_ID = UUID("10000000-0000-4000-8000-000000000012")
TEST_CASE_1_ID = UUID("10000000-0000-4000-8000-000000000020")
TEST_CASE_1_REVISION_1_ID = UUID("10000000-0000-4000-8000-000000000021")
TEST_CASE_1_REVISION_2_ID = UUID("10000000-0000-4000-8000-000000000022")
TEST_CASE_2_ID = UUID("10000000-0000-4000-8000-000000000030")
TEST_CASE_2_REVISION_1_ID = UUID("10000000-0000-4000-8000-000000000031")
SUITE_ID = UUID("10000000-0000-4000-8000-000000000040")
SUITE_REVISION_1_ID = UUID("10000000-0000-4000-8000-000000000041")
SUITE_REVISION_2_ID = UUID("10000000-0000-4000-8000-000000000042")


def _definition(path: str) -> dict[str, object]:
    return {
        "request": {
            "method": "GET",
            "path": path,
            "headers": [
                {"name": "Authorization", "value": {"$secret": "API_TOKEN"}},
            ],
        },
        "assertions": [],
        "comparison_policy": {},
        "redaction": {},
        "allow_unsafe_replay": False,
    }


def test_complete_catalog_journey_preserves_history_pins_and_secret_references(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)

    def unit_of_work() -> PostgresCatalogUnitOfWork:
        return PostgresCatalogUnitOfWork(factory)

    secret_canary = "must-not-cross-the-catalog-boundary"
    monkeypatch.setenv("SENTINEL_SECRET_API_TOKEN", secret_canary)

    project = ProjectService(unit_of_work, ids=lambda: PROJECT_ID, clock=lambda: NOW).create(
        "Acceptance"
    )
    environment_ids = iter(
        [
            ENVIRONMENT_ID,
            ENVIRONMENT_REVISION_1_ID,
            UUID("10000000-0000-4000-8000-000000000013"),
            ENVIRONMENT_REVISION_2_ID,
            UUID("10000000-0000-4000-8000-000000000014"),
        ]
    )
    environments = EnvironmentService(
        unit_of_work,
        ids=lambda: next(environment_ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
    )
    created_environment = environments.create(
        project.id,
        name="Local",
        definition={
            "base_url": "https://api.example",
            "secret_references": [{"$secret": "API_TOKEN"}],
        },
    )
    updated_environment = environments.update(
        created_environment.id,
        expected_state_version=1,
        name="Primary",
        definition={
            "base_url": "https://api.example/v2",
            "secret_references": [{"$secret": "API_TOKEN"}],
        },
    )

    test_case_ids = iter(
        [
            TEST_CASE_1_ID,
            TEST_CASE_1_REVISION_1_ID,
            UUID("10000000-0000-4000-8000-000000000023"),
            TEST_CASE_2_ID,
            TEST_CASE_2_REVISION_1_ID,
            UUID("10000000-0000-4000-8000-000000000032"),
            TEST_CASE_1_REVISION_2_ID,
            UUID("10000000-0000-4000-8000-000000000024"),
        ]
    )
    test_cases = CaseService(
        unit_of_work,
        ids=lambda: next(test_case_ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )
    first_case = test_cases.create(
        project.id,
        name="First",
        definition=_definition("/v1"),
        unsafe_replay_acknowledgement=None,
    )
    second_case = test_cases.create(
        project.id,
        name="Second",
        definition=_definition("/second"),
        unsafe_replay_acknowledgement=None,
    )

    suite_ids = iter(
        [
            SUITE_ID,
            SUITE_REVISION_1_ID,
            UUID("10000000-0000-4000-8000-000000000043"),
            SUITE_REVISION_2_ID,
            UUID("10000000-0000-4000-8000-000000000044"),
        ]
    )
    suites = SuiteService(unit_of_work, ids=lambda: next(suite_ids), clock=lambda: NOW)
    original_suite = suites.create(
        project.id,
        name="Ordered",
        test_case_revision_ids=[
            first_case.active_revision_id,
            second_case.active_revision_id,
        ],
    )
    revised_case = test_cases.update(
        first_case.id,
        expected_state_version=1,
        name="First",
        definition=_definition("/v2"),
        unsafe_replay_acknowledgement=None,
    )

    still_pinned = suites.get(original_suite.id)
    assert [item.test_case_revision_id for item in still_pinned.active_revision.items] == [
        TEST_CASE_1_REVISION_1_ID,
        TEST_CASE_2_REVISION_1_ID,
    ]
    revised_suite = suites.update(
        original_suite.id,
        expected_state_version=1,
        name="Reordered",
        test_case_revision_ids=[
            second_case.active_revision_id,
            revised_case.active_revision_id,
        ],
    )

    assert updated_environment.active_revision.version == 2
    assert first_case.active_revision.definition.policy_fingerprint == (
        revised_case.active_revision.definition.policy_fingerprint
    )
    assert [item.ordinal for item in revised_suite.active_revision.items] == [0, 1]
    assert [item.test_case_revision_id for item in revised_suite.active_revision.items] == [
        TEST_CASE_2_REVISION_1_ID,
        TEST_CASE_1_REVISION_2_ID,
    ]

    with Session(engine) as session:
        counts = {
            ProjectRow: 1,
            EnvironmentRow: 1,
            EnvironmentRevisionRow: 2,
            TestCaseRow: 2,
            TestCaseRevisionRow: 3,
            SuiteRow: 1,
            SuiteRevisionRow: 2,
            SuiteRevisionItemRow: 4,
            ChangeEventRow: 7,
        }
        for table, expected in counts.items():
            assert session.scalar(select(func.count()).select_from(table)) == expected

        suite_history = session.scalars(
            select(SuiteRevisionRow).order_by(SuiteRevisionRow.version)
        ).all()
        original_items = session.scalars(
            select(SuiteRevisionItemRow)
            .where(SuiteRevisionItemRow.suite_revision_id == SUITE_REVISION_1_ID)
            .order_by(SuiteRevisionItemRow.ordinal)
        ).all()
        assert [revision.version for revision in suite_history] == [1, 2]
        assert [item.test_case_revision_id for item in original_items] == [
            TEST_CASE_1_REVISION_1_ID,
            TEST_CASE_2_REVISION_1_ID,
        ]

        persisted_documents = [
            row.definition for row in session.scalars(select(EnvironmentRevisionRow)).all()
        ] + [row.definition for row in session.scalars(select(TestCaseRevisionRow)).all()]
        event_summaries = [row.summary for row in session.scalars(select(ChangeEventRow)).all()]
        assert secret_canary not in str(persisted_documents)
        assert secret_canary not in str(event_summaries)
        assert {row.kind for row in session.scalars(select(ChangeEventRow)).all()} == {
            "environment_created",
            "environment_updated",
            "test_case_created",
            "test_case_revised",
            "suite_created",
            "suite_revised",
        }
