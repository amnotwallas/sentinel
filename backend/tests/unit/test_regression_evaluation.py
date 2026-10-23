from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from sentinel.catalog.definitions import DefinitionValidationError
from sentinel.regression.evaluator import (
    BaselineCandidate,
    EvaluationDefinition,
    EvaluationObservation,
    EvaluationOutcome,
    RedactionPolicy,
    Verdict,
    evaluate,
)
from sentinel.regression.policy import validate_regression_policy

RULE_IDS = [f"00000000-0000-4000-8000-{number:012d}" for number in range(1, 400)]


def make_definition(
    *,
    assertions: list[dict[str, object]] | None = None,
    selectors: list[dict[str, object]] | None = None,
    exact_text_body: bool = False,
    text_body_selector: dict[str, object] | None = None,
    performance_threshold_ms: int | None = None,
    redaction_pointers: tuple[str, ...] = (),
    redaction_headers: tuple[str, ...] = (),
) -> EvaluationDefinition:
    policy = validate_regression_policy(
        assertions or [],
        {
            "schema_version": 1,
            "selectors": selectors or [],
            "exact_text_body": exact_text_body,
            "text_body_selector": text_body_selector,
            "performance_threshold_ms": performance_threshold_ms,
        },
        assertion_json_validator=lambda value: value,
        forbidden_literal_headers=frozenset(),
    )
    return EvaluationDefinition(
        policy=policy,
        redaction=RedactionPolicy(
            json_pointers=redaction_pointers,
            header_names=frozenset(redaction_headers),
        ),
    )


def assertion(kind: str, *, severity: str = "required", **fields: object) -> dict[str, object]:
    return {
        "id": RULE_IDS.pop(0),
        "severity": severity,
        "kind": kind,
        **fields,
    }


def selector(
    *, severity: str = "required", pointer: str = "/value", **normalizer: object
) -> dict[str, object]:
    return {
        "id": RULE_IDS.pop(0),
        "severity": severity,
        "pointer": pointer,
        "normalizer": {"name": "none", "version": 1, **normalizer},
    }


def selector_id(definition: EvaluationDefinition) -> str:
    selectors = cast(list[dict[str, object]], definition.policy.comparison_policy["selectors"])
    return cast(str, selectors[0]["id"])


def observation(
    *,
    status_code: int = 200,
    headers: tuple[tuple[str, str], ...] = (),
    body_kind: str | None = "json",
    body_content: object | None = None,
    truncated: bool = False,
    redaction_unavailable: bool = False,
    expired: bool = False,
) -> EvaluationObservation:
    return EvaluationObservation(
        status_code=status_code,
        headers=headers,
        body_kind=body_kind,
        body_content=body_content,
        truncated=truncated,
        redaction_unavailable=redaction_unavailable,
        expired=expired,
    )


def test_equivalent_inputs_produce_identical_ordered_results() -> None:
    definition = make_definition(
        assertions=[assertion("json_equals", pointer="/object", expected={"a": 1, "b": 2})],
        selectors=[selector(pointer="/value")],
        performance_threshold_ms=100,
    )
    first = evaluate(
        definition,
        observation(body_content={"object": {"b": 2, "a": 1}, "value": Decimal("2.0")}),
        baseline=BaselineCandidate(
            policy_fingerprint=definition.policy.policy_fingerprint,
            values={selector_id(definition): Decimal("2")},
        ),
        duration_ms=100,
    )
    second = evaluate(
        definition,
        observation(body_content={"value": Decimal("2.0"), "object": {"a": 1, "b": 2}}),
        baseline=BaselineCandidate(
            policy_fingerprint=definition.policy.policy_fingerprint,
            values={selector_id(definition): Decimal("2")},
        ),
        duration_ms=100,
    )

    assert first == second
    assert [record.ordinal for record in first.evaluations] == [0, 1, 2]


def test_json_presence_distinguishes_missing_from_explicit_null() -> None:
    definition = make_definition(
        assertions=[
            assertion("json_present", pointer="/present"),
            assertion("json_absent", pointer="/missing"),
            assertion("json_type", pointer="/present", expected_type="null"),
        ]
    )

    result = evaluate(definition, observation(body_content={"present": None}))

    assert result.verdict is Verdict.PASSED
    assert [record.outcome for record in result.evaluations] == [
        EvaluationOutcome.PASSED,
        EvaluationOutcome.PASSED,
        EvaluationOutcome.PASSED,
    ]
    assert result.evaluations[0].actual is None
    assert result.evaluations[0].evidence_omitted is False


