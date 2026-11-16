"""Our own sandbox session over docker-py (replaces llm-sandbox, Nov 16 2026).

Non-root, no capabilities but KILL, a process cap, a read-only root and
memory-backed folders; code and files go in through a read-only staging
bind mount (docs/superpowers/specs/2026-11-16-agent-safety-design.md).
These tests use a fake Docker client; tests/integration/test_sandbox_docker.py
runs the real thing.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.agent.tools.docker_sandbox import (
    SANDBOX_USER,
    DockerSandbox,
    SandboxTimeoutError,
    reap_staging_dirs,
    sandbox_container_config,
)
from src.config import Config


class FakeContainer:
    def __init__(self) -> None:
        self.execs: list[dict[str, Any]] = []
        self.removed = False
        self.killed = False
        self.block = threading.Event()
        self.hang = False
        self.exec_fails_for_root = False
        self.outputs: dict[str, tuple[int, bytes, bytes]] = {}

    def exec_run(self, cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        self.execs.append({"cmd": cmd, **kwargs})
        if kwargs.get("user") == "root" and self.exec_fails_for_root:
            raise RuntimeError("OCI runtime exec failed: Resource temporarily unavailable")
        if cmd[0] == "python" and cmd[1].startswith("/staging/") and self.hang:
            self.block.wait(5)
        code, out, err = self.outputs.get(cmd[0], (0, b"ok\n", b""))
        return SimpleNamespace(exit_code=code, output=(out, err))

    def kill(self) -> None:
        self.killed = True
        self.block.set()

    def remove(self, force: bool = False) -> None:
        self.removed = True


class FakeClient:
    def __init__(self) -> None:
        self.container = FakeContainer()
        self.run_kwargs: dict[str, Any] = {}
        self.containers = SimpleNamespace(run=self._run)

    def _run(self, image: str, command: list[str], **kwargs: Any) -> FakeContainer:
        self.run_kwargs = {"image": image, "command": command, **kwargs}
        return self.container


@pytest.fixture
def sandbox(tmp_path: Path) -> DockerSandbox:
    box = DockerSandbox(FakeClient(), "img:test", tmp_path)
    box.open()
    return box


def _container(box: DockerSandbox) -> FakeContainer:
    container = box.container
    assert isinstance(container, FakeContainer)
    return container


def test_the_container_carries_every_constraint(tmp_path: Path) -> None:
    config = sandbox_container_config(str(tmp_path / "s1"))
    assert config["user"] == SANDBOX_USER == "10001:10001"
    assert config["network_disabled"] is True
    assert config["read_only"] is True
    assert config["pids_limit"] == 128
    assert config["cap_drop"] == ["ALL"]
    assert config["cap_add"] == ["KILL"]
    assert config["security_opt"] == ["no-new-privileges"]
    assert config["mem_limit"] == Config.CODE_SANDBOX_MEMORY_LIMIT
    assert config["init"] is True
    assert config["tmpfs"] == {
        "/work": "size=256m,uid=10001,gid=10001,mode=0755",
        "/output": "size=64m,uid=10001,gid=10001,mode=0755",
        "/tmp": "size=64m,mode=1777",
    }
    assert config["volumes"] == {str(tmp_path / "s1"): {"bind": "/staging", "mode": "ro"}}


def test_run_execs_the_staged_code_as_the_sandbox_user(sandbox: DockerSandbox) -> None:
    result = sandbox.run("print('hi')", timeout_s=5)
    [call] = _container(sandbox).execs
    assert call["cmd"][0] == "python"
    assert call["cmd"][1].startswith("/staging/code-")
    assert call["user"] == SANDBOX_USER
    assert call["workdir"] == "/work"
    assert call["demux"] is True
    assert (result.exit_code, result.stdout) == (0, "ok\n")
    assert list(sandbox.staging_dir.iterdir()) == []  # the code file is removed


def test_the_staged_code_file_is_readable_by_the_sandbox_user(
    sandbox: DockerSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []
    container = _container(sandbox)
    original = container.exec_run

    def spy(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        path = sandbox.staging_dir / Path(cmd[1]).name
        seen.append(path.stat().st_mode & 0o777)
        assert path.read_text() == "print('hi')"
        return original(cmd, **kwargs)

    monkeypatch.setattr(container, "exec_run", spy)
    sandbox.run("print('hi')", timeout_s=5)
    assert seen == [0o644]
    assert sandbox.staging_dir.stat().st_mode & 0o777 == 0o755


def test_a_timeout_kills_the_user_code(sandbox: DockerSandbox) -> None:
    container = _container(sandbox)
    container.hang = True
    with pytest.raises(SandboxTimeoutError):
        sandbox.run("while True: pass", timeout_s=0.2)
    assert any(call.get("user") == "root" for call in container.execs)


def test_a_kill_that_cannot_start_kills_the_container(sandbox: DockerSandbox) -> None:
    container = _container(sandbox)
    container.exec_fails_for_root = True
    sandbox.kill_user_code()
    assert container.killed
    assert not sandbox.alive


def test_put_file_copies_through_staging_as_the_sandbox_user(sandbox: DockerSandbox) -> None:
    sandbox.put_file(b"data", "/work/attachments/a.pdf")
    [call] = _container(sandbox).execs
    assert call["user"] == SANDBOX_USER
    assert call["cmd"][-2:][0] == "/work/attachments/a.pdf"
    assert call["cmd"][-1].startswith("/staging/in-")
    assert list(sandbox.staging_dir.iterdir()) == []


def test_put_file_raises_when_the_copy_fails(sandbox: DockerSandbox) -> None:
    _container(sandbox).outputs["sh"] = (1, b"", b"No space left on device")
    with pytest.raises(OSError, match="No space left"):
        sandbox.put_file(b"data", "/work/attachments/a.pdf")


def test_read_file_returns_the_bytes(sandbox: DockerSandbox) -> None:
    _container(sandbox).outputs["sh"] = (0, b"\x00\x01binary", b"")
    assert sandbox.read_file("/output/x.bin") == b"\x00\x01binary"


def test_read_file_of_a_missing_file_raises(sandbox: DockerSandbox) -> None:
    _container(sandbox).outputs["sh"] = (2, b"", b"not a regular file")
    with pytest.raises(FileNotFoundError):
        sandbox.read_file("/output/missing")


def test_close_removes_the_container_and_the_staging_dir(sandbox: DockerSandbox) -> None:
    staging = sandbox.staging_dir
    sandbox.close()
    assert _container(sandbox).removed
    assert not staging.exists()


def test_reap_removes_staging_dirs_of_dead_owners(tmp_path: Path) -> None:
    (tmp_path / "111-aaaa").mkdir()
    (tmp_path / "222-bbbb").mkdir()
    (tmp_path / "unrelated").mkdir()
    removed = reap_staging_dirs(tmp_path, pid_alive=lambda pid: pid == 222)
    assert removed == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["222-bbbb", "unrelated"]


def test_the_root_kill_cannot_load_code_the_sandbox_planted(sandbox: DockerSandbox) -> None:
    """HOME is /work and `python -c` puts the cwd first on sys.path: a planted
    /work/os.py or user site-package would run as root. Isolated mode (-I: no
    PYTHON* env, no user site, no cwd on the path), no site, cwd /, HOME /root
    (security review, Nov 16 2026)."""
    sandbox.kill_user_code()
    [call] = _container(sandbox).execs
    assert call["user"] == "root"
    assert call["cmd"][:4] == ["python", "-I", "-S", "-c"]
    assert call["workdir"] == "/"
    assert call["environment"] == {"HOME": "/root"}


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "/output/../etc/passwd", "/output/a/b", "/output/"]
)
def test_read_file_refuses_paths_outside_output(sandbox: DockerSandbox, path: str) -> None:
    with pytest.raises(FileNotFoundError):
        sandbox.read_file(path)
    assert _container(sandbox).execs == []
