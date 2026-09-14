from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_HOSTS = frozenset({
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.google",
    "instance-data",
})

METADATA_NETWORKS = (
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)

MAX_REDIRECTS = 3
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT_SEC = 15.0


class UnsafeURLError(ValueError):
    pass


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.ipv6_mapped is not None:
        ip = ip.ipv6_mapped
    if any(ip in network for network in METADATA_NETWORKS):
        return True
    return not ip.is_global


def resolve_public_host(host: str) -> list[str]:
    cleaned = (host or "").strip().lower().rstrip(".")
    if not cleaned:
        raise UnsafeURLError("URL is missing a hostname")
    if cleaned in BLOCKED_HOSTS or cleaned.endswith(".localhost"):
        raise UnsafeURLError(f"Host {cleaned} is not allowed")
    try:
        literal = ipaddress.ip_address(cleaned)
    except ValueError:
        literal = None
    if literal is not None:
        if is_blocked_ip(literal):
            raise UnsafeURLError(f"Address {cleaned} is not a public host")
        return [cleaned]
    try:
        results = socket.getaddrinfo(cleaned, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve {cleaned}") from exc
    addresses: list[str] = []
    for item in results:
        sockaddr = item[4]
        if not sockaddr:
            continue
        ip_text = str(sockaddr[0])
        ip = ipaddress.ip_address(ip_text)
        if is_blocked_ip(ip):
            raise UnsafeURLError(f"Host {cleaned} resolves to a private or reserved address")
        if ip_text not in addresses:
            addresses.append(ip_text)
    if not addresses:
        raise UnsafeURLError(f"Host {cleaned} did not resolve to a public address")
    return addresses


def resolve_fetch_target(url: str, *, allow_http: bool = True) -> tuple[str, list[str]]:
    raw = (url or "").strip()
    if not raw:
        raise UnsafeURLError("URL is required")
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"https", "http"}:
        raise UnsafeURLError("Only HTTP and HTTPS URLs are allowed")
    if scheme == "http" and not allow_http:
        raise UnsafeURLError("Only HTTPS image URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs with credentials are not allowed")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise UnsafeURLError("URL is missing a hostname")
    if parsed.port in {22, 25, 3306, 5432, 6379, 11211, 27017}:
        raise UnsafeURLError("URL port is not allowed")
    return raw, resolve_public_host(host)


def validate_fetch_url(url: str, *, allow_http: bool = True) -> str:
    raw, _ = resolve_fetch_target(url, allow_http=allow_http)
    return raw
