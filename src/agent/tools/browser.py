"""Browser automation tool using Playwright for JavaScript-capable web browsing.

All Playwright operations run on a dedicated daemon thread (the "browser worker")
because Playwright's sync API is greenlet-based and cannot be used from arbitrary
threads. The tool function dispatches commands to the worker via a queue and blocks
until the result is ready.
"""

import atexit
import base64
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import tool

from src.agent.tool_results import get_current_request_id, store_tool_result
from src.agent.tools.context import get_conversation_context
from src.agent.tools.permission_check import check_autonomous_permission
from src.agent.tools.url_safety import validate_public_url
from src.agent.tools.web import _extract_text_from_html, wrap_untrusted_content
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============ Browser Worker Thread ============


def _browser_launch_args() -> list[str]:
    """Chromium launch flags for the agent browser.

    The OS sandbox is kept ON by default - this browser visits untrusted
    pages, so it is exactly the process that needs sandboxing (S8).
    BROWSER_NO_SANDBOX is an explicit opt-out for environments where the
    sandbox cannot run (root in a container without user namespaces).
    """
    args = [
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-extensions",
    ]
    if Config.BROWSER_NO_SANDBOX:
        logger.warning("Chromium OS sandbox disabled via BROWSER_NO_SANDBOX")
        args.append("--no-sandbox")
    return args


@dataclass
class BrowserSession:
    """A browser session tied to a conversation."""

    conversation_id: str
    context: Any  # BrowserContext
    page: Any  # Page
    last_used: float = field(default_factory=time.time)


@dataclass
class _WorkerCommand:
    """A command to execute on the browser worker thread."""

    fn_name: str
    kwargs: dict[str, Any]
    result_event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None


