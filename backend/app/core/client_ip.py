"""Trusted proxy aware client-IP resolution."""

from __future__ import annotations

from functools import lru_cache
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network

from fastapi import Request

from app.core.config import get_settings

IPAddress = IPv4Address | IPv6Address
IPNetwork = IPv4Network | IPv6Network


def _parse_ip(value: str) -> IPAddress | None:
    raw = value.strip().strip('"')
    if not raw:
        return None
    if raw.startswith("[") and "]" in raw:
        raw = raw[1 : raw.index("]")]
    elif raw.count(":") == 1 and "." in raw:
        host, _, port = raw.partition(":")
        if port.isdigit():
            raw = host
    try:
        return ip_address(raw)
    except ValueError:
        return None


@lru_cache(maxsize=64)
def _trusted_proxy_networks(raw: str) -> tuple[IPNetwork, ...]:
    networks: list[IPNetwork] = []
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        try:
            networks.append(ip_network(token, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted_proxy(ip: IPAddress, networks: tuple[IPNetwork, ...]) -> bool:
    return any(ip in network for network in networks)


def resolve_client_ip(
    request: Request,
    *,
    trusted_proxy_ips: str | None = None,
) -> str | None:
    """Resolve a client IP without trusting spoofable forwarding headers.

    ``X-Forwarded-For`` is considered only when the direct peer belongs to
    ``TRUSTED_PROXY_IPS``. The selected hop is the right-most untrusted IP,
    so a proxy-appended chain like ``spoofed, real-client`` resolves to
    ``real-client`` rather than the attacker-controlled left-most value. If
    every forwarded hop is trusted, the direct peer is returned because the
    chain does not contain a trustworthy client hop.
    """

    peer_host = request.client.host.strip() if request.client and request.client.host else ""
    if not peer_host:
        return None

    peer_ip = _parse_ip(peer_host)
    if trusted_proxy_ips is None:
        trusted_proxy_ips = get_settings().trusted_proxy_ips
    trusted_networks = _trusted_proxy_networks(trusted_proxy_ips)

    if peer_ip is None or not _is_trusted_proxy(peer_ip, trusted_networks):
        return peer_host

    forwarded_for = request.headers.get("x-forwarded-for", "")
    forwarded_ips = [
        parsed for part in forwarded_for.split(",") if (parsed := _parse_ip(part)) is not None
    ]
    for hop in reversed(forwarded_ips):
        if not _is_trusted_proxy(hop, trusted_networks):
            return str(hop)
    return peer_host


__all__ = ["resolve_client_ip"]
