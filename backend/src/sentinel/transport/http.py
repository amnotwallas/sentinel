"""Safe, single-dispatch HTTP transport with DNS-pinned connections."""

from __future__ import annotations

import ipaddress
import socket
import ssl
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpcore
from httpcore._backends.base import SOCKET_OPTION

from sentinel.execution.domain import DispatchCertainty, RedirectRejectionCode, TransportOutcome
from sentinel.execution.ports import TransportResult
from sentinel.execution.preparation import PreparationError, PreparedRequest
from sentinel.security.redaction import redact_observation
from sentinel.security.targets import (
    DeploymentTargetPolicy,
    DNSFailure,
    ResolvedTarget,
    Resolver,
    SystemResolver,
    TargetDenied,
    canonical_url,
    resolve_target,
)

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SAFE_REDIRECT_METHODS = {"GET", "HEAD", "OPTIONS"}
_FIXED_CREDENTIAL_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "x-api-key",
}
_CONTENT_HEADERS = {
    "content-length",
    "content-type",
    "transfer-encoding",
    "trailer",
}


class TLSConfigurationError(ValueError):
    def __init__(self, code: str = "tls_configuration_invalid") -> None:
        self.code = code
        super().__init__(code)


class _TLSFailure(httpcore.ConnectError):
    pass


class _ReadObservationFailure(Exception):
    def __init__(self, outcome: TransportOutcome, observation: _Observation) -> None:
        self.outcome = outcome
        self.observation = observation
        super().__init__(outcome.value)


class _TotalTimeout(Exception):
    """The request-wide deadline expired, independent of the active phase."""


class _PinnedSocketStream(httpcore.NetworkStream):
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        try:
            self._sock.settimeout(timeout)
            return self._sock.recv(max_bytes)
        except TimeoutError as exc:
            raise httpcore.ReadTimeout("read timeout") from exc
        except OSError as exc:
            raise httpcore.ReadError("read failed") from exc

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        try:
            self._sock.settimeout(timeout)
            self._sock.sendall(buffer)
        except TimeoutError as exc:
            raise httpcore.WriteTimeout("write timeout") from exc
        except OSError as exc:
            raise httpcore.WriteError("write failed") from exc

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        try:
            self._sock.settimeout(timeout)
            wrapped = ssl_context.wrap_socket(self._sock, server_hostname=server_hostname)
        except ssl.SSLError as exc:
            self.close()
            raise _TLSFailure("tls handshake failed") from exc
        except OSError as exc:
            self.close()
            raise _TLSFailure("tls handshake failed") from exc
        return _PinnedSocketStream(wrapped)

    def get_extra_info(self, info: str) -> object:
        if info == "socket":
            return self._sock
        if info == "client_addr":
            return self._sock.getsockname()
        if info == "server_addr":
            return self._sock.getpeername()
        if info == "ssl_object" and isinstance(self._sock, ssl.SSLSocket):
            return self._sock._sslobj  # type: ignore[attr-defined]
        return None


class _PinnedNetworkBackend(httpcore.NetworkBackend):
    def __init__(self, selected_ip: str) -> None:
        self.selected_ip = selected_ip
        self.connect_calls: list[tuple[str, int]] = []

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        self.connect_calls.append((host, port))
        address = ipaddress.ip_address(self.selected_ip)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            if local_address is not None:
                sock.bind((local_address, 0))
            if socket_options is not None:
                for option in socket_options:
                    sock.setsockopt(*option)
            peer: tuple[Any, ...]
            if address.version == 6:
                peer = (self.selected_ip, port, 0, 0)
            else:
                peer = (self.selected_ip, port)
            sock.connect(peer)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return _PinnedSocketStream(sock)
        except TimeoutError as exc:
            sock.close()
            raise httpcore.ConnectTimeout("connect timeout") from exc
        except OSError as exc:
            sock.close()
            raise httpcore.ConnectError("connection failed") from exc


