from sentinel.catalog.definitions import TestDefinition as _TestDefinition
from sentinel.catalog.environments import EnvironmentDocument as _EnvironmentDocument
from sentinel.execution.preparation import PreparationError, prepare_request, request_fingerprint
from sentinel.security.definition_policy import (
    validate_environment_document,
    validate_test_definition,
)
from sentinel.security.redaction import redact_observation
from sentinel.security.secrets import EnvironmentSecretResolver


def _environment() -> _EnvironmentDocument:
    return validate_environment_document(
        {
            "schema_version": 1,
            "base_url": "https://api.example.test/v1/",
            "variables": {"USER": "alice"},
            "secret_references": [{"$secret": "API_TOKEN"}],
            "target_policy": {},
        }
    )


def _definition(**request_changes: object) -> _TestDefinition:
    request = {
        "method": "POST",
        "path": "/users/{{variables.USER}}",
        "query": [{"name": "q", "value": "{{variables.USER}}"}],
        "headers": [{"name": "Authorization", "value": {"$secret": "API_TOKEN"}}],
        "body": {"kind": "json", "value": {"token": {"$secret": "API_TOKEN"}}},
        **request_changes,
    }
    return validate_test_definition({"schema_version": 1, "request": request})


def test_preparation_resolves_only_in_memory_and_tracks_secret_headers() -> None:
    prepared = prepare_request(
        _environment(),
        _definition(),
        EnvironmentSecretResolver({"SENTINEL_SECRET_API_TOKEN": "canary"}),
    )
    assert prepared.url.endswith("/users/alice?q=alice")
    assert prepared.headers["authorization"] == "canary"
    assert prepared.body is not None and b"canary" in prepared.body
    assert prepared.secret_derived_headers == frozenset({"authorization"})
    assert "canary" not in repr(prepared)


def test_missing_secret_and_tls_opt_out_fail_before_network() -> None:
    try:
        prepare_request(_environment(), _definition(), EnvironmentSecretResolver({}))
    except PreparationError as error:
        assert error.code == "secret_missing"
    else:
        raise AssertionError("missing secret was accepted")
    try:
        prepare_request(
            _environment(), _definition(verify_tls=False), EnvironmentSecretResolver({})
        )
    except PreparationError as error:
        assert error.code == "tls_verification_required"
    else:
        raise AssertionError("insecure TLS was accepted")


def test_fingerprint_is_secret_independent_and_canonical() -> None:
    environment = _environment()
    definition = _definition()
    assert request_fingerprint(environment, definition) == request_fingerprint(
        environment, definition
    )
    assert request_fingerprint(environment, definition) != request_fingerprint(
        environment, _definition(path="/other")
    )


def test_redaction_is_bounded_and_fixed_headers_are_always_redacted() -> None:
    result = redact_observation(
        status_code=200,
        headers={"Authorization": "canary", "Content-Type": "application/json"},
        body=b'{"safe":"ok","secret":"canary"}',
        max_bytes=256,
        json_pointers=("/secret",),
    )
    assert result.headers["authorization"] == "[REDACTED]"
    assert result.body_content == {"safe": "ok", "secret": "[REDACTED]"}
    assert "canary" not in repr(result)


def test_json_content_type_is_parsed_without_configured_redaction() -> None:
    result = redact_observation(
        status_code=200,
        headers={"Content-Type": "application/json; charset=utf-8"},
        body=b'{"value":"stable"}',
        max_bytes=256,
    )

    assert result.body_kind == "json"
    assert result.body_content == {"value": "stable"}
    assert result.redaction_unavailable is False


def test_redaction_failure_omits_body() -> None:
    result = redact_observation(
        status_code=200,
        headers={},
        body=b"not-json",
        max_bytes=128,
        json_pointers=("/secret",),
    )
    assert result.body_content is None
    assert result.redaction_unavailable is True


def test_location_and_large_header_metadata_are_bounded() -> None:
    result = redact_observation(
        status_code=302,
        headers={
            "Location": "https://internal.example.test/?token=canary",
            **{f"X-{index}": "v" * 4096 for index in range(200)},
        },
        body=None,
        max_bytes=128,
    )
    assert result.headers["location"] == "[REDACTED]"
    assert len(result.headers) <= 64
    assert sum(len(key) + len(value) for key, value in result.headers.items()) <= 32_768
    assert "canary" not in repr(result)
