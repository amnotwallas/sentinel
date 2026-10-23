"""Pure, deterministic evaluation of one redacted response observation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from enum import StrEnum
from types import MappingProxyType
from typing import Final, cast

from sentinel.regression.policy import ValidatedRegressionPolicy, canonical_json

_REDACTED: Final = "[REDACTED]"
_MAX_EVIDENCE_BYTES: Final = 4096
_MAX_BASELINE_DOCUMENT_BYTES: Final = 1_048_576
_FIXED_SENSITIVE_HEADERS: Final = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-api-key-secret",
        "location",
    }
)
_MISSING = object()


class EvaluationKind(StrEnum):
    ASSERTION = "assertion"
    BASELINE_SELECTOR = "baseline_selector"
    PERFORMANCE = "performance"


class Severity(StrEnum):
    REQUIRED = "required"
    ADVISORY = "advisory"


class EvaluationOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNEVALUABLE = "unevaluable"
    NOT_EVALUATED = "not_evaluated"


class Verdict(StrEnum):
    PASSED = "passed"
    FUNCTIONAL_REGRESSION = "functional_regression"
    PERFORMANCE_WARNING = "performance_warning"
    OBSERVED_CHANGE = "observed_change"
    INCONCLUSIVE = "inconclusive"
    BASELINE_REQUIRED = "baseline_required"
    NOT_EVALUATED = "not_evaluated"


class BaselineState(StrEnum):
    NOT_REQUESTED = "not_requested"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"
    COMPATIBLE = "compatible"


class MessageCode(StrEnum):
    ASSERTION_PASSED = "assertion_passed"
    SELECTED_VALUE_MATCH = "selected_value_match"
    DURATION_WITHIN_THRESHOLD = "duration_within_threshold"
    STATUS_MISMATCH = "status_mismatch"
    HEADER_MISSING = "header_missing"
    HEADER_MISMATCH = "header_mismatch"
    JSON_MISSING = "json_missing"
    JSON_UNEXPECTED = "json_unexpected"
    JSON_TYPE_MISMATCH = "json_type_mismatch"
    JSON_VALUE_MISMATCH = "json_value_mismatch"
    TEXT_MISMATCH = "text_mismatch"
    INVALID_JSON = "invalid_json"
    SELECTED_VALUE_MISMATCH = "selected_value_mismatch"
    NORMALIZER_INPUT_INVALID = "normalizer_input_invalid"
    BASELINE_MISSING = "baseline_missing"
    BASELINE_INCOMPATIBLE = "baseline_incompatible"
    CONTENT_MISSING = "content_missing"
    CONTENT_EXPIRED = "content_expired"
    CONTENT_TRUNCATED = "content_truncated"
    CONTENT_REDACTED = "content_redacted"
    DURATION_EXCEEDED = "duration_exceeded"
    NOT_EVALUATED = "not_evaluated"


class EvaluationInputError(ValueError):
    """A malformed already-normalized evaluator input."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    json_pointers: tuple[str, ...] = ()
    header_names: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "json_pointers",
            tuple(sorted(self.json_pointers)),
        )
        object.__setattr__(
            self,
            "header_names",
            frozenset(name.lower() for name in self.header_names),
        )


@dataclass(frozen=True, slots=True)
class EvaluationDefinition:
    policy: ValidatedRegressionPolicy
    redaction: RedactionPolicy = RedactionPolicy()


