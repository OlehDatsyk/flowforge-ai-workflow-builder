"""Server-side request forgery protection for outbound HTTP.

The URL's hostname is resolved once, every resulting address is checked, and the
connection is then pinned to a validated IP so a DNS-rebinding answer cannot
redirect the request after validation. Redirects are followed manually so each
hop is validated again (see nodes_integration.safe_request).
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..config import get_settings

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "instance-data.ec2.internal",
    "kubernetes.default",
    "kubernetes.default.svc",
}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa")
METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("192.0.0.192"),
    ipaddress.ip_address("fd00:ec2::254"),
}
ALLOWED_PORTS_NOTE = "Only http and https URLs are allowed"


class BlockedDestination(ValueError):
    pass


@dataclass
class ValidatedTarget:
    url: str
    scheme: str
    hostname: str
    port: int
    ip: str
    pinned: bool


def is_forbidden_ip(raw: str) -> str | None:
    """Returns the reason an address is forbidden, or None when it is public."""
    ip = ipaddress.ip_address(raw.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip.sixtofour:
            ip = ip.sixtofour
        elif ip.teredo:
            return "a tunnelled IPv6 address"
        elif ip in ipaddress.ip_network("64:ff9b::/96"):  # NAT64 embeds an IPv4 target
            ip = ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
    if ip in METADATA_IPS:
        return "a cloud metadata endpoint"
    if ip.is_loopback:
        return "a loopback address"
    if ip.is_link_local:
        return "a link-local address"
    if ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10"):
        return "a private network address"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return "a reserved address"
    if not ip.is_global:
        return "a non-public address"
    return None


def validate_url(url: str, resolver=None) -> ValidatedTarget:
    resolver = resolver or socket.getaddrinfo
    if not isinstance(url, str) or not url.strip():
        raise BlockedDestination("URL is empty")
    if len(url) > 4096:
        raise BlockedDestination("URL is too long")
    if any(ord(c) < 32 for c in url):
        raise BlockedDestination("URL contains control characters")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise BlockedDestination(ALLOWED_PORTS_NOTE)
    if parts.username or parts.password:
        raise BlockedDestination("Credentials in the URL are not allowed; use a stored credential")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedDestination("URL has no host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise BlockedDestination("URL has an invalid port") from exc

    allowlist = get_settings().private_host_allowlist
    allowed_exception = host in allowlist
    if not allowed_exception:
        if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
            raise BlockedDestination(f"Destination '{host}' is blocked: internal hostname")
        try:
            literal_reason = is_forbidden_ip(host.strip("[]"))
        except ValueError:
            literal_reason = None  # not an IP literal
        if literal_reason:
            raise BlockedDestination(f"Destination '{host}' is blocked: it is {literal_reason}")
    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedDestination(f"Could not resolve host '{host}'") from exc
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise BlockedDestination(f"Could not resolve host '{host}'")
    if not allowed_exception:
        for address in addresses:
            reason = is_forbidden_ip(address)
            if reason:
                raise BlockedDestination(f"Destination '{host}' is blocked: it resolves to {reason}")
    return ValidatedTarget(
        url=url.strip(), scheme=scheme, hostname=host, port=port, ip=addresses[0], pinned=not allowed_exception
    )


def validate_host(host: str, port: int) -> None:
    """Used by the SMTP client so it cannot be aimed at internal services either."""
    validate_url(f"https://{host}:{port}/")
