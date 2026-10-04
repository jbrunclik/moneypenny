import { beforeEach, describe, expect, it, vi } from 'vitest';

const mermaid = {
  initialize: vi.fn(),
  render: vi.fn(async (id: string, src: string) => ({ svg: `<svg id="${id}"><text>${src.length}</text></svg>` })),
};
vi.mock('mermaid', () => ({ default: mermaid }));

import { renderMarkdown } from '@/utils/markdown';
import { renderMermaidIn } from '@/utils/mermaid';

function message(markdown: string): HTMLElement {
  const el = document.createElement('div');
  el.className = 'message-content';
  el.innerHTML = renderMarkdown(markdown);
  document.body.replaceChildren(el);
  return el;
}

describe('renderMermaidIn', () => {
  beforeEach(() => vi.clearAllMocks());

  it('draws a mermaid block as a diagram and keeps its source for copying', async () => {
    const el = message('Plán:\n\n```mermaid\ngraph TD; A-->B\n```');

    await renderMermaidIn(el);

    const wrapper = el.querySelector('.code-block-wrapper')!;
    expect(wrapper.querySelector('.mermaid-diagram svg')).not.toBeNull();
    expect(wrapper.classList.contains('code-block-wrapper--diagram')).toBe(true);
    expect(wrapper.querySelector('code')!.textContent).toBe('graph TD; A-->B');
    expect(mermaid.initialize).toHaveBeenCalledWith(expect.objectContaining({ securityLevel: 'strict', startOnLoad: false }));
  });

  it('sanitizes the SVG it inserts (model output is untrusted)', async () => {
    mermaid.render.mockResolvedValueOnce({
      svg: '<svg><script>window.pwned=1</script><a href="javascript:alert(1)"><text>x</text></a><text onclick="alert(1)">y</text></svg>',
    });
    const el = message('```mermaid\ngraph TD; A-->B\n```');

    await renderMermaidIn(el);

    const html = el.querySelector('.mermaid-diagram')!.innerHTML;
    expect(html).not.toContain('script');
    expect(html).not.toContain('javascript:');
    expect(html).not.toContain('onclick');
    // SVG text labels, never HTML labels in foreignObject
    expect(mermaid.initialize).toHaveBeenCalledWith(expect.objectContaining({ htmlLabels: false }));
  });

  it('a diagram that does not parse stays a code block', async () => {
    mermaid.render.mockRejectedValueOnce(new Error('Parse error'));
    const el = message('```mermaid\ngraph oops\n```');

    await renderMermaidIn(el);

    expect(el.querySelector('.mermaid-diagram')).toBeNull();
    expect(el.querySelector('.code-block-wrapper--diagram')).toBeNull();
  });

  it('leaves other code alone and never loads mermaid for it', async () => {
    const el = message('```python\nprint(1)\n```');

    await renderMermaidIn(el);

    expect(mermaid.render).not.toHaveBeenCalled();
    expect(el.querySelector('.mermaid-diagram')).toBeNull();
  });

  it('draws each block once', async () => {
    const el = message('```mermaid\ngraph TD; A-->B\n```');

    await renderMermaidIn(el);
    await renderMermaidIn(el);

    expect(mermaid.render).toHaveBeenCalledTimes(1);
    expect(el.querySelectorAll('.mermaid-diagram')).toHaveLength(1);
  });

  it('draws in the app palette, dark unless data-theme="light"', async () => {
    document.documentElement.style.setProperty('--accent', '#5753e8');
    await renderMermaidIn(message('```mermaid\ngraph TD; A-->B\n```'));
    const dark = mermaid.initialize.mock.lastCall![0];
    expect(dark.theme).toBe('base');
    expect(dark.themeVariables.darkMode).toBe(true);
    expect(dark.themeVariables.primaryBorderColor).toBe('#5753e8');

    document.documentElement.setAttribute('data-theme', 'light');
    try {
      await renderMermaidIn(message('```mermaid\ngraph TD; B-->C\n```'));
    } finally {
      document.documentElement.removeAttribute('data-theme');
      document.documentElement.style.removeProperty('--accent');
    }
    expect(mermaid.initialize.mock.lastCall![0].themeVariables.darkMode).toBe(false);
  });
});
