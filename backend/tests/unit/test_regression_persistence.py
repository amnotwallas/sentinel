from uuid import uuid4

import pytest

from sentinel.persistence.regression import (
    BoundedEvidence,
    PersistenceValidationError,
    bounded_evidence,
    validate_selected_values,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, BoundedEvidence(None, False)), ("x" * 4094, BoundedEvidence("x" * 4094, False))],
)
def test_bounded_evidence_keeps_complete_values(value: object, expected: BoundedEvidence) -> None:
    assert bounded_evidence(value) == expected


def test_bounded_evidence_omits_oversized_values_without_truncation() -> None:
    assert bounded_evidence("x" * 4097) == BoundedEvidence(None, True)


def test_selected_values_require_unique_canonical_rule_ids_and_bounded_values() -> None:
    rule_id = str(uuid4())
    validate_selected_values({"schema_version": 1, "values": [{"rule_id": rule_id, "value": 1}]})
    with pytest.raises(PersistenceValidationError):
        validate_selected_values(
            {
                "schema_version": 1,
                "values": [
                    {"rule_id": rule_id, "value": 1},
                    {"rule_id": rule_id, "value": 2},
                ],
            }
        )
    with pytest.raises(PersistenceValidationError):
        validate_selected_values(
            {"schema_version": 1, "values": [{"rule_id": rule_id, "value": "x" * 4097}]}
        )
