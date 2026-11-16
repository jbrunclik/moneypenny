/**
 * A streamed reply redraws at most once per animation frame: every token
 * re-ran marked + DOMPurify + innerHTML + highlighting (Nov 16 2026).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as markdown from '@/utils/markdown';
import {
  scheduleStreamingUpdate,
  flushStreamingUpdate,
  updateStreamingMessage,
  finalizeStreamingMessage,
} from '@/components/messages/streaming';

let frames: Array<() => void> = [];

function bubble(): HTMLElement {
  const el = document.createElement('div');
  el.className = 'message assistant';
  el.innerHTML = '<div class="message-content-wrapper"><div class="message-content"></div></div>';
  document.body.append(el);
  return el;
}

function runFrames(): void {
  const due = frames;
  frames = [];
  due.forEach((frame) => frame());
}

beforeEach(() => {
  document.body.innerHTML = '';
  frames = [];
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
    frames.push(() => cb(0));
    return frames.length;
  });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined);
});

afterEach(() => vi.restoreAllMocks());

describe('scheduleStreamingUpdate', () => {
  it('50 tokens in one frame render once with the full text', () => {
    const el = bubble();
    const render = vi.spyOn(markdown, 'renderMarkdown');
    let text = '';
    for (let i = 0; i < 50; i++) {
      text += `w${i} `;
      scheduleStreamingUpdate(el, text);
    }
    expect(render).not.toHaveBeenCalled();
    runFrames();
    expect(render).toHaveBeenCalledTimes(1);
    expect(el.querySelector('.message-content')?.textContent).toContain('w49');
  });

  it('a final render before the frame wins; the stale frame draws nothing', () => {
    const el = bubble();
    scheduleStreamingUpdate(el, 'partial');
    updateStreamingMessage(el, 'final answer');
    runFrames();
    expect(el.querySelector('.message-content')?.textContent).toContain('final answer');
    expect(el.querySelector('.message-content')?.textContent).not.toContain('partial');
  });

  it('finalizing draws the text still waiting for a frame (review: lost endings)', () => {
    // done's content equals the streamed text, so nothing else redraws it;
    // a hidden tab never runs frames at all
    const el = bubble();
    scheduleStreamingUpdate(el, 'the whole reply, last words');
    finalizeStreamingMessage(el, 'm1');
    expect(el.querySelector('.message-content')?.textContent).toContain('last words');
    const render = vi.spyOn(markdown, 'renderMarkdown');
    runFrames();
    expect(render).not.toHaveBeenCalled();
  });

  it('flushStreamingUpdate draws the pending text now, once', () => {
    const el = bubble();
    scheduleStreamingUpdate(el, 'early text');
    flushStreamingUpdate(el);
    expect(el.querySelector('.message-content')?.textContent).toContain('early text');
    const render = vi.spyOn(markdown, 'renderMarkdown');
    runFrames();
    expect(render).not.toHaveBeenCalled();
  });

  it('a bubble removed by a conversation switch is not drawn into', () => {
    const el = bubble();
    scheduleStreamingUpdate(el, 'text');
    el.remove();
    const render = vi.spyOn(markdown, 'renderMarkdown');
    runFrames();
    expect(render).not.toHaveBeenCalled();
  });
});
