from __future__ import annotations

import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpcore
import pytest

from sentinel.catalog.environments import TargetPolicy
from sentinel.execution.domain import (
    DispatchCertainty,
    RedirectRejectionCode,
    TransportOutcome,
)
from sentinel.security.targets import (
    DeploymentTargetPolicy,
    TargetDenied,
    resolve_target,
)
from sentinel.transport.http import HTTPTransportAdapter, build_ssl_context
from tests.unit.test_http_transport import MappingResolver, request

_TLS_FIXTURES = Path(__file__).parents[1] / "fixtures" / "tls"
_CA_CERTIFICATE = _TLS_FIXTURES / "synthetic_ca.pem"
_SERVER_CERTIFICATE = _TLS_FIXTURES / "synthetic_server.pem"
_EXPIRED_SERVER_CERTIFICATE = _TLS_FIXTURES / "synthetic_expired_server.pem"
_SERVER_KEY = _TLS_FIXTURES / "synthetic_server.key"


class _TLSServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, _request: object, _client_address: object) -> None:
        pass


@contextmanager
def tls_server(
    certificate: Path = _SERVER_CERTIFICATE,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: bytes = b"ok",
) -> Iterator[tuple[_TLSServer, int, list[str], list[str], list[int]]]:
    hosts: list[str] = []
    server_names: list[str] = []
    client_ports: list[int] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            hosts.append(self.headers["Host"])
            client_ports.append(self.client_address[1])
            self.send_response(status)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    instance = _TLSServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, _SERVER_KEY)
    context.set_servername_callback(
        lambda _socket, hostname, _context: server_names.append(hostname or "")
    )
    instance.socket = context.wrap_socket(instance.socket, server_side=True)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance, instance.server_port, hosts, server_names, client_ports
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=1)


@contextmanager
def http_server(
    status: int,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> Iterator[tuple[ThreadingHTTPServer, int, list[tuple[str, dict[str, str], bytes]]]]:
    requests: list[tuple[str, dict[str, str], bytes]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            request_body = self.rfile.read(length) if length else b""
            requests.append(
                (
                    self.command,
                    {name.lower(): value for name, value in self.headers.items()},
                    request_body,
                )
            )
            self.send_response(status)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = do_HEAD = do_OPTIONS = _handle

        def log_message(self, *_args: object) -> None:
            pass

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance, instance.server_port, requests
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=1)


def tls_adapter(
    port: int, resolver: MappingResolver, *, ca_bundle: Path | None
) -> HTTPTransportAdapter:
    return HTTPTransportAdapter(
        resolver=resolver,
        deployment_policy=DeploymentTargetPolicy(
            allowed_cidrs=("127.0.0.1/32",), allowed_ports=(port,)
        ),
        ca_bundle=str(ca_bundle) if ca_bundle is not None else None,
    )


def test_tls_peer_uses_pinned_ip_original_authority_sni_and_fresh_connections() -> None:
    with tls_server() as (_instance, port, hosts, server_names, client_ports):
        resolver = MappingResolver({"api.test": ("127.0.0.1",)})
        transport = tls_adapter(port, resolver, ca_bundle=_CA_CERTIFICATE)

        first = transport.dispatch(request(f"https://api.test:{port}/first"))
        second = transport.dispatch(request(f"https://api.test:{port}/second"))

    assert first.outcome == second.outcome == TransportOutcome.RESPONSE_RECEIVED
    assert first.body == second.body == b"ok"
    assert resolver.calls == ["api.test", "api.test"]
    assert hosts == [f"api.test:{port}", f"api.test:{port}"]
    assert server_names == ["api.test", "api.test"]
    assert len(set(client_ports)) == 2


@pytest.mark.parametrize(
    ("certificate", "hostname", "ca_bundle"),
    [
        pytest.param(_SERVER_CERTIFICATE, "api.test", None, id="untrusted"),
        pytest.param(_SERVER_CERTIFICATE, "wrong.test", _CA_CERTIFICATE, id="hostname"),
        pytest.param(_EXPIRED_SERVER_CERTIFICATE, "api.test", _CA_CERTIFICATE, id="expired"),
    ],
)
def test_tls_rejects_untrusted_expired_and_hostname_mismatched_certificates(
    certificate: Path,
    hostname: str,
    ca_bundle: Path | None,
) -> None:
    with tls_server(certificate) as (_instance, port, _hosts, _server_names, _client_ports):
        resolver = MappingResolver({hostname: ("127.0.0.1",)})
        result = tls_adapter(port, resolver, ca_bundle=ca_bundle).dispatch(
            request(f"https://{hostname}:{port}/probe")
        )

    assert result.outcome == TransportOutcome.TLS_FAILURE
    assert result.certainty == DispatchCertainty.NOT_SENT
    assert result.not_sent_proof == "tls_failure"


def test_tls_context_keeps_platform_roots_and_disables_legacy_or_early_data() -> None:
    default = build_ssl_context()
    additive = build_ssl_context(str(_CA_CERTIFICATE))

    assert default.check_hostname is additive.check_hostname is True
    assert default.verify_mode == additive.verify_mode == ssl.CERT_REQUIRED
    assert additive.cert_store_stats()["x509_ca"] >= default.cert_store_stats()["x509_ca"]
    assert additive.minimum_version == ssl.TLSVersion.TLSv1_2
    if hasattr(ssl, "OP_NO_EARLY_DATA"):
        assert additive.options & ssl.OP_NO_EARLY_DATA
    else:
        assert not hasattr(ssl.SSLSocket, "write_early_data")


def test_unreviewed_httpcore_upgrade_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpcore, "__version__", "1.0.10")

    with pytest.raises(RuntimeError, match="unsupported httpcore version"):
        HTTPTransportAdapter()