@dataclass(frozen=True, slots=True)
class EvaluationObservation:
    status_code: int | None
    headers: tuple[tuple[str, str], ...] = ()
    body_kind: str | None = None
    body_content: object | None = None
    truncated: bool = False
    redaction_unavailable: bool = False
    expired: bool = False

    def __post_init__(self) -> None:
        normalized: list[tuple[str, str]] = []
        for name, value in self.headers:
            if not isinstance(name, str) or not isinstance(value, str):
                raise EvaluationInputError("malformed_observation")
            normalized.append((name.lower(), value))
        object.__setattr__(self, "headers", tuple(normalized))
        if self.status_code is not None and (
            type(self.status_code) is not int or not 100 <= self.status_code <= 599
        ):
            raise EvaluationInputError("malformed_observation")
        if self.body_kind not in {None, "json", "text", "bytes", "omitted"}:
            raise EvaluationInputError("malformed_observation")
        if any(
            type(flag) is not bool
            for flag in (self.truncated, self.redaction_unavailable, self.expired)
        ):
            raise EvaluationInputError("malformed_observation")


@dataclass(frozen=True, slots=True)
class BaselineCandidate:
    policy_fingerprint: str
    values: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    ordinal: int
    kind: EvaluationKind
    rule_id: str | None
    severity: Severity
    outcome: EvaluationOutcome
    message_code: MessageCode
    expected: object | None
    actual: object | None
    evidence_omitted: bool


@dataclass(frozen=True, slots=True)
class PromotionAssessment:
    eligible: bool
    warning_codes: tuple[str, ...]
    ineligibility_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    evaluations: tuple[EvaluationRecord, ...]
    verdict: Verdict
    baseline_state: BaselineState
    promotion: PromotionAssessment


@dataclass(frozen=True, slots=True)
class _BodyResult:
    available: bool
    value: object | None
    message: MessageCode | None


