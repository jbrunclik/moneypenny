/**
 * Grounding claims anchored in rendered markdown.
 *
 * The server stores each claim as a literal quote of the markdown source plus
 * the text just before it. The rendered text differs (emphasis, link syntax),
 * so both sides are normalised - markdown punctuation dropped, whitespace
 * collapsed - and the match is mapped back onto the DOM text nodes.
 * Spec: docs/superpowers/specs/2026-10-03-grounding-annotations-design.md
 */
import type { ClaimAnnotation, GroundingSummary } from '../../types/api';

// Not answer text: code blocks, math, a streamed bubble's thinking trace and
// attachments, and source numbers already inserted (inline code IS text)
const SKIP_SELECTOR = 'pre, .katex, .thinking-indicator, .message-files, .claim-cite';
// Prefixes are compared on their last few characters, ignoring whitespace
const PREFIX_TAIL_CHARS = 12;
const MARKDOWN_SYNTAX = /\*\*|__|[*_`]|\]\([^)]*\)|[[\]]/g;

interface MessageGrounding {
  annotations: ClaimAnnotation[];
  grounding?: GroundingSummary;
  language?: string;
}
const byMessage = new WeakMap<Element, MessageGrounding>();

export function rememberAnnotations(
  messageEl: Element,
  annotations: ClaimAnnotation[],
  grounding?: GroundingSummary,
  language?: string
): void {
  byMessage.set(messageEl, { annotations, grounding, language });
}
/** The reply's language (cs/en UI text for its cards and claims list). */
export function getMessageLanguage(messageEl: Element): string | undefined {
  return byMessage.get(messageEl)?.language;
}
export function getMessageAnnotations(messageEl: Element): ClaimAnnotation[] | undefined {
  return byMessage.get(messageEl)?.annotations;
}
export function getMessageGrounding(messageEl: Element): GroundingSummary | undefined {
  return byMessage.get(messageEl)?.grounding;
}

/** Markdown source text as it reads once rendered, normalised for matching. */
function normaliseSource(text: string): string {
  return text.replace(MARKDOWN_SYNTAX, '').replace(/\s+/g, ' ').trim().toLowerCase();
}

interface TextIndex {
  /** Normalised rendered text */
  text: string;
  /** For each char of `text`: [text node, offset in that node] */
  map: Array<[Text, number]>;
}

function indexText(root: HTMLElement): TextIndex {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.parentElement?.closest(SKIP_SELECTOR) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  let text = '';
  const map: Array<[Text, number]> = [];
  let lastWasSpace = true;
  for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
    const value = node.data;
    for (let i = 0; i < value.length; i++) {
      const isSpace = /\s/.test(value[i]);
      if (isSpace && lastWasSpace) continue;
      text += isSpace ? ' ' : value[i].toLowerCase();
      map.push([node, i]);
      lastWasSpace = isSpace;
    }
  }
  return { text, map };
}

/** Markdown prefix as it reads rendered: no list bullets, headings or table pipes. */
function normalisePrefix(prefix: string): string {
  const unmarked = prefix.replace(/^\s*(?:[-*+>]|\d+\.|#{1,6})\s+/gm, '').replace(/\|/g, ' ');
  return normaliseSource(unmarked).replace(/\s/g, '');
}

function findOccurrence(index: TextIndex, quote: string, prefix: string): number {
  const starts: number[] = [];
  for (let at = index.text.indexOf(quote); at >= 0; at = index.text.indexOf(quote, at + 1)) starts.push(at);
  const tail = normalisePrefix(prefix).slice(-PREFIX_TAIL_CHARS);
  if (starts.length <= 1 || !tail) return starts[0] ?? -1;
  // Rendered text has no space where a <br> or list item break was
  const before = (at: number) => index.text.slice(0, at).replace(/\s/g, '');
  return starts.find((at) => before(at).endsWith(tail)) ?? starts[0];
}

/** Wrap [start, end) of the index in spans, one per text node it crosses. */
function wrapRange(index: TextIndex, start: number, end: number, make: () => HTMLElement): HTMLElement | null {
  const segments = new Map<Text, [number, number]>();
  for (let i = start; i < end; i++) {
    const [node, offset] = index.map[i];
    const seg = segments.get(node);
    segments.set(node, seg ? [seg[0], offset + 1] : [offset, offset + 1]);
  }
  let last: HTMLElement | null = null;
  for (const [node, [from, to]] of segments) {
    const middle = node.splitText(from);
    middle.splitText(to - from);
    const span = make();
    middle.replaceWith(span);
    span.appendChild(middle);
    last = span;
  }
  return last;
}

function claimSpan(i: number, verdict: string): () => HTMLElement {
  return () => {
    const span = document.createElement('span');
    span.className = `claim claim--${verdict}`;
    span.dataset.claim = String(i);
    span.tabIndex = 0;
    span.setAttribute('role', 'button');
    return span;
  };
}

function citeSup(i: number, source: number): HTMLElement {
  const sup = document.createElement('sup');
  sup.className = 'claim-cite';
  sup.dataset.claim = String(i);
  sup.tabIndex = 0;
  sup.setAttribute('role', 'button');
  sup.textContent = String(source);
  return sup;
}

/** Anchor every claim it can find; returns the indexes that were anchored. */
export function applyAnnotations(contentEl: HTMLElement, annotations: ClaimAnnotation[]): Set<number> {
  const anchored = new Set<number>();
  annotations.forEach((ann, i) => {
    // Re-index per claim: wrapping splits text nodes
    const index = indexText(contentEl);
    const quote = normaliseSource(ann.quote);
    const at = quote ? findOccurrence(index, quote, ann.prefix ?? '') : -1;
    if (at < 0) return;
    const end = at + quote.length;
    if (ann.verdict === 'supported') {
      if (ann.source) {
        const [node, offset] = index.map[end - 1];
        const after = node.splitText(offset + 1);
        after.before(citeSup(i, ann.source));
      }
    } else {
      wrapRange(index, at, end, claimSpan(i, ann.verdict));
    }
    anchored.add(i);
  });
  return anchored;
}

/** A source's domain for display ("spzsluzby.cz"), or the raw URL if it won't parse. */
export function displayHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}
