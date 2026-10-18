from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sentinel.catalog.environments import TargetPolicy
from sentinel.execution.domain import DispatchCertainty, RedirectRejectionCode, TransportOutcome
from sentinel.execution.preparation import PreparationError, PreparedRequest
from sentinel.security.targets import DeploymentTargetPolicy, ResolvedTarget
from sentinel.transport.http import HTTPTransportAdapter


class MappingResolver:
    def __init__(self, mapping: dict[str, tuple[str, ...]]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append(hostname)
        return self.mapping[hostname]


def server(
    reply: tuple[int, dict[str, str], bytes],
) -> tuple[ThreadingHTTPServer, int, list[dict[str, str]]]:
    initial_reply = reply
    requests: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        reply = initial_reply

        def do_GET(self) -> None:  # noqa: N802
            requests.append({key.lower(): value for key, value in self.headers.items()})
            length = int(self.headers.get("content-length", "0"))
            if length:
                self.rfile.read(length)
            status, headers, body = self.__class__.reply
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            self.do_GET()

        def log_message(self, *_args: object) -> None:
            pass

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    return instance, instance.server_port, requests


def request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    follow_redirects: bool = False,
    max_response_bytes: int = 262_144,
    secret_headers: frozenset[str] = frozenset(),
    include_body: bool = True,
) -> PreparedRequest:
    return PreparedRequest(
        method=method,
        url=url,
        headers=headers or {},
        body=b"payload" if method == "POST" and include_body else None,
        timeout_ms=5000,
        connect_timeout_ms=1000,
        read_timeout_ms=1000,
        follow_redirects=follow_redirects,
        max_redirects=3,
        verify_tls=True,
        max_response_bytes=max_response_bytes,
        secret_derived_headers=secret_headers,
        target_policy=TargetPolicy(),
        secret_values=("secret-canary",),
    )


def adapter(port: int, resolver: MappingResolver) -> HTTPTransportAdapter:
    return HTTPTransportAdapter(
        resolver=resolver,
        deployment_policy=DeploymentTargetPolicy(
            allowed_cidrs=("127.0.0.1/32",), allowed_ports=(port, 80, 443)
        ),
    )


def test_status_errors_are_accepted_and_capture_is_bounded() -> None:
    instance, port, _ = server((500, {"X-Secret": "secret-canary"}, b"0123456789"))
    try:
        result = adapter(port, MappingResolver({"api.test": ("127.0.0.1",)})).dispatch(
            request(f"http://api.test:{port}/probe", max_response_bytes=4)
        )
    finally:
        instance.shutdown()
        instance.server_close()
    assert result.outcome == TransportOutcome.RESPONSE_LIMIT_EXCEEDED
    assert result.certainty == DispatchCertainty.RESPONSE_RECEIVED
    assert result.status_code == 500
    assert result.truncated is True
    assert result.body == b"0123"
    assert result.body_kind == "text"
    assert result.body_content == "0123"
    assert result.headers["x-secret"] == "[REDACTED]"


def test_secret_canary_is_removed_from_response_body_before_capture() -> None:
    instance, port, _ = server(
        (200, {"Content-Type": "text/plain"}, b"prefix-secret-canary-suffix")
    )
    try:
        result = adapter(port, MappingResolver({"api.test": ("127.0.0.1",)})).dispatch(
            request(f"http://api.test:{port}/probe", max_response_bytes=128)
        )
    finally:
        instance.shutdown()
        instance.server_close()
    assert result.outcome == TransportOutcome.RESPONSE_RECEIVED
    assert result.body == b"prefix-[REDACTED]-suffix"
    assert b"secret-canary" not in result.body


def test_proxy_environment_is_not_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    instance, port, _ = server((200, {}, b"ok"))
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    try:
        result = adapter(port, MappingResolver({"api.test": ("127.0.0.1",)})).dispatch(
            request(f"http://api.test:{port}/probe")
        )
    finally:
        instance.shutdown()
        instance.server_close()
    assert result.outcome == TransportOutcome.RESPONSE_RECEIVED
    assert result.body == b"ok"


