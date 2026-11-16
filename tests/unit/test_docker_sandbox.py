"""Our own sandbox session over docker-py (replaces llm-sandbox, Nov 16 2026).

Non-root, no capabilities but KILL, a process cap, a read-only root and
memory-backed folders; code and files go in through a read-only staging
bind mount (docs/superpowers/specs/2026-11-16-agent-safety-design.md).
These tests use a fake Docker client; tests/integration/test_sandbox_docker.py
runs the real thing.
"""

from __future__ import annotations

import re
import threading
import time
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
        self.id = "c1"
        self.execs: list[dict[str, Any]] = []
        self.removed = False
        self.killed = False
        self.exec_fails_for_root = False
        self.root_exec_hangs = False
        self.kill_hangs = False
        self.remove_hangs = False
        self.release = threading.Event()
        self.outputs: dict[str, tuple[int, bytes, bytes]] = {}

    def exec_run(self, cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        self.execs.append({"cmd": cmd, **kwargs})
        if kwargs.get("user") == "root" and self.exec_fails_for_root:
            raise RuntimeError("OCI runtime exec failed: Resource temporarily unavailable")
        if kwargs.get("user") == "root" and self.root_exec_hangs:
            self.release.wait(10)
        code, out, err = self.outputs.get(cmd[0], (0, b"ok\n", b""))
        return SimpleNamespace(exit_code=code, output=(out, err))

    def kill(self) -> None:
        if self.kill_hangs:
            self.release.wait(10)
        self.killed = True

    def remove(self, force: bool = False) -> None:
        if self.remove_hangs:
            self.release.wait(10)
        self.removed = True


class FakeApi:
    """docker-py's low-level exec API: the run streams its output."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.chunks: list[tuple[bytes | None, bytes | None]] = [(b"ok\n", None)]
        self.exit_code = 0
        self.hang = threading.Event()
        self.hangs = False

    def exec_create(self, container: str, cmd: list[str], **kwargs: Any) -> dict[str, str]:
        self.created.append({"container": container, "cmd": cmd, **kwargs})
        return {"Id": f"e{len(self.created)}"}

    def exec_start(self, exec_id: str, stream: bool, demux: bool) -> Any:
        assert stream and demux
        if self.hangs:
            self.hang.wait(10)
        yield from self.chunks

    def exec_inspect(self, exec_id: str) -> dict[str, Any]:
        return {"ExitCode": self.exit_code}


class FakeClient:
    def __init__(self) -> None:
        self.container = FakeContainer()
        self.api = FakeApi()
        self.run_kwargs: dict[str, Any] = {}
        self.fail_run = False
        self.containers = SimpleNamespace(run=self._run)

    def _run(self, image: str, command: list[str], **kwargs: Any) -> FakeContainer:
        if self.fail_run:
            raise RuntimeError("No such image")
        self.run_kwargs = {"image": image, "command": command, **kwargs}
        return self.container


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def sandbox(tmp_path: Path, client: FakeClient) -> DockerSandbox:
    box = DockerSandbox(client, "img:test", tmp_path)
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


def test_run_execs_the_staged_code_as_the_sandbox_user(
    sandbox: DockerSandbox, client: FakeClient
) -> None:
    client.api.exit_code = 3
    result = sandbox.run("print('hi')", timeout_s=5)
    [call] = client.api.created
    assert call["container"] == "c1"
    assert call["cmd"][0] == "python"
    assert call["cmd"][1].startswith("/staging/code-")
    assert call["user"] == SANDBOX_USER
    assert call["workdir"] == "/work"
    assert (result.exit_code, result.stdout) == (3, "ok\n")
    assert list(sandbox.staging_dir.iterdir()) == []  # the code file is removed


def test_the_staged_code_is_readable_but_its_dir_unlistable(
    sandbox: DockerSandbox, client: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Other host users cannot list staging, and names carry a random token
    (review: staged code was world-readable on the host)."""
    seen: list[tuple[str, int, str]] = []
    original = client.api.exec_create

    def spy(container: str, cmd: list[str], **kwargs: Any) -> dict[str, str]:
        path = sandbox.staging_dir / Path(cmd[1]).name
        seen.append((path.name, path.stat().st_mode & 0o777, path.read_text()))
        return original(container, cmd, **kwargs)

    monkeypatch.setattr(client.api, "exec_create", spy)
    sandbox.run("print('hi')", timeout_s=5)
    [(name, mode, text)] = seen
    assert (mode, text) == (0o644, "print('hi')")
    assert re.fullmatch(r"code-1-[0-9a-f]{16}\.py", name)
    assert sandbox.staging_dir.stat().st_mode & 0o777 == 0o711


def test_output_past_the_cap_is_dropped_not_buffered(
    sandbox: DockerSandbox, client: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.agent.tools.docker_sandbox as module

    monkeypatch.setattr(module, "OUTPUT_CAP_BYTES", 10)
    client.api.chunks = [(b"a" * 8, None), (b"b" * 8, b"e" * 4), (b"c" * 100, None)]
    result = sandbox.run("spam()", timeout_s=5)
    assert result.stdout.startswith("a" * 8 + "bb")
    assert "[output past 10 bytes dropped]" in result.stdout
    assert result.stderr == "eeee"


def test_a_timeout_kills_the_user_code(sandbox: DockerSandbox, client: FakeClient) -> None:
    client.api.hangs = True
    with pytest.raises(SandboxTimeoutError):
        sandbox.run("while True: pass", timeout_s=0.2)
    assert any(call.get("user") == "root" for call in _container(sandbox).execs)


def test_a_wedged_docker_bounds_the_timeout(
    sandbox: DockerSandbox, client: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exec, kill exec and docker kill all hanging (review: up to ~3 min on
    docker-py's 60 s timeouts) - the run still gives up within its grace."""
    import src.agent.tools.docker_sandbox as module

    monkeypatch.setattr(module, "KILL_GRACE_SECONDS", 0.2)
    client.api.hangs = True
    container = _container(sandbox)
    container.root_exec_hangs = True
    container.kill_hangs = True
    started = time.monotonic()
    with pytest.raises(SandboxTimeoutError):
        sandbox.run("while True: pass", timeout_s=0.2)
    assert time.monotonic() - started < 1.5
    assert not sandbox.alive
    container.release.set()
    client.api.hang.set()


def test_a_kill_that_cannot_start_kills_the_container(sandbox: DockerSandbox) -> None:
    container = _container(sandbox)
    container.exec_fails_for_root = True
    sandbox.kill_user_code()
    assert container.killed
    assert not sandbox.alive


def test_a_failed_open_leaves_no_staging_dir(tmp_path: Path) -> None:
    client = FakeClient()
    client.fail_run = True
    box = DockerSandbox(client, "img:test", tmp_path)
    with pytest.raises(RuntimeError):
        box.open()
    assert list(tmp_path.iterdir()) == []


def test_close_does_not_wait_for_a_wedged_docker(sandbox: DockerSandbox) -> None:
    container = _container(sandbox)
    container.remove_hangs = True
    staging = sandbox.staging_dir
    started = time.monotonic()
    sandbox.close()
    assert time.monotonic() - started < 0.5
    assert not staging.exists()
    container.release.set()


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