class _BrowserWorker:
    """Dedicated thread that owns the Playwright browser instance.

    Playwright's sync API uses greenlets internally and cannot be shared across
    threads. This worker runs all Playwright operations on a single long-lived
    daemon thread and accepts commands via a queue.
    """

    def __init__(self) -> None:
        # Set when a command times out (worker stuck in Playwright) - the
        # worker is then replaced on next use instead of dispatched to forever
        self.unhealthy = False
        self._cmd_queue: queue.Queue[_WorkerCommand | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="browser-worker")
        self._pw: Any = None
        self._browser: Any = None
        self._sessions: dict[str, BrowserSession] = {}
        self._started = threading.Event()
        self._thread.start()
        # Wait for the worker to initialise Playwright
        self._started.wait(timeout=30)

    def _run(self) -> None:
        """Main loop on the dedicated browser thread."""
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=_browser_launch_args(),
        )
        logger.info("Browser worker started")
        self._started.set()

        while True:
            cmd = self._cmd_queue.get()
            if cmd is None:
                # Shutdown sentinel
                break
            try:
                handler = getattr(self, f"_do_{cmd.fn_name}", None)
                if handler is None:
                    cmd.error = ValueError(f"Unknown worker command: {cmd.fn_name}")
                else:
                    cmd.result = handler(**cmd.kwargs)
            except Exception as e:
                cmd.error = e
            finally:
                cmd.result_event.set()

        # Cleanup
        self._cleanup_all()

    def execute(self, fn_name: str, **kwargs: Any) -> Any:
        """Send a command to the worker and block until done."""
        cmd = _WorkerCommand(fn_name=fn_name, kwargs=kwargs)
        self._cmd_queue.put(cmd)
        cmd.result_event.wait(timeout=Config.TOOL_TIMEOUT)
        if not cmd.result_event.is_set():
            # The worker thread is stuck inside a Playwright call and will
            # process queued commands only if/when it ever returns. Mark the
            # worker unhealthy so _get_worker() replaces it (R1); the stuck
            # daemon thread is abandoned and dies with the process.
            self.unhealthy = True
            raise TimeoutError("Browser worker timed out")
        if cmd.error is not None:
            raise cmd.error
        return cmd.result

    def stop(self) -> None:
        """Send shutdown sentinel to the worker thread."""
        self._cmd_queue.put(None)

    # ---- Worker-thread-only methods (called inside _run) ----

    def _get_or_create_session(self, conversation_id: str) -> BrowserSession:
        session = self._sessions.get(conversation_id)
        if session is not None:
            session.last_used = time.time()
            return session

        # Evict oldest if at limit
        if len(self._sessions) >= Config.BROWSER_MAX_CONCURRENT_SESSIONS:
            oldest_id = min(self._sessions, key=lambda k: self._sessions[k].last_used)
            self._close_session(oldest_id)
            logger.info("Evicted oldest browser session", extra={"evicted": oldest_id})

        context = self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(Config.BROWSER_PAGE_TIMEOUT_MS)

        session = BrowserSession(conversation_id=conversation_id, context=context, page=page)
        self._sessions[conversation_id] = session
        logger.info("Created browser session", extra={"conversation_id": conversation_id})
        return session

    def _close_session(self, conversation_id: str) -> None:
        session = self._sessions.pop(conversation_id, None)
        if session is None:
            return
        try:
            session.context.close()
        except Exception:
            logger.debug("Browser context close failed", exc_info=True)

    def _cleanup_all(self) -> None:
        for cid in list(self._sessions.keys()):
            self._close_session(cid)
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                logger.debug("Browser close failed", exc_info=True)
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                logger.debug("Playwright stop failed", exc_info=True)

    def _take_screenshot(self, page: Any) -> dict[str, Any]:
        """Take screenshot and return raw base64 data + metadata."""
        screenshot_bytes = page.screenshot(type="jpeg", quality=80)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        size = len(screenshot_bytes)
        return {
            "url": page.url,
            "size": size,
            "mime_type": "image/jpeg",
            "data": screenshot_b64,
        }

    # ---- Command handlers (each is a _do_<name> method) ----

    def _do_navigate(
        self,
        conversation_id: str,
        url: str,
        wait_for: str | None,
        timeout_ms: int | None,
    ) -> dict[str, Any]:
        session = self._get_or_create_session(conversation_id)
        page = session.page

        kwargs: dict[str, Any] = {}
        if timeout_ms is not None and timeout_ms > 0:
            kwargs["timeout"] = timeout_ms

        logger.info("Browser navigating", extra={"url": url})
        page.goto(url, **kwargs)

        if wait_for:
            page.wait_for_selector(wait_for, timeout=timeout_ms or Config.BROWSER_PAGE_TIMEOUT_MS)

        return {"success": True, "title": page.title(), "url": page.url}

    def _do_click(
        self,
        conversation_id: str,
        selector: str,
        wait_for: str | None,
        timeout_ms: int | None,
    ) -> dict[str, Any]:
        session = self._get_or_create_session(conversation_id)
        page = session.page
        page.click(selector, timeout=timeout_ms or Config.BROWSER_PAGE_TIMEOUT_MS)

        if wait_for:
            page.wait_for_selector(wait_for, timeout=timeout_ms or Config.BROWSER_PAGE_TIMEOUT_MS)

        return {"success": True, "clicked": selector, "title": page.title(), "url": page.url}

    def _do_type(
        self,
        conversation_id: str,
        selector: str,
        text: str,
    ) -> dict[str, Any]:
        session = self._get_or_create_session(conversation_id)
        page = session.page
        page.fill(selector, text)
        return {"success": True, "typed_into": selector, "title": page.title(), "url": page.url}

    def _do_screenshot(self, conversation_id: str) -> dict[str, Any]:
        session = self._get_or_create_session(conversation_id)
        return self._take_screenshot(session.page)

    def _do_extract(self, conversation_id: str) -> dict[str, Any]:
        session = self._get_or_create_session(conversation_id)
        page = session.page
        html = page.content()
        text = _extract_text_from_html(html)
        return {"success": True, "title": page.title(), "url": page.url, "content": text}

    def _do_scroll(self, conversation_id: str, selector: str | None) -> dict[str, Any]:
        session = self._get_or_create_session(conversation_id)
        page = session.page
        if selector:
            page.evaluate(
                """(sel) => {
                const el = document.querySelector(sel);
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }""",
                selector,
            )
        else:
            page.evaluate("window.scrollBy(0, 600)")
        return {
            "success": True,
            "scrolled": selector or "page down",
            "title": page.title(),
            "url": page.url,
        }

    def _do_back(self, conversation_id: str) -> dict[str, Any]:
        session = self._get_or_create_session(conversation_id)
        page = session.page
        page.go_back()
        return {"success": True, "title": page.title(), "url": page.url}

    def _do_close(self, conversation_id: str) -> dict[str, Any]:
        self._close_session(conversation_id)
        return {"success": True, "message": "Browser session closed."}

    def _do_cleanup_stale(self) -> dict[str, Any]:
        now = time.time()
        stale = [
            cid
            for cid, s in self._sessions.items()
            if now - s.last_used > Config.BROWSER_SESSION_TTL_SECONDS
        ]
        for cid in stale:
            self._close_session(cid)
        return {"cleaned": len(stale)}


