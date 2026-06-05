"""Unit tests for src/agent/tools/url_safety (SSRF validation)."""

import socket
from unittest.mock import patch

from src.agent.tools.url_safety import BLOCKED_NETWORKS, validate_public_url


def _addrinfo(ip: str) -> list:
    """Build a getaddrinfo-style result for a single IPv4 address."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))]


def _resolve_to(ip: str):
    """Patch DNS resolution in url_safety to return a fixed IP."""
    return patch("src.agent.tools.url_safety.socket.getaddrinfo", return_value=_addrinfo(ip))


class TestScheme:
    def test_blocks_file_scheme(self) -> None:
        assert "http" in (validate_public_url("file:///etc/passwd") or "")

    def test_blocks_ftp_scheme(self) -> None:
        assert validate_public_url("ftp://example.com") is not None

    def test_blocks_javascript_scheme(self) -> None:
        assert validate_public_url("javascript:alert(1)") is not None

    def test_blocks_missing_scheme(self) -> None:
        assert validate_public_url("not-a-url") is not None

    def test_blocks_empty_hostname(self) -> None:
        assert validate_public_url("http://") is not None


class TestLiteralIPs:
    def test_allows_public_ip(self) -> None:
        assert validate_public_url("http://8.8.8.8") is None

    def test_blocks_loopback(self) -> None:
        assert "blocked" in (validate_public_url("http://127.0.0.1") or "").lower()

    def test_blocks_localhost_alias(self) -> None:
        assert "blocked" in (validate_public_url("http://localhost:8080") or "").lower()

    def test_blocks_private_10(self) -> None:
        assert validate_public_url("http://10.0.0.1") is not None

    def test_blocks_private_172(self) -> None:
        assert validate_public_url("http://172.16.0.1") is not None

    def test_blocks_private_192_168(self) -> None:
        assert validate_public_url("http://192.168.1.1") is not None

    def test_blocks_cloud_metadata_ip(self) -> None:
        assert validate_public_url("http://169.254.169.254/latest/meta-data") is not None

    def test_blocks_ipv6_loopback(self) -> None:
        assert validate_public_url("http://[::1]/") is not None


class TestHostnameResolution:
    def test_allows_hostname_resolving_to_public_ip(self) -> None:
        with _resolve_to("93.184.216.34"):
            assert validate_public_url("https://example.com/path") is None

    def test_blocks_hostname_resolving_to_private_ip(self) -> None:
        # DNS-rebinding / internal-pointing domain
        with _resolve_to("10.0.0.5"):
            error = validate_public_url("https://evil.example.com")
        assert error is not None
        assert "blocked" in error.lower()

    def test_blocks_hostname_resolving_to_metadata_ip(self) -> None:
        with _resolve_to("169.254.169.254"):
            assert validate_public_url("https://rebind.example.com") is not None

    def test_unresolvable_hostname_is_rejected(self) -> None:
        with patch(
            "src.agent.tools.url_safety.socket.getaddrinfo",
            side_effect=socket.gaierror("no such host"),
        ):
            error = validate_public_url("https://does-not-exist.invalid")
        assert error is not None
        assert "resolve" in error.lower()


def test_blocked_networks_populated() -> None:
    assert len(BLOCKED_NETWORKS) >= 5
