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
 * Convert plain text URLs to clickable anchor tags.
 * Opens links in new tab with security attributes.
 *
 * @param text - Plain text that may contain URLs
 * @returns HTML string with URLs converted to <a> tags
 *
 * @example
 * linkifyText('Check out https://example.com')
 * // Returns: 'Check out <a href="https://example.com" target="_blank" rel="noopener noreferrer">https://example.com</a>'
 *
 * @example
 * linkifyText('Visit www.example.com for more')
 * // Returns: 'Visit <a href="https://www.example.com" target="_blank" rel="noopener noreferrer">www.example.com</a> for more'
 */
export function linkifyText(text: string): string {
  return text.replace(URL_PATTERN, (url) => {
    const href = normalizeUrl(url);
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${url}</a>`;
  });
}

/**
 * Check if text contains any URLs
 *
 * @param text - Text to check for URLs
 * @returns true if text contains at least one URL
 */
export function containsUrls(text: string): boolean {
  // Create a new regex without 'g' flag to avoid state issues with .test()
  const pattern = /(\b(?:https?:\/\/|www\.)[^\s<>"{}|\\^`[\]]+)/i;
  return pattern.test(text);
}