@pytest.mark.parametrize(
    ("error", "outcome", "certainty", "proof"),
    [
        (
            httpcore.ConnectTimeout("fixture"),
            TransportOutcome.CONNECT_TIMEOUT,
            DispatchCertainty.NOT_SENT,
            "connect_timeout",
        ),
        (
            httpcore.ConnectError("fixture"),
            TransportOutcome.CONNECTION_FAILURE,
            DispatchCertainty.NOT_SENT,
            "connection_failure",
        ),
        (
            httpcore.WriteTimeout("fixture"),
            TransportOutcome.WRITE_TIMEOUT,
            DispatchCertainty.POSSIBLY_SENT,
            None,
        ),
        (
            httpcore.WriteError("fixture"),
            TransportOutcome.WRITE_FAILURE,
            DispatchCertainty.POSSIBLY_SENT,
            None,
        ),
        (
            httpcore.ReadTimeout("fixture"),
            TransportOutcome.READ_TIMEOUT,
            DispatchCertainty.POSSIBLY_SENT,
            None,
        ),
        (
            httpcore.ReadError("fixture"),
            TransportOutcome.READ_FAILURE,
            DispatchCertainty.POSSIBLY_SENT,
            None,
        ),
        (
            RuntimeError("fixture"),
            TransportOutcome.INDETERMINATE,
            DispatchCertainty.POSSIBLY_SENT,
            None,
        ),
    ],
)
def test_pre_response_transport_failures_have_conservative_certainty(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    outcome: TransportOutcome,
    certainty: DispatchCertainty,
    proof: str | None,
) -> None:
    transport = HTTPTransportAdapter(
        resolver=MappingResolver({"api.test": ("127.0.0.1",)}),
        deployment_policy=DeploymentTargetPolicy(
            allowed_cidrs=("127.0.0.1/32",), allowed_ports=(80,)
        ),
    )
    calls = 0

    def fail(*_args: object, **_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise error

    monkeypatch.setattr(transport, "_send", fail)

    result = transport.dispatch(request("http://api.test/probe"))

    assert (result.outcome, result.certainty, result.not_sent_proof) == (
        outcome,
        certainty,
        proof,
    )
    assert calls == 1


def test_redirect_disabled_accepts_3xx_as_the_final_response() -> None:
    with http_server(302, {"Location": "http://blocked.test/private"}, b"redirect") as (
        _instance,
        port,
        requests,
    ):
        result = HTTPTransportAdapter(
            resolver=MappingResolver({"api.test": ("127.0.0.1",)}),
            deployment_policy=DeploymentTargetPolicy(
                allowed_cidrs=("127.0.0.1/32",), allowed_ports=(port,)
            ),
        ).dispatch(request(f"http://api.test:{port}/start"))

    assert result.outcome == TransportOutcome.RESPONSE_RECEIVED
    assert result.certainty == DispatchCertainty.RESPONSE_RECEIVED
    assert result.status_code == 302
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("status", "method", "expected_method"),
    [
        (301, "OPTIONS", "OPTIONS"),
        (302, "OPTIONS", "OPTIONS"),
        (303, "OPTIONS", "GET"),
        (303, "HEAD", "HEAD"),
        (307, "OPTIONS", "OPTIONS"),
        (308, "OPTIONS", "OPTIONS"),
    ],
)
def test_supported_redirects_preserve_safe_methods_except_303(
    status: int,
    method: str,
    expected_method: str,
) -> None:
    with http_server(200, body=b"ok") as (_second, second_port, second_requests):
        with http_server(
            status,
            {"Location": f"http://second.test:{second_port}/final"},
            b"redirect",
        ) as (_first, first_port, first_requests):
            prepared = request(
                f"http://first.test:{first_port}/start",
                method=method,
                headers={"Content-Length": "7", "Content-Type": "text/plain"},
                follow_redirects=True,
            )
            object.__setattr__(prepared, "body", b"payload")
            result = HTTPTransportAdapter(
                resolver=MappingResolver(
                    {"first.test": ("127.0.0.1",), "second.test": ("127.0.0.1",)}
                ),
                deployment_policy=DeploymentTargetPolicy(
                    allowed_cidrs=("127.0.0.1/32",),
                    allowed_ports=(first_port, second_port),
                ),
            ).dispatch(prepared)

    assert result.outcome == TransportOutcome.RESPONSE_RECEIVED
    assert first_requests[0][0] == method
    assert len(second_requests) == 1
    assert second_requests[0][0] == expected_method
    assert second_requests[0][2] == b""
    assert "content-length" not in second_requests[0][1]
    assert "content-type" not in second_requests[0][1]


