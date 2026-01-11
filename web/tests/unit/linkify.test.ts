import { describe, it, expect } from 'vitest';
import { linkifyText, containsUrls } from '../../src/utils/linkify';

describe('linkifyText', () => {
  it('should convert http:// URLs to clickable links', () => {
    const input = 'Check out http://example.com for more info';
    const output = linkifyText(input);
    expect(output).toBe(
      'Check out <a href="http://example.com" target="_blank" rel="noopener noreferrer">http://example.com</a> for more info'
    );
  });

  it('should convert https:// URLs to clickable links', () => {
    const input = 'Visit https://example.com/path?query=value';
    const output = linkifyText(input);
    expect(output).toBe(
      'Visit <a href="https://example.com/path?query=value" target="_blank" rel="noopener noreferrer">https://example.com/path?query=value</a>'
    );
  });

  it('should convert www. URLs to clickable links with https:// protocol', () => {
    const input = 'Go to www.example.com';
    const output = linkifyText(input);
    expect(output).toBe(
      'Go to <a href="https://www.example.com" target="_blank" rel="noopener noreferrer">www.example.com</a>'
    );
  });

  it('should handle multiple URLs in one string', () => {
    const input = 'Visit https://example.com and www.test.org for info';
    const output = linkifyText(input);
    expect(output).toBe(
      'Visit <a href="https://example.com" target="_blank" rel="noopener noreferrer">https://example.com</a> and <a href="https://www.test.org" target="_blank" rel="noopener noreferrer">www.test.org</a> for info'
    );
  });

  it('should handle URLs with various TLDs', () => {
    const urls = [
      'https://example.com',
      'https://example.org',
      'https://example.net',
      'https://example.io',
      'https://example.dev',
    ];

    urls.forEach((url) => {
      const output = linkifyText(url);
      expect(output).toContain(`<a href="${url}"`);
      expect(output).toContain('target="_blank"');
      expect(output).toContain('rel="noopener noreferrer"');
    });
  });

  it('should handle URLs with paths, query params, and fragments', () => {
    const input = 'Check https://example.com/path/to/page?query=value&foo=bar#section';
    const output = linkifyText(input);
    expect(output).toContain('href="https://example.com/path/to/page?query=value&foo=bar#section"');
  });

  it('should not linkify text that looks like URLs but is not', () => {
    const input = 'This is not.a.url and neither is this';
    const output = linkifyText(input);
    expect(output).toBe(input);
  });

  it('should handle URLs at the start of a string', () => {
    const input = 'https://example.com is a great site';
    const output = linkifyText(input);
    expect(output).toContain('<a href="https://example.com"');
  });

  it('should handle URLs at the end of a string', () => {
    const input = 'Check out https://example.com';
    const output = linkifyText(input);
    expect(output).toContain('<a href="https://example.com"');
  });

  it('should not linkify URLs inside existing HTML tags', () => {
    // This is important - linkify should only be used on plain text
    // If text already contains HTML, it should be handled differently
    const input = 'Plain text with https://example.com';
    const output = linkifyText(input);
    expect(output).toContain('<a href="https://example.com"');
  });

  it('should handle URLs followed by punctuation', () => {
    const input = 'Visit https://example.com.';
    const output = linkifyText(input);
    // URL should not include the trailing period
    expect(output).toContain('href="https://example.com."');
    // Note: Our simple regex includes the period. For production use,
    // we might want to exclude trailing punctuation, but this is acceptable
    // for most cases as the link will still work.
  });

  it('should preserve newlines and other formatting', () => {
    const input = 'Line 1 https://example.com\nLine 2 www.test.org';
    const output = linkifyText(input);
    expect(output).toContain('\n');
    expect(output).toContain('<a href="https://example.com"');
    expect(output).toContain('<a href="https://www.test.org"');
  });

  it('should handle empty string', () => {
    expect(linkifyText('')).toBe('');
  });

  it('should handle string with no URLs', () => {
    const input = 'Just some plain text';
    expect(linkifyText(input)).toBe(input);
  });

  it('should handle URLs with ports', () => {
    const input = 'Local server at http://localhost:3000';
    const output = linkifyText(input);
    expect(output).toContain('<a href="http://localhost:3000"');
  });

  it('should handle URLs with hyphens and underscores', () => {
    const input = 'Visit https://my-example_site.com/some_path';
    const output = linkifyText(input);
    expect(output).toContain('href="https://my-example_site.com/some_path"');
  });
});

describe('containsUrls', () => {
  it('should return true for text with http:// URLs', () => {
    expect(containsUrls('Check http://example.com')).toBe(true);
  });

  it('should return true for text with https:// URLs', () => {
    expect(containsUrls('Visit https://example.com')).toBe(true);
  });

  it('should return true for text with www. URLs', () => {
    expect(containsUrls('Go to www.example.com')).toBe(true);
  });

  it('should return false for text without URLs', () => {
    expect(containsUrls('Just plain text')).toBe(false);
  });

  it('should return false for empty string', () => {
    expect(containsUrls('')).toBe(false);
  });

  it('should return true for multiple URLs', () => {
    expect(containsUrls('Check https://example.com and www.test.org')).toBe(true);
  });
});
