"""Bounded, derived trace evidence with no raw telemetry payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from sentinel.telemetry.ports import ServiceEvidence, TraceLookup

MAX_EVIDENCE_TEXT_BYTES = 128
MAX_EVIDENCE_SERVICES = 32
MAX_LINKED_MATCHES = 16
_SERVICE_FIELDS = ("version", "environment", "revision")


def _text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    if (
        not value
        or len(encoded) > MAX_EVIDENCE_TEXT_BYTES
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        return None
    return value


def _service_documents(services: Iterable[ServiceEvidence]) -> list[dict[str, str | None]]:
    values: set[tuple[str, str | None, str | None, str | None]] = set()
    for service in services:
        name = _text(service.name)
        if name is None:
            continue
        values.add(
            (
                name,
                _text(service.version),
                _text(service.environment),
                _text(service.revision),
            )
        )
    ordered = sorted(values)[:MAX_EVIDENCE_SERVICES]
    return [
        {"name": name, "version": version, "environment": environment, "revision": revision}
        for name, version, environment, revision in ordered
    ]


def _deployment_documents(services: Iterable[ServiceEvidence]) -> list[dict[str, str | None]]:
    values: set[tuple[str, str | None, str | None]] = set()
    for service in services:
        name = _text(service.name)
        environment = _text(service.environment)
        revision = _text(service.revision)
        if name is not None and (environment is not None or revision is not None):
            values.add((name, environment, revision))
    return [
        {"service": name, "environment": environment, "revision": revision}
        for name, environment, revision in sorted(values)[:MAX_EVIDENCE_SERVICES]
    ]


def build_trace_evidence(
    result: TraceLookup,
    *,
    linked_match_count: int,
    comparison_anchor: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "primary_span_found": result.client_span_id is not None,
        "trace_span_count": min(max(result.trace_span_count, 0), 256),
        "error_span_count": min(max(result.error_span_count, 0), 256),
        "services": _service_documents(result.services),
        "deployments": _deployment_documents(result.services),
        "linked_match_count": min(max(linked_match_count, 0), MAX_LINKED_MATCHES),
        "context_continuity": result.context_continuity.value,
        "comparison_anchor": comparison_anchor,
    }


def build_linked_evidence(services: Iterable[ServiceEvidence]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "primary_span_found": False,
        "trace_span_count": 0,
        "error_span_count": 0,
        "services": _service_documents(services),
        "deployments": _deployment_documents(services),
        "linked_match_count": 1,
        "context_continuity": "unknown",
        "comparison_anchor": None,
    }


def _previous_services(previous_evidence: object) -> dict[str, dict[str, object]]:
    if not isinstance(previous_evidence, Mapping):
        return {}
    services = previous_evidence.get("services")
    if not isinstance(services, list):
        return {}
    result: dict[str, dict[str, object]] = {}
    for service in services:
        if not isinstance(service, dict):
            continue
        name = _text(service.get("name"))
        if name is not None:
            result[name] = {
                field: _text(service.get(field)) for field in ("version", "environment", "revision")
            }
    return result


def build_comparison_anchor(
    reference_id: UUID,
    previous_evidence: object,
    current_services: Iterable[ServiceEvidence],
) -> dict[str, object] | None:
    previous = _previous_services(previous_evidence)
    current_documents = _service_documents(current_services)
    current = {str(item["name"]): item for item in current_documents}
    changed: list[dict[str, object]] = []
    for name in sorted(set(previous) | set(current)):
        before = previous.get(name)
        after = current.get(name)
        if before is None or after is None:
            fields = ["name"]
        else:
            fields = [field for field in _SERVICE_FIELDS if before.get(field) != after.get(field)]
        if fields:
            changed.append({"name": name, "fields": fields})
    if not changed:
        return None
    return {"reference_id": str(reference_id), "changed": changed[:MAX_EVIDENCE_SERVICES]}
