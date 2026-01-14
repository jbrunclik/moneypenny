# Scroll Behavior

Scroll behavior in the AI Chatbot is complex and carefully designed to handle multiple scenarios while providing a smooth user experience. This document covers all scroll-related functionality including automatic scrolling, user interruption, image loading, pagination, and streaming.

## Table of Contents

- [Overview](#overview)
- [Scroll Scenarios Reference](#scroll-scenarios-reference)
- [Scroll-to-Bottom Behavior](#scroll-to-bottom-behavior)
- [Streaming Auto-Scroll](#streaming-auto-scroll)
- [Programmatic Scroll Wrapper](#programmatic-scroll-wrapper)
- [Cursor-Based Pagination](#cursor-based-pagination)
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
| **Opening conversation with images** | Initial scroll to bottom (makes images visible), IntersectionObserver triggers thumbnail fetches, smooth scroll after all images finish loading | `thumbnails.ts`, `Messages.ts` |
| **Sending a new message (batch)** | User message added → scroll to bottom → assistant response added → scroll to bottom → if images, smooth scroll after they load | `sendBatchMessage()`, `addMessageToUI()` |
| **Sending a new message (streaming)** | User message added → scroll to bottom → auto-scroll during streaming → if images in final message, smooth scroll after load | `sendStreamingMessage()`, `autoScrollForStreaming()` |
| **Auto-scroll during streaming** | Content auto-scrolls as tokens arrive, keeping latest content visible | `autoScrollForStreaming()` in `Messages.ts` |
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
- If both conditions are true: enables `scrollOnImageLoad()` so images are tracked when observed
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
- **Direction-based detection**: Detects user scroll-up by tracking if `scrollTop` decreases (more reliable than position checks)

### Why Direction-Based Detection

The scroll listener must distinguish user scrolls from our programmatic `scrollToBottom()` calls. Position-based detection has issues:

1. When new content is added, `scrollHeight` increases
2. User appears "not at bottom" even though they never scrolled (just not at NEW bottom)
3. This could incorrectly disable auto-scroll

Direction-based detection solves this: our `scrollToBottom()` always increases `scrollTop`, so if `scrollTop` decreases, it must be a user scroll up. This works reliably regardless of content additions or scroll event timing.

### User Message Scroll

When user sends a message, the app scrolls to bottom immediately after adding the user message to the UI. This ensures the user's message is visible before the assistant's response starts streaming.

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

**2. Messages older pagination** ([../../web/src/components/Messages.ts](../../web/src/components/Messages.ts)):
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
- [../../web/src/components/Messages.ts](../../web/src/components/Messages.ts) - `renderMessages()`, `setupStreamingScrollListener()`, `autoScrollForStreaming()`, `cleanupStreamingContext()`, pagination
- [../../web/src/components/ScrollToBottom.ts](../../web/src/components/ScrollToBottom.ts) - Button component that triggers smooth scroll
- [../../web/src/components/Sidebar.ts](../../web/src/components/Sidebar.ts) - Conversations infinite scroll

**Main:**
- [../../web/src/core/messaging.ts](../../web/src/core/messaging.ts) - `sendBatchMessage()`, `sendStreamingMessage()`, scroll integration

**Backend:**
- [../../src/db/models/](../../src/db/models/) - `build_cursor()`, `parse_cursor()`, pagination methods
- [../../src/api/routes/conversations.py](../../src/api/routes/conversations.py) - Pagination endpoints
- [../../src/api/schemas.py](../../src/api/schemas.py) - Pagination response schemas
- [../../src/config.py](../../src/config.py) - Backend configuration

**Frontend State:**
- [../../web/src/state/store.ts](../../web/src/state/store.ts) - Pagination state management
- [../../web/src/api/client.ts](../../web/src/api/client.ts) - Pagination API methods
- [../../web/src/config.ts](../../web/src/config.ts) - Frontend configuration

## Testing

### E2E Test Coverage

Scroll behavior is comprehensively tested in E2E tests:

- `web/tests/e2e/chat.spec.ts` - "Chat - Streaming Auto-Scroll" describe block
  - `scrolls to bottom when sending a new message`
  - `auto-scroll can be interrupted by scrolling up during streaming`
  - `auto-scroll resumes when scrolling back to bottom during streaming`
  - `scroll position is maintained when scrolling up during active token streaming`
  - `rapid scrolling during streaming does not cause flicker or unexpected scroll jumps`
- `web/tests/e2e/chat.spec.ts` - "Chat - Scroll to Bottom" describe block
- `web/tests/e2e/chat.spec.ts` - "Chat - Conversation Switch During Active Request" describe block
- `web/tests/e2e/chat.spec.ts` - "Chat - Streaming Scroll Pause Indicator" describe block
- `web/tests/e2e/chat.spec.ts` - "Chat - Conversation Switch During Streaming Scroll" describe block
- `web/tests/e2e/pagination.spec.ts` - Pagination tests

### Backend Integration Tests

- [../../tests/integration/test_routes_pagination.py](../../tests/integration/test_routes_pagination.py) - Pagination endpoint tests

## See Also

- [Mobile and PWA](mobile-and-pwa.md) - iOS keyboard handling, viewport issues
- [Components](components.md) - UI component architecture
- [Performance](../backend/performance.md) - Performance optimizations
