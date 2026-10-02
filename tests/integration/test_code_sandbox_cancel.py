"""Live: Stop kills a running sandbox program; the session and /work survive."""

import json
import threading
import time

import pytest

from src.agent import cancellation
from src.agent.tool_results import set_current_request_id
from src.agent.tools.context import set_conversation_context
from tests.integration.test_code_sandbox_isolation import _sandbox_runnable


@pytest.mark.skipif(not _sandbox_runnable(), reason="Docker or sandbox image unavailable")
def test_stop_kills_sleep_and_keeps_work_dir() -> None:
    from src.agent.tools.code_execution import execute_code

    set_conversation_context("conv-cancel-test", "user-cancel-test")
    set_current_request_id("req-live")
    token = cancellation.register_token("req-live")
    try:
        execute_code.invoke({"code": "open('/work/keep.txt','w').write('kept')"})
        threading.Timer(2.0, token.cancel).start()
        started = time.monotonic()
        execute_code.invoke({"code": "import time; time.sleep(30)"})
        elapsed = time.monotonic() - started
    finally:
        cancellation.unregister_token("req-live")

    set_current_request_id("req-live-2")
    after = json.loads(execute_code.invoke({"code": "print(open('/work/keep.txt').read())"}))
    assert elapsed < 10
    assert "kept" in after["stdout"]


_LIST_SLEEPERS = (
    "import os\n"
    "n = sum(open(f'/proc/{p}/cmdline', 'rb').read().startswith(b'sleep')"
    " for p in os.listdir('/proc') if p.isdigit())\n"
    "print(f'sleepers: {n}')"
)


@pytest.mark.skipif(not _sandbox_runnable(), reason="Docker or sandbox image unavailable")
def test_stop_kills_child_processes_of_user_code() -> None:
    """A child without /sandbox/ in its argv (here `sleep`) must die too, or it
    lingers in the pooled container after the turn ended."""
    from src.agent.tools.code_execution import execute_code

    set_conversation_context("conv-cancel-child", "user-cancel-test")
    set_current_request_id("req-live-child")
    token = cancellation.register_token("req-live-child")
    try:
        threading.Timer(2.0, token.cancel).start()
        started = time.monotonic()
        execute_code.invoke({"code": "import subprocess; subprocess.run(['sleep', '30'])"})
        elapsed = time.monotonic() - started
    finally:
        cancellation.unregister_token("req-live-child")

    set_current_request_id("req-live-child-2")
    after = json.loads(execute_code.invoke({"code": _LIST_SLEEPERS}))
    assert elapsed < 10
    assert after["stdout"].strip() == "sleepers: 0"
