# Browser press, select and download - design (short)

**Intent.** The browser tool could not press a key (a search box with no
button, a dialog that closes only on Escape), choose from a native
`<select>` (clicking an `<option>` does nothing in Chromium) or fetch a file
a page offers (ticket PDF, GPX, CSV export).

**Goals.** `press` (`text` = a Playwright key name, `KEY_PATTERN` only;
optional `selector` to focus), `select` (`selector` + option label or value),
both batchable; `download` (`selector` of the link/button; single action):
the request guard covers it, over `BROWSER_MAX_DOWNLOAD_BYTES` (10 MB) it is
refused, otherwise attached to the reply like a shared screenshot; the model
gets name, type, size and, for text formats, the first 2,000 characters as
untrusted content. A8: "Browser downloaded a file" with its size, failures by
action, a regular-review check and a TODO re-measure. A7: an announcement.

**Approaches.** (1) Reuse `selector`/`text` (chosen): no new parameters, one
docstring line each. (2) New `key`/`option` parameters: clearer names, but
three more schema fields re-sent on every call. (3) `evaluate` JavaScript for
selects and keys: bypasses Playwright's waiting and real input events.
