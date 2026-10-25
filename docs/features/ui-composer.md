# Composer

The message input: toolbar, sending, forced tools, clipboard paste and program
quick actions. Part of [UI Features](ui-features.md).

## Input Toolbar

The input area has a toolbar row above the textarea with controls:

```
[Model dropdown] [Stream] [Search]              [Mic] [Attach] [Anonymous]
┌────────────────────────────────────────────────────────────┐
│ Textarea                                          [Send]   │
└────────────────────────────────────────────────────────────┘
```

- **Model selector**: Dropdown to switch between Gemini models
- **Stream toggle**: Enable/disable streaming responses (persisted to localStorage)
- **Search toggle**: One-shot button to force `web_search` tool for the next message only
- **Mic**: Voice input (see [Voice and TTS](voice-and-tts.md))
- **Attach**: File upload (see [File Handling](file-handling.md))
- **Anonymous**: Anonymous mode toggle (see [Anonymous Mode](memory-and-context.md#anonymous-mode))

## Message Sending Behavior

The Enter key behavior differs between desktop and mobile viewports:

- **Desktop** (viewport > 768px): Enter sends the message, Shift+Enter adds a newline
- **Mobile** (viewport ≤ 768px): Enter always adds a newline, users must tap the Send button

This allows mobile users to easily add multiple lines to their prompts (since there's no easy way to type Shift+Enter on mobile keyboards), while preserving the convenient Enter-to-send behavior on desktop.

**Implementation:**
- `isMobileViewport()` in [MessageInput.ts](../../web/src/components/MessageInput.ts) checks `window.innerWidth` against `MOBILE_BREAKPOINT_PX`
- The keydown handler only sends on Enter when NOT in mobile viewport
- `MOBILE_BREAKPOINT_PX` (768px) is defined in [config.ts](../../web/src/config.ts) and matches the CSS media query breakpoint in [layout.css](../../web/src/styles/layout.css)

## Force Tools System

The `forceTools` state in Zustand allows forcing specific tools to be used. Currently only `web_search` is exposed via UI, but the system supports any tool name. The force tools instruction is added to the system prompt when tools are specified.

- **Frontend**: `store.forceTools: string[]` with `toggleForceTool(tool)` and `clearForceTools()`
- **Backend**: `force_tools` parameter in `/chat/batch` and `/chat/stream` endpoints
- **Agent**: `get_force_tools_prompt()` in [prompts.py](../../src/agent/prompts.py)

## Clipboard Paste

Users can paste screenshots directly from the clipboard into the message input (Cmd+V / Ctrl+V).

### How It Works

1. A `paste` event listener on the textarea detects clipboard content
2. If clipboard contains image files, they're extracted and processed
3. Images are renamed with timestamp-based names (`screenshot-YYYY-MM-DDTHH-MM-SS.png`)
4. Uses the existing `addFilesToPending()` flow for validation and preview
5. Text paste is handled normally by the browser (not intercepted)

### Supported Formats

- PNG, JPEG, GIF, WebP images
- Works with screenshots (Cmd+Shift+4 on Mac, PrtScn on Windows)
- Works with copied images from other applications

### Key Files

- [MessageInput.ts](../../web/src/components/MessageInput.ts) - `handlePaste()` function
- [FileUpload.ts](../../web/src/components/FileUpload.ts) - `addFilesToPending()` for file processing

### Testing

- Unit tests: `handlePaste` describe block in [message-input.test.ts](../../web/tests/unit/message-input.test.ts)
- E2E tests: "Chat - Clipboard Paste" describe block in [clipboard.spec.ts](../../web/tests/e2e/chat/clipboard.spec.ts)

## Program Quick Actions

One-tap saved prompts in sports and language program conversations. Everything lives
**inside the composer pill**:

- **Chip row** on the pill's top edge (ghost chips + a gear that opens the editor; on
  mobile the gear is the only entry point because the program header is hidden there).
- **Composer mode**: tapping any chip turns the pill into a small form: header (emoji,
  label, ✕), one compact input per question (inline on desktop, stacked on mobile), and
  the textarea becomes the free-text note. Without questions the cursor lands in the
  note; the note is the way to add today's context to a fixed prompt. The composer's own Send button
  sends `body`, a blank line, `Question: answer` lines (empty ones omitted), then the note
  as its own paragraph. Enter in the last question sends on desktop and focuses the note
  on mobile; ✕ or Escape cancels.
- **Slash menu**: typing `/` in an empty composer lists the actions (filtered by what
  follows), arrow keys + Enter/Tab pick, Escape closes. Picking behaves like tapping the chip.
- **Editor** (autosaving): list with up/down reorder, edit, delete; detail form with a
  free-form emoji input (first grapheme kept), label, message, question rows (reorder,
  remove) and a preview rendered as the user bubble it will become. Closing over a valid,
  unfinished detail form commits it, so no path loses work.
- **Save as quick action** on any of your own messages in a program conversation.

### Storage

Actions live inside each program object in the namespace's `programs` K/V list — never
under `{program_id}:*`, which `program_context.py` injects into the prompt each turn.
Programs without a `quick_actions` key resolve to the namespace defaults
(`QUICK_ACTION_DEFAULTS` in `src/api/routes/program_quick_actions.py`). Corrupt entries are
dropped on read with a warning. Limits: 12 actions, 6 questions, 40-char labels, 2000-char body.

### Key Files

- `src/api/routes/program_quick_actions.py` — defaults, sanitization, `PUT /api/{ns}/programs/<id>/quick-actions`
- `web/src/core/quick-actions.ts` — composition, mount/visibility, composer mode, slash menu, send, editor glue
- `web/src/components/QuickActionsBar.ts`, `QuickActionComposer.ts`, `QuickActionsSlashMenu.ts`, `QuickActionsEditor.ts`
- `web/src/styles/components/quick-actions.css`

### Send path

`core/messaging.ts` exposes `registerComposerHook({ transform, onConsumed })`. Quick actions
register it once at init: `sendMessage()` runs the raw textarea text through `transform`
(composer mode turns the note into the full message) and calls `onConsumed` after the
input is cleared (composer mode exits). Messaging never imports quick-actions, so there is
no cycle. `MessageInput.setComposerHasExternalContent()` keeps Send enabled while the note
is empty in composer mode.

### Behavior notes

- Mobile: the chip row is visible only while the composer is empty and nothing is
  streaming; it is also hidden during composer mode and while the slash menu is open.
- The chip row is part of `.input-container`, so `composer-height.ts` measures it as part
  of the pill with no special case. Visibility toggles via `.hidden` (never animated height).
- Safe areas: the editor header/body pad for `env(safe-area-inset-top/bottom)`; the page
  declares `viewport-fit=cover`.

### Testing

- `tests/unit/test_program_quick_actions.py`, `tests/integration/test_routes_program_quick_actions.py`
- `web/tests/unit/quick-actions*.test.ts`, `web/tests/component/QuickAction*.test.ts`
- `web/tests/e2e/quick-actions.spec.ts`, `web/tests/visual/quick-actions.visual.ts`