@pytest.mark.parametrize("status", [300, 304, 305, 306])
def test_other_3xx_statuses_are_not_followed(status: int) -> None:
    with http_server(status, {"Location": "http://second.test/final"}) as (
        _instance,
        port,
        requests,
    ):
        resolver = MappingResolver({"first.test": ("127.0.0.1",)})
        result = HTTPTransportAdapter(
            resolver=resolver,
            deployment_policy=DeploymentTargetPolicy(
                allowed_cidrs=("127.0.0.1/32",), allowed_ports=(port,)
            ),
        ).dispatch(request(f"http://first.test:{port}/start", follow_redirects=True))

    assert result.outcome == TransportOutcome.RESPONSE_RECEIVED
    assert result.status_code == status
    assert resolver.calls == ["first.test"]
    assert len(requests) == 1


def test_redirect_limit_rejects_before_resolving_the_next_hop() -> None:
    with http_server(302, {"Location": "http://second.test/final"}) as (
        _instance,
        port,
        requests,
    ):
        resolver = MappingResolver({"first.test": ("127.0.0.1",)})
        prepared = request(f"http://first.test:{port}/start", follow_redirects=True)
        object.__setattr__(prepared, "max_redirects", 0)
        result = HTTPTransportAdapter(
            resolver=resolver,
            deployment_policy=DeploymentTargetPolicy(
                allowed_cidrs=("127.0.0.1/32",), allowed_ports=(port,)
            ),
        ).dispatch(prepared)

    assert result.outcome == TransportOutcome.REDIRECT_DENIED
    assert result.redirect_rejection_code == RedirectRejectionCode.REDIRECT_LIMIT_EXCEEDED
    assert resolver.calls == ["first.test"]
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("http://[invalid", RedirectRejectionCode.LOCATION_INVALID),
        ("http://second.test:65534/final", RedirectRejectionCode.PORT_DENIED),
        ("http://blocked.test/final", RedirectRejectionCode.TARGET_DENIED),
    ],
)
def test_rejected_redirect_hops_never_connect_and_return_safe_codes(
    location: str,
    expected: RedirectRejectionCode,
) -> None:
    with http_server(302, {"Location": location}, b"redirect") as (
        _instance,
        port,
        requests,
    ):
        resolver = MappingResolver(
            {
                "first.test": ("127.0.0.1",),
                "second.test": ("127.0.0.1",),
                "blocked.test": ("127.0.0.1",),
            }
        )
        result = HTTPTransportAdapter(
            resolver=resolver,
            deployment_policy=DeploymentTargetPolicy(
                allowed_hostnames=("first.test",), allowed_ports=(port, 80)
            ),
        ).dispatch(request(f"http://first.test:{port}/start", follow_redirects=True))

    assert result.outcome == TransportOutcome.REDIRECT_DENIED
    assert result.certainty == DispatchCertainty.RESPONSE_RECEIVED
    assert result.redirect_rejection_code == expected
    assert result.headers["location"] == "[REDACTED]"
    assert len(requests) == 1


