"""Browser automation tool using Playwright for JavaScript-capable web browsing.

The `browser` tool validates arguments and dispatches actions (single or
batched, see browser_steps.py) to the Playwright worker thread in
browser_worker.py.
"""

import base64
import json
import os
import threading
from typing import Any

from langchain_core.tools import tool

from src.agent.tool_results import get_current_request_id, store_tool_result
from src.agent.tools.attachment import guess_mime_type
from src.agent.tools.browser_steps import (
    BrowserStep,
    frame_page_text,
    run_batch,
    validate_action,
    validate_batch,
    worker_kwargs,
)
from src.agent.tools.browser_worker import (
    BrowserWorker,
    browser_launch_args,
    get_worker,
    start_cleanup_thread,
)
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.permission_check import check_autonomous_permission
from src.agent.tools.web_content import wrap_untrusted_content
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# ============ URL Validation ============

# ============ Availability Check ============

# per-worker: a cached probe of this host's Chromium, the same answer in every worker
_browser_available: bool | None = None


_browser_available_lock = threading.Lock()


def is_browser_available() -> bool:
    """Check if Playwright is installed and Chromium browser is available.

    Caches the result to avoid repeated checks. Double-checked locking: two
    gthread request threads racing the first check would each launch a probe
    Chromium concurrently.
    """
    global _browser_available
    if _browser_available is not None:
        return _browser_available
    with _browser_available_lock:
        if _browser_available is not None:
            return _browser_available
        return _probe_browser_available()


def _probe_browser_available() -> bool:
    """Run the actual Playwright/Chromium probe (callers hold the lock)."""
    global _browser_available

    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 - optional dependency, probed here
    except ImportError:
        _browser_available = False
        logger.info("Playwright not installed — browser tool disabled")
        return False

    # Verify Chromium is actually installed (not just the Python package).
    # MUST probe with the same args the worker uses: a sandboxed probe on a
    # host that cannot run the sandbox would disable the tool even when
    # BROWSER_NO_SANDBOX is set (and vice versa would enable it and then
    # have the worker fail).
    try:
        pw = sync_playwright().start()
        try:
            br = pw.chromium.launch(headless=True, args=browser_launch_args())
            br.close()
            _browser_available = True
            logger.info("Playwright + Chromium available — browser tool enabled")
        except Exception as e:  # any launch failure disables the tool
            _browser_available = False
            logger.warning(
                "Chromium not installed or not launchable",
                extra={
                    "error": str(e),
                    "hint": (
                        "Run 'make browser-setup' to install Chromium. If the error "
                        "mentions the sandbox (e.g. 'No usable sandbox'), either enable "
                        "unprivileged user namespaces on the host or set "
                        "BROWSER_NO_SANDBOX=true"
                    ),
                },
                exc_info=True,
            )
        finally:
            pw.stop()
    except Exception as e:  # any startup failure disables the tool
        _browser_available = False
        logger.warning("Playwright startup failed", extra={"error": str(e)}, exc_info=True)

    return _browser_available


# ============ Main Tool ============


