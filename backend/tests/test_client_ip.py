"""Tests for trusted-proxy client-IP resolution."""

from __future__ import annotations

from starlette.requests import Request

from app.core.client_ip import resolve_client_ip


def _request(*, client_host: str, x_forwarded_for: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if x_forwarded_for is not None:
        headers.append((b"x-forwarded-for", x_forwarded_for.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (client_host, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def test_resolve_client_ip_ignores_x_forwarded_for_from_untrusted_peer() -> None:
    request = _request(
        client_host="192.0.2.44",
        x_forwarded_for="198.51.100.10",
    )

    assert resolve_client_ip(request, trusted_proxy_ips="") == "192.0.2.44"


def test_resolve_client_ip_uses_rightmost_untrusted_hop_from_trusted_proxy() -> None:
    request = _request(
        client_host="10.0.0.10",
        x_forwarded_for="203.0.113.200, 198.51.100.7",
    )

    assert resolve_client_ip(request, trusted_proxy_ips="10.0.0.0/24") == "198.51.100.7"


def test_resolve_client_ip_skips_trusted_proxy_hops_from_right() -> None:
    request = _request(
        client_host="10.0.0.10",
        x_forwarded_for="198.51.100.7, 10.0.0.20",
    )

    assert resolve_client_ip(request, trusted_proxy_ips="10.0.0.0/24") == "198.51.100.7"


def test_resolve_client_ip_uses_peer_when_all_forwarded_hops_are_trusted() -> None:
    request = _request(
        client_host="10.0.0.10",
        x_forwarded_for="10.0.0.40, 10.0.0.20",
    )

    assert resolve_client_ip(request, trusted_proxy_ips="10.0.0.0/24") == "10.0.0.10"
