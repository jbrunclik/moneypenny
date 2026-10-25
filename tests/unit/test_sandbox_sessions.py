"""Tests for the per-conversation sandbox session pool."""

import os

import pytest

from src.agent.tools.sandbox_sessions import (
    OWNER_PID_LABEL,
    SandboxSessionPool,
    reap_orphaned_containers,
)


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
        with pytest.raises(RuntimeError), pool.session("conv-1") as s1:  # noqa: F811 - pre-set: the assert must not NameError
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


class FakeContainer:
    def __init__(self, name: str, owner_pid: str) -> None:
        self.name = name
        self.labels = {OWNER_PID_LABEL: owner_pid}
        self.removed = False

    def remove(self, force: bool = False) -> None:
        self.removed = force


class FakeDockerClient:
    def __init__(self, containers: list[FakeContainer]) -> None:
        self._containers = containers
        self.list_kwargs: dict[str, object] = {}
        self.containers = self

    def list(self, **kwargs: object) -> list[FakeContainer]:
        self.list_kwargs = kwargs
        return self._containers


class TestOrphanReaping:
    """A killed process (SIGTERM/SIGKILL skip atexit) strands its pooled
    containers; the next pool start removes those whose owner is gone."""

    def test_containers_are_labelled_with_owner_pid(self) -> None:
        from src.agent.tools.code_execution import _sandbox_runtime_configs

        labels = _sandbox_runtime_configs()["labels"]
        assert labels[OWNER_PID_LABEL] == str(os.getpid())

    def test_removes_containers_whose_owner_died(self) -> None:
        dead = FakeContainer("dead", "111")
        alive = FakeContainer("alive", "222")
        client = FakeDockerClient([dead, alive])

        removed = reap_orphaned_containers(client, pid_alive=lambda pid: pid == 222)

        assert removed == 1
        assert dead.removed
        assert not alive.removed
        assert client.list_kwargs == {"all": True, "filters": {"label": OWNER_PID_LABEL}}

    def test_keeps_container_with_unparseable_owner(self) -> None:
        odd = FakeContainer("odd", "not-a-pid")

        assert reap_orphaned_containers(FakeDockerClient([odd]), pid_alive=lambda _: False) == 0
        assert not odd.removed
