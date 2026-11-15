"""Unit tests for src/agent/tools/url_safety (SSRF validation)."""

import socket
from typing import Any
from unittest.mock import patch

import httpx
import pytest

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

    def test_empty_resolution_fails_closed(self) -> None:
        """getaddrinfo returning no usable addresses must be rejected, not allowed."""
        with patch("src.agent.tools.url_safety.socket.getaddrinfo", return_value=[]):
            error = validate_public_url("https://weird.example.com")
        assert error is not None

    def test_blocks_cgnat_range(self) -> None:
        assert validate_public_url("http://100.64.0.1") is not None


def test_blocked_networks_populated() -> None:
    assert len(BLOCKED_NETWORKS) >= 5


class TestSSRFSafeTransport:
    """The connect-time transport re-checks the host before the request goes out."""

    def test_blocks_request_to_private_host(self) -> None:
        from src.agent.tools.url_safety import SSRFSafeTransport

        transport = SSRFSafeTransport()
        request = httpx.Request("GET", "http://127.0.0.1/")
        with pytest.raises(httpx.ConnectError, match="SSRF blocked"):
            transport.handle_request(request)


class TestFetchDeadline:
    """A page that sends a byte just inside httpx's per-read timeout must not
    keep its fetch (and research's worker thread) alive past a total
    deadline (security review, Nov 15 2026)."""

    def _transport_reply(self, chunks: list[bytes], clock: list[float], step: float) -> Any:
        import httpx

        from src.agent.tools import url_safety

        def dripping() -> Any:
            for chunk in chunks:
                clock[0] += step
                yield chunk

        def reply(_self: object, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=_Iter(dripping()), request=request)

        return patch.object(url_safety.httpx.HTTPTransport, "handle_request", reply)

    def test_a_dripping_body_hits_the_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        from src.agent.tools import url_safety

        clock = [0.0]
        monkeypatch.setattr(url_safety, "_monotonic", lambda: clock[0])
        monkeypatch.setattr(url_safety, "check_host", lambda *_: None)
        transport = url_safety.SSRFSafeTransport(deadline_s=10)
        with (
            self._transport_reply([b"x"] * 5, clock, step=4.0),
            pytest.raises(httpx.ReadTimeout),
            httpx.Client(transport=transport) as client,
        ):
            client.get("https://example.com/slow")

    def test_a_body_within_the_deadline_is_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        from src.agent.tools import url_safety

        clock = [0.0]
        monkeypatch.setattr(url_safety, "_monotonic", lambda: clock[0])
        monkeypatch.setattr(url_safety, "check_host", lambda *_: None)
        transport = url_safety.SSRFSafeTransport(deadline_s=10)
        with (
            self._transport_reply([b"ab", b"cd"], clock, step=1.0),
            httpx.Client(transport=transport) as client,
        ):
            assert client.get("https://example.com/ok").content == b"abcd"


class _Iter(httpx.SyncByteStream):
    """A sync byte stream over an iterator, as a real transport returns."""

    def __init__(self, chunks: Any) -> None:
        self._chunks = chunks

    def __iter__(self) -> Any:
        return iter(self._chunks)

    def close(self) -> None:
        pass


class TestFetchDeadlineIsShared:
    """One budget for the whole fetch: redirect hops share it, and a reply
    whose headers arrive after it is refused (security review)."""

    def test_hops_share_one_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.agent.tools import url_safety

        clock = [0.0]
        monkeypatch.setattr(url_safety, "_monotonic", lambda: clock[0])
        monkeypatch.setattr(url_safety, "check_host", lambda *_: None)
        transport = url_safety.SSRFSafeTransport(deadline_s=10)

        def reply(_self: object, request: httpx.Request) -> httpx.Response:
            clock[0] += 6  # each hop's headers take 6 s
            return httpx.Response(
                302, headers={"location": "https://example.com/next"}, request=request
            )

        with (
            patch.object(url_safety.httpx.HTTPTransport, "handle_request", reply),
            httpx.Client(transport=transport) as client,
        ):
            client.get("https://example.com/a")  # 6 s: within the budget
            with pytest.raises(httpx.ReadTimeout):
                client.get("https://example.com/next")  # 12 s: past it
