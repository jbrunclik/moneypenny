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
