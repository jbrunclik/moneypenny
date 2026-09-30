"""Browser action validation, batched execution, and post-action page state.

A batch runs a mechanical sequence (navigate -> type -> click) in ONE tool
call: every browser action used to cost a full LLM round-trip. Each step is
validated before anything runs, the steps then execute in order on the
browser worker, and the batch stops at the first failing step.

After page-changing actions the worker also returns a compact summary of the
visible interactive elements with ready-to-use selectors (PAGE_STATE_JS), so
the model can act on the new page without a screenshot or extract round.
"""

import json
import time
from typing import Any, Protocol

from pydantic import BaseModel, Field

from src.agent.tools.url_safety import validate_public_url
from src.agent.tools.web import wrap_untrusted_content
from src.config import Config

VALID_ACTIONS = frozenset(
    {"navigate", "click", "type", "screenshot", "extract", "scroll", "back", "close"}
)
# screenshot and close are excluded: a batch takes its screenshot via the
# tool's `screenshot` flag after the last step, and closing mid-batch would
# discard the session the remaining steps need.
BATCHABLE_ACTIONS = frozenset({"navigate", "click", "type", "scroll", "back", "extract"})

_FAILED_STEP_HINT = (
    "Steps before failed_step already ran - the browser is on the page they left it on. "
    "Fix the failing step (see `elements` for valid selectors) and continue from there; "
    "do not re-run the earlier steps."
)

# Visible interactive elements with a selector Playwright accepts. Input
# values are never read (they may hold passwords); labels come from
# aria-label / text / placeholder / title / name.
PAGE_STATE_JS = """(max) => {
  const query = 'a[href], button, input:not([type=hidden]), select, textarea, '
    + '[role=button], [role=link], [contenteditable=true]';
  const quote = (v) => JSON.stringify(v);
  const out = [];
  for (const el of document.querySelectorAll(query)) {
    if (out.length >= max) break;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (!rect.width || !rect.height || style.visibility === 'hidden') continue;
    const tag = el.tagName.toLowerCase();
    const attr = (name) => el.getAttribute(name);
    const text = tag === 'input' || tag === 'select' || tag === 'textarea' ? '' : el.innerText;
    const label = (attr('aria-label') || text || attr('placeholder') || attr('title')
      || attr('name') || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    let selector = null;
    let matches = [];
    if (el.id) selector = '#' + CSS.escape(el.id);
    else if (attr('name')) selector = `${tag}[name=${quote(attr('name'))}]`;
    else if (attr('aria-label')) selector = `${tag}[aria-label=${quote(attr('aria-label'))}]`;
    if (selector) matches = [...document.querySelectorAll(selector)];
    else if (label && tag !== 'input') {
      // Playwright :has-text is a case-insensitive substring match on the text
      selector = `${tag}:has-text(${quote(label)})`;
      const needle = label.toLowerCase();
      matches = [...document.querySelectorAll(tag)].filter((m) =>
        m.textContent.replace(/\\s+/g, ' ').toLowerCase().includes(needle));
    }
    if (!selector) continue;
    // Shared names (radio groups) and repeated texts ("Learn more") match
    // several elements - Playwright's strict mode would refuse to click them
    if (matches.length > 1) {
      const index = matches.indexOf(el);
      if (index < 0) continue;
      selector = `:nth-match(${selector}, ${index + 1})`;
    }
    const role = attr('role') || (tag === 'input' ? `input:${el.type || 'text'}` : tag);
    out.push({ role, label, selector });
  }
  return out;
}"""


class BrowserStep(BaseModel):
    """One step of a batched browser sequence."""

    action: str = Field(description="One of: navigate, click, type, scroll, back, extract")
    url: str | None = Field(default=None, description="URL (navigate)")
    selector: str | None = Field(default=None, description="CSS selector (click/type; scroll)")
    text: str | None = Field(default=None, description="Text to type (type)")
    wait_for: str | None = Field(default=None, description="Selector to wait for after the step")
    timeout_ms: int | None = Field(default=None, description="Timeout for this step")


class _Worker(Protocol):
    def execute(self, fn_name: str, **kwargs: Any) -> Any: ...


def _now() -> float:
    """Monotonic clock seam (tests patch this, never time itself)."""
    return time.monotonic()