def _format_screenshot_internal(ss_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Format a screenshot as multimodal content for the LLM to see (no attachment)."""
    return [
        {
            "type": "text",
            "text": f"Screenshot of {ss_data['url']} ({ss_data['size']} bytes, JPEG):",
        },
        {
            "type": "image",
            "base64": ss_data["data"],
            "mime_type": "image/jpeg",
        },
    ]


def _save_screenshot_attachment(ss_data: dict[str, Any]) -> None:
    """Save a screenshot as a file attachment for the user via the tool results system."""
    request_id = get_current_request_id()
    if request_id is None:
        return

    attachment_json = json.dumps(
        {
            "browser_screenshot": True,
            "_full_result": {
                "files": [
                    {
                        "name": "screenshot.jpg",
                        "mime_type": "image/jpeg",
                        "data": ss_data["data"],
                        "size": ss_data["size"],
                    }
                ]
            },
        }
    )
    store_tool_result(request_id, attachment_json)


@tool
def browser(
    action: str | None = None,
    url: str | None = None,
    selector: str | None = None,
    text: str | None = None,
    screenshot: bool = False,
    share_screenshot: bool = False,
    wait_for: str | None = None,
    timeout_ms: int | None = None,
    actions: list[BrowserStep] | None = None,
) -> str | list[dict[str, Any]]:
    """Browse the web with a full browser that renders JavaScript.

    Use when a page needs JavaScript or interaction, or fetch_url returned
    incomplete/empty content. The session persists within the conversation.
    Pass EITHER `action` (one) OR `actions` (a batch). Never enter passwords or
    credentials into web forms. Before the first browser call of a task, call
    load_skill('browser-tactics') - batching, selectors, screenshots, budget.

    Actions: navigate (`url`), click (`selector`), type (`selector`, `text`),
    press (`text` = key: Enter, Escape, Tab, ArrowDown, Control+A; optional
    `selector` to focus), select (`selector` of a <select>, `text` = option label or
    value), download (`selector` of the link/button; the file is attached to the
    reply - single action only), screenshot, extract (page text as markdown),
    scroll (optional `selector`), back, close.

    Args:
        action: The browser action to perform (omit when passing `actions`)
        url: URL to navigate to (required for navigate)
        selector: CSS selector for the target element (required for click/type)
        text: Text to type (type), key name (press), option (select)
        screenshot: If True, take a screenshot after the action (visible to you only)
        share_screenshot: If True, also share the screenshot with the user as a file attachment
        wait_for: CSS selector to wait for after the action completes
        timeout_ms: Custom timeout in milliseconds for this action
        actions: A batch of steps to run in order in this one call (instead of `action`)
    """
    steps = [BrowserStep.model_validate(s) for s in actions] if actions is not None else None
    check_autonomous_permission("browser", _permission_args(action, url, steps))

    error = _availability_error() or _call_shape_error(action, steps)
    if error:
        return error

    conversation_id, _ = get_conversation_context()
    conversation_id = conversation_id or "__default__"

    if steps is not None:
        batch_error = validate_batch(steps)
        if batch_error:
            return tool_error(batch_error)
        return _run_steps(conversation_id, steps, screenshot, share_screenshot)

    step = BrowserStep(
        action=str(action), url=url, selector=selector, text=text,
        wait_for=wait_for, timeout_ms=timeout_ms,
    )  # fmt: skip
    step_error = validate_action(step.action, url, selector, text)
    if step_error:
        return tool_error(step_error)
    return _run_single(conversation_id, step, screenshot, share_screenshot)


def _permission_args(
    action: str | None, url: str | None, steps: list[BrowserStep] | None
) -> dict[str, Any]:
    if steps is None:
        return {"action": action, "url": url}
    return {"action": "batch", "urls": [s.url for s in steps if s.url]}


def _availability_error() -> str | None:
    if not Config.BROWSER_ENABLED:
        return tool_error(
            "Browser tool is disabled. Set BROWSER_ENABLED=true to enable.", retriable=False
        )
    if not is_browser_available():
        return tool_error(
            "Playwright is not installed.",
            retriable=False,
            hint="Run: pip install playwright && playwright install chromium --with-deps",
        )
    return None


def _call_shape_error(action: str | None, steps: list[BrowserStep] | None) -> str | None:
    if (action is None) == (steps is None):
        return tool_error("Pass either `action` (one action) or `actions` (a batch), not both.")
    return None


def _with_screenshot(
    worker: BrowserWorker, conversation_id: str, result: dict[str, Any], share: bool
) -> list[dict[str, Any]]:
    """Append a screenshot of the current page (for the LLM) to a JSON result."""
    ss_data = worker.execute("screenshot", conversation_id=conversation_id)
    if share:
        _save_screenshot_attachment(ss_data)
    return [{"type": "text", "text": json.dumps(result)}, *_format_screenshot_internal(ss_data)]


def _run_steps(
    conversation_id: str, steps: list[BrowserStep], screenshot: bool, share: bool
) -> str | list[dict[str, Any]]:
    start_cleanup_thread()
    try:
        worker = get_worker()
        summary = run_batch(worker, conversation_id, steps)
        # A step timeout leaves the worker stuck in Playwright (unhealthy): a
        # screenshot would wait another TOOL_TIMEOUT_SECONDS and then replace the
        # batch summary (failed_step, hint) with a generic error.
        if (screenshot or share) and not worker.unhealthy:
            return _with_screenshot(worker, conversation_id, summary, share)
        return json.dumps(summary)
    except Exception as e:  # noqa: BLE001 - a tool must never raise into the graph
        return _failure_result("batch", None, e)


def _run_single(
    conversation_id: str, step: BrowserStep, screenshot: bool, share: bool
) -> str | list[dict[str, Any]]:
    start_cleanup_thread()
    try:
        worker = get_worker()
        result = worker.execute(step.action, **worker_kwargs(conversation_id, step))

        if step.action == "download":
            return json.dumps(_download_result(result))

        # Screenshot action - always returns multimodal for the LLM
        if step.action == "screenshot":
            if share:
                _save_screenshot_attachment(result)
            return _format_screenshot_internal(result)

        # Frame page-derived text as untrusted external data (prompt-injection
        # mitigation) before it goes back to the LLM.
        result = frame_page_text(result) if isinstance(result, dict) else result
        if screenshot:
            return _with_screenshot(worker, conversation_id, result, share)
        return json.dumps(result)
    except Exception as e:  # noqa: BLE001 - a tool must never raise into the graph
        return _failure_result(step.action, step.selector, e)


# Formats whose first characters are worth showing the model (as untrusted page text)
_TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/gpx+xml")
DOWNLOAD_EXCERPT_CHARS = 2000


def _download_result(download: dict[str, object]) -> dict[str, object]:
    """Attach a downloaded file to the reply; what the model is told about it."""
    # The page names the file: keep only its base name
    name = os.path.basename(str(download.get("name") or "")).strip() or "download"
    mime_type = guess_mime_type(name)
    request_id = get_current_request_id()
    if request_id is not None:
        file_entry = {
            "name": name,
            "mime_type": mime_type,
            "data": download["data"],
            "size": download["size"],
        }
        store_tool_result(request_id, json.dumps({"_full_result": {"files": [file_entry]}}))
    result: dict[str, object] = {
        "success": True,
        "downloaded": name,
        "mime_type": mime_type,
        "size": download["size"],
        "attached": request_id is not None,
    }
    if mime_type.startswith(_TEXT_MIME_PREFIXES):
        text = base64.b64decode(str(download["data"])).decode("utf-8", errors="replace")
        result["excerpt"] = wrap_untrusted_content(text[:DOWNLOAD_EXCERPT_CHARS], name)
    return result


def _failure_result(action: str, selector: str | None, e: Exception) -> str:
    if isinstance(e, TimeoutError):
        return tool_error(
            f"Browser timed out during {action}.",
            hint="The page may be loading slowly. Try increasing timeout_ms.",
        )
    error_msg = str(e)
    logger.warning(
        "Browser action failed",
        extra={"action": action, "error_type": type(e).__name__, "error": error_msg},
        exc_info=e,
    )
    if "selector" in error_msg.lower() or "locator" in error_msg.lower():
        return tool_error(
            f"Element not found: {selector}",
            hint="Take a screenshot to see the current page and verify the selector.",
        )
    return tool_error(f"Browser {action} failed: {error_msg}")
