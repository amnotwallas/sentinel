from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from sentinel.catalog.environments import TargetPolicy
from sentinel.security.targets import (
    DeploymentTargetPolicy,
    DNSFailure,
    TargetDenied,
    resolve_target,
)


class StaticResolver:
    def __init__(self, addresses: tuple[str, ...]) -> None:
        self.addresses = addresses
        self.calls: list[tuple[str, int]] = []

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        return self.addresses


def local_policy(port: int) -> TargetPolicy:
    return TargetPolicy(allowed_ports=(port,))


def deployment_policy(port: int) -> DeploymentTargetPolicy:
    return DeploymentTargetPolicy(allowed_cidrs=("127.0.0.1/32",), allowed_ports=(port,))


def test_resolve_target_selects_only_the_validated_address() -> None:
    resolver = StaticResolver(("127.0.0.1",))
    target = resolve_target(
        "https://example.test:8443/probe",
        resolver=resolver,
        environment_policy=local_policy(8443),
        deployment_policy=deployment_policy(8443),
    )

    assert target.hostname == "example.test"
    assert target.selected_ip == "127.0.0.1"
    assert resolver.calls == [("example.test", 8443)]


def test_mixed_allowed_and_blocked_addresses_fail_closed() -> None:
    resolver = StaticResolver(("203.0.113.10", "127.0.0.1"))

    try:
        resolve_target(
            "https://example.test:8443/probe",
            resolver=resolver,
            environment_policy=local_policy(8443),
            deployment_policy=deployment_policy(8443),
        )
    except TargetDenied as exc:
        assert exc.code == "target_denied"
    else:
        raise AssertionError("mixed DNS answers were not rejected")


def test_explicit_deny_wins_over_an_allowlist() -> None:
    resolver = StaticResolver(("127.0.0.1",))
    environment = TargetPolicy(
        allowed_ports=(8443,),
        denied_hostnames=("example.test",),
    )
    try:
        resolve_target(
            "https://example.test:8443/probe",
            resolver=resolver,
            environment_policy=environment,
            deployment_policy=deployment_policy(8443),
        )
    except TargetDenied as exc:
        assert exc.code == "target_denied"
    else:
        raise AssertionError("explicit deny was bypassed")


def test_dns_timeout_uses_bounded_injected_executor() -> None:
    release = Event()

    class HangingResolver:
        def resolve(self, _hostname: str, _port: int) -> tuple[str, ...]:
            release.wait(1)
            return ("203.0.113.10",)

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        for _ in range(3):
            with pytest.raises(DNSFailure, match="dns_timeout"):
                resolve_target(
                    "https://example.test:8443/probe",
                    resolver=HangingResolver(),
                    environment_policy=local_policy(8443),
                    deployment_policy=deployment_policy(8443),
                    timeout=0.001,
                    executor=executor,
                )
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)
