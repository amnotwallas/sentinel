import json
import re
from collections.abc import Callable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sentinel.catalog.definitions import DefinitionValidationError

_HEADER = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_POINTER = re.compile(r"^(?:/(?:[^~]|~[01])*)*$")


@dataclass(frozen=True, slots=True)
class ValidatedRegressionPolicy:
    assertions: list[dict[str, object]]
    comparison_policy: dict[str, object]
    policy_fingerprint: str


def _definition_object(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise DefinitionValidationError("type_invalid")
    if set(value) - fields:
        raise DefinitionValidationError("extra_field")
    return {key: item for key, item in value.items()}


def _definition_string(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise DefinitionValidationError("type_invalid")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise DefinitionValidationError("value_invalid")
    if len(value.encode("utf-8")) > maximum:
        raise DefinitionValidationError("limit_exceeded")
    return value


def _definition_integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise DefinitionValidationError("type_invalid")
    if not minimum <= value <= maximum:
        raise DefinitionValidationError("limit_exceeded")
    return value


def _definition_version(value: object) -> int:
    if type(value) is not int:
        raise DefinitionValidationError("type_invalid")
    if value != 1:
        raise DefinitionValidationError("value_invalid")
    return value


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise DefinitionValidationError("invalid_uuid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise DefinitionValidationError("invalid_uuid") from None
    if str(parsed) != value:
        raise DefinitionValidationError("invalid_uuid")
    return value


def _header_name(value: object) -> str:
    name = _definition_string(value, maximum=128)
    if not _HEADER.fullmatch(name):
        raise DefinitionValidationError("value_invalid")
    return name.lower()


def _json_pointer(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > 1024
        or not _POINTER.fullmatch(value)
    ):
        raise DefinitionValidationError("invalid_json_pointer")
    return value


def _assertions(
    value: object,
    *,
    assertion_json_validator: Callable[[object], object],
    forbidden_literal_headers: AbstractSet[str],
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise DefinitionValidationError("type_invalid")
    if len(value) > 128:
        raise DefinitionValidationError("limit_exceeded")
    result: list[dict[str, object]] = []
    ids: set[str] = set()
    for item in value:
        candidate = _definition_object(
            item,
            {
                "id",
                "severity",
                "kind",
                "expected_codes",
                "header_name",
                "expected",
                "pointer",
                "expected_type",
            },
        )
        kind = candidate.get("kind")
        if not isinstance(kind, str):
            raise DefinitionValidationError("type_invalid")
        variant_fields = {
            "status_code": {"expected_codes"},
            "header_present": {"header_name"},
            "header_equals": {"header_name", "expected"},
            "json_present": {"pointer"},
            "json_absent": {"pointer"},
            "json_type": {"pointer", "expected_type"},
            "json_equals": {"pointer", "expected"},
            "text_equals": {"expected"},
        }
        if kind not in variant_fields:
            raise DefinitionValidationError("value_invalid")
        data = _definition_object(item, {"id", "severity", "kind"} | variant_fields[kind])
        identifier = _uuid(data.get("id"))
        if identifier in ids:
            raise DefinitionValidationError("duplicate")
        ids.add(identifier)
        severity = data.get("severity")
        if severity not in {"required", "advisory"}:
            raise DefinitionValidationError("value_invalid")
        normalized: dict[str, object] = {"id": identifier, "severity": severity, "kind": kind}
        if kind == "status_code":
            codes = data.get("expected_codes")
            if not isinstance(codes, list):
                raise DefinitionValidationError("type_invalid")
            if len(codes) > 100:
                raise DefinitionValidationError("limit_exceeded")
            if not codes:
                raise DefinitionValidationError("value_invalid")
            if any(type(code) is not int for code in codes):
                raise DefinitionValidationError("type_invalid")
            if any(not 100 <= code <= 599 for code in codes):
                raise DefinitionValidationError("value_invalid")
            if len(set(codes)) != len(codes):
                raise DefinitionValidationError("duplicate")
            normalized["expected_codes"] = list(codes)
        elif kind in {"header_present", "header_equals"}:
            header_name = _header_name(data.get("header_name"))
            if kind == "header_equals" and header_name in forbidden_literal_headers:
                raise DefinitionValidationError("credential_literal_forbidden")
            normalized["header_name"] = header_name
            if kind == "header_equals":
                normalized["expected"] = _definition_string(data.get("expected"), maximum=8192)
        elif kind in {"json_present", "json_absent", "json_type", "json_equals"}:
            normalized["pointer"] = _json_pointer(data.get("pointer"))
            if kind == "json_type":
                if data.get("expected_type") not in {
                    "null",
                    "boolean",
                    "number",
                    "string",
                    "array",
                    "object",
                }:
                    raise DefinitionValidationError("value_invalid")
                normalized["expected_type"] = data["expected_type"]
            elif kind == "json_equals":
                normalized["expected"] = assertion_json_validator(data.get("expected"))
        elif kind == "text_equals":
            normalized["expected"] = _definition_string(data.get("expected"), maximum=131_072)
        else:
            raise DefinitionValidationError("value_invalid")
        result.append(normalized)
    return result


def _normalizer(value: object) -> dict[str, object]:
    data = _definition_object(value, {"name", "version", "scale", "rounding"})
    name = data.get("name")
    if not isinstance(name, str):
        raise DefinitionValidationError("type_invalid")
    _definition_version(data.get("version"))
    if name == "none" or name == "sort_scalar_array":
        if set(data) != {"name", "version"}:
            raise DefinitionValidationError("extra_field")
        return {"name": name, "version": 1}
    if name == "round_decimal":
        if (
            set(data) != {"name", "version", "scale", "rounding"}
            or data.get("rounding") != "half_even"
        ):
            raise DefinitionValidationError("value_invalid")
        return {
            "name": name,
            "version": 1,
            "scale": _definition_integer(data.get("scale"), minimum=0, maximum=12),
            "rounding": "half_even",
        }
    raise DefinitionValidationError("value_invalid")


def _comparison_policy(value: object) -> dict[str, object]:
    data = _definition_object(
        value,
        {
            "schema_version",
            "selectors",
            "exact_text_body",
            "text_body_selector",
            "performance_threshold_ms",
        },
    )
    _definition_version(data.get("schema_version", 1))
    raw_selectors = data.get("selectors", [])
    if not isinstance(raw_selectors, list):
        raise DefinitionValidationError("type_invalid")
    if len(raw_selectors) > 128:
        raise DefinitionValidationError("limit_exceeded")
    selectors: list[dict[str, object]] = []
    selector_ids: set[str] = set()
    selector_pointers: set[str] = set()
    for item in raw_selectors:
        selector = _definition_object(item, {"id", "severity", "pointer", "normalizer"})
        identifier = _uuid(selector.get("id"))
        pointer = _json_pointer(selector.get("pointer"))
        if identifier in selector_ids or pointer in selector_pointers:
            raise DefinitionValidationError("duplicate")
        selector_ids.add(identifier)
        selector_pointers.add(pointer)
        if selector.get("severity") not in {"required", "advisory"}:
            raise DefinitionValidationError("value_invalid")
        selectors.append(
            {
                "id": identifier,
                "severity": selector["severity"],
                "pointer": pointer,
                "normalizer": _normalizer(
                    selector.get("normalizer", {"name": "none", "version": 1})
                ),
            }
        )
    exact_text_body = data.get("exact_text_body", False)
    if type(exact_text_body) is not bool:
        raise DefinitionValidationError("type_invalid")
    text_selector = data.get("text_body_selector")
    if exact_text_body:
        if selectors or not isinstance(text_selector, Mapping):
            raise DefinitionValidationError("incompatible_fields")
        text_data = _definition_object(text_selector, {"id", "severity"})
        text_selector_normalized: object = {
            "id": _uuid(text_data.get("id")),
            "severity": text_data.get("severity"),
        }
        if text_data.get("severity") not in {"required", "advisory"}:
            raise DefinitionValidationError("value_invalid")
    else:
        if text_selector is not None:
            raise DefinitionValidationError("incompatible_fields")
        text_selector_normalized = None
    threshold = data.get("performance_threshold_ms")
    if threshold is not None:
        threshold = _definition_integer(threshold, minimum=1, maximum=120_000)
    return {
        "schema_version": 1,
        "selectors": selectors,
        "exact_text_body": exact_text_body,
        "text_body_selector": text_selector_normalized,
        "performance_threshold_ms": threshold,
    }


def canonical_json(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise DefinitionValidationError("value_invalid")
        if value == 0:
            return "0"
        plain = format(value, "f")
        if "." in plain:
            plain = plain.rstrip("0").rstrip(".")
        return plain
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise DefinitionValidationError("value_invalid")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    if isinstance(value, Mapping):
        entries = sorted(value.items(), key=lambda item: item[0])
        return (
            "{"
            + ",".join(
                canonical_json(str(key)) + ":" + canonical_json(item) for key, item in entries
            )
            + "}"
        )
    raise DefinitionValidationError("type_invalid")


def validate_regression_policy(
    assertions_value: object,
    comparison_policy_value: object,
    *,
    assertion_json_validator: Callable[[object], object],
    forbidden_literal_headers: AbstractSet[str],
) -> ValidatedRegressionPolicy:
    assertions = _assertions(
        assertions_value,
        assertion_json_validator=assertion_json_validator,
        forbidden_literal_headers=forbidden_literal_headers,
    )
    comparison_policy = _comparison_policy(comparison_policy_value)
    rule_ids = {str(assertion["id"]) for assertion in assertions}
    selectors = comparison_policy["selectors"]
    if isinstance(selectors, list):
        for selector in selectors:
            if isinstance(selector, Mapping) and str(selector["id"]) in rule_ids:
                raise DefinitionValidationError("duplicate")
            if isinstance(selector, Mapping):
                rule_ids.add(str(selector["id"]))
    text_selector = comparison_policy["text_body_selector"]
    if isinstance(text_selector, Mapping) and str(text_selector["id"]) in rule_ids:
        raise DefinitionValidationError("duplicate")
    policy_fingerprint = sha256(canonical_json(comparison_policy).encode("utf-8")).hexdigest()
    return ValidatedRegressionPolicy(
        assertions=assertions,
        comparison_policy=comparison_policy,
        policy_fingerprint=policy_fingerprint,
    )
