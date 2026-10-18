"""DNS resolution and target-policy enforcement for outbound dispatch."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Sequence
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

from sentinel.catalog.environments import TargetPolicy

_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)
_DEFAULT_ALLOWED_PORTS = frozenset({80, 443})
_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sentinel-dns")


class TargetResolutionError(ValueError):
    """Stable, sanitized resolver or URL failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DNSFailure(TargetResolutionError):
    def __init__(self, code: str = "dns_failure") -> None:
        super().__init__(code)


class TargetDenied(TargetResolutionError):
    def __init__(self, code: str = "target_denied") -> None:
        super().__init__(code)


Address = ipaddress.IPv4Address | ipaddress.IPv6Address
Network = ipaddress.IPv4Network | ipaddress.IPv6Network


class Resolver(Protocol):
    """Resolver port. Implementations return every address observed for a host."""

    def resolve(self, hostname: str, port: int) -> Sequence[str]:
        raise NotImplementedError


class SystemResolver(Resolver):
    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        try:
            records = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except OSError:
            raise DNSFailure from None
        addresses = tuple(dict.fromkeys(str(record[4][0]) for record in records))
        if not addresses:
            raise DNSFailure
        return addresses


@dataclass(frozen=True, slots=True)
class DeploymentTargetPolicy:
    allowed_hostnames: tuple[str, ...] = ()
    allowed_cidrs: tuple[str, ...] = ()
    denied_hostnames: tuple[str, ...] = ()
    denied_cidrs: tuple[str, ...] = ()
    allowed_ports: tuple[int, ...] | None = tuple(sorted(_DEFAULT_ALLOWED_PORTS))

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_hostnames",
            tuple(sorted(_canonical_hostname(value) for value in self.allowed_hostnames)),
        )
        object.__setattr__(
            self,
            "denied_hostnames",
            tuple(sorted(_canonical_hostname(value) for value in self.denied_hostnames)),
        )
        object.__setattr__(
            self,
            "allowed_cidrs",
            tuple(
                sorted(
                    str(ipaddress.ip_network(value, strict=True)) for value in self.allowed_cidrs
                )
            ),
        )
        object.__setattr__(
            self,
            "denied_cidrs",
            tuple(
                sorted(str(ipaddress.ip_network(value, strict=True)) for value in self.denied_cidrs)
            ),
        )
        if self.allowed_ports is not None:
            if any(not 1 <= port <= 65535 for port in self.allowed_ports):
                raise ValueError("invalid deployment port")
            object.__setattr__(self, "allowed_ports", tuple(sorted(set(self.allowed_ports))))


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    scheme: str
    hostname: str
    port: int
    url: str
    addresses: tuple[str, ...]
    selected_ip: str


def _canonical_hostname(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        return str(address)
    try:
        return value.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        raise TargetDenied from None


def _parse_url(url: str) -> tuple[SplitResult, str, int]:
    try:
        parsed = urlsplit(url)
        hostname_raw = parsed.hostname
        if parsed.username is not None or parsed.password is not None or not hostname_raw:
            raise TargetDenied
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise TargetDenied
        hostname = _canonical_hostname(hostname_raw)
        port = parsed.port or (443 if scheme == "https" else 80)
    except (ValueError, UnicodeError):
        raise TargetDenied from None
    return parsed, hostname, port


def canonical_url(url: str) -> tuple[str, str, int]:
    parsed, hostname, port = _parse_url(url)
    host_for_url = hostname
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        host_for_url = f"[{ip}]" if ip.version == 6 else str(ip)
    authority = host_for_url
    if port != (443 if parsed.scheme.lower() == "https" else 80):
        authority = f"{authority}:{port}"
    normalized = urlunsplit(
        (parsed.scheme.lower(), authority, parsed.path or "/", parsed.query, "")
    )
    return normalized, hostname, port


def _network(value: str) -> Network:
    return ipaddress.ip_network(value, strict=True)


def _matches(address: Address, networks: tuple[str, ...]) -> bool:
    return any(address in _network(network) for network in networks)


def _blocked_by_default(address: Address) -> bool:
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or not address.is_global
        or address in _METADATA_ADDRESSES
    )


def _validate_addresses(
    hostname: str,
    addresses: Sequence[str],
    environment_policy: TargetPolicy,
    deployment_policy: DeploymentTargetPolicy,
) -> tuple[str, ...]:
    normalized: list[Address] = []
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise TargetDenied from None
        if address not in normalized:
            normalized.append(address)
    if not normalized:
        raise DNSFailure
    denied_hosts = set(environment_policy.denied_hostnames) | set(
        deployment_policy.denied_hostnames
    )
    if hostname in denied_hosts:
        raise TargetDenied
    allowed_host = hostname in set(environment_policy.allowed_hostnames) | set(
        deployment_policy.allowed_hostnames
    )
    for address in normalized:
        explicitly_denied = _matches(
            address,
            tuple(environment_policy.denied_cidrs) + tuple(deployment_policy.denied_cidrs),
        )
        explicitly_allowed = allowed_host or _matches(
            address,
            tuple(environment_policy.allowed_cidrs) + tuple(deployment_policy.allowed_cidrs),
        )
        if explicitly_denied or (_blocked_by_default(address) and not explicitly_allowed):
            raise TargetDenied
    return tuple(
        str(address) for address in sorted(normalized, key=lambda item: (item.version, int(item)))
    )


def resolve_target(
    url: str,
    *,
    resolver: Resolver,
    environment_policy: TargetPolicy,
    deployment_policy: DeploymentTargetPolicy,
    timeout: float | None = None,
    executor: Executor | None = None,
) -> ResolvedTarget:
    normalized_url, hostname, port = canonical_url(url)
    allowed_ports = deployment_policy.allowed_ports
    if allowed_ports is not None and port not in allowed_ports:
        raise TargetDenied("port_denied")
    if (
        environment_policy.allowed_ports is not None
        and port not in environment_policy.allowed_ports
    ):
        raise TargetDenied("port_denied")
    try:
        if timeout is None:
            addresses = resolver.resolve(hostname, port)
        else:
            dns_executor = executor or _DNS_EXECUTOR
            future: Future[Sequence[str]] = dns_executor.submit(resolver.resolve, hostname, port)
            try:
                addresses = future.result(timeout=max(0.0, timeout))
            except FutureTimeout:
                future.cancel()
                raise DNSFailure("dns_timeout") from None
    except DNSFailure:
        raise
    except Exception:
        raise DNSFailure from None
    validated = _validate_addresses(hostname, addresses, environment_policy, deployment_policy)
    return ResolvedTarget(
        scheme=normalized_url.split(":", 1)[0],
        hostname=hostname,
        port=port,
        url=normalized_url,
        addresses=validated,
        selected_ip=validated[0],
    )
