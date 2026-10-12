from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ChangeEventKind(StrEnum):
    ENVIRONMENT_CREATED = "environment_created"
    ENVIRONMENT_UPDATED = "environment_updated"
    TEST_CASE_CREATED = "test_case_created"
    TEST_CASE_REVISED = "test_case_revised"
    SUITE_CREATED = "suite_created"
    SUITE_REVISED = "suite_revised"
    BASELINE_ACTIVATED = "baseline_activated"


class ChangeSubjectType(StrEnum):
    ENVIRONMENT = "environment"
    TEST_CASE = "test_case"
    SUITE = "suite"
    BASELINE = "baseline"


class ChangeField(StrEnum):
    NAME = "name"
    BASE_URL = "base_url"
    VARIABLES = "variables"
    SECRET_REFERENCES = "secret_references"
    TARGET_POLICY = "target_policy"
    REQUEST = "request"
    ASSERTIONS = "assertions"
    COMPARISON_POLICY = "comparison_policy"
    REDACTION = "redaction"
    ALLOW_UNSAFE_REPLAY = "allow_unsafe_replay"
    SUITE_ITEMS = "suite_items"
    BASELINE_ACTIVATION = "baseline_activation"


@dataclass(frozen=True, slots=True)
class ChangeSummary:
    changed_fields: tuple[ChangeField, ...]

    @classmethod
    def from_values(cls, values: list[str]) -> "ChangeSummary":
        if len(values) > 16:
            raise ValueError("change summary exceeds field limit")
        try:
            fields = tuple(ChangeField(value) for value in values)
        except ValueError:
            raise ValueError("change summary contains an unsupported field") from None
        if len(set(fields)) != len(fields):
            raise ValueError("change summary contains duplicate fields")
        return cls(fields)

    def to_document(self) -> dict[str, list[str]]:
        return {"changed_fields": [field.value for field in self.changed_fields]}


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    id: UUID
    project_id: UUID
    kind: ChangeEventKind
    subject_type: ChangeSubjectType
    subject_id: UUID
    before_ref: UUID | None
    after_ref: UUID | None
    summary: ChangeSummary
    created_at: datetime
