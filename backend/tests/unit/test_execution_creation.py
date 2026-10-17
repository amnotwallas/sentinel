from datetime import UTC, datetime
from uuid import UUID

from sentinel.api.executions import ExecutionCreate
from sentinel.execution.creation import (
    ExecutionCreateCommand,
    ExecutionItemRecord,
    ExecutionRecord,
    hash_idempotency_key,
    request_hash,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)
ENVIRONMENT_ID = UUID("00000000-0000-4000-8000-000000000001")
TEST_CASE_ID = UUID("00000000-0000-4000-8000-000000000002")


def test_request_hash_is_canonical_and_key_is_not_stored() -> None:
    first = request_hash(ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=TEST_CASE_ID))
    second = request_hash(
        ExecutionCreateCommand(environment_id=ENVIRONMENT_ID, test_case_id=TEST_CASE_ID)
    )
    assert first == second
    assert len(first) == 64
    assert hash_idempotency_key("synthetic-key") == hash_idempotency_key("synthetic-key")
    assert "synthetic-key" not in hash_idempotency_key("synthetic-key")


def test_completed_item_count_counts_terminal_items_not_verdicts() -> None:
    execution = ExecutionRecord(
        id=UUID("00000000-0000-4000-8000-000000000010"),
        project_id=UUID("00000000-0000-4000-8000-000000000011"),
        environment_id=ENVIRONMENT_ID,
        environment_revision_id=UUID("00000000-0000-4000-8000-000000000012"),
        source_type="suite",
        source_id=UUID("00000000-0000-4000-8000-000000000013"),
        source_revision_id=UUID("00000000-0000-4000-8000-000000000014"),
        status="queued",
        verdict=None,
        created_at=NOW,
        started_at=None,
        finished_at=None,
        items=(
            ExecutionItemRecord(
                id=UUID("00000000-0000-4000-8000-000000000015"),
                ordinal=0,
                test_case_id=TEST_CASE_ID,
                test_case_revision_id=UUID("00000000-0000-4000-8000-000000000016"),
                test_case_revision_version=1,
                status="pending",
                verdict=None,
                started_at=None,
                finished_at=None,
            ),
            ExecutionItemRecord(
                id=UUID("00000000-0000-4000-8000-000000000017"),
                ordinal=1,
                test_case_id=TEST_CASE_ID,
                test_case_revision_id=UUID("00000000-0000-4000-8000-000000000018"),
                test_case_revision_version=2,
                status="failed",
                verdict="not_evaluated",
                started_at=NOW,
                finished_at=NOW,
            ),
        ),
    )
    assert execution.completed_item_count == 1


def test_create_body_requires_exactly_one_source() -> None:
    assert (
        ExecutionCreate(environment_id=ENVIRONMENT_ID, test_case_id=TEST_CASE_ID).test_case_id
        == TEST_CASE_ID
    )
