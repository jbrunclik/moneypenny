/**
 * Unit tests for markdown rendering — XSS prevention and feature regression
 */
import { describe, it, expect } from 'vitest';
import { renderMarkdown } from '@/utils/markdown';

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
});

describe('renderMarkdown preserves legitimate features', () => {
  it('renders markdown links as <a> tags', () => {
    const html = renderMarkdown('[example](https://example.com)');
    expect(html).toContain('<a href="https://example.com"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('example</a>');
  });

  it('renders markdown images as <img> tags', () => {
    const html = renderMarkdown('![alt text](https://example.com/img.png)');
    expect(html).toContain('<img');
    expect(html).toContain('src="https://example.com/img.png"');
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
    expect(html).toContain('<th>');
    expect(html).toContain('<td>');
  });

  it('renders inline code with HTML-like content safely', () => {
    const html = renderMarkdown('Use `<script>` tag');
    expect(html).toContain('<code>');
    expect(html).not.toContain('<script>');
  });
});
