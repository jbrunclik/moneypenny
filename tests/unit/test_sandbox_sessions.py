"""Tests for the per-conversation sandbox session pool."""

import pytest

from src.agent.tools.sandbox_sessions import SandboxSessionPool


class FakeSession:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True


def make_pool(**kwargs: object) -> SandboxSessionPool:
    defaults: dict[str, object] = {"factory": FakeSession, "max_sessions": 2, "ttl_seconds": 100}
    defaults.update(kwargs)
    return SandboxSessionPool(**defaults)  # type: ignore[arg-type]


class TestSandboxSessionPool:
    def test_session_reused_for_same_key(self) -> None:
        pool = make_pool()
        with pool.session("conv-1") as s1:
            pass
        with pool.session("conv-1") as s2:
            pass
        assert s1 is s2
        assert s1.opened
        assert not s1.closed

    def test_ephemeral_session_for_none_key_closed_after_use(self) -> None:
        pool = make_pool()
        with pool.session(None) as s:
            assert s.opened
        assert s.closed

    def test_distinct_keys_get_distinct_sessions(self) -> None:
        pool = make_pool()
        with pool.session("a") as sa:
            pass
        with pool.session("b") as sb:
            pass
        assert sa is not sb

    def test_lru_eviction_closes_oldest(self) -> None:
        pool = make_pool()
        with pool.session("a") as sa:
            pass
        with pool.session("b"):
            pass
        with pool.session("c"):
            pass  # capacity 2 - evicts "a"
        assert sa.closed
        # "a" now gets a fresh session
        with pool.session("a") as sa2:
            pass
        assert sa2 is not sa

    def test_broken_session_replaced(self) -> None:
        pool = make_pool()
        s1 = None
        with pytest.raises(RuntimeError):
            with pool.session("conv-1") as s1:
                raise RuntimeError("run failed")
        assert s1 is not None
        assert s1.closed
        with pool.session("conv-1") as s2:
            pass
        assert s2 is not s1

    def test_ttl_cleanup(self) -> None:
        pool = make_pool()
        with pool.session("a") as sa:
            pass
        pool._entries["a"].last_used -= 1000  # age past the 100s TTL
        assert pool.cleanup_expired() == 1
        assert sa.closed
        assert pool.cleanup_expired() == 0

    def test_close_all(self) -> None:
        pool = make_pool()
        with pool.session("a") as sa:
            pass
        with pool.session("b") as sb:
            pass
        pool.close_all()
        assert sa.closed
        assert sb.closed
