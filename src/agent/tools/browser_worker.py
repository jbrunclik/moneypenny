"""Browser worker: the dedicated thread that owns Playwright and its sessions.

All Playwright operations run on a dedicated daemon thread (the "browser worker")
because Playwright's sync API is greenlet-based and cannot be used from arbitrary
threads. Callers dispatch commands via BrowserWorker.execute(), which queues them
and blocks until the result is ready. One browser context per conversation.
"""

import atexit
import base64
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from src.agent.tools.browser_steps import PAGE_STATE_JS
from src.agent.tools.web import _extract_text_from_html
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# ============ Browser Worker Thread ============


def browser_launch_args() -> list[str]:
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


class BrowserWorker:
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
            args=browser_launch_args(),
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
            # worker unhealthy so get_worker() replaces it (R1); the stuck
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

    def _page_state(self, page: Any) -> list[dict[str, str]]:
        """Visible interactive elements with selectors (best effort, never fails the action)."""
        try:
            elements: list[dict[str, str]] = page.evaluate(
                PAGE_STATE_JS, Config.BROWSER_PAGE_STATE_MAX_ELEMENTS
            )
            return elements
        except Exception:
            logger.debug("Browser page-state summary failed", exc_info=True)
            return []

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

        return {
            "success": True,
            "title": page.title(),
            "url": page.url,
            "elements": self._page_state(page),
        }

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

        return {
            "success": True,
            "clicked": selector,
            "title": page.title(),
            "url": page.url,
            "elements": self._page_state(page),
        }

    def _do_type(
        self,
        conversation_id: str,
        selector: str,
        text: str,
    ) -> dict[str, Any]:
        session = self._get_or_create_session(conversation_id)
        page = session.page
        page.fill(selector, text)
        return {
            "success": True,
            "typed_into": selector,
            "title": page.title(),
            "url": page.url,
            "elements": self._page_state(page),
        }

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
            "elements": self._page_state(page),
        }

    def _do_back(self, conversation_id: str) -> dict[str, Any]:
        session = self._get_or_create_session(conversation_id)
        page = session.page
        page.go_back()
        return {
            "success": True,
            "title": page.title(),
            "url": page.url,
            "elements": self._page_state(page),
        }

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

_worker: BrowserWorker | None = None
_worker_lock = threading.Lock()


def get_worker() -> BrowserWorker:
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
        _worker = BrowserWorker()
    return _worker


def shutdown_worker() -> None:
    global _worker
    if _worker is not None:
        _worker.stop()
        _worker = None


atexit.register(shutdown_worker)

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


def start_cleanup_thread() -> None:
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
