/**
 * Unit tests for mobile keyboard viewport pinning (--keyboard-inset).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { initKeyboardViewportPinning } from '@/core/keyboard-viewport';

// The re-pin path calls element.scrollTo, which jsdom doesn't implement -
// without the stub the deferred RAF throws an uncaught async exception
Element.prototype.scrollTo = vi.fn();

class MockVisualViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  scale = 1;
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function getInset(): string {
  return document.documentElement.style.getPropertyValue('--keyboard-inset');
}

describe('keyboard viewport pinning', () => {
  let viewport: MockVisualViewport;
  let textarea: HTMLTextAreaElement;

  beforeEach(() => {
    document.body.innerHTML = '<div id="messages"></div><textarea id="message-input"></textarea>';
    document.documentElement.style.removeProperty('--keyboard-inset');
    viewport = new MockVisualViewport();
    Object.defineProperty(window, 'visualViewport', { value: viewport, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    textarea = document.getElementById('message-input') as HTMLTextAreaElement;
    initKeyboardViewportPinning();
  });

  it('sets the keyboard inset when the viewport shrinks with an input focused', () => {
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('300px');
  });

  it('ignores small shrinks below the keyboard threshold (accessory bars)', () => {
    textarea.focus();
    viewport.height = 760; // 40px < KEYBOARD_INSET_MIN_PX
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('');
  });

  it('resets the stale layout-viewport pan and redraws the caret on inset', async () => {
    // Standalone-PWA caret bug: iOS pans the layout viewport to reveal a
    // focused bottom input; our height shrink then reflows content up but
    // WebKit keeps drawing the caret at the stale pan position (outside
    // the input). Reset the pan and re-assert the selection to force a
    // caret redraw.
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    textarea.value = 'hello';
    textarea.focus();
    textarea.setSelectionRange(3, 3);
    const selectionSpy = vi.spyOn(textarea, 'setSelectionRange');

    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();
    await nextFrame();

    expect(scrollToSpy).toHaveBeenCalledWith(0, 0);
    // Caret redraw nudge preserves the existing caret position
    expect(selectionSpy).toHaveBeenCalledWith(3, 3);
    scrollToSpy.mockRestore();
  });

  it('does not touch scroll or selection when no inset applies', async () => {
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    textarea.focus();
    viewport.height = 760; // below threshold - no inset
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();
    await nextFrame();

    expect(scrollToSpy).not.toHaveBeenCalled();
    scrollToSpy.mockRestore();
  });

  it('ignores pinch zoom (scale != 1)', () => {
    textarea.focus();
    viewport.scale = 2;
    viewport.height = 400;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('');
  });

  it('ignores shrinks when no editable element is focused', () => {
    textarea.blur();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('');
  });

  it('clears the inset when focus leaves the input', async () => {
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('300px');

    viewport.height = 800;
    textarea.blur();
    document.dispatchEvent(new Event('focusout'));
    await nextFrame();
    expect(getInset()).toBe('0px');
  });

  it('accounts for visual viewport panning (offsetTop)', () => {
    textarea.focus();
    viewport.height = 500;
    viewport.offsetTop = 100;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('200px');
  });
});