# ============ Worker Lifecycle ============

_worker: _BrowserWorker | None = None
_worker_lock = threading.Lock()


def _get_worker() -> _BrowserWorker:
    """Get or create the browser worker (lazy init, replaces unhealthy ones)."""
    global _worker
    if _worker is not None and not _worker.unhealthy:
        return _worker

    with _worker_lock:
        if _worker is not None and not _worker.unhealthy:
            return _worker
        if _worker is not None:
            logger.warning("Replacing unhealthy browser worker")
            _worker.stop()  # best effort; the stuck thread may never see it
        _worker = _BrowserWorker()
    return _worker


def _shutdown_worker() -> None:
    global _worker
    if _worker is not None:
        _worker.stop()
        _worker = None


atexit.register(_shutdown_worker)

# Background cleanup timer
_cleanup_thread: threading.Thread | None = None
_cleanup_stop = threading.Event()


def _cleanup_loop() -> None:
    while not _cleanup_stop.is_set():
        if _cleanup_stop.wait(timeout=60):
            break
        if _worker is not None:
            try:
                result = _worker.execute("cleanup_stale")
                if result.get("cleaned", 0) > 0:
                    logger.debug(
                        "Cleaned up stale browser sessions",
                        extra={"count": result["cleaned"]},
                    )
            except Exception:
                logger.debug("Browser session cleanup pass failed", exc_info=True)


_cleanup_thread_lock = threading.Lock()


def _start_cleanup_thread() -> None:
    global _cleanup_thread
    # Double-checked: two gthread request threads racing past the unlocked
    # check would spawn duplicate cleanup loops
    if _cleanup_thread is not None and _cleanup_thread.is_alive():
        return
    with _cleanup_thread_lock:
        if _cleanup_thread is not None and _cleanup_thread.is_alive():
            return
        _cleanup_stop.clear()
        _cleanup_thread = threading.Thread(
            target=_cleanup_loop, daemon=True, name="browser-session-cleanup"
        )
        _cleanup_thread.start()


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
            br = pw.chromium.launch(headless=True, args=_browser_launch_args())
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

