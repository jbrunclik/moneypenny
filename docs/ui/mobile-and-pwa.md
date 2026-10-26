# Mobile and PWA

This document covers mobile-specific functionality, Progressive Web App (PWA) features, touch gestures, and iOS Safari quirks that developers need to be aware of when working on mobile features.

## Table of Contents

- [Touch Gestures](#touch-gestures)
- [iOS Safari Gotchas](#ios-safari-gotchas)
- [Device check runner](#device-check-runner)
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

**The Aug 2026 ten-round keyboard saga - definitive rules:**

- **Apply the inset where fixed positioning lives.** `#app` is
  `position: fixed` - it sizes against the LAYOUT VIEWPORT and ignores
  html/body heights entirely. Three rounds of body-height fixes
  (vh → dvh → JS-driven) changed nothing because the composer lived at the
  bottom of the fixed container. The inset belongs on `#app`
  (`height: calc(var(--app-vh) - var(--keyboard-inset))`, top-anchored).
- **No native height measure tells the truth in every environment**
  (all device-verified, iPhone iOS 26, screen 874pt, saT=62, saB=34):

  | Measure | Safari tab | Standalone PWA |
  |---|---|---|
  | `100vh` | LIES (largest viewport, 743) | truthful (full webview, 874) |
  | `innerHeight` | truthful (654 chrome expanded) | LIES at rest (874-saT=812) and **OSCILLATES 471↔812 while the keyboard is open** |
  | `visualViewport.height` | truthful (363 kb open) | truthful per-state (471 kb open) but **excludes only the keyboard, NOT the floating input-assistant pill** |
  | `env(safe-area-inset-top)` | 0 | 62 |

  Hence `trueViewportHeight()` = 100vh probe in standalone / `innerHeight`
  in browser (exported as `--app-vh`), and ONE keyboard formula everywhere:
  `shrink = trueViewportHeight() - visualViewport.height - safeAreaTop()`
  (standalone kb: 874-471-62=341; Safari kb: 654-363-0=291; all rest
  states: 0; `measureKeyboardInset()`, which also adds the pill below).
  Never build an inset from `innerHeight` - the standalone
  oscillation makes it flap 341→0→341 mid-focus, which collapses the
  layout and DISMISSES the keyboard.
- **Standalone only: add `KEYBOARD_STANDALONE_ACCESSORY_PX` (50) to the
  inset.** iOS's floating prev/next/done pill hovers ~50pt above the
  keyboard OVER page content and is excluded from the visual viewport in
  Safari tabs but INCLUDED in standalone - no API reports it; it covered
  the composer's bottom edge. If a device shows a small overlap/gap right
  at the composer bottom, this constant is the dial (pill size may vary by
  device class/iOS version; iPad renders a full-width bar instead).
- **Reclaim padding while typing via `:root.kb-open`** (toggled by
  keyboard-viewport.ts with the inset). The keyboard + pill take 391pt of
  an 874pt screen; the home indicator sits BELOW the keyboard, so the
  composer's safe-area-bottom padding (34pt) is dead space exactly when
  room is scarcest - dropped while the keyboard is open (~38pt more
  message area). Further dials if "space above the keyboard is tiny"
  comes up again: compact/hidden header while typing (~90-118pt),
  disabling the predictive-text row (costs autocorrect).
- **`interactive-widget=resizes-content` in the viewport meta is a no-op
  on this iOS version** (ICB stayed 654 in Safari with the keyboard open) -
  kept because it's the correct platform hint where supported and harmless
  where not. Do NOT assume it replaces the inset machinery.
- **The stray focus scroll must be reverted, and it needs a `window`
  scroll listener.** iOS scrolls the WINDOW for its caret reveal using
  pre-shrink geometry and never re-clamps (stranded `winY=291/341`,
  composer pinned at screen top over a dead band). The window is never
  legitimately scrolled in this app (html/body overflow hidden) - any
  persistent `winY > 0` is reset whenever no finger is down
  (`touchstart/touchend` tracking; `resetStrayWindowScroll()`). visualViewport events do NOT fire for
  window scrolls; without `window.addEventListener('scroll', ...)` the
  strand is invisible to the update loop.
- **Debug on-device with `?kbdebug=1`** (browser) or **5 quick taps on the
  chat title** (PWA; persists via localStorage) - overlay shows all
  geometry inputs + the last 12 detection events (consecutive duplicates
  deduped, or the 300ms settle poller flushes the interesting
  transitions). Bump the `[kbN]` marker (`KEYBOARD_BUILD_MARKER` in
  `web/src/config.ts`) whenever iterating - it identifies which bundle a
  user screenshot, a [layout check](#layout-checks-field-telemetry) report
  or a [device check run](#device-check-runner) is running, which resolved
  several "fix doesn't work" rounds that were actually stale tabs.
  Other modules log into it via `scrollDebug()` (utils/dom.ts; the overlay is its sink).
- **Mind HTML cache staleness during mobile iteration**: the index page
  must send `Cache-Control: no-cache` (see docs/deployment.md) or Safari
  serves hours-old bundles - and an already-open tab keeps the old bundle
  until reloaded regardless.

**Keyboard-inset rules learned the hard way (Aug 2026, `core/keyboard-viewport.ts`):**

- **Never derive layout from `visualViewport.offsetTop`** (pan position). On
  screens with no inner scroll container (welcome screen), drags pan the
  visual viewport per pixel — a pan-dependent `--keyboard-inset` reflows the
  whole page mid-gesture and scrolling becomes extremely laggy. Derive the
  inset from keyboard GEOMETRY only (the unified formula above);
  `visualViewport` scroll events must be layout-free early-returns.
- **Standalone caret ghost**: iOS pans the layout viewport to reveal a focused
  bottom input BEFORE the inset shrinks the page; WebKit then draws the caret
  at the stale pan position, visibly outside the input. Fix: on the
  keyboard-OPEN transition only, `window.scrollTo(0, 0)` + re-assert the
  selection range to force a caret redraw (`settleWithKeyboardUp()`, which
  also re-pins a bottom-following list across the settle). Never re-run this
  on later inset fluctuations — it fights in-progress user gestures.
- **Layout of the module (Oct 26 2026 refactor, verbatim moves):**
  `initKeyboardViewportPinning()` registers the listeners and owns `update()`,
  which calls `measureKeyboardInset()` → `resetStrayWindowScroll()` → (on an
  inset change) `holdAnchorThroughInsetChange()` for an anchored turn and
  `settleWithKeyboardUp()` while the inset is > 0. Every write it makes, with
  its timing, is recorded in `web/tests/unit/keyboard-viewport-trace.test.ts`
  (gestures, the hardware-keyboard focus and the smooth scroll-to-bottom have
  `gestures-trace`, `message-input-hardware-keyboard` and `smooth-scroll-trace`):
  a refactor must leave those recordings unchanged.

### Layout checks (field telemetry)

The rules above were all found on a device, usually days after a build
shipped. Since Oct 26 2026 phones and tablets check them during normal use
([../../web/src/core/layout-checks.ts](../../web/src/core/layout-checks.ts))
and report a violation to the server, so the admin page shows per build
whether a new one regressed.

**When it checks.** Only at settled moments: `LAYOUT_CHECK_SETTLE_MS` (700ms)
after the last visualViewport resize/scroll, window resize/scroll or focus
change, with the geometry unchanged since that event (iOS moves the viewport
silently at times - then it waits again). A failure must still hold
`LAYOUT_CHECK_CONFIRM_MS` (600ms) later, past the keyboard code's 300ms settle
poller, with no event in between. Pinch zoom (`scale !== 1`) skips. It only
reads: `measureKeyboardInset()`, `isStandaloneDisplay()` and `isTouchActive()`
from keyboard-viewport.ts, the applied `--keyboard-inset`, `turnAnchorDrift()`
from turn-anchor.ts, and the `bottom-done`/`glide-done` scroll diagnostics
(`addScrollDebugListener` in utils/dom.ts). It never writes a style or
scrolls. It runs on iOS (`isIOS()`) or a coarse pointer only.

| Invariant (shapes) | Fails when | Tolerance |
|---|---|---|
| `composer_gap` (`gap`, `overlap`) | keyboard up (applied and computed inset > 0) and the composer's bottom (`.input-area`) is off the keyboard top: `vv.offsetTop + vv.height`, minus the 50px pill in standalone. `gap`: dead band above the keyboard; `overlap`: composer under it | 20px (`LAYOUT_COMPOSER_GAP_TOLERANCE_PX`) |
| `stranded_pan` (`keyboard-open`, `keyboard-closed`) | the window stays scrolled with no finger down (the pan reset missed it) | 1px |
| `inset_mismatch` (`stuck`, `missing`, `off`) | the applied `--keyboard-inset` differs from the unified formula for the settled viewport. `stuck`: left after the keyboard closed; `missing`: a keyboard the inset missed | 4px (`LAYOUT_INSET_TOLERANCE_PX`) |
| `anchor_drift` (`keyboard-open`, `keyboard-close`) | the view rested on an anchored turn (at a settled check or when the send glide ended), the keyboard opened or closed, no user scroll since, no glide running, and the view ended off the anchor | 8px (`LAYOUT_ANCHOR_DRIFT_TOLERANCE_PX`) |
| `scroll_bottom_miss` (`short`) | a smooth scroll to the bottom ended (`bottom-done`) more than the tolerance short, and 600ms later the list is still short (no user input, no anchored turn, no other scroll) | 24px (`LAYOUT_SCROLL_BOTTOM_TOLERANCE_PX`) |

The composer tolerance is a first guess: the pill's size varies by device and
iOS version. If one device reports a steady `composer_gap` of the same size,
the numbers in the report say whether `KEYBOARD_STANDALONE_ACCESSORY_PX` or
the tolerance needs the change.

**What is sent.** Each invariant and shape once per page load, at most
`LAYOUT_REPORTS_PER_PAGE_MAX` (5), at least `LAYOUT_REPORT_MIN_INTERVAL_MS`
(10s) apart (a skipped one goes out if it recurs later), signed-in users
only. `POST /api/client-errors` with `kind: "layout"` and a `layout` object:
the invariant, the shape, the `[kbN]` marker, standalone or tab, the iOS
version (Safari's `Version/` token, else the UA's OS token - frozen at 18.6 on
iOS 26) and at most 16 numbers (CSS px, one decimal): `inner_height`,
`vv_height`, `vv_offset_top`, `keyboard_inset`, `scroll_y`, plus the check's
own (`composer_top`/`composer_bottom`, `expected_inset`/`shrink`, and
`deviation`, signed). Names and numbers only - never text from the screen.

**Reading the admin section** ("Layout checks", [admin.md](../features/admin.md)):
one block per build (app version and `[kbN]` marker), newest first, the
deployed build marked. Each row is one invariant and shape: how often, how
many people, home-screen app or browser tab, iOS version, last seen, and the
latest report's numbers. A check that a build reports and the one before it
didn't is the regression; a steady count across builds is a known gap (or a
tolerance to revisit). A device that reports nothing either works or never
reached a settled failure - the kbdebug overlay is still the tool for a
single session.

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

Device orientation changes cause layout reflows that can lose scroll position. The `initOrientationChangeHandler()` in [../../web/src/components/messages/orientation.ts](../../web/src/components/messages/orientation.ts) saves scroll position as a percentage before orientation change and restores it after layout settles. Also handles resize events as a fallback for devices that don't fire `orientationchange`.

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

### 10. Liquid glass softens header text (iOS 27)

On iOS 27 (Oct 2026) the mobile header title and the sidebar's app name read
slightly soft over the liquid glass (`backdrop-filter`); body text is sharp.
It is not the code: the header renders byte-identically to builds from before
the iOS update in WebKit, and Settings > Accessibility > Reduce Transparency
(which drops the blur) makes the text sharp. Tried and reverted, neither helped
on the device: the frost on a `::before` layer behind the content, and the
title on its own GPU layer (`translateZ(0)`). Only removing the blur fixes it,
and the glass is the chosen look, so it stays. Kept from that work: the title
is centered between gutters, not with `translateX(-50%)` (a half device pixel).

## Device check runner

Scripted layout checks that run inside the app, so they reach the installed
standalone PWA, which no external automation can (Oct 26 2026). Results,
with the measured numbers, go to the admin page's **Device checks** section
per `[kbN]` build ([admin.md](../features/admin.md#device-checks)).

**On the iPhone** (after every keyboard or scroll change, once per build):

1. Deploy, then open the **installed** app (home screen icon - a Safari tab
   measures the tab, also worth a run) and pull a fresh bundle: close and
   reopen it; the kbdebug overlay (5 taps on the title) shows the `[kbN]`.
2. User menu -> **Admin** -> **Device checks** -> **Run device checks**. The
   admin page closes and a card sits over the top of the chat.
3. The run opens a temporary conversation (80 scripted messages, archived so
   no other device lists it, no model call) and checks itself. When the card
   shows **Tap to open the keyboard**, tap it: iOS opens the keyboard only
   from a real tap, so the button's own handler focuses the composer. Don't
   touch the screen otherwise. Then **Tap to close the keyboard**.
4. The summary reads e.g. "6/6 passed"; **Close** returns to the admin page,
   where the run is listed ("[kb19] 6/6 passed - standalone - iOS 26.1 -
   today 14:32"); expand it for every scenario's numbers.

**Stop** ends a run without storing it. Either way the temporary
conversation is deleted permanently and the chat that was open comes back;
one left by a crashed run (app killed mid-run) is purged by the next run.

| Scenario | Passes when |
|---|---|
| Environment | always (standalone, UA summary, inner / visual / true viewport heights, safe-area insets, `[kbN]`, app version) |
| Long conversation opens at the bottom | distance to the bottom <= 2px, no window pan (scrollY, visualViewport.offsetTop <= 1px) |
| Send-to-top anchors the turn | a local user message + the batch loader (`showLoadingIndicator`, which anchors like a real send; nothing is sent): the turn's top within 3px of `scroll-padding-top`, `isTurnAnchored()`, no pan |
| Keyboard opens (tap) | after the settle: `--keyboard-inset` equals the [unified formula](#5-pwa-keyboard-scroll-miscalculation) within 2px; composer-to-keyboard gap (keyboard top = vvH + saT) equals the accessory allowance (50 standalone, 0 tab) within 6px; no pan; the anchored turn moved <= 4px (the note says where it ended relative to the anchor line). Diagnostics stored with it: the list's scrollTop, clientHeight, turn-space reservation, scroll-padding-top, header-hidden and `--composer-height` before/after, `anchored_after` / `at_anchor_after`, `anchor_drift_px`, `anchor_expected_top_px` (0, or minus the offset for a message taller than the band), `turn_from_anchor_px`, and which anchor holds ran (`holds_keyboard`, `holds_keyboard_delayed`, `holds_composer`, `holds_resize`, `resize_refits`, `resize_retargets`) |
| Scroll-to-bottom button with the keyboard up | the button shows after scrolling to the top; its tap ends within 2px of the bottom; composer gap as above; no pan |
| Keyboard closes (tap) | inset 0, `kb-open` gone, `#app` as tall as the true viewport and the composer flush with its bottom (1px), no pan |

The tolerances are `DEVICE_CHECK_*` in `web/src/config.ts`. Without a
software keyboard (desktop, Playwright) the keyboard steps are "skipped - no
software keyboard" with no tap asked; on a touch device whose keyboard never
appears (a hardware keyboard on an iPad) the later steps skip with "the
keyboard did not open", while a keyboard that opened with a wrong inset fails.
The UA summary reads iOS Safari's version from `Version/` (iOS 26 freezes
the OS token at 18.6); the standalone PWA sends no `Version/`, so its run
shows the frozen OS - the build marker and the `standalone` flag tell runs
apart.

**Adding a scenario:** an entry in `DEVICE_CHECK_SCENARIOS`
(`web/src/core/device-checks/scenarios.ts`: drive the app's real code path,
measure with `measure.ts`, judge with a pure function in `evaluate.ts` and
unit-test it with fake numbers in `device-check-evaluate.test.ts`).
`requires` marks the keyboard steps. `core/layout-checks.ts` (field
telemetry) measures similar invariants; the two measurement modules can merge.

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
- [../../web/src/core/gestures.ts](../../web/src/core/gestures.ts) - `setupTouchGestures()`: the conversation-row swipe (`createConversationSwipe`) and the sidebar edge swipe (`createSidebarSwipeHandlers`), sharing one active-swipe state

**Keyboard:**
- [../../web/src/core/keyboard-viewport.ts](../../web/src/core/keyboard-viewport.ts) - `--keyboard-inset`, `--app-vh`, `kb-open`, the pan guard, the settle poller and the kbdebug overlay
- [../../web/src/core/layout-checks.ts](../../web/src/core/layout-checks.ts) - the field layout checks (tests: `web/tests/unit/layout-checks.test.ts`)

**Components:**
- [../../web/src/components/MessageInput.ts](../../web/src/components/MessageInput.ts) - iOS detection, keyboard handling
- [../../web/src/components/messages/orientation.ts](../../web/src/components/messages/orientation.ts) - Orientation change handling
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
- `web/tests/e2e/chat/` - Chat functionality on mobile
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

## Touch Targets

Composer and header controls draw at 30-36px. Under `@media (pointer: coarse)` each gets an
invisible 44px hit area (`::before`, centred - `buttons.css` "Touch hit areas") instead of a
bigger button: growing the buttons would change the composer height and with it the
keyboard geometry. `.btn-send`/`.btn-stop` keep `::after` for the upload ring. Test:
`web/tests/e2e/touch-targets.spec.ts`.
