import pytest

from sentinel.execution.domain import (
    AttemptInvalidTransition,
    AttemptState,
    validate_attempt_transition,
)


def test_all_frozen_attempt_transitions_are_accepted() -> None:
    allowed = {
        AttemptState.PREPARED: (AttemptState.FAILED, AttemptState.DISPATCHING),
        AttemptState.DISPATCHING: (
            AttemptState.RESPONSE_RECEIVED,
            AttemptState.TRANSPORT_FAILED,
            AttemptState.REPLAY_SCHEDULED,
            AttemptState.INDETERMINATE,
        ),
        AttemptState.RESPONSE_RECEIVED: (AttemptState.EVALUATED, AttemptState.FAILED),
    }
    for source, targets in allowed.items():
        for target in targets:
            validate_attempt_transition(source, target)


def test_unlisted_attempt_transitions_are_rejected() -> None:
    for source in AttemptState:
        for target in AttemptState:
            if (source, target) in {
                (AttemptState.PREPARED, AttemptState.FAILED),
                (AttemptState.PREPARED, AttemptState.DISPATCHING),
                (AttemptState.DISPATCHING, AttemptState.RESPONSE_RECEIVED),
                (AttemptState.DISPATCHING, AttemptState.TRANSPORT_FAILED),
                (AttemptState.DISPATCHING, AttemptState.REPLAY_SCHEDULED),
                (AttemptState.DISPATCHING, AttemptState.INDETERMINATE),
                (AttemptState.RESPONSE_RECEIVED, AttemptState.EVALUATED),
                (AttemptState.RESPONSE_RECEIVED, AttemptState.FAILED),
            }:
                continue
            with pytest.raises(AttemptInvalidTransition):
                validate_attempt_transition(source, target)