@pytest.mark.parametrize(
    ("value", "expected_verdict", "message"),
    [
        (Decimal("1.005"), Verdict.PASSED, "selected_value_match"),
        (Decimal("1.015"), Verdict.FUNCTIONAL_REGRESSION, "selected_value_mismatch"),
    ],
)
def test_round_decimal_uses_half_even_without_binary_float(
    value: Decimal, expected_verdict: Verdict, message: str
) -> None:
    definition = make_definition(
        selectors=[selector(pointer="/value", name="round_decimal", scale=2, rounding="half_even")]
    )
    rule_id = selector_id(definition)

    result = evaluate(
        definition,
        observation(body_content={"value": value}),
        baseline=BaselineCandidate(
            policy_fingerprint=definition.policy.policy_fingerprint,
            values={rule_id: Decimal("1.00")},
        ),
    )

    assert result.verdict is expected_verdict
    assert result.evaluations[0].message_code.value == message


def test_json_pointer_escaping_resolves_slash_and_tilde() -> None:
    definition = make_definition(
        assertions=[
            assertion(
                "json_equals",
                pointer="/a~1b/~0key",
                expected="matched",
            )
        ]
    )

    result = evaluate(definition, observation(body_content={"a/b": {"~key": "matched"}}))

    assert result.verdict is Verdict.PASSED


def test_invalid_json_pointer_is_rejected_before_evaluation() -> None:
    with pytest.raises(DefinitionValidationError) as caught:
        make_definition(assertions=[assertion("json_present", pointer="/bad~2escape")])

    assert caught.value.code == "invalid_json_pointer"


def test_header_names_are_case_insensitive_and_duplicate_values_are_not_collapsed() -> None:
    definition = make_definition(
        assertions=[
            assertion("header_present", header_name="X-Thing"),
            assertion("header_equals", header_name="X-Single", expected="ok"),
            assertion("header_equals", header_name="X-Thing", expected="first"),
        ]
    )

    result = evaluate(
        definition,
        observation(headers=(("X-Thing", "first"), ("x-thing", "second"), ("X-Single", "ok"))),
    )

    assert result.verdict is Verdict.FUNCTIONAL_REGRESSION
    assert [record.message_code.value for record in result.evaluations] == [
        "assertion_passed",
        "assertion_passed",
        "header_mismatch",
    ]
    assert result.evaluations[2].actual == ["first", "second"]


def test_required_failure_precedes_advisory_change() -> None:
    definition = make_definition(
        assertions=[
            assertion("status_code", expected_codes=[201]),
            assertion("header_equals", severity="advisory", header_name="x-change", expected="new"),
        ]
    )

    result = evaluate(definition, observation(status_code=500, headers=(("x-change", "old"),)))

    assert result.verdict is Verdict.FUNCTIONAL_REGRESSION
    assert [record.outcome for record in result.evaluations] == [
        EvaluationOutcome.FAILED,
        EvaluationOutcome.FAILED,
    ]


def test_advisory_only_difference_is_observed_change() -> None:
    definition = make_definition(
        assertions=[assertion("status_code", severity="advisory", expected_codes=[201])]
    )

    result = evaluate(definition, observation(status_code=500))

    assert result.verdict is Verdict.OBSERVED_CHANGE


def test_required_unavailable_content_is_inconclusive() -> None:
    definition = make_definition(
        assertions=[assertion("json_equals", pointer="/value", expected="x")]
    )

    result = evaluate(
        definition,
        observation(body_content={"value": "x"}, truncated=True),
    )

    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.evaluations[0].outcome is EvaluationOutcome.UNEVALUABLE
    assert result.evaluations[0].message_code.value == "content_truncated"


