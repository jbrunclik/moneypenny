"""Live regression test for code-sandbox network isolation (S4).

Runs only where Docker and the sandbox image are available (developer
machines, prod-like hosts). Executes code inside the REAL sandbox that
attempts an outbound TCP connection and asserts it cannot succeed.
"""

import json
import subprocess

import pytest

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
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _sandbox_runnable(), reason="Docker or sandbox image unavailable")
def test_sockets_fail_inside_sandbox() -> None:
    from src.agent.tools.code_execution import execute_code

    code = """
import socket
try:
    socket.create_connection(("1.1.1.1", 53), timeout=5)
    print("NETWORK_OPEN")
except OSError as e:
    print(f"NETWORK_BLOCKED: {e}")
"""
    result = json.loads(execute_code.invoke({"code": code}))

    assert result.get("success") is True, f"sandbox execution failed: {result}"
    assert "NETWORK_BLOCKED" in result["stdout"]
    assert "NETWORK_OPEN" not in result["stdout"]
