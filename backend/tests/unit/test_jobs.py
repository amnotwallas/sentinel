import pytest

from sentinel.execution.domain import InvalidTransition, JobState, validate_transition


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (JobState.SUCCEEDED, JobState.LEASED),
        (JobState.DEAD, JobState.PENDING),
        (JobState.PENDING, JobState.SUCCEEDED),
        (JobState.LEASED, JobState.LEASED),
    ],
)
def test_invalid_transitions_are_rejected(source: JobState, target: JobState) -> None:
    with pytest.raises(InvalidTransition):
        validate_transition(source, target)


def test_lease_renewal_requires_explicit_renewal_operation() -> None:
    validate_transition(JobState.LEASED, JobState.LEASED, renewal=True)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (JobState.PENDING, JobState.LEASED),
        (JobState.LEASED, JobState.SUCCEEDED),
        (JobState.LEASED, JobState.PENDING),
        (JobState.LEASED, JobState.DEAD),
        (JobState.PENDING, JobState.DEAD),
    ],
)
def test_supported_transitions(source: JobState, target: JobState) -> None:
    validate_transition(source, target)
