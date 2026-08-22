/**
 * Unit tests for live streaming syntax highlighting — code blocks get
 * colored while the stream is still running, with per-block caching so
 * completed blocks aren't re-highlighted on every markdown re-render.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { highlightLiveCodeBlocks } from '@/components/messages/live-highlight';
import { hljs } from '@/utils/markdown';

function makeContainer(...blocks: Array<{ lang?: string; code: string }>): HTMLElement {
  const container = document.createElement('div');
  container.innerHTML = blocks
    .map(
      (b) =>
        `<pre><code${b.lang ? ` class="language-${b.lang}"` : ''}></code></pre>`
    )
    .join('');
  container.querySelectorAll('pre code').forEach((el, i) => {
    el.textContent = blocks[i].code;
  });
  return container;
}

describe('highlightLiveCodeBlocks', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('highlights a known-language code block', () => {
    const container = makeContainer({ lang: 'python', code: 'def foo():\n    return 42' });
    highlightLiveCodeBlocks(container);
    expect(container.querySelector('code')!.innerHTML).toContain('hljs-');
    expect(container.querySelector('code')!.textContent).toContain('def foo():');
  });

  it('leaves blocks without a language untouched (no auto-detect during stream)', () => {
    const container = makeContainer({ code: 'plain text nobody knows' });
    highlightLiveCodeBlocks(container);
    expect(container.querySelector('code')!.innerHTML).not.toContain('hljs-');
    expect(container.querySelector('code')!.textContent).toBe('plain text nobody knows');
  });

  it('leaves unknown-language blocks untouched', () => {
    const container = makeContainer({ lang: 'klingon', code: 'nuqneH' });
    highlightLiveCodeBlocks(container);
    expect(container.querySelector('code')!.innerHTML).not.toContain('hljs-');
  });

  it('reuses the cached result for unchanged blocks across re-renders', () => {
    const spy = vi.spyOn(hljs, 'highlight');
    const container = makeContainer({ lang: 'js', code: 'const a = 1;' });
    highlightLiveCodeBlocks(container);
    expect(spy).toHaveBeenCalledTimes(1);

    // Simulate the streaming re-render: same container, fresh DOM nodes
    const blocks = makeContainer({ lang: 'js', code: 'const a = 1;' });
    container.innerHTML = blocks.innerHTML;
    highlightLiveCodeBlocks(container);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(container.querySelector('code')!.innerHTML).toContain('hljs-');
  });

  it('re-highlights a block whose content grew since the last render', () => {
    const spy = vi.spyOn(hljs, 'highlight');
    const container = makeContainer({ lang: 'js', code: 'const a =' });
    highlightLiveCodeBlocks(container);

    const grown = makeContainer({ lang: 'js', code: 'const a = 1;\nconst b = 2;' });
    container.innerHTML = grown.innerHTML;
    highlightLiveCodeBlocks(container);
    expect(spy).toHaveBeenCalledTimes(2);
    expect(container.querySelector('code')!.textContent).toContain('const b = 2;');
    expect(container.querySelector('code')!.innerHTML).toContain('hljs-');
  });

  it('caches per block position so multiple blocks stay independent', () => {
    const spy = vi.spyOn(hljs, 'highlight');
    const container = makeContainer(
      { lang: 'js', code: 'const done = true;' },
      { lang: 'python', code: 'x =' }
    );
    highlightLiveCodeBlocks(container);
    expect(spy).toHaveBeenCalledTimes(2);

    // Second block grows; first is unchanged and must come from cache
    const next = makeContainer(
      { lang: 'js', code: 'const done = true;' },
      { lang: 'python', code: 'x = 1' }
    );
    container.innerHTML = next.innerHTML;
    highlightLiveCodeBlocks(container);
    expect(spy).toHaveBeenCalledTimes(3);
    expect(spy.mock.calls[2][0]).toBe('x = 1');
  });

  it('skips oversized blocks to keep streaming updates cheap', () => {
    const spy = vi.spyOn(hljs, 'highlight');
    const container = makeContainer({ lang: 'js', code: 'x'.repeat(30000) });
    highlightLiveCodeBlocks(container);
    expect(spy).not.toHaveBeenCalled();
    expect(container.querySelector('code')!.innerHTML).not.toContain('hljs-');
  });
});

describe('updateStreamingMessage live highlighting', () => {
  it('highlights completed code blocks while the stream is still running', async () => {
    const { updateStreamingMessage } = await import('@/components/messages/streaming');
    const messageEl = document.createElement('div');
    messageEl.innerHTML = '<div class="message-content"></div>';
    document.body.appendChild(messageEl);

    updateStreamingMessage(messageEl, '```python\ndef foo():\n    return 42\n```\n\nAnd then');

    const code = messageEl.querySelector('pre code')!;
    expect(code.innerHTML).toContain('hljs-');
    expect(code.textContent).toContain('def foo():');
    messageEl.remove();
  });
});
