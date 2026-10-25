# Message Content

How message content renders and is copied: links, images, code blocks, tables,
diagrams and artifacts. Part of [UI Features](ui-features.md).

## URL Detection and Link Handling

The app automatically detects URLs in messages and converts them to clickable links. All links (both auto-detected and markdown links from LLM responses) open in new tabs with security attributes.

### Auto-Linkification

**User messages** are scanned for URLs and automatically converted to clickable links.

**Supported patterns:**
- `http://` and `https://` URLs
- `www.` prefixed URLs (automatically prepended with `https://`)

**Example:**
```
User types: "Check out https://example.com and www.test.org"
Result: Both URLs become clickable links
```

### Link Security

All links include security attributes:
- `target="_blank"` - Opens in new tab
- `rel="noopener noreferrer"` - Prevents security vulnerabilities:
  - `noopener` - New tab can't access `window.opener` (prevents tabnabbing)
  - `noreferrer` - Doesn't send referrer header (privacy)

### Implementation

**User messages:**
- Plain text URLs are detected using regex pattern in [linkify.ts](../../web/src/utils/linkify.ts)
- `linkifyText()` converts URLs to anchor tags after HTML escaping
- Applied in [messages/render.ts](../../web/src/components/messages/render.ts) when rendering user messages

**Assistant messages:**
- Markdown links are rendered by the `marked` library
- Custom link renderer in [markdown.ts](../../web/src/utils/markdown.ts) adds security attributes
- Works for all markdown link formats: `[text](url)`, `<url>`, etc.
- External images in model output (`![](https://...)`) render as a `🖼️` link, never an `<img>`: a prompt-injected page could make the model emit an image URL carrying conversation data, which would load as soon as the reply renders. Same-origin, `data:` and `blob:` images still render, and the production CSP `img-src` allows only those plus Google profile photos.

### Key Files

- [linkify.ts](../../web/src/utils/linkify.ts) - URL detection and auto-linking utility
- [markdown.ts](../../web/src/utils/markdown.ts) - Custom link renderer for markdown
- [messages/render.ts](../../web/src/components/messages/render.ts) - Integration into message rendering

### Testing

- Unit tests: [linkify.test.ts](../../web/tests/unit/linkify.test.ts) - URL detection patterns, edge cases
- E2E tests: [links.spec.ts](../../web/tests/e2e/links.spec.ts) - Link behavior in user and assistant messages, security attributes

---

## Image Lightbox / Gallery

[Lightbox.ts](../../web/src/components/Lightbox.ts) (markup in [init.ts](../../web/src/core/init.ts), styles in lightbox.css). Opens via `lightbox:open` CustomEvents dispatched from message images; images marked `data-pending` (unconfirmed sends) don't open it.

- **Gallery** = all images of the same message: prev/next arrows + `1 / N` counter, ←/→ keys, swipe on touch (disabled while zoomed). Adjacent images prefetch; blob URLs are cached per session and revoked on close.
- **Download** reuses the displayed blob with the original filename.
- **Fullscreen** via the Fullscreen API — feature-detected, button hidden on iPhone Safari (no element fullscreen there).
- **Zoom**: double-click/double-tap toggles `LIGHTBOX_ZOOM_SCALE` (2.5x) anchored at the pointer; wheel zooms up to `LIGHTBOX_ZOOM_MAX_SCALE` (4x); drag-to-pan with clamped bounds while zoomed.
- Closing: Escape (central popup handler), backdrop, or non-interactive toolbar area. `loadToken` guards against a slow fetch clobbering a newer navigation.
- E2E: "Chat - Lightbox Gallery" in [lightbox.spec.ts](../../web/tests/e2e/chat/lightbox.spec.ts) (navigation, counter, download filename, single-image chrome).

---

## Copy to Clipboard

The app provides copy-to-clipboard functionality at two levels:

### 1. Message-Level Copy

Copy button in message actions copies the entire message content.

**Behavior:**
- Excludes file attachments, thinking/tool traces, inline copy buttons, and language labels
- Appends `[Artifact: <title>]` per [artifact](artifacts.md) card (`artifactCopyText()`)
- Available on both user and assistant messages
- Shows checkmark feedback for 2 seconds after successful copy

### 2. Inline Copy

Individual copy buttons on code blocks and tables.

**Appearance:**
- Appear on hover (desktop) or always visible at 70% opacity (touch devices)
- Code blocks: Shows language label (e.g., "python") in top-left corner
- Tables: Wrapped in a bordered container for visual distinction
- Copy button positioned in top-right corner of each block

### Rich Text Support

- Copies both HTML and plain text formats using the Clipboard API
- When pasted into rich text editors (Word, Google Docs, etc.), formatting is preserved
- Tables are copied as HTML tables (preserves structure when pasted)
- Code blocks are copied as plain text (no syntax highlighting in clipboard)
- Plain text fallback for applications that don't support rich text

### Key Files

- [markdown.ts](../../web/src/utils/markdown.ts) - Custom renderers for code blocks and tables with copy button injection
- [file-actions.ts](../../web/src/core/file-actions.ts) - `copyMessageContent()`, `copyInlineContent()`, `copyWithRichText()`
- [messages.css](../../web/src/styles/components/messages.css) - `.copyable-content`, `.inline-copy-btn`, `.code-language` styles

### Testing

- E2E tests: "Chat - Copy to Clipboard" describe block in [clipboard.spec.ts](../../web/tests/e2e/chat/clipboard.spec.ts)

---

## Mermaid Diagrams

A ```` ```mermaid ```` code block in an answer renders as an SVG diagram
([mermaid.ts](../../web/src/utils/mermaid.ts), called from
`messages/render.ts` and `messages/streaming.ts`):

- The library (~2 MB) is imported only when a finished message contains a
  diagram - never per streamed token - as its own lazy chunk.
- It runs with `securityLevel: 'strict'` and the SVG is sanitized again with
  DOMPurify, since the diagram source is model output.
- The `base` theme is fed from the app's colour tokens, so diagrams match the
  light and dark themes.
- A block that doesn't parse stays the code block it was; the source stays in
  the DOM (hidden) so the copy button still copies it.

## Inline Artifacts

An [artifact](artifacts.md) renders as a card under the reply text, in tool-call
order: a title row ("View source", badges) and a sandboxed frame sized to its
content (up to 80% of the viewport, then it scrolls inside). A card for an older
version shows "v{n} · newer below" and flashes the newer card on click; a frame
that fails shows "Couldn't display" with Retry; a runtime error shows an
"Artifact error" badge. Frames follow the app theme live. Rendering:
[components/messages/artifacts.ts](../../web/src/components/messages/artifacts.ts),
styles: [artifacts.css](../../web/src/styles/components/artifacts.css).