def test_proxy_authorization_is_never_sent_to_target() -> None:
    instance, port, requests = server((200, {}, b"ok"))
    try:
        result = adapter(port, MappingResolver({"api.test": ("127.0.0.1",)})).dispatch(
            request(
                f"http://api.test:{port}/probe",
                headers={"Proxy-Authorization": "secret-canary"},
            )
        )
    finally:
        instance.shutdown()
        instance.server_close()
    assert result.outcome == TransportOutcome.RESPONSE_RECEIVED
    assert "proxy-authorization" not in requests[0]


def test_partial_body_is_a_sanitized_response_received_read_failure() -> None:
    class PartialHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", "10")
            self.end_headers()
            self.wfile.write(b"partial")
            self.wfile.flush()
            self.connection.shutdown(1)

        def log_message(self, *_args: object) -> None:
            pass

    instance = ThreadingHTTPServer(("127.0.0.1", 0), PartialHandler)
    threading.Thread(target=instance.serve_forever, daemon=True).start()
    port = instance.server_port
    try:
        result = adapter(port, MappingResolver({"api.test": ("127.0.0.1",)})).dispatch(
            request(f"http://api.test:{port}/probe")
        )
    finally:
        instance.shutdown()
        instance.server_close()
    assert result.outcome == TransportOutcome.READ_FAILURE
    assert result.certainty == DispatchCertainty.RESPONSE_RECEIVED
    assert result.body == b"partial"


def test_total_deadline_after_response_head_is_a_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class AdvancingClock:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> float:
            self.calls += 1
            return 0.0 if self.calls <= 2 else 1.0

    class ResponseStub:
        status = 200
        headers: list[tuple[bytes, bytes]] = []

        def iter_stream(self) -> Iterator[bytes]:
            yield b"chunk"

        def close(self) -> None:
            pass

    clock = AdvancingClock()
    transport = adapter(80, MappingResolver({"api.test": ("127.0.0.1",)}))
    monkeypatch.setattr(transport, "clock", clock)
    monkeypatch.setattr(
        transport,
        "_send",
        lambda *args, **kwargs: (ResponseStub(), None),
    )
    prepared = request("http://api.test/probe")
    object.__setattr__(prepared, "timeout_ms", 500)
    result = transport.dispatch(prepared)
    assert result.outcome == TransportOutcome.READ_TIMEOUT
    assert result.certainty == DispatchCertainty.RESPONSE_RECEIVED


def test_blocked_destination_is_not_sent() -> None:
    resolver = MappingResolver({"blocked.test": ("127.0.0.1",)})
    result = HTTPTransportAdapter(
        resolver=resolver,
        deployment_policy=DeploymentTargetPolicy(allowed_ports=(80, 443)),
    ).dispatch(request("http://blocked.test/probe"))
    assert result.outcome == TransportOutcome.TARGET_DENIED
    assert result.certainty == DispatchCertainty.NOT_SENT


def test_tls_opt_out_is_rejected_before_resolution() -> None:
    resolver = MappingResolver({"api.test": ("127.0.0.1",)})
    prepared = request("https://api.test/probe")
    object.__setattr__(prepared, "verify_tls", False)
    try:
        HTTPTransportAdapter(resolver=resolver).dispatch(prepared)
    except PreparationError as error:
        assert error.code == "tls_verification_required"
    else:
        raise AssertionError("insecure transport was accepted")
    assert resolver.calls == []


def test_cross_origin_redirect_strips_credentials_and_secret_headers() -> None:
    second, second_port, second_requests = server((200, {}, b"ok"))
    first, first_port, _ = server(
        (302, {"Location": f"http://second.test:{second_port}/final"}, b"redirect")
    )
    try:
        resolver = MappingResolver({"first.test": ("127.0.0.1",), "second.test": ("127.0.0.1",)})
        result = HTTPTransportAdapter(
            resolver=resolver,
            deployment_policy=DeploymentTargetPolicy(
                allowed_cidrs=("127.0.0.1/32",),
                allowed_ports=(first_port, second_port),
            ),
        ).dispatch(
            request(
                f"http://first.test:{first_port}/start",
                headers={
                    "authorization": "secret-canary",
                    "cookie": "secret-canary",
                    "X-Custom-Secret": "secret-canary",
                    "x-safe": "keep",
                },
                follow_redirects=True,
                secret_headers=frozenset({"Authorization", "X-Custom-Secret"}),
            )
        )
    finally:
        first.shutdown()
        second.shutdown()
        first.server_close()
        second.server_close()
    assert result.outcome == TransportOutcome.RESPONSE_RECEIVED
    assert len(second_requests) == 1
    assert "authorization" not in second_requests[0]
    assert "cookie" not in second_requests[0]
    assert "x-custom-secret" not in second_requests[0]
    assert second_requests[0]["x-safe"] == "keep"


