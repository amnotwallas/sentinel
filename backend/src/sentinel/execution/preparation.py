"""Deterministic, pre-network request preparation for the HTTP adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from urllib.parse import urlencode, urljoin

from sentinel.catalog.definitions import TestDefinition
from sentinel.catalog.environments import EnvironmentDocument
from sentinel.regression.policy import canonical_json
from sentinel.security.secrets import SecretNotFound, SecretResolver

_TEMPLATE = re.compile(r"\{\{variables\.([A-Za-z_][A-Za-z0-9_]{0,63})\}\}")
_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
}


class PreparationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class PreparedRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout_ms: int
    connect_timeout_ms: int
    read_timeout_ms: int
    follow_redirects: bool
    max_redirects: int
    verify_tls: bool
    max_response_bytes: int
    secret_derived_headers: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

    def __repr__(self) -> str:
        return (
            f"PreparedRequest(method={self.method!r}, url=<redacted>, "
            f"headers=<redacted>, body=<redacted>, timeout_ms={self.timeout_ms!r}, "
            f"verify_tls={self.verify_tls!r})"
        )


def _substitute(value: str, variables: Mapping[str, str]) -> str:
    missing = False

    def replace(match: re.Match[str]) -> str:
        nonlocal missing
        name = match.group(1)
        if name not in variables:
            missing = True
            return ""
        return variables[name]

    result = _TEMPLATE.sub(replace, value)
    if missing:
        raise PreparationError("template_variable_missing")
    return result


def _resolve_value(
    value: object,
    *,
    variables: Mapping[str, str],
    resolver: SecretResolver,
    secret_derived_headers: set[str] | None = None,
    header_name: str | None = None,
    allowed_secrets: frozenset[str] = frozenset(),
) -> object:
    if isinstance(value, Mapping):
        if set(value) == {"$secret"}:
            name = value.get("$secret")
            if not isinstance(name, str):
                raise PreparationError("request_invalid")
            if name not in allowed_secrets:
                raise PreparationError("secret_missing")
            try:
                resolved = resolver.resolve(name)
            except (SecretNotFound, KeyError):
                raise PreparationError("secret_missing") from None
            except Exception:
                raise PreparationError("infrastructure_failure") from None
            if secret_derived_headers is not None and header_name is not None:
                secret_derived_headers.add(header_name)
            return resolved
        if "$secret" in value:
            raise PreparationError("request_invalid")
        return {
            str(key): _resolve_value(
                item,
                variables=variables,
                resolver=resolver,
                secret_derived_headers=secret_derived_headers,
                header_name=header_name,
                allowed_secrets=allowed_secrets,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_value(
                item,
                variables=variables,
                resolver=resolver,
                secret_derived_headers=secret_derived_headers,
                header_name=header_name,
                allowed_secrets=allowed_secrets,
            )
            for item in value
        ]
    if isinstance(value, str):
        return _substitute(value, variables)
    return value


def request_fingerprint(environment: EnvironmentDocument, definition: TestDefinition) -> str:
    """Hash canonical references and templates; never resolve a secret."""
    payload = {
        "environment": environment.to_document(),
        "definition": definition.to_document(),
    }
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def prepare_request(
    environment: EnvironmentDocument,
    definition: TestDefinition,
    resolver: SecretResolver,
) -> PreparedRequest:
    document = definition.to_document()
    request = document.get("request")
    if not isinstance(request, Mapping):
        raise PreparationError("request_invalid")
    if request.get("verify_tls") is False:
        raise PreparationError("tls_verification_required")
    variables = dict(environment.variables)
    allowed_secrets = frozenset(reference.name for reference in environment.secret_references)
    method = request.get("method")
    path = request.get("path")
    if not isinstance(method, str) or not isinstance(path, str):
        raise PreparationError("request_invalid")
    path = _substitute(path, variables)
    url = urljoin(environment.base_url, path.lstrip("/"))
    query = request.get("query", [])
    if not isinstance(query, list):
        raise PreparationError("request_invalid")
    pairs: list[tuple[str, str]] = []
    for item in query:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise PreparationError("request_invalid")
        name, value = item["name"], item.get("value")
        if not isinstance(value, str):
            raise PreparationError("request_invalid")
        pairs.append((_substitute(name, variables), _substitute(value, variables)))
    if pairs:
        url = f"{url}?{urlencode(pairs)}"

    headers_value = request.get("headers", [])
    if not isinstance(headers_value, list):
        raise PreparationError("request_invalid")
    headers: dict[str, str] = {}
    secret_headers: set[str] = set()
    for item in headers_value:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise PreparationError("request_invalid")
        name = item["name"].lower()
        raw_value = item.get("value")
        resolved = _resolve_value(
            raw_value,
            variables=variables,
            resolver=resolver,
            secret_derived_headers=secret_headers,
            header_name=name,
            allowed_secrets=allowed_secrets,
        )
        if not isinstance(resolved, str):
            raise PreparationError("request_invalid")
        headers[name] = resolved

    body_value = request.get("body")
    body: bytes | None = None
    if body_value is not None:
        if not isinstance(body_value, Mapping):
            raise PreparationError("request_invalid")
        kind, value = body_value.get("kind"), body_value.get("value")
        resolved = _resolve_value(
            value, variables=variables, resolver=resolver, allowed_secrets=allowed_secrets
        )
        if kind == "json":
            try:
                body = canonical_json(resolved).encode("utf-8")
            except (TypeError, ValueError):
                raise PreparationError("request_invalid") from None
        elif kind == "text" and isinstance(resolved, str):
            body = resolved.encode("utf-8")
        else:
            raise PreparationError("request_invalid")

    try:
        return PreparedRequest(
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout_ms=int(request["timeout_ms"]),
            connect_timeout_ms=int(request["connect_timeout_ms"]),
            read_timeout_ms=int(request["read_timeout_ms"]),
            follow_redirects=bool(request["follow_redirects"]),
            max_redirects=int(request["max_redirects"]),
            verify_tls=True,
            max_response_bytes=int(request["max_response_bytes"]),
            secret_derived_headers=frozenset(secret_headers),
        )
    except (KeyError, TypeError, ValueError):
        raise PreparationError("request_invalid") from None
