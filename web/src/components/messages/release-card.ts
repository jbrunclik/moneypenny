/**
 * What's new posts as release cards.
 *
 * A post is markdown from announcements/*.md (docs/features/whats-new.md):
 * a `#` title, an intro paragraph, sections as a bold-only paragraph plus a
 * list, and a closing line. The rendered markdown is regrouped in place into
 * a dated header, the intro, a grid of section tiles and a quiet footer, so
 * the read-only chat reads as release notes, not as chat replies.
 */

import { SPARKLES_ICON, setIcon } from '../../utils/icons';

const LIST_TAGS = new Set(['UL', 'OL']);

function el(tag: string, className: string): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  return node;
}

/** A section label: a paragraph holding nothing but one bold run. */
function sectionTitle(node: Element): string | null {
  if (node.tagName !== 'P' || node.children.length !== 1) return null;
  const strong = node.firstElementChild;
  if (strong?.tagName !== 'STRONG') return null;
  const text = node.textContent?.trim() ?? '';
  return text && text === strong.textContent?.trim() ? text : null;
}

function header(createdAt: string | null | undefined, language: string | null | undefined): HTMLElement {
  const row = el('div', 'release-card-header');
  const mark = el('span', 'release-card-mark');
  setIcon(mark, SPARKLES_ICON);
  row.append(mark);
  const when = createdAt ? new Date(createdAt) : null;
  if (when && !Number.isNaN(when.getTime())) {
    const time = el('time', 'release-card-date');
    time.setAttribute('datetime', createdAt ?? '');
    time.textContent = new Intl.DateTimeFormat(language || undefined, {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    }).format(when);
    row.append(time);
  }
  return row;
}

function sectionTile(title: string, list: Element): HTMLElement {
  const tile = el('section', 'release-card-section');
  const heading = el('h3', 'release-card-section-title');
  heading.textContent = title;
  tile.append(heading, list);
  return tile;
}

interface Parts {
  intro: Element | null;
  body: Element[];
  tiles: HTMLElement[];
  footer: Element[];
}

/** Sort the post's blocks (after the title) into intro, body, tiles and footer. */
function splitBlocks(blocks: Element[]): Parts {
  const parts: Parts = { intro: null, body: [], tiles: [], footer: [] };
  const first = blocks[0];
  let i = 0;
  if (first && first.tagName === 'P' && !sectionTitle(first)) {
    parts.intro = first;
    i = 1;
  }
  for (; i < blocks.length; i++) {
    const block = blocks[i];
    if (!block) break;
    const title = sectionTitle(block);
    const next = blocks[i + 1];
    if (title && next && LIST_TAGS.has(next.tagName)) {
      // Paragraphs between two sections belong to the one above
      parts.tiles.at(-1)?.append(...parts.footer);
      parts.footer = [];
      parts.tiles.push(sectionTile(title, next));
      i++;
    } else if (parts.tiles.length > 0) {
      // After the sections: the closing line(s)
      parts.footer.push(block);
    } else {
      parts.body.push(block);
    }
  }
  return parts;
}

function group(className: string, children: Element[]): HTMLElement | null {
  if (children.length === 0) return null;
  const wrapper = el('div', className);
  wrapper.append(...children);
  return wrapper;
}

/** Regroup a rendered post into a release card (in place); a post without a
 *  `#` title is left as it is. */
export function asReleaseCard(
  content: HTMLElement,
  createdAt: string | null | undefined,
  language: string | null | undefined,
): void {
  const blocks = [...content.children];
  const titleEl = blocks[0];
  if (titleEl?.tagName !== 'H1') return;

  const title = el('h2', 'release-card-title');
  title.textContent = titleEl.textContent;
  const parts = splitBlocks(blocks.slice(1));
  if (parts.intro) parts.intro.classList.add('release-card-intro');

  const nodes: (Element | null)[] = [
    header(createdAt, language),
    title,
    parts.intro,
    group('release-card-body', parts.body),
    group('release-card-grid', parts.tiles),
    group('release-card-footer', parts.footer),
  ];
  content.replaceChildren(...nodes.filter((n): n is Element => n !== null));
  content.classList.add('release-card');
}