class _Evaluator:
    def __init__(
        self,
        definition: EvaluationDefinition,
        observation: EvaluationObservation,
        baseline: BaselineCandidate | None,
        duration_ms: int | None,
    ) -> None:
        self.definition = definition
        self.observation = observation
        self.baseline = baseline
        self.duration_ms = duration_ms
        self.records: list[EvaluationRecord] = []
        self.inconclusive = False
        self.baseline_required = False
        self.functional_regression = False
        self.performance_warning = False
        self.observed_change = False
        self.selected_value_unavailable = False
        self.selected_value_too_large = False
        self.selected_value_redacted = False
        self._selected_values: list[dict[str, object]] = []

        self._selectors = self._json_selectors()
        self._text_selector = self._text_selector_data()
        self.baseline_state = self._baseline_state()

    def run(self) -> EvaluationResult:
        self._evaluate_assertions()
        self._evaluate_selectors()
        self._evaluate_performance()
        verdict = self._verdict()
        return EvaluationResult(
            evaluations=tuple(self.records),
            verdict=verdict,
            baseline_state=self.baseline_state,
            promotion=self._promotion(verdict),
        )

    def _json_selectors(self) -> tuple[Mapping[str, object], ...]:
        policy = self.definition.policy.comparison_policy
        raw = policy.get("selectors")
        if not isinstance(raw, list):
            raise EvaluationInputError("malformed_policy")
        selectors: list[Mapping[str, object]] = []
        for value in raw:
            if not isinstance(value, Mapping):
                raise EvaluationInputError("malformed_policy")
            selectors.append(value)
        return tuple(selectors)

    def _text_selector_data(self) -> Mapping[str, object] | None:
        value = self.definition.policy.comparison_policy.get("text_body_selector")
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise EvaluationInputError("malformed_policy")
        return value

    def _baseline_state(self) -> BaselineState:
        if not self._selectors and self._text_selector is None:
            return BaselineState.NOT_REQUESTED
        if self.baseline is None:
            return BaselineState.MISSING
        if self.baseline.policy_fingerprint != self.definition.policy.policy_fingerprint:
            return BaselineState.INCOMPATIBLE
        rule_ids = [self._rule_id(selector) for selector in self._selectors]
        if self._text_selector is not None:
            rule_ids.append(self._rule_id(self._text_selector))
        if any(rule_id not in self.baseline.values for rule_id in rule_ids):
            return BaselineState.MISSING
        return BaselineState.COMPATIBLE

    def _evaluate_assertions(self) -> None:
        for raw in self.definition.policy.assertions:
            if not isinstance(raw, Mapping):
                raise EvaluationInputError("malformed_policy")
            self._evaluate_assertion(raw)

    def _evaluate_assertion(self, rule: Mapping[str, object]) -> None:
        kind = self._string(rule, "kind")
        rule_id = self._rule_id(rule)
        severity = self._severity(rule)

        if kind in {"header_present", "header_equals"}:
            self._evaluate_header_assertion(rule, kind, rule_id, severity)
            return
        if kind in {"json_present", "json_absent", "json_type", "json_equals"}:
            self._evaluate_json_assertion(rule, kind, rule_id, severity)
            return
        if kind == "status_code":
            expected = rule.get("expected_codes")
            if not isinstance(expected, list) or any(type(code) is not int for code in expected):
                raise EvaluationInputError("malformed_policy")
            if self.observation.status_code is None:
                self._unavailable(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.CONTENT_MISSING,
                    expected=expected,
                )
            elif self.observation.status_code in expected:
                self._record(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    EvaluationOutcome.PASSED,
                    MessageCode.ASSERTION_PASSED,
                    expected=expected,
                    actual=self.observation.status_code,
                )
            else:
                self._failed(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.STATUS_MISMATCH,
                    expected=expected,
                    actual=self.observation.status_code,
                )
            return
        if kind == "text_equals":
            self._evaluate_text_assertion(rule, rule_id, severity)
            return
        raise EvaluationInputError("unsupported_assertion")

    def _evaluate_header_assertion(
        self,
        rule: Mapping[str, object],
        kind: str,
        rule_id: str,
        severity: Severity,
    ) -> None:
        header_name = self._string(rule, "header_name").lower()
        if self._sensitive_header(header_name):
            self._unavailable(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                MessageCode.CONTENT_REDACTED,
            )
            return
        values = [value for name, value in self.observation.headers if name == header_name]
        if kind == "header_present":
            if not values:
                self._failed(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.HEADER_MISSING,
                    actual=_MISSING,
                )
            elif any(_contains_redacted(value) for value in values):
                self._unavailable(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.CONTENT_REDACTED,
                )
            else:
                self._record(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    EvaluationOutcome.PASSED,
                    MessageCode.ASSERTION_PASSED,
                    actual=values,
                )
            return

        expected = rule.get("expected")
        if not isinstance(expected, str):
            raise EvaluationInputError("malformed_policy")
        if _contains_redacted(expected):
            self._unavailable(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                MessageCode.CONTENT_REDACTED,
            )
        elif not values:
            self._failed(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                MessageCode.HEADER_MISSING,
                expected=expected,
                actual=_MISSING,
            )
        elif len(values) != 1 or _contains_redacted(values[0]):
            if any(_contains_redacted(value) for value in values):
                self._unavailable(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.CONTENT_REDACTED,
                    expected=expected,
                )
            else:
                self._failed(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.HEADER_MISMATCH,
                    expected=expected,
                    actual=values,
                )
        elif values[0] == expected:
            self._record(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                EvaluationOutcome.PASSED,
                MessageCode.ASSERTION_PASSED,
                expected=expected,
                actual=values[0],
            )
        else:
            self._failed(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                MessageCode.HEADER_MISMATCH,
                expected=expected,
                actual=values[0],
            )

    def _evaluate_json_assertion(
        self,
        rule: Mapping[str, object],
        kind: str,
        rule_id: str,
        severity: Severity,
    ) -> None:
        pointer = self._string(rule, "pointer")
        if self._redaction_overlaps(pointer):
            self._unavailable(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                MessageCode.CONTENT_REDACTED,
            )
            return
        body = self._json_body()
        if not body.available:
            if body.message is MessageCode.INVALID_JSON:
                self._failed(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.INVALID_JSON,
                )
                return
            self._unavailable(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                cast(MessageCode, body.message),
            )
            return
        found, actual = _resolve_pointer(body.value, pointer)
        if kind == "json_present":
            if found and not _contains_redacted(actual):
                self._record(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    EvaluationOutcome.PASSED,
                    MessageCode.ASSERTION_PASSED,
                    actual=actual,
                )
            elif found:
                self._unavailable(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.CONTENT_REDACTED,
                )
            else:
                self._failed(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.JSON_MISSING,
                    actual=_MISSING,
                )
        elif kind == "json_absent":
            if found:
                if _contains_redacted(actual):
                    self._unavailable(
                        EvaluationKind.ASSERTION,
                        rule_id,
                        severity,
                        MessageCode.CONTENT_REDACTED,
                    )
                else:
                    self._failed(
                        EvaluationKind.ASSERTION,
                        rule_id,
                        severity,
                        MessageCode.JSON_UNEXPECTED,
                        actual=actual,
                    )
            else:
                self._record(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    EvaluationOutcome.PASSED,
                    MessageCode.ASSERTION_PASSED,
                    actual=_MISSING,
                )
        elif not found:
            self._failed(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                MessageCode.JSON_MISSING,
                expected=rule.get("expected", rule.get("expected_type")),
                actual=_MISSING,
            )
        elif _contains_redacted(actual) or _contains_redacted(rule.get("expected")):
            self._unavailable(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                MessageCode.CONTENT_REDACTED,
            )
        elif kind == "json_type":
            expected_type = self._string(rule, "expected_type")
            actual_type = _json_type(actual)
            if actual_type == expected_type:
                self._record(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    EvaluationOutcome.PASSED,
                    MessageCode.ASSERTION_PASSED,
                    expected=expected_type,
                    actual=actual_type,
                )
            else:
                self._failed(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.JSON_TYPE_MISMATCH,
                    expected=expected_type,
                    actual=actual_type,
                )
        else:
            expected = rule.get("expected")
            if _json_equal(actual, expected):
                self._record(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    EvaluationOutcome.PASSED,
                    MessageCode.ASSERTION_PASSED,
                    expected=expected,
                    actual=actual,
                )
            else:
                self._failed(
                    EvaluationKind.ASSERTION,
                    rule_id,
                    severity,
                    MessageCode.JSON_VALUE_MISMATCH,
                    expected=expected,
                    actual=actual,
                )

    def _evaluate_text_assertion(
        self, rule: Mapping[str, object], rule_id: str, severity: Severity
    ) -> None:
        expected = rule.get("expected")
        if not isinstance(expected, str):
            raise EvaluationInputError("malformed_policy")
        body = self._text_body()
        if body.message is not None:
            self._unavailable(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                body.message,
                expected=expected,
            )
        elif _contains_redacted(body.value) or _contains_redacted(expected):
            self._unavailable(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                MessageCode.CONTENT_REDACTED,
                expected=expected,
            )
        elif body.value == expected:
            self._record(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                EvaluationOutcome.PASSED,
                MessageCode.ASSERTION_PASSED,
                expected=expected,
                actual=body.value,
            )
        else:
            self._failed(
                EvaluationKind.ASSERTION,
                rule_id,
                severity,
                MessageCode.TEXT_MISMATCH,
                expected=expected,
                actual=body.value,
            )

    def _evaluate_selectors(self) -> None:
        for selector in self._selectors:
            self._evaluate_selector(selector, is_text=False)
        if self._text_selector is not None:
            self._evaluate_selector(self._text_selector, is_text=True)

    def _evaluate_selector(self, selector: Mapping[str, object], *, is_text: bool) -> None:
        rule_id = self._rule_id(selector)
        severity = self._severity(selector)
        if not is_text and self._redaction_overlaps(self._string(selector, "pointer")):
            self.selected_value_unavailable = True
            self.selected_value_redacted = True
            self._unavailable(
                EvaluationKind.BASELINE_SELECTOR,
                rule_id,
                severity,
                MessageCode.CONTENT_REDACTED,
            )
            return

        body = self._text_body() if is_text else self._json_body()
        if not body.available:
            self.selected_value_unavailable = True
            self._unavailable(
                EvaluationKind.BASELINE_SELECTOR,
                rule_id,
                severity,
                cast(MessageCode, body.message),
            )
            return
        if is_text:
            found = True
            selected = body.value
        else:
            found, selected = _resolve_pointer(body.value, self._string(selector, "pointer"))
        if not found:
            self.selected_value_unavailable = True
            self._unavailable(
                EvaluationKind.BASELINE_SELECTOR,
                rule_id,
                severity,
                MessageCode.CONTENT_MISSING,
            )
            return
        if _contains_redacted(selected):
            self.selected_value_unavailable = True
            self.selected_value_redacted = True
            self._unavailable(
                EvaluationKind.BASELINE_SELECTOR,
                rule_id,
                severity,
                MessageCode.CONTENT_REDACTED,
            )
            return

        normalized = selected
        if not is_text:
            normalized, normalizer_error = _normalize_selector_value(
                selected, selector.get("normalizer")
            )
            if normalizer_error:
                self.selected_value_unavailable = True
                self._unavailable(
                    EvaluationKind.BASELINE_SELECTOR,
                    rule_id,
                    severity,
                    MessageCode.NORMALIZER_INPUT_INVALID,
                    actual=selected,
                )
                return
        if _encoded_size(normalized) > _MAX_EVIDENCE_BYTES:
            self.selected_value_too_large = True
        self._selected_values.append({"rule_id": rule_id, "value": normalized})
        if (
            _encoded_size({"schema_version": 1, "values": self._selected_values})
            > _MAX_BASELINE_DOCUMENT_BYTES
        ):
            self.selected_value_too_large = True

        if self.baseline_state is not BaselineState.COMPATIBLE:
            message = (
                MessageCode.BASELINE_MISSING
                if self.baseline_state is BaselineState.MISSING
                else MessageCode.BASELINE_INCOMPATIBLE
            )
            self._record(
                EvaluationKind.BASELINE_SELECTOR,
                rule_id,
                severity,
                EvaluationOutcome.NOT_EVALUATED,
                message,
                expected=_MISSING,
                actual=normalized,
            )
            if severity is Severity.REQUIRED:
                self.baseline_required = True
            return

        assert self.baseline is not None
        expected = self.baseline.values[rule_id]
        if _contains_redacted(expected):
            self.selected_value_unavailable = True
            self.selected_value_redacted = True
            self._unavailable(
                EvaluationKind.BASELINE_SELECTOR,
                rule_id,
                severity,
                MessageCode.CONTENT_REDACTED,
            )
        elif _json_equal(normalized, expected):
            self._record(
                EvaluationKind.BASELINE_SELECTOR,
                rule_id,
                severity,
                EvaluationOutcome.PASSED,
                MessageCode.SELECTED_VALUE_MATCH,
                expected=expected,
                actual=normalized,
            )
        else:
            self._failed(
                EvaluationKind.BASELINE_SELECTOR,
                rule_id,
                severity,
                MessageCode.SELECTED_VALUE_MISMATCH,
                expected=expected,
                actual=normalized,
            )

    def _evaluate_performance(self) -> None:
        threshold = self.definition.policy.comparison_policy.get("performance_threshold_ms")
        if threshold is None:
            return
        if type(threshold) is not int or threshold < 1:
            raise EvaluationInputError("malformed_policy")
        if self.duration_ms is None:
            self._record(
                EvaluationKind.PERFORMANCE,
                None,
                Severity.ADVISORY,
                EvaluationOutcome.NOT_EVALUATED,
                MessageCode.NOT_EVALUATED,
                expected=threshold,
                actual=_MISSING,
            )
        elif type(self.duration_ms) is not int or self.duration_ms < 0:
            raise EvaluationInputError("malformed_duration")
        elif self.duration_ms <= threshold:
            self._record(
                EvaluationKind.PERFORMANCE,
                None,
                Severity.ADVISORY,
                EvaluationOutcome.PASSED,
                MessageCode.DURATION_WITHIN_THRESHOLD,
                expected=threshold,
                actual=self.duration_ms,
            )
        else:
            self.performance_warning = True
            self._record(
                EvaluationKind.PERFORMANCE,
                None,
                Severity.ADVISORY,
                EvaluationOutcome.FAILED,
                MessageCode.DURATION_EXCEEDED,
                expected=threshold,
                actual=self.duration_ms,
            )

    def _json_body(self) -> _BodyResult:
        unavailable = self._body_unavailable()
        if unavailable is not None:
            return _BodyResult(False, None, unavailable)
        if self.observation.body_kind is None or self.observation.body_kind == "omitted":
            return _BodyResult(False, None, MessageCode.CONTENT_MISSING)
        if self.observation.body_kind != "json":
            return _BodyResult(False, None, MessageCode.INVALID_JSON)
        value = self.observation.body_content
        if isinstance(value, str):
            try:
                value = json.loads(value, parse_float=Decimal, parse_int=Decimal)
            except (TypeError, ValueError):
                return _BodyResult(False, None, MessageCode.INVALID_JSON)
        if not _is_supported_json(value):
            return _BodyResult(False, None, MessageCode.INVALID_JSON)
        return _BodyResult(True, value, None)

    def _text_body(self) -> _BodyResult:
        unavailable = self._body_unavailable()
        if unavailable is not None:
            return _BodyResult(False, None, unavailable)
        if self.observation.body_kind != "text":
            return _BodyResult(False, None, MessageCode.CONTENT_MISSING)
        if not isinstance(self.observation.body_content, str):
            return _BodyResult(False, None, MessageCode.CONTENT_MISSING)
        return _BodyResult(True, self.observation.body_content, None)

    def _body_unavailable(self) -> MessageCode | None:
        if self.observation.expired:
            return MessageCode.CONTENT_EXPIRED
        if self.observation.redaction_unavailable:
            return MessageCode.CONTENT_REDACTED
        if self.observation.truncated:
            return MessageCode.CONTENT_TRUNCATED
        return None

    def _sensitive_header(self, name: str) -> bool:
        return name in _FIXED_SENSITIVE_HEADERS or name in self.definition.redaction.header_names

    def _redaction_overlaps(self, pointer: str) -> bool:
        return any(
            _pointers_overlap(pointer, configured)
            for configured in self.definition.redaction.json_pointers
        )

    def _record(
        self,
        kind: EvaluationKind,
        rule_id: str | None,
        severity: Severity,
        outcome: EvaluationOutcome,
        message_code: MessageCode,
        *,
        expected: object = _MISSING,
        actual: object = _MISSING,
        force_omit: bool = False,
    ) -> None:
        if expected is _MISSING:
            expected_value, expected_omitted = None, False
        else:
            expected_value, expected_omitted = _evidence(expected)
        actual_value, actual_omitted = _evidence(actual)
        if force_omit:
            expected_value = None
            actual_value = None
            expected_omitted = True
            actual_omitted = True
        self.records.append(
            EvaluationRecord(
                ordinal=len(self.records),
                kind=kind,
                rule_id=rule_id,
                severity=severity,
                outcome=outcome,
                message_code=message_code,
                expected=expected_value,
                actual=actual_value,
                evidence_omitted=actual_omitted or expected_omitted,
            )
        )

    def _failed(
        self,
        kind: EvaluationKind,
        rule_id: str | None,
        severity: Severity,
        message_code: MessageCode,
        *,
        expected: object = _MISSING,
        actual: object = _MISSING,
    ) -> None:
        if kind is not EvaluationKind.PERFORMANCE:
            if severity is Severity.REQUIRED:
                self.functional_regression = True
            else:
                self.observed_change = True
        self._record(
            kind,
            rule_id,
            severity,
            EvaluationOutcome.FAILED,
            message_code,
            expected=expected,
            actual=actual,
        )

    def _unavailable(
        self,
        kind: EvaluationKind,
        rule_id: str | None,
        severity: Severity,
        message_code: MessageCode,
        *,
        expected: object = _MISSING,
        actual: object = _MISSING,
    ) -> None:
        if severity is Severity.REQUIRED:
            self.inconclusive = True
        self._record(
            kind,
            rule_id,
            severity,
            EvaluationOutcome.UNEVALUABLE,
            message_code,
            expected=expected,
            actual=actual,
            force_omit=message_code is MessageCode.CONTENT_REDACTED,
        )

    def _verdict(self) -> Verdict:
        if self.inconclusive:
            return Verdict.INCONCLUSIVE
        if self.baseline_required:
            return Verdict.BASELINE_REQUIRED
        if self.functional_regression:
            return Verdict.FUNCTIONAL_REGRESSION
        if self.performance_warning:
            return Verdict.PERFORMANCE_WARNING
        if self.observed_change:
            return Verdict.OBSERVED_CHANGE
        if not self.records and self.observation.status_code is None:
            return Verdict.NOT_EVALUATED
        return Verdict.PASSED

    def _promotion(self, verdict: Verdict) -> PromotionAssessment:
        warnings: list[str] = []
        if self.baseline_state is BaselineState.MISSING:
            warnings.append("missing_baseline")
        elif self.baseline_state is BaselineState.INCOMPATIBLE:
            warnings.append("incompatible_baseline")
        if self.observed_change:
            warnings.append("observed_change")
        if self.performance_warning:
            warnings.append("performance_warning")

        ineligibility: list[str] = []
        if not self._selectors and self._text_selector is None:
            ineligibility.append("no_selectors")
        if self.observation.status_code is None:
            ineligibility.append("attempt_not_evaluated")
        if self.functional_regression:
            ineligibility.append("required_functional_check_failed")
        if self.inconclusive:
            ineligibility.append("evaluation_inconclusive")
        if self.selected_value_unavailable:
            ineligibility.append("selected_value_unavailable")
        if self.selected_value_too_large:
            ineligibility.append("selected_value_too_large")
        eligible = (
            bool(self._selectors or self._text_selector)
            and not ineligibility
            and verdict
            in {
                Verdict.PASSED,
                Verdict.OBSERVED_CHANGE,
                Verdict.PERFORMANCE_WARNING,
                Verdict.BASELINE_REQUIRED,
            }
        )
        return PromotionAssessment(eligible, tuple(warnings), tuple(ineligibility))

    @staticmethod
    def _string(value: Mapping[str, object], key: str) -> str:
        result = value.get(key)
        if not isinstance(result, str):
            raise EvaluationInputError("malformed_policy")
        return result

    @staticmethod
    def _rule_id(value: Mapping[str, object]) -> str:
        result = value.get("id")
        if not isinstance(result, str):
            raise EvaluationInputError("malformed_policy")
        return result

    @staticmethod
    def _severity(value: Mapping[str, object]) -> Severity:
        result = value.get("severity")
        if not isinstance(result, str):
            raise EvaluationInputError("malformed_policy")
        try:
            return Severity(result)
        except ValueError:
            raise EvaluationInputError("malformed_policy") from None