def test_redaction_overlap_and_placeholder_are_never_compared() -> None:
    definition = make_definition(
        assertions=[assertion("json_equals", pointer="/secret/value", expected="[REDACTED]")],
        selectors=[selector(pointer="/value")],
        redaction_pointers=("/secret",),
    )
    rule_id = selector_id(definition)

    result = evaluate(
        definition,
        observation(body_content={"secret": {"value": "[REDACTED]"}, "value": "[REDACTED]"}),
        baseline=BaselineCandidate(
            policy_fingerprint=definition.policy.policy_fingerprint,
            values={rule_id: "[REDACTED]"},
        ),
    )

    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.evaluations[0].message_code.value == "content_redacted"
    assert result.evaluations[1].message_code.value == "content_redacted"
    assert result.evaluations[0].evidence_omitted is True
    assert result.evaluations[1].evidence_omitted is True


def test_configured_sensitive_header_is_unevaluable() -> None:
    definition = make_definition(
        assertions=[assertion("header_present", header_name="X-Synthetic-Secret")],
        redaction_headers=("x-synthetic-secret",),
    )

    result = evaluate(
        definition,
        observation(headers=(("X-Synthetic-Secret", "[REDACTED]"),)),
    )

    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.evaluations[0].message_code.value == "content_redacted"


def test_header_redaction_placeholder_fragment_is_not_compared() -> None:
    definition = make_definition(
        assertions=[
            assertion(
                "header_equals",
                header_name="X-Trace",
                expected="prefix[REDACTED]suffix",
            )
        ]
    )

    result = evaluate(
        definition,
        observation(headers=(("X-Trace", "prefix[REDACTED]suffix"),)),
    )

    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.evaluations[0].message_code.value == "content_redacted"


def test_text_redaction_placeholder_fragment_is_not_compared() -> None:
    definition = make_definition(
        assertions=[
            assertion("text_equals", expected="prefix[REDACTED]suffix"),
        ]
    )

    result = evaluate(
        definition,
        observation(
            body_kind="text",
            body_content="prefix[REDACTED]suffix",
        ),
    )

    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.evaluations[0].message_code.value == "content_redacted"


def test_safe_sibling_remains_usable_when_another_json_value_is_redacted() -> None:
    definition = make_definition(
        selectors=[selector(pointer="/safe")],
        redaction_pointers=("/secret",),
    )
    rule_id = selector_id(definition)

    result = evaluate(
        definition,
        observation(body_content={"safe": "ok", "secret": "[REDACTED]"}),
        baseline=BaselineCandidate(
            policy_fingerprint=definition.policy.policy_fingerprint,
            values={rule_id: "ok"},
        ),
    )

    assert result.verdict is Verdict.PASSED
    assert result.evaluations[0].outcome is EvaluationOutcome.PASSED


def test_missing_and_incompatible_baselines_have_distinct_non_comparison_results() -> None:
    definition = make_definition(selectors=[selector(pointer="/value")])
    rule_id = selector_id(definition)

    missing = evaluate(definition, observation(body_content={"value": 1}))
    incompatible = evaluate(
        definition,
        observation(body_content={"value": 2}),
        baseline=BaselineCandidate(policy_fingerprint="f" * 64, values={rule_id: 1}),
    )

    assert missing.baseline_state.value == "missing"
    assert missing.verdict is Verdict.BASELINE_REQUIRED
    assert missing.evaluations[0].outcome is EvaluationOutcome.NOT_EVALUATED
    assert missing.evaluations[0].message_code.value == "baseline_missing"
    assert incompatible.baseline_state.value == "incompatible"
    assert incompatible.verdict is Verdict.BASELINE_REQUIRED
    assert incompatible.evaluations[0].message_code.value == "baseline_incompatible"


def test_advisory_only_missing_baseline_does_not_create_observed_change() -> None:
    definition = make_definition(selectors=[selector(severity="advisory", pointer="/value")])

    result = evaluate(definition, observation(body_content={"value": 1}))

    assert result.verdict is Verdict.PASSED
    assert result.evaluations[0].outcome is EvaluationOutcome.NOT_EVALUATED
    assert result.evaluations[0].message_code.value == "baseline_missing"


@pytest.mark.parametrize("severity", ["required", "advisory"])
def test_invalid_normalizer_input_has_severity_specific_effect(severity: str) -> None:
    definition = make_definition(
        selectors=[selector(severity=severity, pointer="/value", name="sort_scalar_array")]
    )

    result = evaluate(
        definition,
        observation(body_content={"value": [1, "2"]}),
        baseline=BaselineCandidate(
            policy_fingerprint=definition.policy.policy_fingerprint,
            values={selector_id(definition): [1, "2"]},
        ),
    )

    assert result.evaluations[0].outcome is EvaluationOutcome.UNEVALUABLE
    assert result.evaluations[0].message_code.value == "normalizer_input_invalid"
    assert result.verdict is (Verdict.INCONCLUSIVE if severity == "required" else Verdict.PASSED)


