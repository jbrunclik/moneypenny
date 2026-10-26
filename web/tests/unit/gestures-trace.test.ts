/**
 * Characterization of core/gestures.ts (setupTouchGestures): the listener
 * registrations (target, type, passive flag, order) and, for each step of
 * the conversation-row swipe and the sidebar edge swipe, what the handlers
 * wrote (styles, classes, preventDefault, sidebar open/close calls).
 *
 * Swipes can only be verified on a real iPhone, so a refactor must leave
 * these recordings identical. One sequence in one test: the module's
 * document listeners cannot be removed, so it is set up exactly once.
 */
import { describe, expect, it, vi } from 'vitest';

const calls: string[] = [];
vi.mock('@/components/Sidebar', () => ({
  toggleSidebar: () => calls.push('toggleSidebar'),
  closeSidebar: () => calls.push('closeSidebar'),
}));
vi.mock('@/utils/haptics', () => ({ hapticTick: () => calls.push('hapticTick') }));
vi.mock('@/gestures/swipe', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/gestures/swipe')>()),
  isTouchDevice: () => true,
}));

import { setupTouchGestures } from '@/core/gestures';
import { useStore } from '@/state/store';

function nameOf(target: EventTarget): string {
  if (target === document) return 'document';
  const el = target as HTMLElement;
  return el.id ? `#${el.id}` : `.${el.className}`;
}

