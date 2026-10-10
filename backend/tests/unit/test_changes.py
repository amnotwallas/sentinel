from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from sentinel.catalog.changes import (
    ChangeEvent,
    ChangeEventKind,
    ChangeField,
    ChangeSubjectType,
    ChangeSummary,
)
from sentinel.persistence.catalog.changes import SqlAlchemyChangeRepository
from sentinel.persistence.models import ChangeEventRow


def test_change_summary_accepts_only_fixed_safe_field_names() -> None:
    summary = ChangeSummary.from_values(["name", "target_policy"])

    assert summary.changed_fields == (ChangeField.NAME, ChangeField.TARGET_POLICY)

    with pytest.raises(ValueError):
        ChangeSummary.from_values(["canary-secret-value"])


def test_change_summary_rejects_duplicates_and_excessive_fields() -> None:
    with pytest.raises(ValueError):
        ChangeSummary.from_values(["name", "name"])

    with pytest.raises(ValueError):
        ChangeSummary.from_values(["name"] * 17)


def test_change_event_contains_references_and_safe_summary_only() -> None:
    event = ChangeEvent(
        id=UUID("00000000-0000-4000-8000-000000000010"),
        project_id=UUID("00000000-0000-4000-8000-000000000001"),
        kind=ChangeEventKind.ENVIRONMENT_CREATED,
        subject_type=ChangeSubjectType.ENVIRONMENT,
        subject_id=UUID("00000000-0000-4000-8000-000000000020"),
        before_ref=None,
        after_ref=UUID("00000000-0000-4000-8000-000000000021"),
        summary=ChangeSummary.from_values(["name", "base_url"]),
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )

    assert event.summary.to_document() == {"changed_fields": ["name", "base_url"]}


def test_change_repository_maps_only_the_safe_summary_document() -> None:
    event = ChangeEvent(
        id=UUID("00000000-0000-4000-8000-000000000010"),
        project_id=UUID("00000000-0000-4000-8000-000000000001"),
        kind=ChangeEventKind.ENVIRONMENT_CREATED,
        subject_type=ChangeSubjectType.ENVIRONMENT,
        subject_id=UUID("00000000-0000-4000-8000-000000000020"),
        before_ref=None,
        after_ref=UUID("00000000-0000-4000-8000-000000000021"),
        summary=ChangeSummary.from_values(["name"]),
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    session = Session()

    SqlAlchemyChangeRepository(session).add(event)

    row = next(iter(session.new))
    assert isinstance(row, ChangeEventRow)
    assert row.summary == {"changed_fields": ["name"]}
    assert row.kind == "environment_created"
    assert row.subject_type == "environment"