def test_invalid_json_assertion_differs_from_selector_parse_failure() -> None:
    assertion_definition = make_definition(
        assertions=[assertion("json_equals", pointer="/value", expected=1)]
    )
    selector_definition = make_definition(selectors=[selector(pointer="/value")])

    assertion_result = evaluate(
        assertion_definition,
        observation(body_kind="json", body_content="not-json"),
    )
    selector_result = evaluate(
        selector_definition,
        observation(body_kind="json", body_content="not-json"),
    )

    assert assertion_result.verdict is Verdict.FUNCTIONAL_REGRESSION
    assert assertion_result.evaluations[0].message_code.value == "invalid_json"
    assert selector_result.verdict is Verdict.INCONCLUSIVE
    assert selector_result.evaluations[0].outcome is EvaluationOutcome.UNEVALUABLE
    assert selector_result.evaluations[0].message_code.value == "invalid_json"


def test_performance_threshold_is_an_advisory_warning() -> None:
    definition = make_definition(performance_threshold_ms=100)

    result = evaluate(definition, observation(body_content=None, body_kind=None), duration_ms=101)

    assert result.verdict is Verdict.PERFORMANCE_WARNING
    assert result.evaluations[0].kind.value == "performance"
    assert result.evaluations[0].severity.value == "advisory"


def test_evidence_above_cap_is_omitted_without_changing_comparison() -> None:
    expected = "e" * 5000
    actual = "a" * 5000
    definition = make_definition(
        assertions=[assertion("text_equals", severity="advisory", expected=expected)]
    )

    result = evaluate(definition, observation(body_kind="text", body_content=actual))

    record = result.evaluations[0]
    assert result.verdict is Verdict.OBSERVED_CHANGE
    assert record.message_code.value == "text_mismatch"
    assert record.expected is None
    assert record.actual is None
    assert record.evidence_omitted is True


def test_selected_value_above_cap_blocks_promotion() -> None:
    definition = make_definition(selectors=[selector(pointer="/value")])
    rule_id = selector_id(definition)
    value = "v" * 5000

    result = evaluate(
        definition,
        observation(body_content={"value": value}),
        baseline=BaselineCandidate(
            policy_fingerprint=definition.policy.policy_fingerprint,
            values={rule_id: "different"},
        ),
    )

    assert result.evaluations[0].evidence_omitted is True
    assert "selected_value_too_large" in result.promotion.ineligibility_codes


def test_maximum_evaluation_order_is_128_assertions_128_selectors_then_performance() -> None:
    assertions: list[dict[str, object]] = [
        {
            "id": RULE_IDS.pop(0),
            "severity": "required",
            "kind": "status_code",
            "expected_codes": [200],
        }
        for _ in range(128)
    ]
    selectors = [selector(pointer=f"/value{index}") for index in range(128)]
    definition = make_definition(
        assertions=assertions, selectors=selectors, performance_threshold_ms=100
    )
    baseline_values = {
        cast(str, item["id"]): index
        for index, item in enumerate(
            cast(list[dict[str, object]], definition.policy.comparison_policy["selectors"])
        )
    }

    result = evaluate(
        definition,
        observation(body_content={f"value{index}": index for index in range(128)}),
        baseline=BaselineCandidate(
            policy_fingerprint=definition.policy.policy_fingerprint,
            values=baseline_values,
        ),
        duration_ms=100,
    )

    assert len(result.evaluations) == 257
    assert result.evaluations[0].ordinal == 0
    assert result.evaluations[127].ordinal == 127
    assert result.evaluations[128].ordinal == 128
    assert result.evaluations[-1].ordinal == 256
    assert result.evaluations[-1].kind.value == "performance"


def test_unsupported_normalizer_is_rejected_as_malformed_policy_input() -> None:
    with pytest.raises(DefinitionValidationError) as caught:
        make_definition(selectors=[selector(pointer="/value", name="unsupported")])

    assert caught.value.code == "value_invalid"
