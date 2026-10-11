import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/api/artifacts', () => ({
  fetchArtifactVersion: vi.fn(() =>
    Promise.resolve({ id: 'a', version: 1, title: 'Tips', html: '<p>x</p>', state: { n: 1 } })
  ),
  saveArtifactState: vi.fn(() => Promise.resolve()),
}));
vi.mock('@/core/messaging', () => ({ sendUiMessage: vi.fn(() => Promise.resolve(true)) }));
import { fetchArtifactVersion, saveArtifactState } from '@/api/artifacts';
import { sendUiMessage } from '@/core/messaging';
import { _resetArtifactHost, observeTheme, registerFrame } from '@/core/artifact-host';
import { ARTIFACT_MAX_HEIGHT_VH, ARTIFACT_READY_TIMEOUT_MS, ARTIFACT_STATE_SAVE_DEBOUNCE_MS } from '@/config';

const REF = { id: 'a', version: 1, title: 'Tips' };

function makeFrame(): { frame: HTMLIFrameElement; posted: unknown[] } {
  const frame = document.createElement('iframe');
  document.getElementById('messages')!.appendChild(frame);
  const posted: unknown[] = [];
  vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((m: unknown) => {
    posted.push(m);
  });
  return { frame, posted };
}

function fromFrame(frame: HTMLIFrameElement, data: unknown): void {
  window.dispatchEvent(new MessageEvent('message', { data, source: frame.contentWindow }));
}

const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  document.body.innerHTML = '<div id="messages"></div>';
  document.documentElement.removeAttribute('data-theme');
  vi.mocked(sendUiMessage).mockClear();
  vi.mocked(saveArtifactState).mockClear();
  vi.mocked(fetchArtifactVersion).mockClear();
});

afterEach(() => {
  _resetArtifactHost();
  vi.useRealTimers();
});

describe('registerFrame', () => {
  it('answers ready with the html, theme and saved state', async () => {
    const { frame, posted } = makeFrame();
    registerFrame(frame, REF, {});
    fromFrame(frame, { type: 'mp:ready' });
    await flush();
    expect(posted).toEqual([{ type: 'mp:init', html: '<p>x</p>', theme: 'dark', state: { n: 1 } }]);
  });

  it('ignores messages from frames it did not create', () => {
    const { frame } = makeFrame();
    registerFrame(frame, REF, {});
    const stranger = makeFrame().frame;
    fromFrame(stranger, { type: 'mp:send', text: 'hi' });
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'mp:send', text: 'hi' } }));
    expect(sendUiMessage).not.toHaveBeenCalled();
  });

  it('sends the text as the user', () => {
    const { frame } = makeFrame();
    registerFrame(frame, REF, {});
    fromFrame(frame, { type: 'mp:send', text: 'Scale to 6' });
    expect(sendUiMessage).toHaveBeenCalledWith('Scale to 6');
  });

  it('opens only https links', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    const { frame } = makeFrame();
    registerFrame(frame, REF, {});
    fromFrame(frame, { type: 'mp:link', href: 'javascript:alert(1)' });
    fromFrame(frame, { type: 'mp:link', href: 'https://example.com/' });
    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith('https://example.com/', '_blank', 'noopener');
    open.mockRestore();
  });

  it('saves state once after quick updates', () => {
    vi.useFakeTimers();
    const { frame } = makeFrame();
    registerFrame(frame, REF, {});
    for (const n of [1, 2, 3]) fromFrame(frame, { type: 'mp:state', state: { n } });
    vi.advanceTimersByTime(ARTIFACT_STATE_SAVE_DEBOUNCE_MS + 1);
    expect(saveArtifactState).toHaveBeenCalledTimes(1);
    expect(saveArtifactState).toHaveBeenCalledWith('a', { n: 3 });
  });

  it('applies the reported height, capped', () => {
    const { frame } = makeFrame();
    const onHeight = vi.fn();
    registerFrame(frame, REF, { onHeight });
    fromFrame(frame, { type: 'mp:height', height: 240 });
    expect(frame.style.height).toBe('240px');
    fromFrame(frame, { type: 'mp:height', height: 100000 });
    const cap = Math.round((window.innerHeight * ARTIFACT_MAX_HEIGHT_VH) / 100);
    expect(frame.style.height).toBe(`${cap}px`);
    expect(onHeight).toHaveBeenLastCalledWith(cap);
  });

  it('reports failure when the frame never says ready', () => {
    vi.useFakeTimers();
    const { frame } = makeFrame();
    const onFailed = vi.fn();
    registerFrame(frame, REF, { onFailed });
    vi.advanceTimersByTime(ARTIFACT_READY_TIMEOUT_MS + 1);
    expect(onFailed).toHaveBeenCalledTimes(1);
  });

  it('forwards errors to the card', () => {
    const { frame } = makeFrame();
    const onError = vi.fn();
    registerFrame(frame, REF, { onError });
    fromFrame(frame, { type: 'mp:error', message: 'boom' });
    expect(onError).toHaveBeenCalledWith('boom');
  });

  it('unregistering stops handling the frame', () => {
    const { frame } = makeFrame();
    const stop = registerFrame(frame, REF, {});
    stop();
    fromFrame(frame, { type: 'mp:send', text: 'hi' });
    expect(sendUiMessage).not.toHaveBeenCalled();
  });
});

describe('frames registered before they are in the DOM', () => {
  it('are served once attached (history renders cards before appending them)', async () => {
    const frame = document.createElement('iframe');
    registerFrame(frame, REF, {});
    document.getElementById('messages')!.appendChild(frame);
    const posted: unknown[] = [];
    vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((m: unknown) => {
      posted.push(m);
    });
    fromFrame(frame, { type: 'mp:ready' });
    await flush();
    expect(posted).toHaveLength(1);
  });
});

describe('observeTheme', () => {
  it('pushes theme changes to every frame', async () => {
    const a = makeFrame();
    const b = makeFrame();
    registerFrame(a.frame, REF, {});
    registerFrame(b.frame, { ...REF, id: 'b' }, {});
    observeTheme();
    document.documentElement.setAttribute('data-theme', 'light');
    await flush();
    expect(a.posted).toContainEqual({ type: 'mp:theme', theme: 'light' });
    expect(b.posted).toContainEqual({ type: 'mp:theme', theme: 'light' });
    // The iframe's own colour scheme must match its page, or Chrome paints
    // an opaque backdrop behind the transparent artifact
    expect(a.frame.style.colorScheme).toBe('light');
  });
});