describe('touch gestures write trace', () => {
  it('records registrations and every swipe step', () => {
    document.body.innerHTML = `
      <aside id="sidebar" class="sidebar">
        <div id="conversations-list">
          <div class="conversation-item-wrapper" id="w1">
            <div class="conversation-item" id="i1"></div>
            <button class="conversation-archive-swipe" id="b1"></button>
          </div>
          <div class="conversation-item-wrapper" id="w2">
            <div class="conversation-item" id="i2"></div>
          </div>
        </div>
      </aside>
      <div class="sidebar-overlay" id="overlay"></div>
      <main class="main"><div id="messages"></div></main>`;
    const sidebar = document.getElementById('sidebar') as HTMLElement;
    const main = document.querySelector('.main') as HTMLElement;
    const messages = document.getElementById('messages') as HTMLElement;
    const overlay = document.getElementById('overlay') as HTMLElement;
    const el = (id: string): HTMLElement => document.getElementById(id) as HTMLElement;

    const registrations: string[] = [];
    const original = EventTarget.prototype.addEventListener;
    const spy = vi.spyOn(EventTarget.prototype, 'addEventListener').mockImplementation(function (
      this: EventTarget,
      type,
      listener,
      options
    ) {
      registrations.push(`${nameOf(this)} ${type} ${JSON.stringify(options)}`);
      original.call(this, type, listener, options);
    });
    setupTouchGestures();
    spy.mockRestore();
    expect(registrations).toMatchInlineSnapshot(`
      [
        "#conversations-list touchstart {"passive":true}",
        "#conversations-list touchmove {"passive":true}",
        "#conversations-list touchend {"passive":true}",
        "#conversations-list touchcancel {"passive":true}",
        ".main touchstart {"passive":true}",
        ".main touchmove {"passive":false}",
        ".main touchend {"passive":true}",
        ".main touchcancel {"passive":true}",
        "#sidebar touchstart {"passive":true}",
        "#sidebar touchmove {"passive":false}",
        "#sidebar touchend {"passive":true}",
        "#sidebar touchcancel {"passive":true}",
        "document touchstart {"passive":true}",
        "document touchmove {"passive":true}",
        "document touchend {"passive":true}",
        "document touchcancel {"passive":true}",
        "document touchstart {"passive":true}",
      ]
    `);

    const steps: string[] = [];
    const state = (): string =>
      [
        `sb=${sidebar.className}|${sidebar.style.transform}|${sidebar.style.transition}`,
        `w1=${el('w1').className}|${el('i1').style.transform}|${el('i1').style.transition}`,
        `w2=${el('w2').className}|${el('i2').style.transform}`,
        `calls=${calls.splice(0).join(',')}`,
      ].join(' ');
    const touch = (label: string, target: HTMLElement, type: string, x = 0, y = 0): void => {
      const evt = new Event(type, { bubbles: true, cancelable: true });
      const point = [{ clientX: x, clientY: y }];
      Object.defineProperty(evt, 'touches', { value: type === 'touchend' || type === 'touchcancel' ? [] : point });
      Object.defineProperty(evt, 'changedTouches', { value: point });
      target.dispatchEvent(evt);
      steps.push(`${label} ${type}(${x},${y}) prevented=${evt.defaultPrevented} ${state()}`);
    };

    // Sidebar edge swipe: open from the left edge
    touch('edge-open', messages, 'touchstart', 5, 300);
    touch('edge-open', messages, 'touchmove', 8, 301);
    touch('edge-open', messages, 'touchmove', 40, 302);
    touch('edge-open', messages, 'touchmove', 200, 303);
    touch('edge-open', messages, 'touchend', 200, 303);
    sidebar.classList.add('open');

    // Swipe left on the open sidebar to close
    touch('close', sidebar, 'touchstart', 250, 300);
    touch('close', sidebar, 'touchmove', 245, 300);
    touch('close', sidebar, 'touchmove', 100, 302);
    touch('close', sidebar, 'touchend', 100, 302);

    // Overlay swipe, too short to close
    touch('overlay-short', overlay, 'touchstart', 300, 300);
    touch('overlay-short', overlay, 'touchmove', 280, 300);
    touch('overlay-short', overlay, 'touchend', 280, 300);
    sidebar.classList.remove('open');

    // Edge touch that turns out vertical: native scroll
    touch('edge-vertical', messages, 'touchstart', 5, 300);
    touch('edge-vertical', messages, 'touchmove', 7, 340);
    touch('edge-vertical', messages, 'touchmove', 60, 345);
    touch('edge-vertical', messages, 'touchend', 60, 345);

    // Edge swipe cancelled by iOS
    touch('edge-cancel', main, 'touchstart', 5, 300);
    touch('edge-cancel', main, 'touchmove', 60, 301);
    touch('edge-cancel', main, 'touchcancel', 60, 301);

    // Touch outside the edge zone: no sidebar swipe
    touch('mid', messages, 'touchstart', 200, 300);
    touch('mid', messages, 'touchmove', 260, 300);
    touch('mid', messages, 'touchend', 260, 300);

    // Conversation row: a rightward drag on a closed row does nothing
    touch('row-open', el('i1'), 'touchstart', 50, 100);
    touch('row-open', el('i1'), 'touchmove', 70, 101);
    touch('row-open', el('i1'), 'touchmove', 150, 102);
    touch('row-open', el('i1'), 'touchend', 150, 102);

    // Swiping the second row closes the first one first (outside-touch reset)
    touch('row2-snap', el('i2'), 'touchstart', 50, 200);
    touch('row2-snap', el('i2'), 'touchmove', 75, 200);
    touch('row2-snap', el('i2'), 'touchend', 75, 200);

    // A rightward drag again, then swipe left to reveal the actions
    touch('row-reopen', el('i1'), 'touchstart', 50, 100);
    touch('row-reopen', el('i1'), 'touchmove', 150, 100);
    touch('row-reopen', el('i1'), 'touchend', 150, 100);
    touch('row-close', el('i1'), 'touchstart', 150, 100);
    touch('row-close', el('i1'), 'touchmove', 100, 100);
    touch('row-close', el('i1'), 'touchmove', 40, 100);
    touch('row-close', el('i1'), 'touchend', 40, 100);

    // A touch on an action button never starts a swipe
    touch('button', el('b1'), 'touchstart', 50, 100);
    touch('button', el('b1'), 'touchmove', 150, 100);
    touch('button', el('b1'), 'touchend', 150, 100);

    // Swipe the revealed row 1 back closed
    touch('row-unswipe', el('i1'), 'touchstart', 40, 100);
    touch('row-unswipe', el('i1'), 'touchmove', 80, 100);
    touch('row-unswipe', el('i1'), 'touchmove', 150, 100);
    touch('row-unswipe', el('i1'), 'touchend', 150, 100);

    // A short left swipe snaps back
    touch('row-snap', el('i2'), 'touchstart', 150, 200);
    touch('row-snap', el('i2'), 'touchmove', 125, 200);
    touch('row-snap', el('i2'), 'touchend', 125, 200);

    // Mid row swipe, a second finger at the edge: the sidebar stays out
    touch('row-then-edge', el('i2'), 'touchstart', 150, 200);
    touch('row-then-edge', el('i2'), 'touchmove', 120, 200);
    touch('row-then-edge', messages, 'touchstart', 5, 300);
    touch('row-then-edge', messages, 'touchmove', 80, 300);
    touch('row-then-edge', el('i2'), 'touchend', 120, 200);

    // A row swipe in progress blocks the sidebar swipe; cancel resets
    touch('row-cancel', el('i2'), 'touchstart', 5, 200);
    touch('row-cancel', el('i2'), 'touchmove', 60, 200);
    touch('row-cancel', el('i2'), 'touchcancel', 60, 200);

    // Selection mode: rows do not swipe
    useStore.setState({ isSelecting: true });
    touch('selecting', el('i2'), 'touchstart', 50, 200);
    touch('selecting', el('i2'), 'touchmove', 150, 200);
    touch('selecting', el('i2'), 'touchend', 150, 200);
    useStore.setState({ isSelecting: false });

    expect(steps).toMatchInlineSnapshot(`
      [
        "edge-open touchstart(5,300) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-open touchmove(8,301) prevented=true sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-open touchmove(40,302) prevented=true sb=sidebar|translateX(-245px)|none w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-open touchmove(200,303) prevented=true sb=sidebar|translateX(-85px)|none w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-open touchend(200,303) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=toggleSidebar",
        "close touchstart(250,300) prevented=false sb=sidebar open|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "close touchmove(245,300) prevented=false sb=sidebar open|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "close touchmove(100,302) prevented=true sb=sidebar open|translateX(-150px)|none w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "close touchend(100,302) prevented=false sb=sidebar open|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=closeSidebar",
        "overlay-short touchstart(300,300) prevented=false sb=sidebar open|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "overlay-short touchmove(280,300) prevented=false sb=sidebar open|translateX(-20px)|none w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "overlay-short touchend(280,300) prevented=false sb=sidebar open|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-vertical touchstart(5,300) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-vertical touchmove(7,340) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-vertical touchmove(60,345) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-vertical touchend(60,345) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-cancel touchstart(5,300) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-cancel touchmove(60,301) prevented=true sb=sidebar|translateX(-225px)|none w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "edge-cancel touchcancel(60,301) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "mid touchstart(200,300) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "mid touchmove(260,300) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "mid touchend(260,300) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-open touchstart(50,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-open touchmove(70,101) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-open touchmove(150,102) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-open touchend(150,102) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row2-snap touchstart(50,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row2-snap touchmove(75,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row2-snap touchend(75,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-reopen touchstart(50,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-reopen touchmove(150,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-reopen touchend(150,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-close touchstart(150,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-close touchmove(100,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper|translateX(-50px)|none w2=conversation-item-wrapper| calls=",
        "row-close touchmove(40,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper|translateX(-110px)|none w2=conversation-item-wrapper| calls=",
        "row-close touchend(40,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper swiped|| w2=conversation-item-wrapper| calls=hapticTick",
        "button touchstart(50,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper swiped|| w2=conversation-item-wrapper| calls=",
        "button touchmove(150,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper swiped|| w2=conversation-item-wrapper| calls=",
        "button touchend(150,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper swiped|| w2=conversation-item-wrapper| calls=",
        "row-unswipe touchstart(40,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper swiped|| w2=conversation-item-wrapper| calls=",
        "row-unswipe touchmove(80,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper swiped|translateX(-120px)|none w2=conversation-item-wrapper| calls=",
        "row-unswipe touchmove(150,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper swiped|translateX(-50px)|none w2=conversation-item-wrapper| calls=",
        "row-unswipe touchend(150,100) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-snap touchstart(150,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-snap touchmove(125,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper|translateX(-25px) calls=",
        "row-snap touchend(125,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-then-edge touchstart(150,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-then-edge touchmove(120,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper|translateX(-30px) calls=",
        "row-then-edge touchstart(5,300) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper|translateX(-30px) calls=",
        "row-then-edge touchmove(80,300) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper|translateX(-30px) calls=",
        "row-then-edge touchend(120,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-cancel touchstart(5,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-cancel touchmove(60,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "row-cancel touchcancel(60,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "selecting touchstart(50,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "selecting touchmove(150,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
        "selecting touchend(150,200) prevented=false sb=sidebar|| w1=conversation-item-wrapper|| w2=conversation-item-wrapper| calls=",
      ]
    `);
  });
});
