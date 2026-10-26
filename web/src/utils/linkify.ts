/**
 * Utilities for detecting and converting URLs to clickable links
 */

/**
 * URL pattern that matches common URL formats:
 * - http:// or https:// protocols
 * - www. prefix (will auto-add https://)
 * - Common TLDs (.com, .org, .net, etc.)
 *
 * This is intentionally simple and may miss some edge cases,
 * but covers the vast majority of URLs users will paste.
 */
const URL_PATTERN = /(\b(?:https?:\/\/|www\.)[^\s<>"{}|\\^`[\]]+)/gi;

/**
 * Check if a URL needs protocol added (starts with www. but no protocol)
 */
function normalizeUrl(url: string): string {
  if (url.startsWith('www.')) {
    return `https://${url}`;
  }
  return url;
}

/**
 * Plain text with its URLs as links (new tab, noopener). The text is never
 * parsed as HTML; a URL ends at whitespace, a quote or an angle bracket.
 *
 * @example
 * linkify('Visit www.example.com for more')
 * // 'Visit ', <a href="https://www.example.com" target="_blank" rel="noopener noreferrer">www.example.com</a>, ' for more'
 */
export function linkify(text: string): DocumentFragment {
  const fragment = document.createDocumentFragment();
  let last = 0;
  for (const match of text.matchAll(URL_PATTERN)) {
    const url = match[0];
    if (match.index > last) fragment.append(text.slice(last, match.index));
    const link = document.createElement('a');
    link.href = normalizeUrl(url);
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = url;
    fragment.append(link);
    last = match.index + url.length;
  }
  if (last < text.length) fragment.append(text.slice(last));
  return fragment;
}

/**
 * The normalized URL when it is http(s), else null. For server- or
 * agent-provided URLs put into an href: escaping keeps them inside the
 * attribute, but a javascript: or data: URL would still run when clicked.
 */
export function safeHttpUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null;
  }
}
