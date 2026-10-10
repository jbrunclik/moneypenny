# Scroll Behavior

Scroll behavior in the Moneypenny is complex and carefully designed to handle multiple scenarios while providing a smooth user experience. This document covers all scroll-related functionality including automatic scrolling, user interruption, image loading, pagination, and streaming.

## Table of Contents

- [Overview](#overview)
- [Scroll Scenarios Reference](#scroll-scenarios-reference)
- [Scroll-to-Bottom Behavior](#scroll-to-bottom-behavior)
- [Streaming Auto-Scroll](#streaming-auto-scroll)
- [Programmatic Scroll Wrapper](#programmatic-scroll-wrapper)
- [Cursor-Based Pagination](#cursor-based-pagination)
- [Auto-Scroll Rules (Aug 2026 audit)](#auto-scroll-rules-aug-2026-audit)
- [Race Conditions and Edge Cases](#race-conditions-and-edge-cases)
- [Key Files](#key-files)
- [Testing](#testing)

## Overview

The application implements sophisticated scroll behavior that:

- Automatically scrolls to bottom when opening conversations
- Handles lazy-loaded images gracefully
- Provides interruptible auto-scroll during streaming
- Maintains scroll position during pagination
- Prevents scroll hijacking when users are browsing history

**CRITICAL**: This behavior took significant effort to get right. Before modifying any scroll-related code, understand all scenarios and ensure changes don't break them.

## Scroll Scenarios Reference

| Scenario | Expected Behavior | Key Files |
|----------|-------------------|-----------|
| **Opening a conversation** | Scroll to bottom immediately, then smooth scroll again after all images load | `renderMessages()`, `enableScrollOnImageLoad()` |
| **Opening conversation with images** | Initial scroll to bottom (makes images visible), IntersectionObserver triggers thumbnail fetches, smooth scroll after all images finish loading | `thumbnails.ts`, `messages/render.ts` |
| **Sending a new message (batch)** | User message added → loader added → **send-to-top**: the turn glides under the header, the loader reserves room → the reply takes over the reservation, view stays | `showLoadingIndicator()`, `anchorTurn()`, `renderBatchReply()` |
| **Sending a new message (streaming)** | User message added → streaming bubble added → **send-to-top** (turn under the header, reply grows below, view stays; "New messages" pill once it runs past the screen) → no move at the end | `addStreamingMessage()`, `anchorTurn()`, `autoScrollForStreaming()` |
| **Auto-scroll during streaming** | Content auto-scrolls as tokens arrive, keeping latest content visible | `autoScrollForStreaming()` in `messages/streaming.ts` |
| **User scrolls up during streaming** | Auto-scroll pauses immediately, scroll button highlights with pulsing animation | `setupStreamingScrollListener()`, `setStreamingPausedIndicator()` |
| **User scrolls back to bottom during streaming** | Auto-scroll resumes automatically, scroll button returns to normal | streaming scroll listener threshold check |
| **Streaming completes** | Scroll button indicator cleared automatically | `cleanupStreamingContext()` |
| **Click scroll-to-bottom button** | Smooth animated scroll to bottom | `ScrollToBottom.ts`, `scrollToBottom()` |
| **Images loading after initial render** | Track all pending images, smooth scroll only after ALL finish loading | `pendingImageLoads` counter, `scheduleScrollAfterImageLoad()` |
| **User scrolled up when images finish loading** | NO scroll (user is browsing history, don't hijack position) | `safelyDisableScrollOnImageLoad()` |
| **PWA keyboard opens** | Scroll input into view using visualViewport API | `MessageInput.ts` `isIOSPWA()` check |
| **Conversation switch during streaming** | Clean up streaming context if switching away, restore if switching back | `cleanupStreamingContext()`, `restoreStreamingMessage()` |
| **Loading older messages with images** | Track image loads and re-adjust scroll position as images load | `trackPrependedImagesForScrollAdjustment()` |

## Scroll-to-Bottom Behavior

The app automatically scrolls to the bottom when loading conversations and when new messages are added, but handles lazy-loaded images specially to avoid scrolling before images have loaded and affected the layout.

### How It Works

1. **Initial conversation load**: When `renderMessages()` is called, it always scrolls to bottom immediately to ensure latest messages are visible and images at the bottom become visible (triggering IntersectionObserver)
2. **Track image loads**: Each image that starts loading increments a `pendingImageLoads` counter
3. **Wait for completion**: The code waits for each image's `load` event (not just the fetch) to ensure it has fully rendered
4. **Debounced smooth scroll**: When all images finish loading (`pendingImageLoads === 0`), a smooth scroll animation is triggered after layout has settled
5. **Smooth animation**: Uses custom ease-out-cubic easing with duration based on scroll distance (300-600ms)

### New Message Additions

When a new message with images is added (via `sendBatchMessage()` or `finalizeStreamingMessage()`):

- Checks if the message has images that need loading (images without `previewUrl`)
- Checks if user was already at the bottom (`isScrolledToBottom()`)
- If both conditions are true: calls `enableScrollOnImageLoad()` so images are tracked when observed
- **Batch mode**: Message is added via `addMessageToUI()` (images are created and observed synchronously)
- **Streaming mode**: Images are added via `renderMessageFiles()` in `finalizeStreamingMessage()` (images are created and observed synchronously)
- Scrolls to bottom immediately (non-smooth) to ensure images are visible
- Uses double `requestAnimationFrame` to ensure scroll completed and layout settled
- Fallback: Checks if images are visible but haven't started loading, and re-observes them to trigger intersection check
- IntersectionObserver fires for visible images (either immediately or after re-observation)
- Scroll happens automatically after all images finish loading
- If no images or user wasn't at bottom: scrolls immediately (if at bottom)

### Smooth Scroll Implementation

- Custom animation in `scrollToBottom()` with ease-out-cubic easing
- Used both for button clicks and automatic scrolls after image loading
- Prevents abrupt flashing when images load and push content down

### User Scroll Detection

The app tracks user scrolls to disable auto-scroll when the user is browsing history:

- A scroll listener is set up when `enableScrollOnImageLoad()` is called
- Uses **direction-based detection**: only disables scroll mode when `scrollTop` DECREASES (user scrolled up)
- This prevents false positives when images loading above viewport increase `scrollHeight` (which increases distance from bottom but doesn't change `scrollTop`)
- Tracks `previousScrollTopForImageLoad` to detect scroll direction
- This prevents hijacking the scroll position when the user is viewing older messages
- **Critical**: The scroll listener distinguishes between user scrolls and programmatic scrolls (see Programmatic Scroll Wrapper section)

**Note**: Streaming auto-scroll uses a different approach - `wheel`/`touchmove` events instead of direction-based detection. See [Streaming Auto-Scroll](#streaming-auto-scroll) for details.

### Scroll Hijacking Prevention

When images load while the user is scrolled up, the system checks scroll position at multiple points to prevent race conditions:

- **Image load completion**: When an image finishes loading, the handler immediately checks scroll position using `isScrolledToBottom()` BEFORE decrementing `pendingImageLoads`. This prevents a race condition where layout changes from image loading could make the scroll position appear >200px from bottom, causing incorrect disabling. By checking BEFORE, we capture the state before layout changes affect the check.
- **Scheduled scroll protection**: The `isSchedulingScroll` flag prevents the user scroll listener from disabling scroll mode while a scroll is actively being scheduled. This prevents false positives from layout shifts during image loading.
- **Safe disable function**: `safelyDisableScrollOnImageLoad()` checks `isSchedulingScroll` before actually disabling scroll mode. This centralizes the logic and prevents race conditions.
- **Scheduled scroll**: `scheduleScrollAfterImageLoad()` re-checks `shouldScrollOnImageLoad` inside nested RAFs and ignores scroll-away checks when `isSchedulingScroll` is true (layout changes can cause false positives).
- **Final verification**: Verifies the user is still at/near the bottom using `isScrolledToBottom()` before actually scrolling
- If the user has scrolled up at any point, disables scroll mode immediately and returns early (prevents hijacking)

## Streaming Auto-Scroll

During streaming responses, a separate scroll system manages auto-scrolling to keep the latest content visible while allowing user interruption.

### How It Works

1. **Initial state**: When `addStreamingMessage()` is called, it checks if user is at bottom
2. **Scroll listener**: A streaming-specific scroll listener is set up to detect user scroll
3. **Auto-scroll during streaming**: `autoScrollForStreaming()` scrolls to bottom after each content update (thinking, tool, token)
4. **User interruption**: If user scrolls up (scrollTop decreases), auto-scroll is paused **immediately**
5. **Auto-scroll resume**: If user scrolls back to bottom, auto-scroll resumes automatically (with debounce)
6. **Cleanup**: When streaming ends (success or error), the scroll listener is cleaned up

### Key Behaviors

- **Interruptible**: User can scroll up during streaming to read history - auto-scroll pauses immediately
- **Resumable**: User can scroll back to bottom to resume auto-scroll (with 150ms debounce)
- **Threshold-based**: Uses 100px threshold to determine "at bottom" state for resume detection
- **Event-based detection**: Uses `wheel` and `touchmove` events to detect user scroll interaction

### Why Event-Based Detection

The scroll listener must distinguish user scrolls from layout changes (like images loading). We use `wheel` and `touchmove` events instead of scroll direction detection because:

1. **Reliable**: These events ONLY fire on actual user input (mouse wheel, trackpad, touch)
2. **No false positives**: Image loading can change `scrollTop` without user interaction, but never fires wheel/touchmove
3. **Layout-shift safe**: Content additions or layout shifts don't trigger these events

The previous direction-based approach (tracking `scrollTop` decreases) had issues when images loaded above the viewport - they could change `scrollTop` and incorrectly pause auto-scroll.

### Send-to-top (Oct 2026)

The ChatGPT / Claude.ai pattern ([turn-anchor.ts](../../web/src/components/messages/turn-anchor.ts)). Sending pins the user message to the bottom, then the reply placeholder (streaming bubble or batch loader) arrives and `anchorTurn()` glides the turn up so the user message sits just under the floating header (`scroll-padding-top`). Continue anchors the new bubble itself. A user message taller than the screen scrolls only far enough to keep `TURN_REPLY_MIN_VISIBLE_PX` of the reply in view.

- **Reserved space**: a short reply in a short chat can't reach the top on its own, so the reply element gets a `min-height` (`data-turn-space`) filling the band to the composer. It is held only while the reply streams: when it finishes, `settleTurnSpace` animates it away (`TURN_SPACE_RELEASE_MS`, instant under reduced motion) so a short answer settles above the composer like a normal chat instead of leaving an empty area until the next message (Oct 10 2026, user feedback); a long answer is taller than its reservation, so nothing moves. The clamped scrolling is marked programmatic - but only if no other programmatic scroll (the send glide) holds the single global marker, or ending it would expose the glide's last frames to the header auto-hide. A new turn or re-render drops any leftover (`releaseTurnSpace` / `resetTurnAnchor`). The batch reply takes the loader's reservation via `reserveTurnSpace()` **in the same task** the loader is removed — any layout read in between lets the browser clamp the position first.
- **No chasing**: anchored streams start with `shouldAutoScroll = false`. Once the reply runs past the screen the scroll button becomes the "New messages" pill. Tapping it, or the user scrolling to the real bottom (`STREAMING_RESUME_THRESHOLD_PX`, 16px — not the 200px follow threshold: the anchored view already sits at the reserved bottom, so any small scroll re-armed following), switches following back on. Programmatic scrolls never re-arm it.
- **No end-of-turn jump** for long answers: an anchored reply that wasn't re-followed stays in place (`settleAnchoredReply`); a followed one stays at the bottom; a short one glides down as its reserved space is released. The old read-from-start jump (`scrollToFinishedStreamMessage`) is gone; `RESPONSE_JUMP_MIN_VIEWPORT_RATIO` only steers an unanchored batch reply.
- **Reduced motion**: `scrollToBottom`/`scrollToPosition` and the native `scrollIntoView` calls jump instead of animating under `prefers-reduced-motion: reduce`.
- **Pitfalls found shipping it** (each has an E2E in `Chat - Send-to-top` / `program auto-start on a phone`):
  - The anchored view sits *at its reserved bottom*, so every "pin if at bottom" path fires on it. `applyCompactionMarkers` (runs after every turn) now returns early when no divider changed and checks a 1px bottom, and `composer-height.ts` re-fits the reservation (`refreshTurnSpace`) instead of pinning when a turn is anchored (the sports quick-actions bar grows the composer after the reservation). Any new "re-pin if at bottom" code must check `isTurnAnchored()`.
  - Measure with `offsetTop`, not `getBoundingClientRect`: entrance animations transform new messages.
  - While anchored, `.messages.turn-anchored` drops the first message's bottom-aligning `margin-top: auto`; it collapsed/expanded as the batch loader was swapped for the reply and moved every measurement.
  - The turn element is any non-assistant message before the reply (`.message:not(.assistant)`): a program's auto-start sends a `.trigger-message` chip, not a user bubble. Views that clear `#messages` themselves (sports/language) call `resetTurnAnchor`.

## Programmatic Scroll Wrapper

The app uses a programmatic scroll wrapper to distinguish between user-initiated scrolls and app-initiated scrolls, preventing the user scroll listener from incorrectly disabling auto-scroll.

### Why It Exists

- The user scroll listener disables auto-scroll when the user scrolls up (browsing history)
- Without the wrapper, programmatic scrolls (from `scrollToBottom()`, `renderMessages()`, etc.) would be detected as user scrolls
- This would cause auto-scroll to be disabled immediately after the app scrolls, breaking the scroll-on-image-load behavior

### How It Works

- `programmaticScrollToBottom()` automatically sets programmatic scroll markers before and after scrolling
- The scroll listener checks `isProgrammaticScroll` flag and ignores programmatic scrolls
- Markers are cleared after a short delay (150ms) to ensure scroll events have fired

### When to Use

**Always use `programmaticScrollToBottom()`** instead of raw `scrollToBottom()` for any programmatic scroll operations.

This includes:
- Scrolling after rendering messages
- Scrolling after adding new messages
- Scrolling after images load
- Any other app-initiated scroll operations

### Usage Example

```typescript
import { programmaticScrollToBottom } from './utils/thumbnails';

// Instead of:
scrollToBottom(container, false);

// Use:
programmaticScrollToBottom(container, false);

// For smooth scrolling:
programmaticScrollToBottom(container, true);
```

### Implementation Details

- `markProgrammaticScrollStart()` - Sets flag before scroll
- `markProgrammaticScrollEnd()` - Clears flag after scroll (with 150ms delay for scroll events)
- `programmaticScrollToBottom()` - Convenience wrapper that handles markers automatically
- For smooth scrolls, waits 700ms before clearing the flag (smooth scroll takes 300-600ms)

## Cursor-Based Pagination

The app uses cursor-based pagination for both conversations and messages to efficiently handle large datasets.

### Why Cursor-Based Pagination

- **Stable**: Cursors use `(timestamp, id)` tuples - new items don't shift existing pages
- **Efficient**: Uses existing indexes (`idx_conversations_user_id_updated_at`, `idx_messages_conversation_id_created_at`)
- **Bi-directional**: Supports both forward (older) and backward (newer) pagination for messages

### Cursor Format

- Format: `{timestamp}:{id}` (e.g., `2024-01-01T12:00:00.123456:msg-abc-123`)
- The ID serves as a tie-breaker when multiple items have the same timestamp
- Built with `build_cursor()` and parsed with `parse_cursor()` in [../../src/db/models/](../../src/db/models/)

### API Endpoints

1. **Conversations list** - `GET /api/conversations`
   - Query params: `limit` (default: 30, max: 100), `cursor` (optional)
   - Returns: Paginated conversations ordered by `updated_at DESC` (newest first)
   - Response includes: `next_cursor`, `has_more`, `total_count`

2. **Conversation detail** - `GET /api/conversations/<id>`
   - Query params: `message_limit` (default: 50, max: 200), `message_cursor` (optional), `direction` ("older" or "newer", default: "older")
   - Returns: Conversation with paginated messages ordered by `created_at ASC` (oldest first)
   - Response includes: `older_cursor`, `newer_cursor`, `has_older`, `has_newer`, `total_count`

3. **Messages endpoint** - `GET /api/conversations/<id>/messages`
   - Dedicated endpoint for fetching message pages (more efficient than full conversation endpoint)
   - Same query params and response format as conversation detail's message pagination

### Frontend Implementation

**1. Conversations infinite scroll** ([../../web/src/components/Sidebar.ts](../../web/src/components/Sidebar.ts)):
- Calculates optimal page size based on viewport height (`calculatePageSize()`)
- Uses `IntersectionObserver` to detect when user scrolls near bottom
- Automatically fetches next page when threshold reached (200px from bottom)
- Shows loading spinner during fetch
- Debounced scroll handler (100ms) to avoid excessive checks

**2. Messages older pagination** ([../../web/src/components/messages/pagination.ts](../../web/src/components/messages/pagination.ts)):
- Scroll listener detects when user scrolls near the top (within 200px)
- Automatically fetches older messages when threshold reached
- Prepends messages to UI while maintaining scroll position
- Shows loading indicator at top during fetch
- Debounced scroll handler (100ms) to avoid excessive checks
- **Disabled during streaming**: Older messages loading is skipped when streaming is active to prevent interference with streaming auto-scroll
- Cleanup function ensures proper listener removal on conversation switch

**3. Dynamic page sizing**:
- Conversations: Based on viewport height, ~60px per item, minimum 15 items
- Messages: ~120px per message estimate, minimum 20 items
- Buffer multiplier (1.5x) ensures smooth scrolling without gaps

### Configuration

**Backend** ([../../src/config.py](../../src/config.py)):
- `CONVERSATIONS_DEFAULT_PAGE_SIZE`: Default limit (30)
- `CONVERSATIONS_MAX_PAGE_SIZE`: Server-enforced maximum (100)
- `MESSAGES_DEFAULT_PAGE_SIZE`: Default limit (50)
- `MESSAGES_MAX_PAGE_SIZE`: Server-enforced maximum (200)

**Frontend** ([../../web/src/config.ts](../../web/src/config.ts)):
- `CONVERSATION_ITEM_HEIGHT_PX`: Estimated item height (60px)
- `MESSAGE_AVG_HEIGHT_PX`: Estimated message height (120px)
- `CONVERSATIONS_MIN_PAGE_SIZE`: Minimum items (15)
- `MESSAGES_MIN_PAGE_SIZE`: Minimum items (20)
- `VIEWPORT_BUFFER_MULTIPLIER`: Buffer for page size calculation (1.5x)
- `LOAD_MORE_THRESHOLD_PX`: Distance from bottom to trigger loading more conversations (200px)
- `LOAD_OLDER_MESSAGES_THRESHOLD_PX`: Distance from top to trigger loading older messages (200px)
- `INFINITE_SCROLL_DEBOUNCE_MS`: Scroll handler debounce (100ms)

## Auto-Scroll Rules (Aug 2026 audit)

The scroll behavior is the most annoyance-sensitive UX area (regressions here hurt daily use more than visual bugs). Key mechanics after the Aug 2026 audit:

- **One follow threshold**: every "is the user following?" decision uses `SCROLL_USER_DETECTION_THRESHOLD_PX` (200px) — `SCROLL_BOTTOM_THRESHOLD_PX` aliases it and `isScrolledToBottom` defaults to it. Don't introduce new distance constants for the same question.
- **Streaming pause** ([streaming.ts](../../web/src/components/messages/streaming.ts)): wheel/touchmove pause immediately; the scroll handler additionally pauses on **direction** (an upward, non-programmatic move landing away from the bottom) to cover scrollbar drags and keyboard scrolling. Never pause on position alone — streaming growth changes `scrollHeight` and produced false positives historically.
- **Scroll-button tap re-arms follow synchronously** (`setOnJumpToBottom` hook) — the debounced position-based resume can miss while tokens grow `scrollHeight` during the smooth animation. While paused mid-stream, the button becomes a labeled "New messages" pill.
- **End-of-turn**: see Send-to-top above — anchored turns don't move when the reply finishes.
- **Scrolls to an element clear the floating header** (Oct 2026): the header/toolbar float OVER the list, so `.messages` sets `scroll-padding-top` to the header spacer + list gap, and `scrollToElementTop` subtracts it (native `scrollIntoView` honours it already). Without it an element's first line landed under the header.
- **Stream-follow scrolls never hide the auto-hide header**: follow scrolls aren't marked programmatic (a marker window per token would swallow the scroll-up that pauses following), so `header-autohide.ts` asks `isStreamFollowScroll(container)`. Scroll events dispatch a frame after the write — by then finalize may have cleared the context and shrunk the message (the browser clamps to the new bottom) — so the last follow position, or a clamp below it to the bottom, still counts. Regression tests: `Chat - Send-to-top` in `chat/streaming.spec.ts`.
- **Older-page image compensation is per image** (`trackPrependedImagesForScrollAdjustment`): only the prepended page's images, each adding its own growth when it sits above the viewport. Comparing whole-list `scrollHeight` against the page-load baseline counted everything that grew since (a streamed reply) and threw the list down. The baseline height is taken before the loader goes in (it's gone again before compensation runs).
- **`overflow-anchor: none` on `.messages`**: scroll anchoring is manual (pagination prepend compensation + image-load adjustment); browser anchoring on top of it double-adjusted.
- **Mobile keyboard** ([core/keyboard-viewport.ts](../../web/src/core/keyboard-viewport.ts)): the fixed 100vh layout means keyboards OVERLAY the page. The visualViewport overlap becomes `--keyboard-inset` (shrinks `html/body` height) and the messages view re-pins to the bottom when the user was following. Guards: pinch zoom (`scale !== 1`), no editable element focused, overlaps under `KEYBOARD_INSET_MIN_PX`.
- **Thinking-trace collapse compensation**: finalizing the trace shrinks content above a reader scrolled below it — `finalizeThinkingIndicator` measures the height delta and restores `scrollTop`.
- **Don't touch** `scheduleScrollAfterImageLoad` in [thumbnails.ts](../../web/src/utils/thumbnails.ts) without a confirmed bug — it's correct-by-heavy-defense with dedicated regression E2E tests (2-image races in conversation.spec.ts).

## Race Conditions and Edge Cases

### Race Conditions Handled

1. **Image load timing**: The scroll listener has a 100ms debounce, but images can load faster than that. Without the immediate scroll position check in the image load handler, an image could finish loading while `shouldScrollOnImageLoad` is still `true` (because the debounced handler hasn't run yet), causing an unwanted scroll. The fix checks scroll position synchronously when the image finishes loading, ensuring we never scroll when the user has scrolled up, regardless of timing.

2. **Layout shift false positives**: When images load, they cause layout shifts that can temporarily make it appear the user has scrolled away from the bottom (scrollHeight increases, making distanceFromBottom > 200px). The `isSchedulingScroll` flag prevents the user scroll listener from disabling scroll mode during these layout shifts, and `scheduleScrollAfterImageLoad()` ignores scroll-away checks when `isSchedulingScroll` is true.

3. **Cached images on initial load**: On initial load, images may load instantly from cache before IntersectionObserver fires or before we can count them. The system verifies all tracked images are actually loaded before scheduling scroll.

4. **Images above viewport**: When loading a conversation with images at the TOP (above viewport), only VISIBLE images are tracked and waited for. The `checkTrackedImagesLoaded()` function only checks images marked with `data-scroll-tracked` (visible images), not all images. Images above the viewport will lazy-load when the user scrolls up, but they don't block the initial scroll to bottom.

5. **img.complete quirk**: Per MDN, `img.complete` returns `true` for images without a `src` attribute. When counting visible images, we check `img.src && img.complete` (not `img.src || img.complete`) to correctly identify cached images that are actually loaded.

6. **Programmatic vs user scrolls**: The programmatic marker system prevents false positives from layout shifts or race conditions between scroll events and debounced handlers.

## Key Files

**Scroll Utilities:**
- [../../web/src/utils/thumbnails.ts](../../web/src/utils/thumbnails.ts) - Image load tracking, `enableScrollOnImageLoad()`, `scheduleScrollAfterImageLoad()`, `programmaticScrollToBottom()`, user scroll detection
- [../../web/src/utils/dom.ts](../../web/src/utils/dom.ts) - `scrollToBottom()` with smooth animation, `isScrolledToBottom()`

**Components:**
- [../../web/src/components/messages/](../../web/src/components/messages/) - Message display modules:
  - `render.ts` - `renderMessages()`, `addMessageToUI()`
  - `streaming.ts` - `setupStreamingScrollListener()`, `autoScrollForStreaming()`, `cleanupStreamingContext()`
  - `pagination.ts` - Older/newer messages infinite scroll
- [../../web/src/components/ScrollToBottom.ts](../../web/src/components/ScrollToBottom.ts) - Button component that triggers smooth scroll
- [../../web/src/components/Sidebar.ts](../../web/src/components/Sidebar.ts) - Conversations infinite scroll

**Main:**
- [../../web/src/core/response-scroll.ts](../../web/src/core/response-scroll.ts) - end-of-response scroll (`settleAnchoredReply()`, `scrollToBatchReply()`, `watchForUserScroll()`), used by [stream-done.ts](../../web/src/core/stream-done.ts) and [batch-send.ts](../../web/src/core/batch-send.ts)

**Backend:**
- [../../src/db/models/](../../src/db/models/) - `build_cursor()`, `parse_cursor()`, pagination methods
- [../../src/api/routes/conversations.py](../../src/api/routes/conversations.py), [conversation_messages.py](../../src/api/routes/conversation_messages.py) - Pagination endpoints
- [../../src/api/schemas/conversations.py](../../src/api/schemas/conversations.py) - Pagination response schemas
- [../../src/config.py](../../src/config.py) - Backend configuration

**Frontend State:**
- [../../web/src/state/store.ts](../../web/src/state/store.ts) - Pagination state management
- [../../web/src/api/conversations.ts](../../web/src/api/conversations.ts) - Pagination API methods
- [../../web/src/config.ts](../../web/src/config.ts) - Frontend configuration

## Testing

### E2E Test Coverage

Scroll behavior is comprehensively tested in E2E tests:

- `web/tests/e2e/chat/streaming.spec.ts` - "Chat - Streaming Auto-Scroll" describe block
  - `scrolls to bottom when sending a new message`
  - `auto-scroll can be interrupted by scrolling up during streaming`
  - `auto-scroll resumes when scrolling back to bottom during streaming`
  - `scroll position is maintained when scrolling up during active token streaming`
  - `rapid scrolling during streaming does not cause flicker or unexpected scroll jumps`
- `web/tests/e2e/conversation.spec.ts` - "Scroll to bottom behavior" describe block
- `web/tests/e2e/chat/conversation-switch.spec.ts` - "Chat - Conversation Switch During Active Request" describe block
- `web/tests/e2e/chat/streaming.spec.ts` - "Chat - Streaming Scroll Pause Indicator" describe block
- `web/tests/e2e/chat/conversation-switch.spec.ts` - "Chat - Conversation Switch During Streaming Scroll" describe block
- `web/tests/e2e/chat/streaming.spec.ts` - "Chat - Send-to-top" (desktop + phone: long/short/batch, re-follow)
- `web/tests/e2e/pagination.spec.ts` - Pagination tests (incl. older page keeps the reading position)

### Backend Integration Tests

- [../../tests/integration/test_routes_pagination.py](../../tests/integration/test_routes_pagination.py) - Pagination endpoint tests

## See Also

- [Mobile and PWA](mobile-and-pwa.md) - iOS keyboard handling, viewport issues
- [Components](components.md) - UI component architecture