def test_https_downgrade_is_rejected_before_the_next_hop() -> None:
    with tls_server(
        status=302,
        headers={"Location": "http://second.test/final"},
        body=b"redirect",
    ) as (_instance, port, hosts, _server_names, _client_ports):
        resolver = MappingResolver({"api.test": ("127.0.0.1",)})
        result = tls_adapter(port, resolver, ca_bundle=_CA_CERTIFICATE).dispatch(
            request(f"https://api.test:{port}/start", follow_redirects=True)
        )

    assert result.outcome == TransportOutcome.REDIRECT_DENIED
    assert result.certainty == DispatchCertainty.RESPONSE_RECEIVED
    assert result.redirect_rejection_code == RedirectRejectionCode.SCHEME_DENIED
    assert hosts == [f"api.test:{port}"]


def test_redirect_write_failure_keeps_possibly_sent_after_an_earlier_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = MappingResolver({"first.test": ("127.0.0.1",), "second.test": ("127.0.0.1",)})
    transport = HTTPTransportAdapter(
        resolver=resolver,
        deployment_policy=DeploymentTargetPolicy(
            allowed_cidrs=("127.0.0.1/32",), allowed_ports=(80,)
        ),
    )
    responses: Iterator[httpcore.Response | Exception] = iter(
        [
            httpcore.Response(302, headers={"Location": "http://second.test/final"}),
            httpcore.WriteError("fixture"),
        ]
    )

    def send(*_args: object, **_kwargs: object) -> tuple[httpcore.Response, object]:
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return item, object()

    monkeypatch.setattr(transport, "_send", send)
    result = transport.dispatch(request("http://first.test/start", follow_redirects=True))

    assert result.outcome == TransportOutcome.WRITE_FAILURE
    assert result.certainty == DispatchCertainty.POSSIBLY_SENT
    assert result.status_code == 302
    assert resolver.calls == ["first.test", "second.test"]


def test_empty_dns_result_is_not_sent() -> None:
    result = HTTPTransportAdapter(
        resolver=MappingResolver({"api.test": ()}),
    ).dispatch(request("http://api.test/probe"))

    assert result.outcome == TransportOutcome.DNS_FAILURE
    assert result.certainty == DispatchCertainty.NOT_SENT
    assert result.not_sent_proof == "dns_failure"


@pytest.mark.parametrize(
    "address",
    [
        "127.1",
        "0177.0.0.1",
        "2130706433",
        "0x7f000001",
        "127.0.0.1",
        "::ffff:127.0.0.1",
        "169.254.169.254",
        "fd00:ec2::254",
    ],
)
def test_alternate_loopback_and_metadata_addresses_fail_closed(address: str) -> None:
    with pytest.raises(TargetDenied):
        resolve_target(
            "http://api.test/probe",
            resolver=MappingResolver({"api.test": (address,)}),
            environment_policy=TargetPolicy(),
            deployment_policy=DeploymentTargetPolicy(),
        )