def build_ssl_context(ca_bundle: str | None = None) -> ssl.SSLContext:
    """Create mandatory-verification context with additive deployment trust."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if hasattr(ssl, "OP_NO_EARLY_DATA"):
        context.options |= ssl.OP_NO_EARLY_DATA
    if ca_bundle is not None:
        path = ca_bundle
        if not path.startswith("/"):
            raise TLSConfigurationError
        try:
            context.load_verify_locations(cafile=path)
        except (OSError, ssl.SSLError):
            raise TLSConfigurationError from None
    return context


@dataclass(frozen=True, slots=True)
class _Observation:
    status_code: int
    headers: dict[str, str]
    body: bytes | None
    source_bytes_captured: int
    truncated: bool
    redaction_unavailable: bool
    location: str | None = None


class HTTPTransportAdapter:
    """Dispatch one request through the locked, version-coupled httpcore seam."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        deployment_policy: DeploymentTargetPolicy | None = None,
        ca_bundle: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        dns_executor: Executor | None = None,
    ) -> None:
        # The pinned-IP backend uses httpcore's network seam deliberately. The
        # exact lockfile version is guarded here so an upgrade cannot silently
        # reintroduce hostname resolution, pooling, proxy, or retry behavior.
        if httpcore.__version__ != "1.0.9":
            raise RuntimeError("unsupported httpcore version")
        self.resolver = resolver or SystemResolver()
        self.deployment_policy = deployment_policy or DeploymentTargetPolicy()
        self.ssl_context = build_ssl_context(ca_bundle)
        self.clock = clock
        self.dns_executor = dns_executor

    def dispatch(self, request: PreparedRequest) -> TransportResult:
        if not request.verify_tls:
            raise PreparationError("tls_verification_required")
        deadline = self.clock() + request.timeout_ms / 1000
        current_url = request.url
        method = request.method
        body = request.body
        headers = dict(request.headers)
        previous_response = False
        redirects = 0
        last_observation: _Observation | None = None
        while True:
            try:
                target = resolve_target(
                    current_url,
                    resolver=self.resolver,
                    environment_policy=request.target_policy,
                    deployment_policy=self.deployment_policy,
                    timeout=max(0.0, deadline - self.clock()),
                    executor=self.dns_executor,
                )
            except DNSFailure as error:
                if error.code == "dns_timeout":
                    return self._failure(
                        TransportOutcome.DNS_FAILURE
                        if previous_response
                        else TransportOutcome.TOTAL_TIMEOUT,
                        DispatchCertainty.RESPONSE_RECEIVED
                        if previous_response
                        else DispatchCertainty.POSSIBLY_SENT,
                        last_observation,
                        not_sent_proof=None,
                    )
                return self._failure(
                    TransportOutcome.DNS_FAILURE,
                    DispatchCertainty.RESPONSE_RECEIVED
                    if previous_response
                    else DispatchCertainty.NOT_SENT,
                    last_observation,
                    not_sent_proof="dns_failure" if not previous_response else None,
                )
            except TargetDenied as error:
                if previous_response:
                    return self._failure(
                        TransportOutcome.REDIRECT_DENIED,
                        DispatchCertainty.RESPONSE_RECEIVED,
                        last_observation,
                        redirect_code=self._redirect_code(error.code),
                    )
                return self._failure(
                    TransportOutcome.TARGET_DENIED,
                    DispatchCertainty.NOT_SENT,
                    None,
                    not_sent_proof="target_denied",
                )

            try:
                response, backend = self._send(
                    target,
                    method=method,
                    headers=headers,
                    body=body,
                    request=request,
                    deadline=deadline,
                )
            except _TotalTimeout:
                return self._failure(
                    TransportOutcome.TOTAL_TIMEOUT,
                    DispatchCertainty.POSSIBLY_SENT,
                    last_observation,
                )
            except httpcore.ConnectTimeout:
                return self._failure(
                    TransportOutcome.CONNECT_TIMEOUT,
                    DispatchCertainty.RESPONSE_RECEIVED
                    if previous_response
                    else DispatchCertainty.NOT_SENT,
                    last_observation,
                    not_sent_proof="connect_timeout" if not previous_response else None,
                )
            except _TLSFailure:
                return self._failure(
                    TransportOutcome.TLS_FAILURE,
                    DispatchCertainty.RESPONSE_RECEIVED
                    if previous_response
                    else DispatchCertainty.NOT_SENT,
                    last_observation,
                    not_sent_proof="tls_failure" if not previous_response else None,
                )
            except httpcore.ConnectError:
                return self._failure(
                    TransportOutcome.CONNECTION_FAILURE,
                    DispatchCertainty.RESPONSE_RECEIVED
                    if previous_response
                    else DispatchCertainty.NOT_SENT,
                    last_observation,
                    not_sent_proof="connection_failure" if not previous_response else None,
                )
            except httpcore.WriteTimeout:
                return self._failure(
                    TransportOutcome.WRITE_TIMEOUT,
                    DispatchCertainty.POSSIBLY_SENT,
                    last_observation,
                )
            except httpcore.WriteError:
                return self._failure(
                    TransportOutcome.WRITE_FAILURE,
                    DispatchCertainty.POSSIBLY_SENT,
                    last_observation,
                )
            except httpcore.ReadTimeout:
                return self._failure(
                    TransportOutcome.READ_TIMEOUT,
                    DispatchCertainty.POSSIBLY_SENT,
                    last_observation,
                )
            except httpcore.ReadError:
                return self._failure(
                    TransportOutcome.READ_FAILURE,
                    DispatchCertainty.POSSIBLY_SENT,
                    last_observation,
                )
            except Exception:
                return self._failure(
                    TransportOutcome.INDETERMINATE,
                    DispatchCertainty.POSSIBLY_SENT,
                    last_observation,
                )

            try:
                observation = self._read_observation(response, request, deadline)
            except _ReadObservationFailure as error:
                response.close()
                return self._failure(
                    error.outcome,
                    DispatchCertainty.RESPONSE_RECEIVED,
                    error.observation,
                )
            finally:
                response.close()
            last_observation = observation
            status = observation.status_code
            location = observation.location
            if not request.follow_redirects or status not in _REDIRECT_STATUSES:
                return self._response(observation)
            if method not in _SAFE_REDIRECT_METHODS:
                return self._failure(
                    TransportOutcome.REDIRECT_DENIED,
                    DispatchCertainty.RESPONSE_RECEIVED,
                    observation,
                    redirect_code=RedirectRejectionCode.METHOD_NOT_ALLOWED,
                )
            if redirects >= request.max_redirects:
                return self._failure(
                    TransportOutcome.REDIRECT_DENIED,
                    DispatchCertainty.RESPONSE_RECEIVED,
                    observation,
                    redirect_code=RedirectRejectionCode.REDIRECT_LIMIT_EXCEEDED,
                )
            if location is None or not location.strip():
                return self._failure(
                    TransportOutcome.REDIRECT_DENIED,
                    DispatchCertainty.RESPONSE_RECEIVED,
                    observation,
                    redirect_code=RedirectRejectionCode.LOCATION_MISSING,
                )
            try:
                next_url, next_host, _ = canonical_url(urljoin(current_url, location))
                old_url, old_host, old_port = canonical_url(current_url)
                next_scheme = urlsplit(next_url).scheme
                if old_url.startswith("https:") and next_scheme != "https":
                    raise TargetDenied("scheme_denied")
            except TargetDenied as error:
                return self._failure(
                    TransportOutcome.REDIRECT_DENIED,
                    DispatchCertainty.RESPONSE_RECEIVED,
                    observation,
                    redirect_code=self._redirect_code(error.code),
                )
            except (ValueError, UnicodeError):
                return self._failure(
                    TransportOutcome.REDIRECT_DENIED,
                    DispatchCertainty.RESPONSE_RECEIVED,
                    observation,
                    redirect_code=RedirectRejectionCode.LOCATION_INVALID,
                )
            origin_changed = (urlsplit(old_url).scheme, old_host, old_port) != (
                urlsplit(next_url).scheme,
                next_host,
                urlsplit(next_url).port or (443 if urlsplit(next_url).scheme == "https" else 80),
            )
            if origin_changed:
                headers = {
                    name: value
                    for name, value in headers.items()
                    if name.lower() not in _FIXED_CREDENTIAL_HEADERS
                    and name.lower() not in request.secret_derived_headers
                }
            headers.pop("host", None)
            headers = {
                name: value
                for name, value in headers.items()
                if name.lower() not in _CONTENT_HEADERS
            }
            body = None
            if status == 303:
                method = "GET" if method in {"GET", "OPTIONS"} else "HEAD"
            current_url = next_url
            previous_response = True
            redirects += 1

    def _send(
        self,
        target: ResolvedTarget,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        request: PreparedRequest,
        deadline: float,
    ) -> tuple[httpcore.Response, _PinnedNetworkBackend]:
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise _TotalTimeout
        backend = _PinnedNetworkBackend(target.selected_ip)
        try:
            target_ip = ipaddress.ip_address(target.hostname)
        except ValueError:
            authority = target.hostname
        else:
            authority = f"[{target_ip}]" if target_ip.version == 6 else str(target_ip)
        if target.port != (443 if target.scheme == "https" else 80):
            authority = f"{authority}:{target.port}"
        wire_headers = [
            (name, value)
            for name, value in headers.items()
            if name.lower() not in {"host", "proxy-authorization"}
        ]
        wire_headers.append(("Host", authority))
        connection = httpcore.HTTPConnection(
            origin=httpcore.Origin(target.scheme.encode(), target.hostname.encode(), target.port),
            ssl_context=self.ssl_context,
            keepalive_expiry=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=backend,
        )
        timeout = {
            "connect": min(request.connect_timeout_ms / 1000, remaining),
            "read": min(request.read_timeout_ms / 1000, remaining),
            "write": min(request.timeout_ms / 1000, remaining),
            "pool": min(request.timeout_ms / 1000, remaining),
        }
        http_request = httpcore.Request(
            method,
            target.url,
            headers=wire_headers,
            content=body,
            extensions={"sni_hostname": target.hostname, "timeout": timeout},
        )
        try:
            return connection.handle_request(http_request), backend
        except Exception:
            connection.close()
            raise

    def _read_observation(
        self, response: httpcore.Response, request: PreparedRequest, deadline: float
    ) -> _Observation:
        headers = {
            name.decode("latin-1"): value.decode("latin-1") for name, value in response.headers
        }
        chunks = bytearray()
        truncated = False
        try:
            for chunk in response.iter_stream():
                if self.clock() >= deadline:
                    raise _ReadObservationFailure(
                        TransportOutcome.TOTAL_TIMEOUT,
                        self._redacted_observation(
                            response, request, bytes(chunks), truncated, headers
                        ),
                    )
                remaining = request.max_response_bytes - len(chunks)
                if remaining <= 0:
                    truncated = True
                    break
                chunks.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated = True
                    break
                if self.clock() >= deadline:
                    raise _ReadObservationFailure(
                        TransportOutcome.TOTAL_TIMEOUT,
                        self._redacted_observation(
                            response, request, bytes(chunks), truncated, headers
                        ),
                    )
        except _ReadObservationFailure:
            raise
        except httpcore.ReadTimeout:
            raise _ReadObservationFailure(
                TransportOutcome.READ_TIMEOUT,
                self._redacted_observation(response, request, bytes(chunks), truncated, headers),
            ) from None
        except httpcore.ReadError:
            raise _ReadObservationFailure(
                TransportOutcome.READ_FAILURE,
                self._redacted_observation(response, request, bytes(chunks), truncated, headers),
            ) from None
        except Exception:
            raise _ReadObservationFailure(
                TransportOutcome.READ_FAILURE,
                self._redacted_observation(response, request, bytes(chunks), truncated, headers),
            ) from None
        return self._redacted_observation(response, request, bytes(chunks), truncated, headers)

    def _redacted_observation(
        self,
        response: httpcore.Response,
        request: PreparedRequest,
        body: bytes,
        truncated: bool,
        headers: dict[str, str],
    ) -> _Observation:
        safe_headers = {
            key: self._mask_secret(value, request.secret_values) for key, value in headers.items()
        }
        body = self._mask_secret_bytes(body, request.secret_values)
        redacted = redact_observation(
            status_code=response.status,
            headers=safe_headers,
            body=body,
            max_bytes=request.max_response_bytes,
            json_pointers=request.redaction_json_pointers,
            header_names=request.redaction_header_names,
        )
        safe_body: bytes | None = None
        if redacted.body_content is not None:
            if redacted.body_kind == "bytes":
                safe_body = str(redacted.body_content).encode("ascii")
            elif redacted.body_kind == "text":
                safe_body = str(redacted.body_content).encode("utf-8")
            else:
                from sentinel.regression.policy import canonical_json

                safe_body = canonical_json(redacted.body_content).encode("utf-8")
        return _Observation(
            status_code=redacted.status_code,
            headers=redacted.headers,
            body=safe_body,
            source_bytes_captured=redacted.source_bytes_captured,
            truncated=truncated or redacted.truncated,
            redaction_unavailable=redacted.redaction_unavailable,
            location=self._header(headers, "location"),
        )

    @staticmethod
    def _mask_secret(value: str, secrets: Sequence[str]) -> str:
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value

    @staticmethod
    def _mask_secret_bytes(value: bytes, secrets: Sequence[str]) -> bytes:
        for secret in secrets:
            if secret:
                value = value.replace(secret.encode("utf-8"), b"[REDACTED]")
        return value

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str | None:
        for key, value in headers.items():
            if key.lower() == name:
                return value
        return None

    @staticmethod
    def _redirect_code(code: str) -> RedirectRejectionCode:
        try:
            return RedirectRejectionCode(code)
        except ValueError:
            return RedirectRejectionCode.TARGET_DENIED

    @staticmethod
    def _response(observation: _Observation) -> TransportResult:
        return TransportResult(
            TransportOutcome.RESPONSE_LIMIT_EXCEEDED
            if observation.truncated
            else TransportOutcome.RESPONSE_RECEIVED,
            DispatchCertainty.RESPONSE_RECEIVED,
            observation.status_code,
            observation.headers,
            observation.body,
            observation.source_bytes_captured,
            observation.truncated,
            None,
            observation.redaction_unavailable,
            None,
        )

    @staticmethod
    def _failure(
        outcome: TransportOutcome,
        certainty: DispatchCertainty,
        observation: _Observation | None,
        *,
        not_sent_proof: str | None = None,
        redirect_code: RedirectRejectionCode | None = None,
    ) -> TransportResult:
        return TransportResult(
            outcome,
            certainty,
            observation.status_code if observation is not None else None,
            observation.headers if observation is not None else {},
            observation.body if observation is not None else None,
            observation.source_bytes_captured if observation is not None else 0,
            observation.truncated if observation is not None else False,
            redirect_code,
            observation.redaction_unavailable if observation is not None else False,
            not_sent_proof,
        )
