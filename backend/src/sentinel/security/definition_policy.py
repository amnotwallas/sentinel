import ipaddress
import json
import re
from collections.abc import Callable, Mapping
from urllib.parse import unquote, urlsplit, urlunsplit

from sentinel.catalog.environments import (
    EnvironmentDocument,
    EnvironmentValidationError,
    SecretReference,
    TargetPolicy,
)

_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SECRET = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _mapping(value: object, *, fields: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise EnvironmentValidationError("object required")
    if set(value) - fields:
        raise EnvironmentValidationError("unsupported field")
    return value


def _canonical_hostname(value: object) -> str:
    if not isinstance(value, str) or not value or value.endswith(".") or "*" in value:
        raise EnvironmentValidationError("invalid hostname")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise EnvironmentValidationError("IP literals must use CIDR")
    try:
        result = value.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise EnvironmentValidationError("invalid hostname") from None
    if len(result) > 253 or any(not label or len(label) > 63 for label in result.split(".")):
        raise EnvironmentValidationError("invalid hostname")
    return result


def _canonical_cidr(value: object) -> str:
    if not isinstance(value, str):
        raise EnvironmentValidationError("invalid CIDR")
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError:
        raise EnvironmentValidationError("invalid CIDR") from None
    return str(network)


def _unique_sorted(values: object, canonicalize: Callable[[object], str]) -> tuple[str, ...]:
    if not isinstance(values, list) or len(values) > 128:
        raise EnvironmentValidationError("invalid policy list")
    normalized = [canonicalize(value) for value in values]
    if len(set(normalized)) != len(normalized):
        raise EnvironmentValidationError("duplicate policy value")
    return tuple(sorted(normalized))


def _base_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 2048:
        raise EnvironmentValidationError("invalid base URL")
    if any(character in value for character in "{}\\\r\n\t "):
        raise EnvironmentValidationError("invalid base URL")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise EnvironmentValidationError("invalid base URL")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise EnvironmentValidationError("invalid base URL")
    try:
        port = parsed.port
    except ValueError:
        raise EnvironmentValidationError("invalid base URL") from None
    if any(segment in {".", ".."} for segment in unquote(parsed.path).split("/")):
        raise EnvironmentValidationError("invalid base URL")
    try:
        host_ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        host = _canonical_hostname(parsed.hostname)
    else:
        host = f"[{host_ip}]" if host_ip.version == 6 else str(host_ip)
    if port is not None and not 1 <= port <= 65535:
        raise EnvironmentValidationError("invalid base URL")
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parsed.scheme.lower(), host, path, "", ""))


def _target_policy(value: object) -> TargetPolicy:
    data = _mapping(
        value,
        fields={
            "schema_version",
            "allowed_hostnames",
            "allowed_cidrs",
            "denied_hostnames",
            "denied_cidrs",
            "allowed_ports",
        },
    )
    if data.get("schema_version", 1) != 1:
        raise EnvironmentValidationError("unsupported target policy version")
    ports_value = data.get("allowed_ports")
    ports: tuple[int, ...] | None
    if ports_value is None:
        ports = None
    elif isinstance(ports_value, list) and len(ports_value) <= 128:
        if any(type(port) is not int or not 1 <= port <= 65535 for port in ports_value):
            raise EnvironmentValidationError("invalid allowed port")
        if len(set(ports_value)) != len(ports_value):
            raise EnvironmentValidationError("duplicate allowed port")
        ports = tuple(sorted(ports_value))
    else:
        raise EnvironmentValidationError("invalid allowed ports")
    return TargetPolicy(
        allowed_hostnames=_unique_sorted(data.get("allowed_hostnames", []), _canonical_hostname),
        allowed_cidrs=_unique_sorted(data.get("allowed_cidrs", []), _canonical_cidr),
        denied_hostnames=_unique_sorted(data.get("denied_hostnames", []), _canonical_hostname),
        denied_cidrs=_unique_sorted(data.get("denied_cidrs", []), _canonical_cidr),
        allowed_ports=ports,
    )


def validate_environment_document(value: object) -> EnvironmentDocument:
    data = _mapping(
        value,
        fields={"schema_version", "base_url", "variables", "secret_references", "target_policy"},
    )
    if data.get("schema_version", 1) != 1 or "base_url" not in data:
        raise EnvironmentValidationError("invalid environment document")
    variables_value = data.get("variables", {})
    variables = _mapping(
        variables_value,
        fields=set(variables_value) if isinstance(variables_value, Mapping) else set(),
    )
    if len(variables) > 128:
        raise EnvironmentValidationError("too many variables")
    canonical_variables: list[tuple[str, str]] = []
    for key, item in variables.items():
        if (
            not _VARIABLE.fullmatch(key)
            or not isinstance(item, str)
            or len(item.encode("utf-8")) > 4096
        ):
            raise EnvironmentValidationError("invalid variable")
        if "$secret" in item:
            raise EnvironmentValidationError("secret reference forbidden in variable")
        canonical_variables.append((key, item))
    references_value = data.get("secret_references", [])
    if not isinstance(references_value, list) or len(references_value) > 128:
        raise EnvironmentValidationError("invalid secret references")
    references: list[SecretReference] = []
    for item in references_value:
        reference = _mapping(item, fields={"$secret"})
        name = reference.get("$secret")
        if not isinstance(name, str) or not _SECRET.fullmatch(name):
            raise EnvironmentValidationError("invalid secret reference")
        references.append(SecretReference(name))
    if len({reference.name for reference in references}) != len(references):
        raise EnvironmentValidationError("duplicate secret reference")
    document = EnvironmentDocument(
        base_url=_base_url(data["base_url"]),
        variables=tuple(sorted(canonical_variables)),
        secret_references=tuple(sorted(references, key=lambda reference: reference.name)),
        target_policy=_target_policy(data.get("target_policy", {})),
    )
    if (
        len(
            json.dumps(document.to_document(), separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        )
        > 262_144
    ):
        raise EnvironmentValidationError("environment document too large")
    return document
