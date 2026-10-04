import { describe, expect, it } from 'vitest';
import { htmlToMarkdown } from '@/utils/html-to-markdown';

describe('htmlToMarkdown', () => {
  it('keeps headings, emphasis, links and paragraphs from a web page', () => {
    const html = `<h2>Ceny</h2><p>Přepis stojí <strong>1 590 Kč</strong> a trvá <em>dva dny</em>.</p>
      <p>Viz <a href="https://example.cz/cenik">ceník</a>.</p>`;
    expect(htmlToMarkdown(html)).toBe(
      '## Ceny\n\nPřepis stojí **1 590 Kč** a trvá *dva dny*.\n\nViz [ceník](https://example.cz/cenik).'
    );
  });

  it('reads Google Docs styling (bold by font-weight, a normal-weight b wrapper)', () => {
    const html = `<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1">
      <p dir="ltr"><span style="font-weight:700;">Tučně</span><span style="font-weight:400;"> a </span><span style="font-style:italic;">kurzíva</span></p></b>`;
    expect(htmlToMarkdown(html)).toBe('**Tučně** a *kurzíva*');
  });

  it('nests lists', () => {
    const html = '<ul><li>Jedna<ul><li>Pod</li></ul></li><li>Dvě</li></ul><ol><li>A</li><li>B</li></ol>';
    expect(htmlToMarkdown(html)).toBe('- Jedna\n  - Pod\n- Dvě\n\n1. A\n2. B');
  });

  it('turns a table into a GFM table', () => {
    const html = '<table><tr><th>Model</th><th>Cena</th></tr><tr><td>RoS 3</td><td>6 990 | akce</td></tr></table>';
    expect(htmlToMarkdown(html)).toBe('| Model | Cena |\n| --- | --- |\n| RoS 3 | 6 990 \\| akce |');
  });

  it('keeps email-style line breaks and quotes', () => {
    const html = '<div>Ahoj,<br>díky za zprávu.</div><blockquote>Původní text</blockquote>';
    expect(htmlToMarkdown(html)).toBe('Ahoj,\ndíky za zprávu.\n\n> Původní text');
  });

  it('keeps code', () => {
    const html = '<p>Spusť <code>make test</code>:</p><pre><code>make lint\nmake test</code></pre>';
    expect(htmlToMarkdown(html)).toBe('Spusť `make test`:\n\n```\nmake lint\nmake test\n```');
  });

  it('a bare link stays a bare URL', () => {
    expect(htmlToMarkdown('<p><a href="https://a.cz">https://a.cz</a> <strong>x</strong></p>')).toBe('https://a.cz **x**');
  });

  it('returns null when the HTML carries no formatting (code editors, plain copies)', () => {
    expect(htmlToMarkdown('<div><span style="color:#d4d4d4">const x = 1;</span></div>')).toBeNull();
    expect(htmlToMarkdown('<meta charset="utf-8"><span>plain words</span>')).toBeNull();
  });

  it('ignores scripts and styles', () => {
    expect(htmlToMarkdown('<style>p{}</style><script>alert(1)</script><p><b>ok</b></p>')).toBe('**ok**');
  });
});
