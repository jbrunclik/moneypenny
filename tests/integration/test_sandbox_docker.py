"""Live checks of the sandbox's safety constraints (Nov 16 2026).

Runs only where Docker and the sandbox image are available. Non-root, a
read-only root, a capped memory-backed /work, a process cap, files in and
out through staging and exec, and Stop
(docs/superpowers/specs/2026-11-16-agent-safety-design.md).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent.tools.docker_sandbox import DockerSandbox, docker_client
from src.config import Config


def _sandbox_runnable() -> bool:
    try:
        result = subprocess.run(
            ["docker", "images", "-q", Config.CODE_SANDBOX_IMAGE],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except FileNotFoundError, subprocess.TimeoutExpired:
        return False


pytestmark = pytest.mark.skipif(
    not _sandbox_runnable(), reason="Docker or sandbox image unavailable"
)


@pytest.fixture
def box(tmp_path: Path) -> Iterator[DockerSandbox]:
    sandbox = DockerSandbox(docker_client(), Config.CODE_SANDBOX_IMAGE, tmp_path)
    sandbox.open()
    try:
        yield sandbox
    finally:
        sandbox.close()


def _run(box: DockerSandbox, code: str, timeout_s: float = 30) -> str:
    result = box.run(code, timeout_s=timeout_s)
    return result.stdout + result.stderr


def test_code_runs_as_the_sandbox_user_in_work(box: DockerSandbox) -> None:
    assert _run(box, "import os; print(os.getuid(), os.getcwd())").strip() == "10001 /work"


def test_the_root_filesystem_is_read_only(box: DockerSandbox) -> None:
    out = _run(box, "open('/etc/x', 'w')")
    assert "Read-only file system" in out


def test_a_full_work_dir_fails_inside_and_the_sandbox_lives(box: DockerSandbox) -> None:
    out = _run(
        box,
        "f = open('/work/big', 'wb')\n"
        "try:\n"
        "    for _ in range(300): f.write(b'0' * 1024 * 1024)\n"
        "except OSError as e: print('ENOSPC', e.errno)\n",
    )
    assert "ENOSPC 28" in out
    assert _run(box, "import os; os.remove('/work/big'); print('alive')").strip() == "alive"


def test_a_fork_bomb_is_bounded(box: DockerSandbox) -> None:
    out = _run(
        box,
        "import os, time\n"
        "n = 0\n"
        "try:\n"
        "    while True:\n"
        "        if os.fork() == 0:\n"
        "            time.sleep(3); os._exit(0)\n"  # children hold their pid until the cap
        "        n += 1\n"
        "except OSError: print('capped at', n)\n",
    )
    assert "capped at" in out
    assert int(out.split("capped at")[1].split()[0]) < Config.CODE_SANDBOX_PIDS_LIMIT


def test_a_long_script_runs(box: DockerSandbox) -> None:
    code = "x = 1\n" * 40_000 + "print('done', len('" + "y" * 1000 + "'))"
    assert len(code) > 200_000
    assert _run(box, code).strip() == "done 1000"


def test_files_go_in_and_come_out_byte_identical(box: DockerSandbox) -> None:
    data = os.urandom(3_000_000)
    box.put_file(data, "/work/attachments/a.bin")
    out = _run(
        box,
        "import hashlib, shutil\n"
        "print(hashlib.sha256(open('/work/attachments/a.bin','rb').read()).hexdigest())\n"
        "shutil.copy('/work/attachments/a.bin', '/output/b.bin')\n",
    )
    assert out.strip() == hashlib.sha256(data).hexdigest()
    assert box.read_file("/output/b.bin") == data


def test_the_sandbox_cannot_write_staging(box: DockerSandbox) -> None:
    out = _run(box, "open('/staging/x', 'w')")
    assert "Read-only file system" in out
    assert not (box.staging_dir / "x").exists()


def test_stop_kills_the_program_and_keeps_work(box: DockerSandbox) -> None:
    _run(box, "open('/work/keep.txt', 'w').write('kept')")
    killer = threading.Timer(1.0, box.kill_user_code)
    killer.start()
    started = time.monotonic()
    result = box.run("import time; time.sleep(60)", timeout_s=30)  # what the Stop cuts short
    assert time.monotonic() - started < 10
    assert result.exit_code != 0
    assert _run(box, "print(open('/work/keep.txt').read())").strip() == "kept"


def test_close_leaves_no_container_or_staging(tmp_path: Path) -> None:
    sandbox = DockerSandbox(docker_client(), Config.CODE_SANDBOX_IMAGE, tmp_path)
    sandbox.open()
    container_id = sandbox.container.id
    sandbox.close()
    assert list(tmp_path.iterdir()) == []
    ids = [c.id for c in docker_client().containers.list(all=True)]
    assert container_id not in ids


def test_the_root_kill_does_not_run_planted_modules(box: DockerSandbox) -> None:
    """Sandbox code plants /work/os.py, /work/json.py and a usercustomize in the
    user site (HOME is /work) that would leave /tmp/ran-<uid> if imported by the
    root kill (security review, Nov 16 2026). Per-uid files: root holds no
    DAC capability, so it could not append to a file the sandbox user owns."""
    marker = "open(f\"/tmp/ran-{__import__('posix').getuid()}\", 'w').write('x')\n"
    _run(
        box,
        "import os, site\n"
        f"open('/work/os.py', 'w').write({marker!r})\n"
        f"open('/work/json.py', 'w').write({marker!r})\n"
        "p = site.getusersitepackages(); os.makedirs(p, exist_ok=True)\n"
        f"open(p + '/usercustomize.py', 'w').write({marker!r})\n",
    )
    box.kill_user_code()
    assert _run(box, "import os; print(os.path.exists('/tmp/ran-0'))").strip() == "False"


@pytest.mark.parametrize("name", ["../etc/passwd", "../dev/urandom", "fifo", "link"])
def test_reading_outputs_refuses_anything_but_a_small_regular_file(
    box: DockerSandbox, name: str
) -> None:
    """Output names come from stdout, which user code controls (review, Nov 16
    2026): a path outside /output, a device, a FIFO or a symlink must fail fast,
    never stream into the app worker or block it."""
    _run(
        box,
        "import os\nos.mkfifo('/output/fifo')\nos.symlink('/dev/urandom', '/output/link')\n",
    )
    started = time.monotonic()
    with pytest.raises(FileNotFoundError):
        box.read_file(f"/output/{name}")
    assert time.monotonic() - started < 15


def test_an_output_over_the_size_limit_is_refused(
    box: DockerSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Config, "MAX_FILE_SIZE_BYTES", 1000)
    _run(box, "open('/output/big.bin', 'wb').write(b'0' * 5000)")
    with pytest.raises(FileNotFoundError, match="too large"):
        box.read_file("/output/big.bin")
