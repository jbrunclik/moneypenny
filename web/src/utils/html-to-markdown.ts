/**
 * Clipboard HTML -> markdown for pasting rich text into the composer.
 *
 * Keeps headings, bold/italic (tags or Google Docs' font-weight / font-style
 * styles), links, lists, tables, quotes and code. Returns null when the HTML
 * carries no such formatting - code editors and plain copies put span/div
 * soup on the clipboard, and the browser's plain-text paste is right there.
 * DOMParser never runs scripts; nothing here is ever inserted as HTML.
 */

const SKIP = new Set(['SCRIPT', 'STYLE', 'META', 'TITLE', 'HEAD', 'NOSCRIPT', 'TEMPLATE', 'IMG']);
const BLOCKS = new Set(['P', 'DIV', 'SECTION', 'ARTICLE', 'HEADER', 'FOOTER', 'MAIN', 'ASIDE', 'NAV']);
const FORMATTING = 'h1,h2,h3,h4,h5,h6,strong,b,em,i,ul,ol,a[href],table,blockquote,pre,code,[style*="font-weight"],[style*="font-style"]';

function isBold(el: HTMLElement): boolean {
  const weight = el.style.fontWeight;
  if (weight) return weight === 'bold' || Number(weight) >= 600;
  return el.tagName === 'STRONG' || el.tagName === 'B';
}

function isItalic(el: HTMLElement): boolean {
  if (el.style.fontStyle) return el.style.fontStyle === 'italic';
  return el.tagName === 'EM' || el.tagName === 'I';
}

/** Wrap trimmed text in a marker, keeping the surrounding spaces outside it. */
function wrap(text: string, marker: string): string {
  const match = /^(\s*)([\s\S]*?)(\s*)$/.exec(text);
  if (!match || !match[2]) return text;
  return `${match[1]}${marker}${match[2]}${marker}${match[3]}`;
}

function inline(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return (node.textContent ?? '').replace(/\s+/g, ' ');
  if (!(node instanceof HTMLElement) || SKIP.has(node.tagName)) return '';
  const tag = node.tagName;
  if (tag === 'BR') return '\n';
  if (tag === 'CODE') return `\`${node.textContent ?? ''}\``;
  let text = [...node.childNodes].map(inline).join('');
  if (tag === 'A') {
    const href = node.getAttribute('href') ?? '';
    if (/^https?:\/\//.test(href)) text = text.trim() === href ? href : `[${text.trim()}](${href})`;
  }
  if (isBold(node)) text = wrap(text, '**');
  if (isItalic(node)) text = wrap(text, '*');
  return text;
}

function cleanLines(text: string): string {
  return text
    .split('\n')
    .map((line) => line.trim())
    .join('\n')
    .trim();
}

function listMarkdown(list: HTMLElement, depth: number): string {
  const ordered = list.tagName === 'OL';
  const pad = '  '.repeat(depth);
  const lines: string[] = [];
  [...list.children].filter((c) => c.tagName === 'LI').forEach((li, i) => {
    const nested = [...li.children].filter((c) => c.tagName === 'UL' || c.tagName === 'OL');
    const own = [...li.childNodes].filter((n) => !nested.includes(n as Element));
    const text = cleanLines(own.map(inline).join('')).replace(/\n/g, ' ');
    lines.push(`${pad}${ordered ? `${i + 1}.` : '-'} ${text}`);
    nested.forEach((sub) => lines.push(listMarkdown(sub as HTMLElement, depth + 1)));
  });
  return lines.join('\n');
}

function tableMarkdown(table: HTMLElement): string {
  const rows = [...table.querySelectorAll('tr')].map((tr) =>
    [...tr.querySelectorAll('th,td')].map((cell) =>
      cleanLines(inline(cell)).replace(/\n/g, ' ').replace(/\|/g, '\\|')
    )
  );
  if (!rows.length) return '';
  const width = Math.max(...rows.map((r) => r.length));
  const line = (cells: string[]) =>
    `| ${[...cells, ...Array(width - cells.length).fill('')].join(' | ')} |`;
  return [line(rows[0]), line(Array(width).fill('---')), ...rows.slice(1).map(line)].join('\n');
}

/** Markdown blocks of an element's children, separated by blank lines. */
function blocks(parent: Node): string[] {
  const out: string[] = [];
  let run = '';
  const flush = (): void => {
    const text = cleanLines(run);
    if (text) out.push(text);
    run = '';
  };
  for (const node of parent.childNodes) {
    const el = node instanceof HTMLElement ? node : null;
    const tag = el?.tagName ?? '';
    if (el && SKIP.has(tag)) continue;
    if (el && /^H[1-6]$/.test(tag)) {
      flush();
      out.push(`${'#'.repeat(Number(tag[1]))} ${cleanLines(inline(el)).replace(/\n/g, ' ')}`);
    } else if (el && (tag === 'UL' || tag === 'OL')) {
      flush();
      out.push(listMarkdown(el, 0));
    } else if (el && tag === 'TABLE') {
      flush();
      out.push(tableMarkdown(el));
    } else if (el && tag === 'PRE') {
      flush();
      out.push(`\`\`\`\n${(el.textContent ?? '').replace(/\n$/, '')}\n\`\`\``);
    } else if (el && tag === 'BLOCKQUOTE') {
      flush();
      out.push(blocks(el).join('\n\n').split('\n').map((l) => `> ${l}`.trimEnd()).join('\n'));
    } else if (el && tag === 'HR') {
      flush();
      out.push('---');
    } else if (el && (BLOCKS.has(tag) || hasBlockChild(el))) {
      flush();
      // A bold/italic wrapper around blocks (Google Docs' <b style="font-weight:normal">)
      out.push(...blocks(el));
    } else {
      run += inline(node);
    }
  }
  flush();
  return out;
}

function hasBlockChild(el: HTMLElement): boolean {
  return [...el.children].some((c) => BLOCKS.has(c.tagName) || /^(H[1-6]|UL|OL|TABLE|PRE|BLOCKQUOTE)$/.test(c.tagName));
}

/** Markdown for clipboard HTML, or null when it has no formatting worth keeping. */
export function htmlToMarkdown(html: string): string | null {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll([...SKIP].join(',')).forEach((el) => el.remove());
  const formatted = [...doc.body.querySelectorAll<HTMLElement>(FORMATTING)].some(
    (el) => !el.matches('[style*="font-weight"],[style*="font-style"]') || isBold(el) || isItalic(el)
  );
  if (!formatted) return null;
  const markdown = blocks(doc.body).join('\n\n').replace(/\n{3,}/g, '\n\n').trim();
  return markdown || null;
}