def evaluate(
    definition: EvaluationDefinition,
    observation: EvaluationObservation,
    *,
    baseline: BaselineCandidate | None = None,
    duration_ms: int | None = None,
) -> EvaluationResult:
    """Evaluate one immutable redacted observation without performing I/O."""

    return _Evaluator(definition, observation, baseline, duration_ms).run()


def _normalize_selector_value(value: object, normalizer_value: object) -> tuple[object, bool]:
    if not isinstance(normalizer_value, Mapping):
        return value, True
    name = normalizer_value.get("name")
    if name == "none":
        return (value, False) if _is_supported_json(value) else (value, True)
    if name == "sort_scalar_array":
        if not isinstance(value, list):
            return value, True
        if not value:
            return [], False
        if not all(_is_scalar(item) for item in value):
            return value, True
        scalar_type = _scalar_type(value[0])
        if any(_scalar_type(item) != scalar_type for item in value):
            return value, True
        if scalar_type == "null":
            return list(value), False
        if scalar_type == "number":
            return sorted(value, key=lambda item: _as_decimal(item)), False
        if scalar_type == "boolean":
            return sorted(value), False
        return sorted(value), False
    if name == "round_decimal":
        scale = normalizer_value.get("scale")
        if (
            type(scale) is not int
            or not 0 <= scale <= 12
            or normalizer_value.get("rounding") != "half_even"
        ):
            return value, True
        if type(value) is bool or not isinstance(value, (int, Decimal)):
            return value, True
        number = _as_decimal(value)
        if not number.is_finite():
            return value, True
        exponent = number.as_tuple().exponent
        if not isinstance(exponent, int):
            return value, True
        try:
            with localcontext() as context:
                context.prec = max(64, len(number.as_tuple().digits) + abs(exponent) + scale + 2)
                return number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN), False
        except (InvalidOperation, ValueError):
            return value, True
    return value, True