def test_unsafe_redirect_is_rejected_with_redacted_location() -> None:
    instance, port, _ = server((302, {"Location": "http://other.test/final"}, b"redirect"))
    try:
        result = adapter(port, MappingResolver({"api.test": ("127.0.0.1",)})).dispatch(
            request(
                f"http://api.test:{port}/probe",
                method="POST",
                follow_redirects=True,
                include_body=False,
            )
        )
    finally:
        instance.shutdown()
        instance.server_close()
    assert result.outcome == TransportOutcome.REDIRECT_DENIED
    assert result.redirect_rejection_code == RedirectRejectionCode.METHOD_NOT_ALLOWED
    assert result.headers["location"] == "[REDACTED]"


def test_empty_redirect_location_is_rejected_without_a_follow_up_request() -> None:
    instance, port, requests = server((302, {"Location": ""}, b"redirect"))
    try:
        result = adapter(port, MappingResolver({"api.test": ("127.0.0.1",)})).dispatch(
            request(f"http://api.test:{port}/probe", follow_redirects=True)
        )
    finally:
        instance.shutdown()
        instance.server_close()
    assert result.outcome == TransportOutcome.REDIRECT_DENIED
    assert result.redirect_rejection_code == RedirectRejectionCode.LOCATION_MISSING
    assert len(requests) == 1


def test_ipv6_host_authority_is_bracketed() -> None:
    instance, port, requests = server((200, {}, b"ok"))
    target = ResolvedTarget(
        "http",
        "2001:db8::1",
        port,
        f"http://[2001:db8::1]:{port}/probe",
        ("127.0.0.1",),
        "127.0.0.1",
    )
    prepared = request(target.url)
    try:
        response, _ = HTTPTransportAdapter(
            deployment_policy=DeploymentTargetPolicy(allowed_ports=(port,))
        )._send(
            target,
            method=prepared.method,
            headers=prepared.headers,
            body=prepared.body,
            request=prepared,
            deadline=10**12,
        )
        response.close()
    finally:
        instance.shutdown()
        instance.server_close()
    assert requests[0]["host"] == f"[2001:db8::1]:{port}"


def test_dns_timeout_is_conservative_and_does_not_claim_not_sent() -> None:
    release = threading.Event()

    class HangingResolver:
        def resolve(self, _hostname: str, _port: int) -> tuple[str, ...]:
            release.wait(1)
            return ("203.0.113.10",)

    prepared = request("http://api.test/probe", max_response_bytes=32)
    object.__setattr__(prepared, "timeout_ms", 1)
    try:
        result = HTTPTransportAdapter(
            resolver=HangingResolver(),
            clock=lambda: 0.0,
        ).dispatch(prepared)
    finally:
        release.set()
    assert result.outcome == TransportOutcome.TOTAL_TIMEOUT
    assert result.certainty == DispatchCertainty.POSSIBLY_SENT


def test_redirect_dns_timeout_preserves_received_certainty() -> None:
    release = threading.Event()
    second_host = "second.test"
    first, first_port, _ = server((302, {"Location": f"http://{second_host}/final"}, b"redirect"))

    class SequencedResolver:
        def __init__(self) -> None:
            self.calls = 0

        def resolve(self, hostname: str, _port: int) -> tuple[str, ...]:
            self.calls += 1
            if hostname == second_host:
                release.wait(1)
            return ("127.0.0.1",)

    resolver = SequencedResolver()
    prepared = request(
        f"http://first.test:{first_port}/start",
        follow_redirects=True,
        max_response_bytes=32,
    )
    object.__setattr__(prepared, "timeout_ms", 1)
    try:
        result = HTTPTransportAdapter(
            resolver=resolver,
            deployment_policy=DeploymentTargetPolicy(
                allowed_cidrs=("127.0.0.1/32",), allowed_ports=(first_port, 80)
            ),
            clock=lambda: 0.0,
        ).dispatch(prepared)
    finally:
        release.set()
        first.shutdown()
        first.server_close()
    assert result.outcome == TransportOutcome.DNS_FAILURE
    assert result.certainty == DispatchCertainty.RESPONSE_RECEIVED
