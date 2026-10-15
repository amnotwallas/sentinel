import ipaddress
import json
import re
from collections.abc import Callable, Mapping
from decimal import Decimal
from urllib.parse import unquote, unquote_to_bytes, urlsplit, urlunsplit

from sentinel.catalog.definitions import DefinitionValidationError, TestDefinition
from sentinel.catalog.environments import (
    EnvironmentDocument,
    EnvironmentValidationError,
    SecretReference,
    TargetPolicy,
)
from sentinel.regression.policy import canonical_json, validate_regression_policy

_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SECRET = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_HEADER = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_BAGGAGE_VALUE = re.compile(r"^[\x21-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]*$")
_POINTER = re.compile(r"^(?:/(?:[^~]|~[01])*)*$")
_TEMPLATE = re.compile(r"\{\{variables\.([A-Za-z_][A-Za-z0-9_]{0,63})\}\}")
_METHODS = {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}
_CREDENTIAL_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
}
_MANAGED_HEADERS = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "upgrade",
    "proxy-connection",
    "trailer",
    "te",
    "expect",
}


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


def _definition_object(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise DefinitionValidationError("type_invalid")
    if set(value) - fields:
        raise DefinitionValidationError("extra_field")
    return {key: item for key, item in value.items()}


def _definition_string(value: object, *, maximum: int, controls: bool = False) -> str:
    if not isinstance(value, str):
        raise DefinitionValidationError("type_invalid")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise DefinitionValidationError("value_invalid")
    if len(value.encode("utf-8")) > maximum:
        raise DefinitionValidationError("limit_exceeded")
    if controls and any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise DefinitionValidationError("value_invalid")
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


def _secret_name(value: object) -> str:
    if not isinstance(value, str) or not _SECRET.fullmatch(value):
        raise DefinitionValidationError("invalid_secret_reference")
    return value


def _secret_reference(value: object, *, allowed: bool) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or "$secret" not in value:
        return None
    if not allowed:
        raise DefinitionValidationError("secret_placement_forbidden")
    if set(value) != {"$secret"}:
        raise DefinitionValidationError("invalid_secret_reference")
    return {"$secret": _secret_name(value["$secret"])}


def _json_value(value: object, *, allow_secret_leaves: bool, depth: int = 0) -> object:
    if depth > 32:
        raise DefinitionValidationError("limit_exceeded")
    if value is None or type(value) is bool:
        return value
    number: Decimal | None = None
    if type(value) is int:
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    if number is not None:
        if (
            not number.is_finite()
            or len(number.as_tuple().digits) > 38
            or not -128 <= number.adjusted() <= 128
        ):
            raise DefinitionValidationError("value_invalid")
        return value
    if isinstance(value, float):
        raise DefinitionValidationError("type_invalid")
    if isinstance(value, str):
        return _body_text(value, maximum=65_536)
    if isinstance(value, list):
        if len(value) > 1000:
            raise DefinitionValidationError("limit_exceeded")
        return [
            _json_value(item, allow_secret_leaves=allow_secret_leaves, depth=depth + 1)
            for item in value
        ]
    if isinstance(value, Mapping):
        secret = _secret_reference(value, allowed=allow_secret_leaves)
        if secret is not None:
            return secret
        if len(value) > 256:
            raise DefinitionValidationError("limit_exceeded")
        if any(not isinstance(key, str) for key in value):
            raise DefinitionValidationError("type_invalid")
        if any(key == "$secret" for key in value):
            raise DefinitionValidationError("value_invalid")
        return {
            _definition_string(key, maximum=65_536): _json_value(
                item, allow_secret_leaves=allow_secret_leaves, depth=depth + 1
            )
            for key, item in value.items()
        }
    raise DefinitionValidationError("type_invalid")


def _assertion_json_value(value: object) -> object:
    return _json_value(value, allow_secret_leaves=False)


def _template_text(value: object, *, maximum: int) -> str:
    if isinstance(value, Mapping) and "$secret" in value:
        _secret_reference(value, allowed=False)
    text = _definition_string(value, maximum=maximum, controls=True)
    remainder = _TEMPLATE.sub("", text)
    if "{" in remainder or "}" in remainder:
        raise DefinitionValidationError("value_invalid")
    return text


def _body_text(value: object, *, maximum: int) -> str:
    if isinstance(value, Mapping) and "$secret" in value:
        _secret_reference(value, allowed=False)
    text = _definition_string(value, maximum=maximum)
    start = 0
    while (template_start := text.find("{{variables.", start)) != -1:
        match = _TEMPLATE.match(text, template_start)
        if match is None:
            raise DefinitionValidationError("value_invalid")
        start = match.end()
    return text


def _header_name(value: object) -> str:
    name = _definition_string(value, maximum=128, controls=True)
    if not _HEADER.fullmatch(name):
        raise DefinitionValidationError("value_invalid")
    return name.lower()


def _baggage(value: str) -> None:
    if (
        len(value.encode("ascii", errors="ignore")) != len(value)
        or len(value.encode("utf-8")) > 4096
    ):
        raise DefinitionValidationError("trace_context_forbidden")
    if "{{" in value or "$secret" in value:
        raise DefinitionValidationError("trace_context_forbidden")
    members = value.split(",")
    if not 1 <= len(members) <= 32:
        raise DefinitionValidationError("trace_context_forbidden")
    seen_names: set[str] = set()
    for member in members:
        member_parts = member.strip().split(";")
        pair = member_parts[0].split("=", 1)
        if (
            len(pair) != 2
            or not pair[0]
            or not _HEADER.fullmatch(pair[0])
            or not _BAGGAGE_VALUE.fullmatch(pair[1])
        ):
            raise DefinitionValidationError("trace_context_forbidden")
        decoded: list[bytes] = []
        for component in pair:
            if any(
                character == "%"
                and (
                    index + 2 >= len(component)
                    or not re.fullmatch(r"[0-9A-Fa-f]{2}", component[index + 1 : index + 3])
                )
                for index, character in enumerate(component)
            ):
                raise DefinitionValidationError("trace_context_forbidden")
            decoded_component = unquote_to_bytes(component)
            if any(byte < 0x20 or byte == 0x7F for byte in decoded_component):
                raise DefinitionValidationError("trace_context_forbidden")
            decoded.append(decoded_component)
        for raw_property in member_parts[1:]:
            property_pair = raw_property.strip().split("=", 1)
            if (
                not property_pair[0]
                or not _HEADER.fullmatch(property_pair[0])
                or (len(property_pair) == 2 and not _BAGGAGE_VALUE.fullmatch(property_pair[1]))
            ):
                raise DefinitionValidationError("trace_context_forbidden")
            for component in property_pair:
                if any(
                    character == "%"
                    and (
                        index + 2 >= len(component)
                        or not re.fullmatch(r"[0-9A-Fa-f]{2}", component[index + 1 : index + 3])
                    )
                    for index, character in enumerate(component)
                ):
                    raise DefinitionValidationError("trace_context_forbidden")
                decoded_component = unquote_to_bytes(component)
                if any(byte < 0x20 or byte == 0x7F for byte in decoded_component):
                    raise DefinitionValidationError("trace_context_forbidden")
        try:
            decoded_name = decoded[0].decode("ascii")
        except UnicodeDecodeError:
            raise DefinitionValidationError("trace_context_forbidden") from None
        if not _HEADER.fullmatch(decoded_name) or decoded_name.lower() in {
            "sentinel.execution.id",
            "sentinel.attempt.id",
        }:
            raise DefinitionValidationError("trace_context_forbidden")
        if decoded_name in seen_names:
            raise DefinitionValidationError("trace_context_forbidden")
        seen_names.add(decoded_name)


def _request(value: object) -> dict[str, object]:
    data = _definition_object(
        value,
        {
            "method",
            "path",
            "query",
            "headers",
            "body",
            "timeout_ms",
            "connect_timeout_ms",
            "read_timeout_ms",
            "follow_redirects",
            "max_redirects",
            "verify_tls",
            "max_response_bytes",
        },
    )
    method = data.get("method")
    if not isinstance(method, str):
        raise DefinitionValidationError("type_invalid")
    if method not in _METHODS:
        raise DefinitionValidationError("value_invalid")
    path = _template_text(data.get("path"), maximum=2048)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "?" in path
        or "#" in path
        or "\\" in path
    ):
        raise DefinitionValidationError("value_invalid")
    if any(segment in {".", ".."} for segment in path.split("/")):
        raise DefinitionValidationError("value_invalid")
    path = _template_text(path, maximum=2048)

    raw_query = data.get("query", [])
    if not isinstance(raw_query, list):
        raise DefinitionValidationError("type_invalid")
    if len(raw_query) > 128:
        raise DefinitionValidationError("limit_exceeded")
    query: list[dict[str, str]] = []
    for item in raw_query:
        parameter = _definition_object(item, {"name", "value"})
        name = _template_text(parameter.get("name"), maximum=128)
        if not name:
            raise DefinitionValidationError("limit_exceeded")
        query.append(
            {
                "name": name,
                "value": _template_text(parameter.get("value"), maximum=4096),
            }
        )

    raw_headers = data.get("headers", [])
    if not isinstance(raw_headers, list):
        raise DefinitionValidationError("type_invalid")
    if len(raw_headers) > 64:
        raise DefinitionValidationError("limit_exceeded")
    headers: list[dict[str, object]] = []
    seen_headers: set[str] = set()
    aggregate_bytes = 0
    for item in raw_headers:
        header = _definition_object(item, {"name", "value"})
        name = _header_name(header.get("name"))
        if name in seen_headers:
            raise DefinitionValidationError("duplicate")
        seen_headers.add(name)
        if name in _MANAGED_HEADERS:
            raise DefinitionValidationError("value_invalid")
        if name in {"traceparent", "tracestate"}:
            raise DefinitionValidationError("trace_context_forbidden")
        raw_value = header.get("value")
        secret = _secret_reference(raw_value, allowed=True)
        if secret is not None:
            if name == "baggage":
                raise DefinitionValidationError("trace_context_forbidden")
            normalized_value: object = secret
        else:
            normalized_value = _template_text(raw_value, maximum=8192)
            if name in _CREDENTIAL_HEADERS:
                raise DefinitionValidationError("credential_literal_forbidden")
            if name == "baggage":
                _baggage(normalized_value)
        aggregate_bytes += len(name.encode("utf-8")) + len(
            json.dumps(normalized_value, separators=(",", ":")).encode("utf-8")
        )
        headers.append({"name": name, "value": normalized_value})
    if aggregate_bytes > 32_768:
        raise DefinitionValidationError("limit_exceeded")

    raw_body = data.get("body")
    body: object | None = None
    if raw_body is not None:
        body_data = _definition_object(raw_body, {"kind", "value"})
        kind = body_data.get("kind")
        if not isinstance(kind, str):
            raise DefinitionValidationError("type_invalid")
        if kind == "json":
            body = {
                "kind": "json",
                "value": _json_value(body_data.get("value"), allow_secret_leaves=True),
            }
        elif kind == "text":
            body = {
                "kind": "text",
                "value": _body_text(body_data.get("value"), maximum=131_072),
            }
        else:
            raise DefinitionValidationError("value_invalid")

    timeout = _definition_integer(data.get("timeout_ms", 30_000), minimum=1, maximum=120_000)
    connect_timeout = _definition_integer(
        data.get("connect_timeout_ms", 5_000), minimum=1, maximum=120_000
    )
    read_timeout = _definition_integer(
        data.get("read_timeout_ms", 10_000), minimum=1, maximum=120_000
    )
    if connect_timeout > timeout or read_timeout > timeout:
        raise DefinitionValidationError("incompatible_fields")
    follow_redirects = data.get("follow_redirects", False)
    if type(follow_redirects) is not bool:
        raise DefinitionValidationError("type_invalid")
    max_redirects = _definition_integer(data.get("max_redirects", 3), minimum=0, maximum=3)
    verify_tls = data.get("verify_tls", True)
    if type(verify_tls) is not bool:
        raise DefinitionValidationError("type_invalid")
    max_response_bytes = _definition_integer(
        data.get("max_response_bytes", 262_144), minimum=1, maximum=1_048_576
    )
    return {
        "method": method,
        "path": path,
        "query": query,
        "headers": headers,
        "body": body,
        "timeout_ms": timeout,
        "connect_timeout_ms": connect_timeout,
        "read_timeout_ms": read_timeout,
        "follow_redirects": follow_redirects,
        "max_redirects": max_redirects,
        "verify_tls": verify_tls,
        "max_response_bytes": max_response_bytes,
    }