def _resolve_pointer(document: object, pointer: str) -> tuple[bool, object]:
    if pointer == "":
        return True, document
    current = document
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return False, _MISSING
            current = current[token]
        elif isinstance(current, list):
            if token == "-" or (len(token) > 1 and token.startswith("0")) or not token.isdigit():
                return False, _MISSING
            index = int(token)
            if index >= len(current):
                return False, _MISSING
            current = current[index]
        else:
            return False, _MISSING
    return True, current


def _pointers_overlap(left: str, right: str) -> bool:
    if left == right or left == "" or right == "":
        return True
    return left.startswith(right + "/") or right.startswith(left + "/")


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if isinstance(value, (int, Decimal)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    raise EvaluationInputError("malformed_json")


def _json_equal(left: object, right: object) -> bool:
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if isinstance(left, (int, Decimal)) and not isinstance(left, bool):
        return (
            isinstance(right, (int, Decimal))
            and not isinstance(right, bool)
            and _as_decimal(left) == _as_decimal(right)
        )
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(_json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


def _is_scalar(value: object) -> bool:
    return value is None or type(value) is bool or isinstance(value, (int, Decimal, str))


def _scalar_type(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if isinstance(value, (int, Decimal)):
        return "number"
    return "string"


def _as_decimal(value: int | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(value)


def _is_supported_json(value: object) -> bool:
    if value is None or type(value) is bool or type(value) is int:
        return True
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(_is_supported_json(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _is_supported_json(item) for key, item in value.items())
    return False


def _contains_redacted(value: object) -> bool:
    if isinstance(value, str) and _REDACTED in value:
        return True
    if isinstance(value, list):
        return any(_contains_redacted(item) for item in value)
    if isinstance(value, Mapping):
        return any(_contains_redacted(item) for item in value.values())
    return False


def _to_json_value(value: object) -> object:
    if isinstance(value, tuple):
        return [_to_json_value(item) for item in value]
    if isinstance(value, list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    return value


def _encoded_size(value: object) -> int:
    try:
        return len(canonical_json(_to_json_value(value)).encode("utf-8"))
    except (TypeError, ValueError):
        return _MAX_EVIDENCE_BYTES + 1


def _evidence(value: object) -> tuple[object | None, bool]:
    if value is _MISSING:
        return None, True
    if _contains_redacted(value):
        return None, True
    encoded_size = _encoded_size(value)
    if encoded_size > _MAX_EVIDENCE_BYTES:
        return None, True
    return _to_json_value(value), False
