"""Browser automation tool using Playwright for JavaScript-capable web browsing.

The `browser` tool validates arguments and dispatches actions (single or
batched, see browser_steps.py) to the Playwright worker thread in
browser_worker.py.
"""

import json
import threading
from typing import Any

from langchain_core.tools import tool

from src.agent.tool_results import get_current_request_id, store_tool_result
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
from src.agent.tools.permission_check import check_autonomous_permission
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# ============ URL Validation ============

# ============ Availability Check ============

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
        from playwright.sync_api import sync_playwright
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
        except Exception as e:
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
            )
        finally:
            pw.stop()
    except Exception as e:
        _browser_available = False
        logger.warning("Playwright startup failed", extra={"error": str(e)})

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

    Use this tool when you need to interact with web pages that require JavaScript rendering,
    or when fetch_url returns incomplete/empty content. The browser session persists across
    calls within the same conversation (cookies, history, JS state are maintained).

    Pass EITHER `action` (one action) OR `actions` (a batch). Never enter passwords or
    credentials into web forms.

    Before the first browser call of a task, call load_skill('browser-tactics').

    Actions:
    - navigate: Go to a URL. Requires `url`. Returns page title and URL.
    - click: Click an element. Requires `selector` (CSS selector).
    - type: Type text into a form field. Requires `selector` and `text`.
    - screenshot: Take a screenshot. By default, only you (the LLM) can see it.
      Set `share_screenshot=True` to also share it with the user as a file attachment.
    - extract: Extract all text content from the current page (rendered HTML to markdown).
    - scroll: Scroll down the page. Optional `selector` to scroll to a specific element.
    - back: Go back in browser history.
    - close: Close the browser session and free resources.

    ## Batches (`actions`)

    When you already know the steps - a known URL, then fill a field, then click submit -
    send them as one `actions` list instead of one call per step, e.g.
    `actions=[{"action": "navigate", "url": "..."}, {"action": "type", "selector": "#q",
    "text": "..."}, {"action": "click", "selector": "button[type=submit]"}]`.
    Steps run in order and stop at the first failure (the result says which step failed).
    Batchable: navigate, click, type, scroll, back, extract. On an unfamiliar page, look
    first (a single navigate returns its `elements`), then batch.

    ## Page state

    navigate/click/type/scroll/back return `elements`: the visible buttons, links and
    inputs with ready-to-use selectors. Prefer those selectors over guessing.

    ## Screenshots

    - `screenshot=True` on any action or batch: takes a screenshot (after the last step)
      for YOU to see the page (internal).
    - `share_screenshot=True`: also shares the screenshot with the user as a visible attachment.

    Use internal screenshots freely for navigation (finding elements, understanding layout).
    Only share screenshots when the result is relevant to the user (final page, visual answer).

    Args:
        action: The browser action to perform (omit when passing `actions`)
        url: URL to navigate to (required for navigate)
        selector: CSS selector for the target element (required for click/type)
        text: Text to type (required for type)
        screenshot: If True, take a screenshot after the action (visible to you only)
        share_screenshot: If True, also share the screenshot with the user as a file attachment
        wait_for: CSS selector to wait for after the action completes
        timeout_ms: Custom timeout in milliseconds for this action
        actions: A batch of steps to run in order in this one call (instead of `action`)

    Returns:
        JSON for non-screenshot results. Multimodal content (with image) for screenshots.
    """
    steps = [BrowserStep.model_validate(s) for s in actions] if actions is not None else None
    check_autonomous_permission("browser", _permission_args(action, url, steps))

    error = _availability_error() or _call_shape_error(action, steps)
    if error:
        return json.dumps(error)

    conversation_id, _ = get_conversation_context()
    conversation_id = conversation_id or "__default__"

    if steps is not None:
        batch_error = validate_batch(steps)
        if batch_error:
            return json.dumps({"error": batch_error})
        return _run_steps(conversation_id, steps, screenshot, share_screenshot)

    step = BrowserStep(
        action=str(action), url=url, selector=selector, text=text,
        wait_for=wait_for, timeout_ms=timeout_ms,
    )  # fmt: skip
    step_error = validate_action(step.action, url, selector, text)
    if step_error:
        return json.dumps({"error": step_error})
    return _run_single(conversation_id, step, screenshot, share_screenshot)


def _permission_args(
    action: str | None, url: str | None, steps: list[BrowserStep] | None
) -> dict[str, Any]:
    if steps is None:
        return {"action": action, "url": url}
    return {"action": "batch", "urls": [s.url for s in steps if s.url]}


def _availability_error() -> dict[str, Any] | None:
    if not Config.BROWSER_ENABLED:
        return {
            "error": "Browser tool is disabled. Set BROWSER_ENABLED=true to enable.",
            "retriable": False,
        }
    if not is_browser_available():
        return {
            "error": "Playwright is not installed.",
            "retriable": False,
            "hint": "Run: pip install playwright && playwright install chromium --with-deps",
        }
    return None


def _call_shape_error(action: str | None, steps: list[BrowserStep] | None) -> dict[str, Any] | None:
    if (action is None) == (steps is None):
        return {"error": "Pass either `action` (one action) or `actions` (a batch), not both."}
    return None


def _with_screenshot(
    worker: BrowserWorker, conversation_id: str, result: dict[str, Any], share: bool
) -> list[dict[str, Any]]:
    """Append a screenshot of the current page (for the LLM) to a JSON result."""
    ss_data = worker.execute("screenshot", conversation_id=conversation_id)
    if share:
        _save_screenshot_attachment(ss_data)
    return [{"type": "text", "text": json.dumps(result)}] + _format_screenshot_internal(ss_data)


def _run_steps(
    conversation_id: str, steps: list[BrowserStep], screenshot: bool, share: bool
) -> str | list[dict[str, Any]]:
    start_cleanup_thread()
    try:
        worker = get_worker()
        summary = run_batch(worker, conversation_id, steps)
        # A step timeout leaves the worker stuck in Playwright (unhealthy): a
        # screenshot would wait another TOOL_TIMEOUT and then replace the
        # batch summary (failed_step, hint) with a generic error.
        if (screenshot or share) and not worker.unhealthy:
            return _with_screenshot(worker, conversation_id, summary, share)
        return json.dumps(summary)
    except Exception as e:
        return json.dumps(_failure_result("batch", None, e))


def _run_single(
    conversation_id: str, step: BrowserStep, screenshot: bool, share: bool
) -> str | list[dict[str, Any]]:
    start_cleanup_thread()
    try:
        worker = get_worker()
        result = worker.execute(step.action, **worker_kwargs(conversation_id, step))

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
    except Exception as e:
        return json.dumps(_failure_result(step.action, step.selector, e))


def _failure_result(action: str, selector: str | None, e: Exception) -> dict[str, Any]:
    if isinstance(e, TimeoutError):
        return {
            "error": f"Browser timed out during {action}.",
            "hint": "The page may be loading slowly. Try increasing timeout_ms.",
        }
    error_msg = str(e)
    logger.warning(
        "Browser action failed",
        extra={"action": action, "error_type": type(e).__name__, "error": error_msg},
    )
    if "selector" in error_msg.lower() or "locator" in error_msg.lower():
        return {
            "error": f"Element not found: {selector}",
            "hint": "Take a screenshot to see the current page and verify the selector.",
        }
    return {"error": f"Browser {action} failed: {error_msg}"}
