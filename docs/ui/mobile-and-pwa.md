# Mobile and PWA

This document covers mobile-specific functionality, Progressive Web App (PWA) features, touch gestures, and iOS Safari quirks that developers need to be aware of when working on mobile features.

## Table of Contents

- [Touch Gestures](#touch-gestures)
- [iOS Safari Gotchas](#ios-safari-gotchas)
- [PWA Viewport Height Fix](#pwa-viewport-height-fix)
- [Key Files](#key-files)
- [Testing](#testing)

## Touch Gestures

The app uses a reusable swipe gesture system (`createSwipeHandler` in [../../web/src/gestures/swipe.ts](../../web/src/gestures/swipe.ts)) that provides consistent swipe interactions across the application.

### Implemented Gestures

1. **Conversation swipe actions**: Swipe left on a conversation item to reveal rename and delete buttons, swipe right to close
2. **Sidebar swipe-to-open**: Swipe from left edge (within 50px) to open sidebar, swipe left on main content to close

### Gesture Priority

The swipe handler prevents conflicts by giving priority to more specific gestures (conversation swipes) over global gestures (sidebar edge swipe).

### Implementation Details

**Important considerations:**

- All touch handlers include `touchcancel` listeners for iOS Safari, which can cancel touches during system gestures
- The `activeSwipeType` state variable tracks whether a `'conversation'` or `'sidebar'` swipe is in progress to prevent conflicts
- **Critical**: `activeSwipeType` must only be set when actual swiping starts (in `onSwipeMove`), NOT in `shouldStart`. Setting it on touch start causes taps (non-swipes) to block subsequent sidebar swipes since `onComplete`/`onSnapBack` only run when `isSwiping` is true

### Usage Pattern

```typescript
import { createSwipeHandler } from './gestures/swipe';

const swipeHandler = createSwipeHandler({
  element: myElement,
  threshold: 50, // px to start swipe
  shouldStart: (x, y) => {
    // Determine if swipe should start based on position
    return true;
  },
  onSwipeMove: (deltaX, deltaY) => {
    // Handle swipe movement
    // Set activeSwipeType here, not in shouldStart!
  },
  onComplete: () => {
    // Swipe completed
  },
  onSnapBack: () => {
    // Swipe cancelled, snap back
  },
});
```

## iOS Safari Gotchas

When working on mobile/PWA features, beware of these iOS Safari issues:

### 1. PWA Viewport Height

In a PWA (no address bar), use `position: fixed; inset: 0` on the root container (`#app`) to fill the viewport. The flex children (sidebar and main panel) should use `align-self: stretch` (default) to fill the container height. Avoid explicit `height: 100vh` or `height: 100%` on flex children - let flexbox handle it naturally.

See [../../web/src/styles/layout.css](../../web/src/styles/layout.css) for the working implementation and the [PWA Viewport Height Fix](#pwa-viewport-height-fix) section below for detailed explanation.

### 2. Inline onclick Handlers

Inline `onclick` handlers don't work reliably on iOS Safari. Use event delegation instead of inline `onclick` on dynamically created elements. Attach listeners to parent containers.

**Bad:**
```typescript
element.innerHTML = `<button onclick="handleClick()">Click</button>`;
```

**Good:**
```typescript
element.innerHTML = `<button data-action="click">Click</button>`;
element.addEventListener('click', (e) => {
  if (e.target.dataset.action === 'click') {
    handleClick();
  }
});
```

### 3. PWA Caching

PWA caching is aggressive. Users may need to remove and re-add the app to home screen to see changes. Vite handles cache busting via hashed filenames, but be aware of this during development.

### 4. Touch Events Can Be Cancelled

iOS Safari may cancel touch sequences during system gestures (e.g., Control Center swipe, incoming calls). Always handle `touchcancel` events to reset gesture state.

```typescript
element.addEventListener('touchstart', handleStart);
element.addEventListener('touchmove', handleMove);
element.addEventListener('touchend', handleEnd);
element.addEventListener('touchcancel', handleCancel); // ← Essential!
```

### 5. PWA Keyboard Scroll Miscalculation

iOS Safari in PWA mode miscalculates the scroll position when the keyboard opens, causing the cursor to appear below the input initially. The fix uses the `visualViewport` API to detect when the keyboard opens (viewport height shrinks) and scrolls the input area into view.

See `isIOSPWA()` in [../../web/src/components/MessageInput.ts](../../web/src/components/MessageInput.ts):

```typescript
function isIOSPWA(): boolean {
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const isStandalone = ('standalone' in window.navigator) &&
                       (window.navigator as any).standalone;
  return isIOS && isStandalone;
}

// Listen for viewport changes
if (isIOSPWA() && window.visualViewport) {
  window.visualViewport.addEventListener('resize', () => {
    // Scroll input into view when keyboard opens
  });
}
```

### 6. Momentum Scroll Rubber-Banding

iOS Safari uses momentum scrolling with rubber-banding at scroll boundaries. This can cause `scrollTop` to temporarily go negative or exceed `scrollHeight - clientHeight`. The streaming scroll listener ignores these out-of-bounds values to prevent false user-scroll detection.

```typescript
function isScrolledToBottom(container: HTMLElement): boolean {
  const { scrollTop, scrollHeight, clientHeight } = container;

  // Ignore rubber-band values
  if (scrollTop < 0 || scrollTop > scrollHeight - clientHeight) {
    return false;
  }

  return scrollHeight - scrollTop - clientHeight < 200;
}
```

### 7. Background/Foreground Viewport Changes

When PWA goes to background and returns, `visualViewport` resize events may fire. The keyboard handler tracks `visibilitychange` events and ignores viewport resizes within 500ms of visibility changes.

```typescript
let lastVisibilityChange = 0;

document.addEventListener('visibilitychange', () => {
  lastVisibilityChange = Date.now();
});

window.visualViewport.addEventListener('resize', () => {
  // Ignore viewport changes shortly after visibility change
  if (Date.now() - lastVisibilityChange < 500) {
    return;
  }
  // Handle keyboard open/close
});
```

### 8. Orientation Change Scroll Position

Device orientation changes cause layout reflows that can lose scroll position. The `initOrientationChangeHandler()` in [../../web/src/components/Messages.ts](../../web/src/components/Messages.ts) saves scroll position as a percentage before orientation change and restores it after layout settles. Also handles resize events as a fallback for devices that don't fire `orientationchange`.

```typescript
function initOrientationChangeHandler() {
  let savedScrollPercentage: number | null = null;

  const saveScrollPosition = () => {
    const { scrollTop, scrollHeight, clientHeight } = messagesContainer;
    savedScrollPercentage = scrollTop / (scrollHeight - clientHeight);
  };

  const restoreScrollPosition = () => {
    if (savedScrollPercentage !== null) {
      const { scrollHeight, clientHeight } = messagesContainer;
      messagesContainer.scrollTop = savedScrollPercentage *
                                     (scrollHeight - clientHeight);
      savedScrollPercentage = null;
    }
  };

  window.addEventListener('orientationchange', () => {
    saveScrollPosition();
    requestAnimationFrame(() => {
      requestAnimationFrame(restoreScrollPosition);
    });
  });
}
```

### 9. Auto-Focus Causes Viewport Jumping

On iOS/iPad, focusing the textarea triggers the keyboard or accessory bar, causing the viewport to shift up. When switching conversations, this creates jarring up-down-up jumps: open conversation → viewport up, switch away → viewport down, new conversation → viewport up again.

**The fix**: Never auto-focus on iOS, only on desktop.

See `shouldAutoFocusInput()` in [../../web/src/components/MessageInput.ts](../../web/src/components/MessageInput.ts):

```typescript
function isIOS(): boolean {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
         (navigator.platform === 'MacIntel' &&
          navigator.maxTouchPoints > 1); // iPadOS 13+
}

function shouldAutoFocusInput(): boolean {
  return !isIOS();
}

// Usage
function focusMessageInput() {
  if (shouldAutoFocusInput()) {
    textarea.focus();
  }
}
```

**Key implementation details:**

- `isIOS()` detects all iOS devices including iPadOS 13+ (which reports as `MacIntel` but has `maxTouchPoints > 1`)
- `shouldAutoFocusInput()` returns `false` on iOS, `true` on desktop
- All `focusMessageInput()` calls are wrapped with `if (shouldAutoFocusInput())`
- For iPad + hardware keyboard users: a global `keydown` listener focuses the input when the user starts typing anywhere (so they can type immediately without tapping)
- This provides stable UX (no jumping) while preserving "type immediately" for hardware keyboard users

## PWA Viewport Height Fix

The app uses a specific layout approach to ensure the sidebar and main panel fill 100% of the screen height in PWA mode (no address bar, full screen).

### The Problem

Initially, the app had gaps at the bottom of the sidebar and main panel, especially when the keyboard opened/closed. Various approaches were tried (JavaScript viewport fixes, `100vh`, `100dvh`, `100svh`, explicit heights) but none worked reliably.

### The Solution

The final working solution uses:

1. **Root container**: `#app` with `position: fixed; inset: 0` - this naturally fills the viewport without needing explicit height
2. **Flex children**: Sidebar and main panel use `align-self: stretch` (default flexbox behavior) to fill the container height
3. **No explicit heights**: Avoid `height: 100%` or `height: 100vh` on flex children - let flexbox handle it

### Key Implementation

```css
#app {
    display: flex;
    position: fixed;
    inset: 0;  /* Fills viewport naturally */
    overflow: hidden;
}

.sidebar {
    display: flex;
    flex-direction: column;
    align-self: stretch;  /* Fills parent height */
    /* No explicit height needed */
}

.main {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-self: stretch;  /* Fills parent height */
    /* No explicit height needed */
}
```

### Why This Works

- `position: fixed; inset: 0` makes `#app` fill the viewport regardless of parent height
- Flexbox's default `align-items: stretch` (on flex container) makes children fill cross-axis (height)
- No JavaScript needed - pure CSS solution
- Works consistently in PWA mode where there's no address bar

### Layout Jump Prevention

The conversation cost display below the input area has `min-height: 16px` and is never hidden (no `:empty { display: none }`). This prevents layout jumping when the cost updates or when switching between conversations with/without costs.

## Key Files

**Gestures:**
- [../../web/src/gestures/swipe.ts](../../web/src/gestures/swipe.ts) - Reusable swipe handler

**Components:**
- [../../web/src/components/MessageInput.ts](../../web/src/components/MessageInput.ts) - iOS detection, keyboard handling
- [../../web/src/components/Messages.ts](../../web/src/components/Messages.ts) - Orientation change handling
- [../../web/src/components/Sidebar.ts](../../web/src/components/Sidebar.ts) - Conversation swipe actions

**Styles:**
- [../../web/src/styles/layout.css](../../web/src/styles/layout.css) - PWA viewport height fix
- [../../web/src/styles/main.css](../../web/src/styles/main.css) - Conversation cost display

## Testing

### E2E Tests

Mobile-specific functionality is tested in:

- `web/tests/e2e/mobile.spec.ts` - Mobile viewport tests
  - Touch gesture tests
  - Swipe actions
  - Mobile layout tests
- `web/tests/e2e/chat.spec.ts` - Chat functionality on mobile
  - Message sending with touch
  - Scroll behavior on mobile

### Visual Tests

Mobile UI is captured in visual regression tests:

- `web/tests/visual/mobile.visual.ts` - Mobile/iPad layout screenshots
  - Portrait and landscape orientations
  - Sidebar open/closed states
  - PWA viewport height

### Testing Strategy

**Desktop testing:**
```bash
make test-fe-e2e  # Run E2E tests (default desktop viewport)
```

**Mobile testing:**
```typescript
// In test file
test.use({ viewport: { width: 375, height: 812 } }); // iPhone X

test('mobile feature', async ({ page }) => {
  // Test will use mobile viewport
});
```

**iOS Simulator:**
For real iOS testing, use Xcode Simulator or physical devices. Note that some iOS-specific issues (like viewport jumping) may not reproduce in browser DevTools mobile emulation.

## See Also

- [Scroll Behavior](scroll-behavior.md) - Scroll handling including mobile considerations
- [Components](components.md) - UI component architecture
- [Testing](../testing.md) - Comprehensive testing documentation
