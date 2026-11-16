"""The code sandbox: one Docker container per session, over docker-py.

Replaced llm-sandbox on Nov 16 2026 (agent safety,
docs/superpowers/specs/2026-11-16-agent-safety-design.md). Code runs as a
non-root user (10001) with no capabilities but KILL (the Stop kill runs as
root), a process cap, no network, a read-only root filesystem and
memory-backed /work, /output and /tmp - a full disk is a failed write inside
the sandbox, counted against its memory limit, never the host's disk (the
production host's ext4 cannot quota a container).

Docker's copy cannot see tmpfs nor write a read-only root, so files move
differently: the app writes code and incoming files into a per-session host
directory bind-mounted read-only at /staging (the sandbox user cannot write
it), an exec as the sandbox user copies them into /work, and files come out
through an exec ``cat``. During a fork bomb a new exec may fail to start;
the kill then falls back to ``docker kill`` and the session is dropped.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

SANDBOX_UID = 10001  # not a likely host uid: a host file it owns stays foreign
SANDBOX_USER = f"{SANDBOX_UID}:{SANDBOX_UID}"
STAGING_MOUNT = "/staging"
OWNER_PID_LABEL = "moneypenny.owner_pid"  # the reaper finds a dead worker's containers

# Seconds the Stop kill and the exec it ends get before docker kill
_KILL_GRACE_SECONDS = 5.0

# Kills the user's program inside a live session container without touching
# the container: /work must survive a Stop. Spares PID 1 (docker-init), its
# oldest child (the container's keep-alive command) and itself; everything
# else is user code - exec'd programs, their children (whatever their argv)
# and orphans re-parented to PID 1. No procps in the slim image, so scan
# /proc from Python (always present in the image).
_KILL_USER_CODE = (
    "import os\n"
    "me = os.getpid()\n"
    "procs = {}\n"
    "for p in filter(str.isdigit, os.listdir('/proc')):\n"
    "    try:\n"
    "        stat = open(f'/proc/{p}/stat').read().rsplit(')', 1)[1].split()\n"
    "        procs[int(p)] = (int(stat[1]), int(stat[19]))\n"
    "    except OSError:\n"
    "        pass\n"
    "init_children = [p for p, (ppid, _) in procs.items() if ppid == 1]\n"
    "keep = {1, me}\n"
    "if init_children:\n"
    "    keep.add(min(init_children, key=lambda p: procs[p][1]))\n"
    "for p in procs.keys() - keep:\n"
    "    try:\n"
    "        os.kill(p, 9)\n"
    "    except OSError:\n"
    "        pass\n"
)


class SandboxTimeoutError(TimeoutError):
    """The code ran past its time limit and was killed."""


@dataclass
class ExecResult:
    """A finished run: what the program printed and how it ended."""

    exit_code: int
    stdout: str
    stderr: str


def sandbox_container_config(staging_dir: str) -> dict[str, Any]:
    """Every constraint the sandbox container runs under (docker-py run kwargs)."""
    owned = f"uid={SANDBOX_UID},gid={SANDBOX_UID},mode=0755"
    return {
        "user": SANDBOX_USER,
        "network_disabled": True,
        "mem_limit": Config.CODE_SANDBOX_MEMORY_LIMIT,
        "nano_cpus": int(Config.CODE_SANDBOX_CPU_LIMIT * 1_000_000_000),
        "pids_limit": Config.CODE_SANDBOX_PIDS_LIMIT,
        "cap_drop": ["ALL"],
        "cap_add": ["KILL"],
        "security_opt": ["no-new-privileges"],
        "read_only": True,
        "tmpfs": {
            "/work": f"size={Config.CODE_SANDBOX_WORK_MB}m,{owned}",
            "/output": f"size={Config.CODE_SANDBOX_OUTPUT_MB}m,{owned}",
            "/tmp": f"size={Config.CODE_SANDBOX_TMP_MB}m,mode=1777",  # noqa: S108 - the container's own /tmp
        },
        "volumes": {staging_dir: {"bind": STAGING_MOUNT, "mode": "ro"}},
        # An init (tini) as PID 1: without it SIGTERM is ignored and every
        # teardown waits the ~10 s docker-stop grace (measured)
        "init": True,
    }


def docker_client() -> Any:
    """A docker-py client from the environment (imported lazily: kept off startup;
    by name, since mypy resolves ``docker`` to the repo's docker/ directory)."""
    import importlib  # noqa: PLC0415 - lazy by design

    return importlib.import_module("docker").from_env()


class DockerSandbox:
    """One sandbox container and its staging directory."""

    def __init__(self, client: Any, image: str, staging_root: Path) -> None:
        self._client = client
        self._image = image
        self._names = itertools.count(1)
        self.container: Any = None
        self.staging_dir = staging_root / f"{os.getpid()}-{uuid.uuid4().hex[:12]}"
        self.alive = False

    def open(self) -> None:
        self.staging_dir.mkdir(parents=True, mode=0o755)
        self.staging_dir.chmod(0o755)  # mkdir's mode is masked by the umask
        self.container = self._client.containers.run(
            self._image,
            ["tail", "-f", "/dev/null"],  # keep-alive (the kill spares it)
            detach=True,
            labels={OWNER_PID_LABEL: str(os.getpid())},
            **sandbox_container_config(str(self.staging_dir)),
        )
        self.alive = True

    def close(self) -> None:
        self.alive = False
        if self.container is not None:
            with contextlib.suppress(Exception):
                self.container.remove(force=True)
        shutil.rmtree(self.staging_dir, ignore_errors=True)

    def _stage(self, prefix: str, data: bytes) -> Path:
        path = self.staging_dir / f"{prefix}-{next(self._names)}"
        path.write_bytes(data)
        path.chmod(0o644)
        return path

    def run(self, code: str, timeout_s: float) -> ExecResult:
        """Run a Python script as the sandbox user in /work.

        Raises SandboxTimeoutError after ``timeout_s`` (the program is killed).
        """
        script = self._stage("code", code.encode())
        outcome: list[Any] = []

        def _exec() -> None:
            try:
                outcome.append(
                    self.container.exec_run(
                        ["python", f"{STAGING_MOUNT}/{script.name}"],
                        user=SANDBOX_USER,
                        workdir="/work",
                        demux=True,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - re-raised on the caller's thread
                outcome.append(exc)

        worker = threading.Thread(target=_exec, daemon=True, name="sandbox-exec")
        try:
            worker.start()
            worker.join(timeout_s)
            if worker.is_alive():
                self.kill_user_code()
                worker.join(_KILL_GRACE_SECONDS)
                raise SandboxTimeoutError(f"timed out after {timeout_s:g} s")
        finally:
            script.unlink(missing_ok=True)
        [result] = outcome
        if isinstance(result, Exception):
            raise result
        stdout, stderr = result.output
        return ExecResult(
            exit_code=int(result.exit_code),
            stdout=(stdout or b"").decode("utf-8", errors="replace"),
            stderr=(stderr or b"").decode("utf-8", errors="replace"),
        )

    def put_file(self, data: bytes, dest: str) -> None:
        """Copy bytes into the sandbox at ``dest`` (owned by the sandbox user)."""
        staged = self._stage("in", data)
        try:
            result = self.container.exec_run(
                [
                    "sh",
                    "-c",
                    'mkdir -p "$(dirname "$1")" && cp "$2" "$1"',
                    "sh",
                    dest,
                    f"{STAGING_MOUNT}/{staged.name}",
                ],
                user=SANDBOX_USER,
                demux=True,
            )
        finally:
            staged.unlink(missing_ok=True)
        if result.exit_code != 0:
            _, stderr = result.output
            raise OSError(f"copy into the sandbox failed: {(stderr or b'').decode()[:200]}")

    def read_file(self, path: str) -> bytes:
        """The bytes of a file in the sandbox (FileNotFoundError if unreadable)."""
        result = self.container.exec_run(["cat", path], user=SANDBOX_USER, demux=True)
        stdout, stderr = result.output
        if result.exit_code != 0:
            raise FileNotFoundError(f"{path}: {(stderr or b'').decode()[:200]}")
        return bytes(stdout or b"")

    def work_bytes(self) -> int | None:
        """How much /work holds (None when it cannot be measured)."""
        try:
            result = self.container.exec_run(["du", "-sb", "/work"], user=SANDBOX_USER)
            return int(result.output.split()[0]) if result.exit_code == 0 else None
        except Exception:  # noqa: BLE001 - telemetry never fails a run
            return None

    def kill_user_code(self) -> None:
        """SIGKILL the running program; ``docker kill`` when no exec can start."""
        try:
            self.container.exec_run(["python", "-c", _KILL_USER_CODE], user="root")
        except Exception:
            logger.warning("Sandbox kill exec failed - killing the container", exc_info=True)
            self.alive = False
            with contextlib.suppress(Exception):
                self.container.kill()


def reap_staging_dirs(staging_root: Path, pid_alive: Callable[[int], bool]) -> int:
    """Remove staging dirs (``<pid>-<id>``) whose owner process has died."""
    removed = 0
    if not staging_root.is_dir():
        return 0
    for entry in staging_root.iterdir():
        owner, _, rest = entry.name.partition("-")
        if not (entry.is_dir() and owner.isdigit() and rest) or pid_alive(int(owner)):
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1
    return removed