def _redaction(value: object) -> dict[str, object]:
    data = _definition_object(value, {"schema_version", "json_pointers", "header_names"})
    _definition_version(data.get("schema_version", 1))
    raw_pointers = data.get("json_pointers", [])
    raw_headers = data.get("header_names", [])
    if not isinstance(raw_pointers, list) or not isinstance(raw_headers, list):
        raise DefinitionValidationError("type_invalid")
    if len(raw_pointers) > 128 or len(raw_headers) > 128:
        raise DefinitionValidationError("limit_exceeded")
    pointers: list[str] = []
    for pointer in raw_pointers:
        if (
            not isinstance(pointer, str)
            or len(pointer.encode("utf-8")) > 1024
            or not _POINTER.fullmatch(pointer)
        ):
            raise DefinitionValidationError("invalid_json_pointer")
        pointers.append(pointer)
    headers = [_header_name(header) for header in raw_headers]
    if len(set(pointers)) != len(pointers) or len(set(headers)) != len(headers):
        raise DefinitionValidationError("duplicate")
    return {
        "schema_version": 1,
        "json_pointers": sorted(pointers),
        "header_names": sorted(headers),
    }


def validate_test_definition(value: object) -> TestDefinition:
    data = _definition_object(
        value,
        {
            "schema_version",
            "request",
            "assertions",
            "comparison_policy",
            "redaction",
            "allow_unsafe_replay",
        },
    )
    _definition_version(data.get("schema_version", 1))
    if "request" not in data:
        raise DefinitionValidationError("value_invalid")
    request = _request(data["request"])
    regression = validate_regression_policy(
        data.get("assertions", []),
        data.get("comparison_policy", {}),
        assertion_json_validator=_assertion_json_value,
        forbidden_literal_headers=_CREDENTIAL_HEADERS,
    )
    redaction = _redaction(data.get("redaction", {}))
    allow_unsafe_replay = data.get("allow_unsafe_replay", False)
    if type(allow_unsafe_replay) is not bool:
        raise DefinitionValidationError("type_invalid")
    canonical: dict[str, object] = {
        "schema_version": 1,
        "request": request,
        "assertions": regression.assertions,
        "comparison_policy": regression.comparison_policy,
        "redaction": redaction,
        "allow_unsafe_replay": allow_unsafe_replay,
    }
    encoded = canonical_json(canonical)
    if len(encoded.encode("utf-8")) > 262_144:
        raise DefinitionValidationError("limit_exceeded")
    return TestDefinition(document=canonical, policy_fingerprint=regression.policy_fingerprint)
