from copy import deepcopy
from decimal import Decimal
from typing import cast

import pytest

from sentinel.catalog.definitions import DefinitionValidationError
from sentinel.regression.policy import validate_regression_policy
from sentinel.security.definition_policy import validate_test_definition

PROJECT_ID = "00000000-0000-4000-8000-000000000001"
SELECTOR_ID = "00000000-0000-4000-8000-000000000101"
ASSERTION_ID = "00000000-0000-4000-8000-000000000102"


def valid_definition() -> dict[str, object]:
    return {
        "schema_version": 1,
        "request": {
            "method": "POST",
            "path": "/v1/items/{{variables.ITEM}}",
            "query": [{"name": "q", "value": "synthetic"}],
            "headers": [
                {"name": "Authorization", "value": {"$secret": "API_TOKEN"}},
                {"name": "Baggage", "value": "vendor=value"},
            ],
            "body": {
                "kind": "json",
                "value": {"amount": Decimal("1.0"), "token": {"$secret": "BODY_TOKEN"}},
            },
            "timeout_ms": 30000,
            "connect_timeout_ms": 5000,
            "read_timeout_ms": 10000,
            "follow_redirects": False,
            "max_redirects": 3,
            "verify_tls": True,
            "max_response_bytes": 262144,
        },
        "assertions": [
            {
                "id": ASSERTION_ID,
                "severity": "required",
                "kind": "status_code",
                "expected_codes": [200, 201],
            }
        ],
        "comparison_policy": {
            "schema_version": 1,
            "selectors": [
                {
                    "id": SELECTOR_ID,
                    "severity": "required",
                    "pointer": "/data",
                }
            ],
            "exact_text_body": False,
            "text_body_selector": None,
            "performance_threshold_ms": 1000,
        },
        "redaction": {"json_pointers": ["/secret"], "header_names": ["X-Api-Key"]},
        "allow_unsafe_replay": False,
    }


