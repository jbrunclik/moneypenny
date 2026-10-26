/**
 * The keyboard debug overlay (?kbdebug=1, or 5 quick taps on the chat
 * title in a PWA): every input to the keyboard-inset decision, so a user
 * screenshot pinpoints a failure on a real device.
 */
import { setScrollDebugSink } from '../../utils/dom';
import { KEYBOARD_BUILD_MARKER } from '../../config';

// Diagnostic overlay for real-device debugging (?kbdebug=1): the keyboard
// inset has failed on iOS in ways that resist local reproduction - this
// shows every input to the decision so a user screenshot pinpoints it.
let debugEl: HTMLDivElement | null = null;
// UI-local (F2): the ?kbdebug overlay's log
let debugEventLog: string[] = [];

function kbDebugEnabled(): boolean {
  // ?kbdebug=1 in a browser tab; PWAs launch from a fixed start_url, so
  // the flag also persists via localStorage (toggled by 5 quick taps on
  // the chat title - see initKbDebugToggle)
  return location.search.includes('kbdebug') || localStorage.getItem('kbdebug') === '1';
}

/** 5 quick taps on the chat title toggle the overlay (PWA has no URL bar). */
export function initKbDebugToggle(): void {
  setScrollDebugSink(kbDebug);
  let taps = 0;
  let lastTap = 0;
  let lastTouchTs = 0;
  const onTap = (e: Event): void => {
    if (
      !(e.target instanceof Element) ||
      !e.target.closest('#current-chat-title, .mobile-header, .chat-header')
    ) {
      return;
    }
    const now = Date.now();
    // A touch tap fires touchend AND a synthesized click - count it once
    if (e.type === 'touchend') {
      lastTouchTs = now;
    } else if (now - lastTouchTs < 500) {
      return;
    }
    taps = now - lastTap < 600 ? taps + 1 : 1;
    lastTap = now;
    if (taps >= 5) {
      taps = 0;
      const next = localStorage.getItem('kbdebug') === '1' ? '0' : '1';
      localStorage.setItem('kbdebug', next);
      if (next === '0' && debugEl) {
        debugEl.remove();
        debugEl = null;
      } else {
        kbDebug('enabled', {});
      }
    }
  };
  // touchend, not only click: iOS does NOT deliver document-level click
  // events for taps on non-interactive elements (the same quirk that
  // forbids inline onclick in this codebase)
  document.addEventListener('touchend', onTap);
  document.addEventListener('click', onTap);
}

function backdropFilterSupported(): boolean | undefined {
  return (
    typeof CSS !== 'undefined' &&
    (CSS.supports?.('backdrop-filter', 'blur(1px)') ||
      CSS.supports?.('-webkit-backdrop-filter', 'blur(1px)'))
  );
}

export function kbDebug(event: string, data: Record<string, unknown>): void {
  if (!kbDebugEnabled()) return;
  if (!debugEl) {
    debugEl = document.createElement('div');
    debugEl.style.cssText =
      'position:fixed;top:60px;left:8px;right:8px;z-index:99999;background:rgba(0,0,0,0.85);' +
      'color:#7fff7f;font:11px/1.5 monospace;padding:8px;border-radius:8px;pointer-events:none;' +
      'white-space:pre-wrap;';
    document.body.appendChild(debugEl);
  }
  const vv = window.visualViewport;
  // Keep the overlay inside the VISUAL viewport - keyboard-open pans move
  // fixed elements out of view exactly when the numbers matter most
  debugEl.style.top = `${Math.round((vv?.offsetTop ?? 0) + window.scrollY + 60)}px`;
  // Dedupe consecutive identical lines: the settle poller emits an update
  // every 300ms while the keyboard is open, flushing the interesting
  // transition events out of the log window
  const line = `${event} ${JSON.stringify(data)}`;
  if (debugEventLog[debugEventLog.length - 1] !== line) {
    debugEventLog.push(line);
    debugEventLog = debugEventLog.slice(-12);
  }
  // Resolved safe-area insets are only readable via a probe element
  let saProbe = document.getElementById('kbdebug-sa-probe');
  if (!saProbe) {
    saProbe = document.createElement('div');
    saProbe.id = 'kbdebug-sa-probe';
    saProbe.style.cssText =
      'position:fixed;visibility:hidden;height:env(safe-area-inset-bottom,0px);' +
      'width:env(safe-area-inset-top,0px);pointer-events:none;';
    document.body.appendChild(saProbe);
  }
  debugEl.textContent =
    `inH=${window.innerHeight} vvH=${vv?.height?.toFixed(0)} vvTop=${vv?.offsetTop?.toFixed(0)} ` +
    `scale=${vv?.scale} active=${document.activeElement?.tagName}\n` +
    `winY=${window.scrollY} docST=${document.scrollingElement?.scrollTop} ` +
    `bodyH=${document.body.clientHeight} docH=${document.documentElement.clientHeight}\n` +
    `scrH=${screen.height} outH=${window.outerHeight} scrY=${window.screenY} ` +
    `saB=${saProbe.offsetHeight} saT=${saProbe.offsetWidth} ` +
    `standalone=${(navigator as Navigator & { standalone?: boolean }).standalone === true} [${KEYBOARD_BUILD_MARKER}]\n` +
    (() => {
      const m = document.getElementById('messages');
      const ia = document.querySelector('.input-area');
      const pill = document.getElementById('input-container');
      const cph = getComputedStyle(document.documentElement).getPropertyValue('--composer-height').trim();
      const padB = m ? getComputedStyle(m).paddingBottom : '?';
      const dist = m ? Math.round(m.scrollHeight - m.scrollTop - m.clientHeight) : -1;
      const r = (el: Element | null) => (el ? el.getBoundingClientRect() : null);
      const mr = r(m), iar = r(ia), pr = r(pill);
      const reduceT = window.matchMedia?.('(prefers-reduced-transparency: reduce)').matches;
      const bfOk = backdropFilterSupported();
      const hdr = document.querySelector('.mobile-header');
      const hdrBg = hdr ? getComputedStyle(hdr).backgroundColor : '?';
      return (
        `msgST=${m?.scrollTop.toFixed(0)} msgSH=${m?.scrollHeight} msgCH=${m?.clientHeight} distBottom=${dist} cph=${cph} padB=${padB}\n` +
        `msgBot=${mr?.bottom.toFixed(0)} iaTop=${iar?.top.toFixed(0)} iaBot=${iar?.bottom.toFixed(0)} pillTop=${pr?.top.toFixed(0)} pillBot=${pr?.bottom.toFixed(0)}\n` +
        `reduceTransparency=${reduceT} backdropOk=${bfOk} hdrBg=${hdrBg}\n`
      );
    })() +
    debugEventLog.join('\n');
}
