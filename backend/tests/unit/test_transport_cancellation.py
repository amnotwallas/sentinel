from __future__ import annotations

from collections.abc import Iterator

import httpcore
import pytest

from sentinel.catalog.environments import TargetPolicy
from sentinel.execution.ports import DispatchCancelled
from sentinel.execution.preparation import PreparedRequest
from sentinel.security.targets import DeploymentTargetPolicy
from sentinel.transport.http import HTTPTransportAdapter
from sentinel.worker.runtime import WorkerCancellation
from tests.unit.test_http_transport import (
    MappingResolver,
    adapter,
    server,
)
from tests.unit.test_http_transport import (
    request as transport_request,
)


class RecordingResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls += 1
        return ("127.0.0.1",)


def request() -> PreparedRequest:
    return PreparedRequest(
        method="GET",
        url="http://fixture.test/",
        headers={},
        body=None,
        timeout_ms=1000,
        connect_timeout_ms=1000,
        read_timeout_ms=1000,
        follow_redirects=False,
        max_redirects=0,
        verify_tls=True,
        max_response_bytes=1024,
        secret_derived_headers=frozenset(),
        target_policy=TargetPolicy(),
    )


def test_cancelled_dispatch_never_starts_dns_resolution() -> None:
    cancellation = WorkerCancellation()
    cancellation.cancel()
    resolver = RecordingResolver()
    adapter = HTTPTransportAdapter(
        resolver=resolver,
        deployment_policy=DeploymentTargetPolicy(
            allowed_cidrs=("127.0.0.1/32",), allowed_ports=(80,)
        ),
    )

    with pytest.raises(DispatchCancelled):
        adapter.dispatch_cancellable(request(), cancellation)

    assert resolver.calls == 0


def test_cancellation_after_resolution_prevents_socket_dispatch() -> None:
    class CancelBeforeSend(WorkerCancellation):
        def __init__(self) -> None:
            super().__init__()
            self.checks = 0

        def raise_if_cancelled(self) -> None:
            self.checks += 1
            if self.checks == 2:
                self.cancel()
            super().raise_if_cancelled()

    cancellation = CancelBeforeSend()
    resolver = RecordingResolver()
    transport = HTTPTransportAdapter(
        resolver=resolver,
        deployment_policy=DeploymentTargetPolicy(
            allowed_cidrs=("127.0.0.1/32",), allowed_ports=(80,)
        ),
    )

    with pytest.raises(DispatchCancelled):
        transport.dispatch_cancellable(request(), cancellation)

    assert resolver.calls == 1


def test_cancellation_is_checked_before_each_redirect_resolution() -> None:
    class CancelAtSecondHop(WorkerCancellation):
        def __init__(self) -> None:
            super().__init__()
            self.checks = 0

        def raise_if_cancelled(self) -> None:
            self.checks += 1
            if self.checks == 5:
                self.cancel()
            super().raise_if_cancelled()

    instance, port, requests = server((302, {"Location": "http://second.test/done"}, b""))
    resolver = MappingResolver({"fixture.test": ("127.0.0.1",), "second.test": ("127.0.0.1",)})
    cancellation = CancelAtSecondHop()
    try:
        with pytest.raises(DispatchCancelled):
            adapter(port, resolver).dispatch_cancellable(
                transport_request(f"http://fixture.test:{port}/", follow_redirects=True),
                cancellation,
            )
    finally:
        instance.shutdown()
        instance.server_close()
    assert len(requests) == 1
    assert resolver.calls == ["fixture.test"]


def test_cancellation_during_response_streaming_is_not_classified_as_transport_failure() -> None:
    cancellation = WorkerCancellation()

    def stream() -> Iterator[bytes]:
        yield b"first"
        cancellation.cancel()
        yield b"second"

    response = httpcore.Response(200, content=stream())
    transport = HTTPTransportAdapter(
        resolver=RecordingResolver(),
        deployment_policy=DeploymentTargetPolicy(
            allowed_cidrs=("127.0.0.1/32",), allowed_ports=(80,)
        ),
    )

    with pytest.raises(DispatchCancelled):
        transport._read_observation(response, request(), 10**12, cancellation)