_VALID_ACTIONS = {"navigate", "click", "type", "screenshot", "extract", "scroll", "back", "close"}


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
    action: str,
    url: str | None = None,
    selector: str | None = None,
    text: str | None = None,
    screenshot: bool = False,
    share_screenshot: bool = False,
    wait_for: str | None = None,
    timeout_ms: int | None = None,
) -> str | list[dict[str, Any]]:
    """Browse the web with a full browser that renders JavaScript.

    Use this tool when you need to interact with web pages that require JavaScript rendering,
    or when fetch_url returns incomplete/empty content. The browser session persists across
    calls within the same conversation (cookies, history, JS state are maintained).

    IMPORTANT: Call ONE action per turn. Do not call multiple browser actions simultaneously.
    Never enter passwords or credentials into web forms.

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

    ## Screenshots

    - `screenshot=True` on any action: takes a screenshot for YOU to see the page (internal).
    - `share_screenshot=True`: also shares the screenshot with the user as a visible attachment.

    Use internal screenshots freely for navigation (finding elements, understanding layout).
    Only share screenshots when the result is relevant to the user (final page, visual answer).

    Args:
        action: The browser action to perform
        url: URL to navigate to (required for navigate)
        selector: CSS selector for the target element (required for click/type)
        text: Text to type (required for type)
        screenshot: If True, take a screenshot after the action (visible to you only)
        share_screenshot: If True, also share the screenshot with the user as a file attachment
        wait_for: CSS selector to wait for after the action completes
        timeout_ms: Custom timeout in milliseconds for this action

    Returns:
        JSON for non-screenshot results. Multimodal content (with image) for screenshots.
    """
    # Permission check for autonomous agents
    check_autonomous_permission("browser", {"action": action, "url": url})

    if not Config.BROWSER_ENABLED:
        return json.dumps(
            {
                "error": "Browser tool is disabled. Set BROWSER_ENABLED=true to enable.",
                "retriable": False,
            }
        )

    if not is_browser_available():
        return json.dumps(
            {
                "error": "Playwright is not installed.",
                "retriable": False,
                "hint": "Run: pip install playwright && playwright install chromium --with-deps",
            }
        )

    if action not in _VALID_ACTIONS:
        return json.dumps(
            {
                "error": f"Unknown action '{action}'. "
                f"Valid actions: {', '.join(sorted(_VALID_ACTIONS))}"
            }
        )

    # Validate args before dispatching to worker
    if action == "navigate":
        if not url:
            return json.dumps({"error": "url is required for navigate action."})
        error = validate_public_url(url)
        if error:
            return json.dumps({"error": error})
    if action == "click" and not selector:
        return json.dumps({"error": "selector is required for click action."})
    if action == "type":
        if not selector:
            return json.dumps({"error": "selector is required for type action."})
        if text is None:
            return json.dumps({"error": "text is required for type action."})

    # Get conversation ID for session routing
    conversation_id, _ = get_conversation_context()
    if not conversation_id:
        conversation_id = "__default__"

    # Start cleanup thread on first use
    _start_cleanup_thread()

    try:
        worker = _get_worker()

        # Build kwargs for worker command
        kwargs: dict[str, Any] = {"conversation_id": conversation_id}
        if action == "navigate":
            kwargs.update(url=url, wait_for=wait_for, timeout_ms=timeout_ms)
        elif action == "click":
            kwargs.update(selector=selector, wait_for=wait_for, timeout_ms=timeout_ms)
        elif action == "type":
            kwargs.update(selector=selector, text=text)
        elif action == "scroll":
            kwargs.update(selector=selector)

        result = worker.execute(action, **kwargs)

        # Frame page-derived text as untrusted external data (prompt-injection
        # mitigation) before it goes back to the LLM.
        if isinstance(result, dict) and isinstance(result.get("content"), str):
            result["content"] = wrap_untrusted_content(result["content"], result.get("url"))

        # Handle screenshot action — always returns multimodal for the LLM
        if action == "screenshot":
            if share_screenshot:
                _save_screenshot_attachment(result)
            return _format_screenshot_internal(result)

        # Handle screenshot=True on other actions — append screenshot for the LLM
        if screenshot:
            ss_data = worker.execute("screenshot", conversation_id=conversation_id)
            if share_screenshot:
                _save_screenshot_attachment(ss_data)
            multimodal = _format_screenshot_internal(ss_data)
            # Combine action result (JSON) + screenshot (multimodal)
            return [{"type": "text", "text": json.dumps(result)}] + multimodal

        return json.dumps(result)

    except TimeoutError:
        return json.dumps(
            {
                "error": f"Browser timed out during {action}.",
                "hint": "The page may be loading slowly. Try increasing timeout_ms.",
            }
        )
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.warning(
            "Browser action failed",
            extra={"action": action, "error_type": error_type, "error": error_msg},
        )

        if "selector" in error_msg.lower() or "locator" in error_msg.lower():
            return json.dumps(
                {
                    "error": f"Element not found: {selector}",
                    "hint": "Take a screenshot to see the current page and verify the selector.",
                }
            )

        return json.dumps({"error": f"Browser {action} failed: {error_msg}"})
