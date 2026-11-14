/**
 * The bridge inside the frame (src/artifact/bridge-client.ts): the `mp` API
 * an artifact calls, and what it posts to the chat.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { checklistKeys, installBridgeClient, type MpApi } from '../../src/artifact/bridge-client';
import type { FromFrame } from '../../src/artifact/protocol';

let posted: FromFrame[];
let mp: MpApi;
let client: ReturnType<typeof installBridgeClient>;

function setActivation(isActive: boolean | undefined): void {
  Object.defineProperty(navigator, 'userActivation', {
    configurable: true,
    value: isActive === undefined ? undefined : { isActive },
  });
}

beforeEach(() => {
  posted = [];
  document.body.innerHTML = '';
  client = installBridgeClient(window, (m) => posted.push(m));
  mp = (window as unknown as { mp: MpApi }).mp;
});

afterEach(() => {
  client.uninstall();
  setActivation(undefined);
});

describe('mp.send', () => {
  it('posts nothing without a user gesture', () => {
    setActivation(false);
    mp.send('Scale to 6');
    expect(posted.filter((m) => m.type === 'mp:send')).toEqual([]);
  });

  it('posts the text during a user gesture', () => {
    setActivation(true);
    mp.send('Scale to 6');
    expect(posted).toContainEqual({ type: 'mp:send', text: 'Scale to 6' });
  });

  it('falls back to a recent click where userActivation is missing', () => {
    setActivation(undefined);
    mp.send('no click yet');
    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    mp.send('after click');
    const sent = posted.filter((m) => m.type === 'mp:send');
    expect(sent).toEqual([{ type: 'mp:send', text: 'after click' }]);
  });
});

describe('mp.state', () => {
  it('get resolves to the init state, set posts the new one', async () => {
    const pending = mp.state.get();
    client.applyInit({ checked: [1] }, 'dark');
    expect(await pending).toEqual({ checked: [1] });

    mp.state.set({ checked: [1, 2] });
    expect(posted).toContainEqual({
      type: 'mp:state',
      state: { app: { checked: [1, 2] }, checklist: {} },
    });
    expect(await mp.state.get()).toEqual({ checked: [1, 2] });
  });

  it("hands artifact code only its own state", async () => {
    client.applyInit({ app: { n: 1 }, checklist: { Milk: true } }, 'dark');
    expect(await mp.state.get()).toEqual({ n: 1 });
  });
});

describe('checklist ticks', () => {
  const item = (label: string) => `<li><label><input type="checkbox"> ${label}</label></li>`;
  const list = (...labels: string[]) =>
    (document.body.innerHTML = `<ul class="mp-checklist">${labels.map(item).join('')}</ul>`);
  const boxes = () => [...document.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
  const tick = (box: HTMLInputElement, checked = true) => {
    box.checked = checked;
    box.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const lastState = () => posted.filter((m) => m.type === 'mp:state').at(-1);

  it('saves a tick as the whole envelope', () => {
    client.applyInit(null, 'dark');
    list('Milk');
    tick(boxes()[0]!);
    expect(lastState()).toEqual({ type: 'mp:state', state: { app: null, checklist: { Milk: true } } });
    tick(boxes()[0]!, false);
    expect(lastState()).toEqual({ type: 'mp:state', state: { app: null, checklist: {} } });
  });

  it('keeps ticks when artifact code sets its state', () => {
    client.applyInit(null, 'dark');
    list('Milk');
    tick(boxes()[0]!);
    mp.state.set({ score: 3 });
    expect(lastState()).toEqual({
      type: 'mp:state',
      state: { app: { score: 3 }, checklist: { Milk: true } },
    });
  });

  it('restores ticks after render, telling repeated labels apart', () => {
    client.applyInit({ checklist: { 'Eggs #2': true } }, 'dark');
    list('Milk', 'Eggs', 'Eggs');
    client.restoreChecklist();
    expect(boxes().map((b) => b.checked)).toEqual([false, false, true]);
  });

  it('keys nested label markup by its text', () => {
    document.body.innerHTML =
      '<ul class="mp-checklist"><li><label><input type="checkbox"> <b>Milk</b>  2 l</label></li></ul>';
    expect(checklistKeys(document).map((k) => k.key)).toEqual(['Milk 2 l']);
  });

  it('ignores checkboxes outside a checklist', () => {
    client.applyInit(null, 'dark');
    document.body.innerHTML = '<label><input type="checkbox"> Dark mode</label>';
    tick(boxes()[0]!);
    expect(lastState()).toBeUndefined();
  });
});

describe('theme', () => {
  it('applies the theme to the document and tells the artifact', () => {
    const seen: string[] = [];
    window.addEventListener('mp:theme', () => seen.push(mp.theme));
    client.applyInit(null, 'light');
    expect(document.documentElement.dataset.theme).toBe('light');
    client.applyTheme('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(mp.theme).toBe('dark');
    expect(seen).toEqual(['light', 'dark']);
  });
});

describe('links and errors', () => {
  it('a link click is held back and forwarded to the chat', () => {
    document.body.innerHTML = '<a href="https://example.com/x">x</a>';
    const link = document.querySelector('a')!;
    const event = new MouseEvent('click', { bubbles: true, cancelable: true });
    link.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(posted).toContainEqual({ type: 'mp:link', href: 'https://example.com/x' });
  });

  it('an in-page anchor scrolls instead of leaving', () => {
    document.body.innerHTML = '<a href="#steps">x</a>';
    const event = new MouseEvent('click', { bubbles: true, cancelable: true });
    document.querySelector('a')!.dispatchEvent(event);
    expect(posted.filter((m) => m.type === 'mp:link')).toEqual([]);
  });

  it('console.error and uncaught errors are forwarded, capped', () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    console.error('x'.repeat(500));
    window.dispatchEvent(new ErrorEvent('error', { message: 'boom' }));
    const errors = posted.filter((m) => m.type === 'mp:error');
    expect(errors).toHaveLength(2);
    expect(errors[0]?.type === 'mp:error' && errors[0]?.message.length).toBeLessThanOrEqual(300);
    expect(errors[1]).toEqual({ type: 'mp:error', message: 'boom' });
    spy.mockRestore();
  });
});