def validate_action(
    action: str, url: str | None, selector: str | None, text: str | None
) -> str | None:
    """Return an error message for an invalid action, or None when it is valid."""
    if action not in VALID_ACTIONS:
        return f"Unknown action '{action}'. Valid actions: {', '.join(sorted(VALID_ACTIONS))}"
    if action == "navigate":
        if not url:
            return "url is required for navigate action."
        return validate_public_url(url)
    if action in ("click", "type") and not selector:
        return f"selector is required for {action} action."
    if action == "type" and text is None:
        return "text is required for type action."
    return None


def worker_kwargs(conversation_id: str, step: BrowserStep) -> dict[str, Any]:
    """Build the worker command kwargs for one action."""
    kwargs: dict[str, Any] = {"conversation_id": conversation_id}
    if step.action == "navigate":
        kwargs.update(url=step.url, wait_for=step.wait_for, timeout_ms=step.timeout_ms)
    elif step.action == "click":
        kwargs.update(selector=step.selector, wait_for=step.wait_for, timeout_ms=step.timeout_ms)
    elif step.action == "type":
        kwargs.update(selector=step.selector, text=step.text)
    elif step.action == "scroll":
        kwargs.update(selector=step.selector)
    return kwargs


def validate_batch(steps: list[BrowserStep]) -> str | None:
    """Validate a whole batch up front; nothing runs if any step is invalid."""
    if not steps:
        return "actions must contain at least one step."
    limit = Config.BROWSER_MAX_BATCH_ACTIONS
    if len(steps) > limit:
        return f"A batch can hold at most {limit} actions ({len(steps)} given) - split it."
    for index, step in enumerate(steps):
        if step.action not in BATCHABLE_ACTIONS:
            return (
                f"Step {index}: '{step.action}' cannot be batched. Batchable actions: "
                f"{', '.join(sorted(BATCHABLE_ACTIONS))}. Use screenshot=True for a final "
                "screenshot; call close on its own."
            )
        error = validate_action(step.action, step.url, step.selector, step.text)
        if error:
            return f"Step {index}: {error}"
    return None


def frame_page_text(result: dict[str, Any]) -> dict[str, Any]:
    """Wrap page-derived text (content, element labels) as untrusted, in place."""
    url = result.get("url")
    if isinstance(result.get("content"), str):
        result["content"] = wrap_untrusted_content(result["content"], url)
    elements = result.pop("elements", None)
    if elements:
        result["elements"] = wrap_untrusted_content(json.dumps(elements, ensure_ascii=False), url)
    return result


def run_batch(worker: _Worker, conversation_id: str, steps: list[BrowserStep]) -> dict[str, Any]:
    """Run validated steps in order; stop at the first failure or when time runs out."""
    deadline = _now() + Config.BROWSER_BATCH_TIMEOUT_SECONDS
    done: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    for index, step in enumerate(steps):
        if _now() > deadline:
            error = (
                f"Batch time budget ({Config.BROWSER_BATCH_TIMEOUT_SECONDS}s) ran out "
                "before this step."
            )
            return _batch_summary(done, last, failed=(index, error))
        try:
            last = worker.execute(step.action, **worker_kwargs(conversation_id, step))
        except Exception as e:
            reason = "timed out" if isinstance(e, TimeoutError) else str(e)
            return _batch_summary(done, last, failed=(index, f"{step.action} failed: {reason}"))
        done.append({"action": step.action, **_without_elements(last)})
    return _batch_summary(done, last, failed=None)


def _without_elements(result: dict[str, Any]) -> dict[str, Any]:
    step = {k: v for k, v in result.items() if k != "elements"}
    return frame_page_text(step)


def _batch_summary(
    done: list[dict[str, Any]],
    last: dict[str, Any],
    failed: tuple[int, str] | None,
) -> dict[str, Any]:
    """Batch result: per-step results plus the final page's title, URL and elements."""
    summary: dict[str, Any] = {"success": failed is None, "completed": len(done), "steps": done}
    if failed is not None:
        summary.update(failed_step=failed[0], error=failed[1], hint=_FAILED_STEP_HINT)
    page = {k: last[k] for k in ("title", "url", "elements") if k in last}
    summary.update(frame_page_text(page))
    return summary
