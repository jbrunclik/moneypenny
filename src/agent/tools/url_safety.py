"""Shared URL safety validation for outbound-fetching tools (SSRF protection).

Used by both ``fetch_url`` (web.py) and the ``browser`` tool. Beyond rejecting
literal private/reserved IPs, this resolves the hostname via DNS and rejects it
if *any* resolved address falls in a blocked range — so a public-looking domain
that points at an internal/metadata IP is also blocked.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Private/reserved IP ranges to block (SSRF protection)
BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("10.0.0.0/8"),  # Private
    ipaddress.ip_network("172.16.0.0/12"),  # Private
    ipaddress.ip_network("192.168.0.0/16"),  # Private
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / cloud metadata
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

_LOCALHOST_ALIASES = {"localhost", "localhost.localdomain"}


def _blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the address is in a blocked range or otherwise non-public."""
    if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_reserved:
        return True
    return any(addr in network for network in BLOCKED_NETWORKS)


def validate_public_url(url: str) -> str | None:
    """Validate that a URL is safe to fetch. Returns an error message, or None if OK.

    Rejects non-http(s) schemes, missing hostnames, localhost aliases, literal
    private/reserved IPs, and hostnames that DNS-resolve to a blocked address.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return f"Invalid URL: {url}"

    if parsed.scheme not in ("http", "https"):
        return f"Only http:// and https:// URLs are allowed, got {parsed.scheme}://"

    hostname = parsed.hostname
    if not hostname:
        return "URL has no hostname."

    if hostname.lower() in _LOCALHOST_ALIASES:
        return f"Access to {hostname} is blocked."

    # Literal IP in the hostname
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        addr = None
    if addr is not None:
        if _blocked_ip(addr):
            return f"Access to {hostname} is blocked (private/reserved address)."
        return None

    # Hostname → resolve and check every address it points to
    try:
        infos = socket.getaddrinfo(hostname, parsed.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"Could not resolve hostname: {hostname}"

    for info in infos:
        ip_str = info[4][0]
        try:
            resolved = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _blocked_ip(resolved):
            logger.warning(
                "Blocked URL resolving to private/reserved address",
                extra={"hostname": hostname, "resolved_ip": ip_str},
            )
            return f"Access to {hostname} is blocked (resolves to a private/reserved address)."

    return None
