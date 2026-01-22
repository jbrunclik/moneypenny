/**
 * Unit tests for DOM utility functions
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  escapeHtml,
  getElementById,
  querySelector,
  querySelectorAll,
  createElement,
  autoResizeTextarea,
  scrollToBottom,
  scrollToElementTop,
  isScrolledToBottom,
  toggleClass,
  showElement,
  hideElement,
  clearElement,
} from '@/utils/dom';

describe('escapeHtml', () => {
  it('escapes HTML special characters', () => {
    expect(escapeHtml('<script>alert("xss")</script>')).toBe(
      '&lt;script&gt;alert("xss")&lt;/script&gt;'
    );
  });

  it('escapes ampersand', () => {
    expect(escapeHtml('foo & bar')).toBe('foo &amp; bar');
  });

  it('escapes quotes', () => {
    expect(escapeHtml('say "hello"')).toBe('say "hello"');
  });

  it('handles empty string', () => {
    expect(escapeHtml('')).toBe('');
  });

  it('handles plain text without special characters', () => {
    expect(escapeHtml('Hello World')).toBe('Hello World');
  });

  it('handles multiple special characters', () => {
    expect(escapeHtml('<div class="test">&nbsp;</div>')).toBe(
      '&lt;div class="test"&gt;&amp;nbsp;&lt;/div&gt;'
    );
  });
});

describe('getElementById', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="test-element">Test</div>';
  });

  it('returns element when found', () => {
    const element = getElementById<HTMLDivElement>('test-element');
    expect(element).not.toBeNull();
    expect(element?.textContent).toBe('Test');
  });

  it('returns null when not found', () => {
    const element = getElementById('nonexistent');
    expect(element).toBeNull();
  });
});

describe('querySelector', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="container">
        <span class="item">First</span>
        <span class="item">Second</span>
      </div>
    `;
  });

  it('returns first matching element', () => {
    const element = querySelector<HTMLSpanElement>('.item');
    expect(element).not.toBeNull();
    expect(element?.textContent).toBe('First');
  });

  it('returns null when not found', () => {
    const element = querySelector('.nonexistent');
    expect(element).toBeNull();
  });

  it('searches within parent when provided', () => {
    const container = querySelector<HTMLDivElement>('.container');
    const item = querySelector<HTMLSpanElement>('.item', container!);
    expect(item?.textContent).toBe('First');
  });
});

describe('querySelectorAll', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <ul>
        <li class="item">One</li>
        <li class="item">Two</li>
        <li class="item">Three</li>
      </ul>
    `;
  });

  it('returns all matching elements', () => {
    const items = querySelectorAll<HTMLLIElement>('.item');
    expect(items.length).toBe(3);
    expect(items[0].textContent).toBe('One');
    expect(items[2].textContent).toBe('Three');
  });

  it('returns empty NodeList when not found', () => {
    const items = querySelectorAll('.nonexistent');
    expect(items.length).toBe(0);
  });
});

describe('createElement', () => {
  it('creates element with tag', () => {
    const div = createElement('div');
    expect(div.tagName).toBe('DIV');
  });

  it('creates element with attributes', () => {
    const input = createElement('input', {
      type: 'text',
      placeholder: 'Enter text',
      'data-testid': 'my-input',
    });
    expect(input.type).toBe('text');
    expect(input.placeholder).toBe('Enter text');
    expect(input.dataset.testid).toBe('my-input');
  });

  it('creates element with text children', () => {
    const p = createElement('p', {}, ['Hello, ', 'World!']);
    expect(p.textContent).toBe('Hello, World!');
  });

  it('creates element with node children', () => {
    const span = createElement('span', {}, ['Text']);
    const div = createElement('div', {}, [span]);
    expect(div.children.length).toBe(1);
    expect(div.children[0].tagName).toBe('SPAN');
  });

  it('creates element with mixed children', () => {
    const span = createElement('span', {}, ['inside']);
    const p = createElement('p', {}, ['Before ', span, ' after']);
    expect(p.textContent).toBe('Before inside after');
  });

  it('creates element with class attribute', () => {
    const div = createElement('div', { class: 'foo bar' });
    expect(div.classList.contains('foo')).toBe(true);
    expect(div.classList.contains('bar')).toBe(true);
  });
});

describe('autoResizeTextarea', () => {
  it('sets height based on scrollHeight', () => {
    const textarea = document.createElement('textarea');
    textarea.value = 'Some text';
    document.body.appendChild(textarea);

    // Mock scrollHeight
    Object.defineProperty(textarea, 'scrollHeight', { value: 100 });

    autoResizeTextarea(textarea);

    expect(textarea.style.height).toBe('100px');

    document.body.removeChild(textarea);
  });
});

describe('scrollToBottom', () => {
  it('scrolls to bottom without smooth', () => {
    const div = document.createElement('div');
    div.scrollTo = vi.fn();
    Object.defineProperty(div, 'scrollHeight', { value: 1000 });

    scrollToBottom(div, false);

    expect(div.scrollTo).toHaveBeenCalledWith({
      top: 1000,
      behavior: 'auto',
    });
  });

  it('uses requestAnimationFrame for smooth scroll', () => {
    const div = document.createElement('div');
    Object.defineProperty(div, 'scrollHeight', { value: 1000 });
    Object.defineProperty(div, 'clientHeight', { value: 500 });
    Object.defineProperty(div, 'scrollTop', { value: 0, writable: true });

    const rafSpy = vi.spyOn(window, 'requestAnimationFrame');

    scrollToBottom(div, true);

    expect(rafSpy).toHaveBeenCalled();
  });
});

describe('scrollToElementTop', () => {
  // Helper to mock getBoundingClientRect for container and target
  function mockBoundingRects(
    container: HTMLElement,
    target: HTMLElement,
    containerTop: number,
    targetTop: number,
    scrollTop: number
  ): void {
    container.getBoundingClientRect = vi.fn().mockReturnValue({ top: containerTop });
    target.getBoundingClientRect = vi.fn().mockReturnValue({ top: targetTop });
    Object.defineProperty(container, 'scrollTop', { value: scrollTop, writable: true });
  }

  it('scrolls container so target element is at top (instant)', () => {
    const container = document.createElement('div');
    const target = document.createElement('div');
    container.appendChild(target);

    container.scrollTo = vi.fn();
    // Container at y=100, target at y=300, scrollTop=0 → target is 200px into scroll content
    mockBoundingRects(container, target, 100, 300, 0);

    scrollToElementTop(container, target, false);

    expect(container.scrollTo).toHaveBeenCalledWith({
      top: 200,
      behavior: 'auto',
    });
  });

  it('uses requestAnimationFrame for smooth scroll', () => {
    const container = document.createElement('div');
    const target = document.createElement('div');
    container.appendChild(target);

    mockBoundingRects(container, target, 0, 500, 0);

    const rafSpy = vi.spyOn(window, 'requestAnimationFrame');

    scrollToElementTop(container, target, true);

    expect(rafSpy).toHaveBeenCalled();
  });

  it('scrolls to correct offset when target is further down', () => {
    const container = document.createElement('div');
    const target = document.createElement('div');
    container.appendChild(target);

    container.scrollTo = vi.fn();
    // Container at y=50, target at y=800, scrollTop=0 → target is 750px into scroll content
    mockBoundingRects(container, target, 50, 800, 0);

    scrollToElementTop(container, target, false);

    expect(container.scrollTo).toHaveBeenCalledWith({
      top: 750,
      behavior: 'auto',
    });
  });

  it('defaults to smooth scrolling when no smooth parameter provided', () => {
    const container = document.createElement('div');
    const target = document.createElement('div');
    container.appendChild(target);

    mockBoundingRects(container, target, 0, 300, 0);

    const rafSpy = vi.spyOn(window, 'requestAnimationFrame');

    // Call without the smooth parameter (defaults to true)
    scrollToElementTop(container, target);

    expect(rafSpy).toHaveBeenCalled();
  });

  it('handles element at top of container', () => {
    const container = document.createElement('div');
    const target = document.createElement('div');
    container.appendChild(target);

    container.scrollTo = vi.fn();
    // Container and target at same position → scroll to 0
    mockBoundingRects(container, target, 100, 100, 0);

    scrollToElementTop(container, target, false);

    expect(container.scrollTo).toHaveBeenCalledWith({
      top: 0,
      behavior: 'auto',
    });
  });

  it('accounts for current scroll position when calculating target', () => {
    const container = document.createElement('div');
    const target = document.createElement('div');
    container.appendChild(target);

    container.scrollTo = vi.fn();
    // Container at y=0, target at y=200, but container is already scrolled 500px
    // Visual offset is 200, but absolute position in scroll content is 200 + 500 = 700
    mockBoundingRects(container, target, 0, 200, 500);

    scrollToElementTop(container, target, false);

    expect(container.scrollTo).toHaveBeenCalledWith({
      top: 700,
      behavior: 'auto',
    });
  });
});

describe('isScrolledToBottom', () => {
  it('returns true when at bottom', () => {
    const div = document.createElement('div');
    Object.defineProperty(div, 'scrollHeight', { value: 1000 });
    Object.defineProperty(div, 'scrollTop', { value: 500 });
    Object.defineProperty(div, 'clientHeight', { value: 500 });

    expect(isScrolledToBottom(div)).toBe(true);
  });

  it('returns true when within threshold of bottom', () => {
    const div = document.createElement('div');
    Object.defineProperty(div, 'scrollHeight', { value: 1000 });
    Object.defineProperty(div, 'scrollTop', { value: 450 });
    Object.defineProperty(div, 'clientHeight', { value: 500 });

    expect(isScrolledToBottom(div, 100)).toBe(true);
  });

  it('returns false when not at bottom', () => {
    const div = document.createElement('div');
    Object.defineProperty(div, 'scrollHeight', { value: 1000 });
    Object.defineProperty(div, 'scrollTop', { value: 0 });
    Object.defineProperty(div, 'clientHeight', { value: 500 });

    expect(isScrolledToBottom(div)).toBe(false);
  });

  it('uses default threshold of 100', () => {
    const div = document.createElement('div');
    Object.defineProperty(div, 'scrollHeight', { value: 1000 });
    Object.defineProperty(div, 'scrollTop', { value: 401 });
    Object.defineProperty(div, 'clientHeight', { value: 500 });

    // 1000 - 401 - 500 = 99 < 100, so should be true
    expect(isScrolledToBottom(div)).toBe(true);
  });
});

describe('toggleClass', () => {
  it('adds class when not present', () => {
    const div = document.createElement('div');
    const result = toggleClass(div, 'active');
    expect(result).toBe(true);
    expect(div.classList.contains('active')).toBe(true);
  });

  it('removes class when present', () => {
    const div = document.createElement('div');
    div.classList.add('active');
    const result = toggleClass(div, 'active');
    expect(result).toBe(false);
    expect(div.classList.contains('active')).toBe(false);
  });

  it('forces class on', () => {
    const div = document.createElement('div');
    div.classList.add('active');
    const result = toggleClass(div, 'active', true);
    expect(result).toBe(true);
    expect(div.classList.contains('active')).toBe(true);
  });

  it('forces class off', () => {
    const div = document.createElement('div');
    const result = toggleClass(div, 'active', false);
    expect(result).toBe(false);
    expect(div.classList.contains('active')).toBe(false);
  });
});

describe('showElement', () => {
  it('removes hidden class', () => {
    const div = document.createElement('div');
    div.classList.add('hidden');
    showElement(div);
    expect(div.classList.contains('hidden')).toBe(false);
  });

  it('does nothing if not hidden', () => {
    const div = document.createElement('div');
    showElement(div);
    expect(div.classList.contains('hidden')).toBe(false);
  });
});

describe('hideElement', () => {
  it('adds hidden class', () => {
    const div = document.createElement('div');
    hideElement(div);
    expect(div.classList.contains('hidden')).toBe(true);
  });

  it('keeps hidden class if already hidden', () => {
    const div = document.createElement('div');
    div.classList.add('hidden');
    hideElement(div);
    expect(div.classList.contains('hidden')).toBe(true);
  });
});

describe('clearElement', () => {
  it('removes all text content', () => {
    const div = document.createElement('div');
    div.textContent = 'Hello World';
    clearElement(div);
    expect(div.textContent).toBe('');
  });

  it('removes all child elements', () => {
    const div = document.createElement('div');
    div.innerHTML = '<span>Child 1</span><span>Child 2</span>';
    expect(div.children.length).toBe(2);
    clearElement(div);
    expect(div.children.length).toBe(0);
    expect(div.innerHTML).toBe('');
  });

  it('handles already empty elements', () => {
    const div = document.createElement('div');
    clearElement(div);
    expect(div.textContent).toBe('');
    expect(div.children.length).toBe(0);
  });

  it('removes nested content', () => {
    const div = document.createElement('div');
    div.innerHTML = '<div><span>Nested</span></div>';
    clearElement(div);
    expect(div.innerHTML).toBe('');
  });
});