def test_valid_definition_materializes_defaults_and_fingerprints_policy() -> None:
    result = validate_test_definition(valid_definition())

    document = result.to_document()
    request = cast(dict[str, object], document["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    policy = cast(dict[str, object], document["comparison_policy"])
    selectors = cast(list[dict[str, object]], policy["selectors"])
    assert document["schema_version"] == 1
    assert headers[0] == {
        "name": "authorization",
        "value": {"$secret": "API_TOKEN"},
    }
    assert selectors[0]["normalizer"] == {
        "name": "none",
        "version": 1,
    }
    assert len(result.policy_fingerprint) == 64
    assert (
        result.policy_fingerprint == validate_test_definition(deepcopy(document)).policy_fingerprint
    )


def test_policy_fingerprint_is_order_independent_but_policy_changes_are_visible() -> None:
    first = valid_definition()
    second = deepcopy(first)
    first_policy = cast(dict[str, object], first["comparison_policy"])
    second["comparison_policy"] = {
        "performance_threshold_ms": 1000,
        "text_body_selector": None,
        "selectors": first_policy["selectors"],
        "exact_text_body": False,
        "schema_version": 1,
    }
    changed = deepcopy(second)
    changed_policy = cast(dict[str, object], changed["comparison_policy"])
    changed_policy["performance_threshold_ms"] = 1001

    assert (
        validate_test_definition(first).policy_fingerprint
        == validate_test_definition(second).policy_fingerprint
    )
    assert (
        validate_test_definition(first).policy_fingerprint
        != validate_test_definition(changed).policy_fingerprint
    )


def test_security_adapter_composes_the_regression_owned_policy() -> None:
    definition = valid_definition()

    regression = validate_regression_policy(
        definition["assertions"],
        definition["comparison_policy"],
        assertion_json_validator=lambda value: value,
        forbidden_literal_headers=frozenset(),
    )
    result = validate_test_definition(definition)
    document = result.to_document()

    assert document["assertions"] == regression.assertions
    assert document["comparison_policy"] == regression.comparison_policy
    assert regression.policy_fingerprint == (
        "4c5148c0484b67354d1ceafffd4f1b2842e418adc2195fcbcec6673ba3052c57"
    )
    assert result.policy_fingerprint == regression.policy_fingerprint


def test_security_adapter_rejects_credential_assertions_before_expected_value_parsing() -> None:
    definition = valid_definition()
    assertions = cast(list[dict[str, object]], definition["assertions"])
    assertions[0] = {
        "id": ASSERTION_ID,
        "severity": "required",
        "kind": "header_equals",
        "header_name": "Authorization",
        "expected": {"malformed": "synthetic"},
    }

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "credential_literal_forbidden"


def test_rule_ids_must_be_unique_across_assertions_and_selectors() -> None:
    definition = valid_definition()
    comparison = cast(dict[str, object], definition["comparison_policy"])
    selectors = cast(list[dict[str, object]], comparison["selectors"])
    selectors[0]["id"] = ASSERTION_ID

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "duplicate"


@pytest.mark.parametrize(
    ("kind", "field", "value"),
    [
        ("status_code", "expected", "unexpected"),
        ("header_present", "pointer", "/unexpected"),
        ("json_present", "header_name", "x-unexpected"),
        ("text_equals", "expected_codes", [200]),
    ],
)
def test_assertion_variants_reject_fields_from_other_variants(
    kind: str, field: str, value: object
) -> None:
    definition = valid_definition()
    assertions = cast(list[dict[str, object]], definition["assertions"])
    assertion = assertions[0]
    assertion.clear()
    assertion.update({"id": ASSERTION_ID, "severity": "required", "kind": kind})
    if kind == "status_code":
        assertion["expected_codes"] = [200]
    elif kind == "header_present":
        assertion["header_name"] = "x-synthetic"
    elif kind == "json_present":
        assertion["pointer"] = "/data"
    else:
        assertion["expected"] = "synthetic"
    assertion[field] = value

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "extra_field"


@pytest.mark.parametrize(
    ("location", "value"),
    [
        ("path", {"$secret": "API_TOKEN"}),
        ("query", [{"name": "token", "value": {"$secret": "API_TOKEN"}}]),
        ("body", {"kind": "text", "value": {"$secret": "API_TOKEN"}}),
    ],
)
def test_secret_references_are_restricted_to_headers_and_json_leaves(
    location: str, value: object
) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    if location == "path":
        request["path"] = value
    elif location == "query":
        request["query"] = value
    else:
        request["body"] = value

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code in {"secret_placement_forbidden", "invalid_secret_reference"}


@pytest.mark.parametrize(
    "header_name",
    ["Authorization", "PROXY-AUTHORIZATION", "Cookie", "Set-Cookie", "X-Api-Key"],
)
def test_credential_literals_are_rejected_without_echoing_the_value(header_name: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[0]["name"] = header_name
    headers[0]["value"] = "Bearer synthetic-canary"

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "credential_literal_forbidden"
    assert "synthetic-canary" not in str(caught.value)


@pytest.mark.parametrize("header_name", ["traceparent", "TraceState"])
def test_sentinel_trace_headers_are_rejected_case_insensitively(header_name: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers.append({"name": header_name, "value": "synthetic"})

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "trace_context_forbidden"


def test_secret_trace_headers_are_rejected_before_secret_resolution() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers.append({"name": "traceparent", "value": {"$secret": "TRACE_TOKEN"}})

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "trace_context_forbidden"


def test_secret_baggage_is_rejected_before_secret_resolution() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[1] = {"name": "baggage", "value": {"$secret": "BAGGAGE_TOKEN"}}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "trace_context_forbidden"


def test_sentinel_owned_baggage_is_rejected_but_unrelated_baggage_is_allowed() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[1] = {
        "name": "baggage",
        "value": "sentinel.execution.id=synthetic",
    }

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "trace_context_forbidden"


@pytest.mark.parametrize(
    "baggage",
    [
        "sentinel%2Eexecution%2Eid=synthetic",
        "SENTINEL%2EATTEMPT%2EID=synthetic",
        "vendor=%00",
        "vendor=%0A",
    ],
)
def test_baggage_security_checks_apply_after_one_percent_decode(baggage: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[1] = {"name": "baggage", "value": baggage}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "trace_context_forbidden"


@pytest.mark.parametrize("baggage", ["vendor=%", "vendor=%0", "vendor=%GG", "vendor%G0=value"])
def test_baggage_rejects_malformed_percent_encoding(baggage: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[1] = {"name": "baggage", "value": baggage}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "trace_context_forbidden"


def test_baggage_is_percent_decoded_exactly_once() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[1] = {
        "name": "baggage",
        "value": "sentinel%252Eexecution%252Eid=synthetic",
    }

    result = validate_test_definition(definition)

    result_request = cast(dict[str, object], result.to_document()["request"])
    result_headers = cast(list[dict[str, object]], result_request["headers"])
    assert result_headers[1]["value"] == "sentinel%252Eexecution%252Eid=synthetic"


def test_baggage_member_names_must_be_unique_after_one_percent_decode() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[1] = {"name": "baggage", "value": "vendor=one,v%65ndor=two"}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "trace_context_forbidden"


def test_baggage_accepts_valid_percent_encoded_unicode_value() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[1] = {"name": "baggage", "value": "vendor=caf%C3%A9"}

    document = validate_test_definition(definition).to_document()

    result_request = cast(dict[str, object], document["request"])
    result_headers = cast(list[dict[str, object]], result_request["headers"])
    assert result_headers[1]["value"] == "vendor=caf%C3%A9"


@pytest.mark.parametrize("baggage", ["vendor=has space", "vendor=value; property=has space"])
def test_baggage_rejects_values_outside_w3c_member_grammar(baggage: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[1] = {"name": "baggage", "value": baggage}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "trace_context_forbidden"


@pytest.mark.parametrize("baggage", ["vendor=", "vendor=has%20space", "vendor=value;property"])
def test_baggage_accepts_valid_empty_encoded_and_property_values(baggage: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    headers = cast(list[dict[str, object]], request["headers"])
    headers[1] = {"name": "baggage", "value": baggage}

    document = validate_test_definition(definition).to_document()

    result_request = cast(dict[str, object], document["request"])
    result_headers = cast(list[dict[str, object]], result_request["headers"])
    assert result_headers[1]["value"] == baggage


@pytest.mark.parametrize(
    "value",
    [
        10**37,
        Decimal("99999999999999999999999999999999999999"),
        Decimal("1e128"),
        Decimal("1e-128"),
        Decimal("0e-128"),
    ],
)
def test_json_numbers_accept_contract_boundaries(value: int | Decimal) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request["body"] = {"kind": "json", "value": {"number": value}}

    document = validate_test_definition(definition).to_document()

    result_request = cast(dict[str, object], document["request"])
    body = cast(dict[str, object], result_request["body"])
    body_value = cast(dict[str, object], body["value"])
    assert body_value["number"] == value


@pytest.mark.parametrize(
    "value",
    [
        10**38,
        Decimal("999999999999999999999999999999999999999"),
        Decimal("1e129"),
        Decimal("1e-129"),
        Decimal("0e-129"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_json_numbers_reject_precision_and_exponent_violations(value: int | Decimal) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request["body"] = {"kind": "json", "value": {"number": value}}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "value_invalid"


def test_json_numbers_reject_binary_float_representations() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request["body"] = {"kind": "json", "value": {"number": 1.0}}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "type_invalid"


def test_query_parameter_name_must_not_be_empty() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request["query"] = [{"name": "", "value": "synthetic"}]

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "limit_exceeded"


@pytest.mark.parametrize("kind", ["text", "json"])
def test_literal_non_template_braces_are_preserved_in_body_data(kind: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    value = "literal { brace } and {{not-a-variable-template}}"
    request["body"] = {"kind": kind, "value": value if kind == "text" else {"text": value}}

    document = validate_test_definition(definition).to_document()

    result_request = cast(dict[str, object], document["request"])
    body = cast(dict[str, object], result_request["body"])
    assert body["value"] == (value if kind == "text" else {"text": value})


@pytest.mark.parametrize("kind", ["text", "json"])
def test_malformed_variable_templates_are_rejected_in_body_data(kind: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    value = "{{variables.}}"
    request["body"] = {"kind": kind, "value": value if kind == "text" else {"text": value}}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "value_invalid"


def test_validated_definition_is_deeply_immutable_and_returns_independent_documents() -> None:
    result = validate_test_definition(valid_definition())
    original = result.to_document()
    fingerprint = result.policy_fingerprint

    exposed = result.to_document()
    exposed_request = cast(dict[str, object], exposed["request"])
    exposed_headers = cast(list[dict[str, object]], exposed_request["headers"])
    exposed_headers[0]["name"] = "mutated"

    internal_request = cast(dict[str, object], result.document["request"])
    with pytest.raises(TypeError):
        internal_request["path"] = "/mutated"

    assert result.to_document() == original
    assert result.policy_fingerprint == fingerprint
    assert validate_test_definition(result.to_document()).policy_fingerprint == fingerprint


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", 1),
        ("query", {}),
        ("headers", {}),
        ("timeout_ms", "30000"),
    ],
)
def test_incorrect_request_field_types_return_type_invalid(field: str, value: object) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request[field] = value

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "type_invalid"


@pytest.mark.parametrize(
    "case",
    [
        "definition_schema_version",
        "method",
        "body_kind",
        "assertion_codes",
        "normalizer_version",
        "comparison_schema_version",
        "redaction_schema_version",
    ],
)
def test_incorrect_definition_field_types_return_type_invalid(case: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    assertions = cast(list[dict[str, object]], definition["assertions"])
    comparison = cast(dict[str, object], definition["comparison_policy"])
    selectors = cast(list[dict[str, object]], comparison["selectors"])
    redaction = cast(dict[str, object], definition["redaction"])
    if case == "definition_schema_version":
        definition["schema_version"] = "1"
    elif case == "method":
        request["method"] = 1
    elif case == "body_kind":
        request["body"] = {"kind": 1, "value": "synthetic"}
    elif case == "assertion_codes":
        assertions[0]["expected_codes"] = {}
    elif case == "normalizer_version":
        selectors[0]["normalizer"] = {"name": "none", "version": "1"}
    elif case == "comparison_schema_version":
        comparison["schema_version"] = "1"
    else:
        redaction["schema_version"] = "1"

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "type_invalid"


def test_assertion_count_limit_returns_limit_exceeded() -> None:
    definition = valid_definition()
    assertions = cast(list[dict[str, object]], definition["assertions"])
    assertions[0]["expected_codes"] = list(range(100, 201))

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "limit_exceeded"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", "/" + "a" * 2048),
        ("query", [{"name": "q", "value": "v"}] * 129),
    ],
)
def test_request_size_violations_return_limit_exceeded(field: str, value: object) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request[field] = value

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "limit_exceeded"


@pytest.mark.parametrize(
    ("field", "value"),
    [("timeout_ms", 0), ("max_redirects", 4), ("max_response_bytes", 1_048_577)],
)
def test_numeric_bound_violations_return_limit_exceeded(field: str, value: int) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request[field] = value

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "limit_exceeded"


def test_json_nesting_limit_accepts_32_levels_and_rejects_33() -> None:
    accepted_value: object = "synthetic"
    for _ in range(32):
        accepted_value = [accepted_value]
    accepted = valid_definition()
    accepted_request = cast(dict[str, object], accepted["request"])
    accepted_request["body"] = {"kind": "json", "value": accepted_value}

    validate_test_definition(accepted)

    rejected_value: object = [accepted_value]
    rejected = valid_definition()
    rejected_request = cast(dict[str, object], rejected["request"])
    rejected_request["body"] = {"kind": "json", "value": rejected_value}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(rejected)

    assert caught.value.code == "limit_exceeded"


@pytest.mark.parametrize("invalid_text", ["\ud800", "\udfff"])
def test_unpaired_unicode_surrogates_return_stable_validation_error(invalid_text: str) -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request["body"] = {"kind": "json", "value": {"text": invalid_text}}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "value_invalid"


def test_unpaired_unicode_surrogates_in_object_keys_return_stable_validation_error() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request["body"] = {"kind": "json", "value": {"\ud800": "synthetic"}}

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "value_invalid"


def test_valid_unicode_is_preserved_without_normalization() -> None:
    definition = valid_definition()
    request = cast(dict[str, object], definition["request"])
    request["body"] = {"kind": "json", "value": {"text": "Cafe\u0301 \U0001f680"}}

    document = validate_test_definition(definition).to_document()

    result_request = cast(dict[str, object], document["request"])
    body = cast(dict[str, object], result_request["body"])
    body_value = cast(dict[str, object], body["value"])
    assert body_value["text"] == "Cafe\u0301 \U0001f680"


@pytest.mark.parametrize(
    "policy",
    [
        {"name": "none", "version": 2},
        {"name": "round_decimal", "version": 1, "scale": 2},
        {"name": "round_decimal", "version": 1, "scale": 2, "rounding": "half_up"},
    ],
)
def test_normalizer_requires_a_supported_versioned_shape(policy: dict[str, object]) -> None:
    definition = valid_definition()
    comparison = cast(dict[str, object], definition["comparison_policy"])
    selectors = cast(list[dict[str, object]], comparison["selectors"])
    selectors[0]["normalizer"] = policy

    with pytest.raises(DefinitionValidationError) as caught:
        validate_test_definition(definition)

    assert caught.value.code == "value_invalid"
