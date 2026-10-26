/**
 * Unit tests for Modal dialog component
 *
 * These tests focus on:
 * 1. Modal initialization
 * 2. Alert/Confirm/Prompt behavior
 * 3. Keyboard navigation
 * 4. Accessibility
 * 5. XSS prevention
 *
 * Note: Tests use vi.resetModules() to get fresh Modal instances since the
 * component uses module-level state (modalContainer, currentResolve, modalType).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Reset DOM and modules before each test
function resetAll() {
  document.body.innerHTML = '';
  vi.resetModules();
}

describe('Modal - Initialization', () => {
  beforeEach(() => {
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('creates modal container element', async () => {
    const { initModal } = await import('@/components/Modal');
    initModal();

    const container = document.getElementById('modal-container');
    expect(container).not.toBeNull();
    expect(container?.classList.contains('modal-container')).toBe(true);
    expect(container?.classList.contains('modal-hidden')).toBe(true);
  });
});

describe('Modal - showAlert', () => {
  beforeEach(() => {
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows alert modal with message', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    // Don't await - just trigger the modal
    showAlert({ message: 'This is an alert' });

    // Run pending timers for any initialization
    vi.runAllTimers();

    const container = document.getElementById('modal-container');
    expect(container?.classList.contains('modal-hidden')).toBe(false);

    const message = container?.querySelector('.modal-message');
    expect(message?.textContent).toBe('This is an alert');
  });

  it('shows alert modal with title', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    showAlert({ title: 'Error', message: 'Something went wrong' });
    vi.runAllTimers();

    const container = document.getElementById('modal-container');
    const title = container?.querySelector('.modal-title');
    expect(title?.textContent).toBe('Error');
  });

  it('has only OK button', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    showAlert({ message: 'Alert' });
    vi.runAllTimers();

    const container = document.getElementById('modal-container');
    const confirmBtn = container?.querySelector('.modal-confirm');
    const cancelBtn = container?.querySelector('.modal-cancel');

    expect(confirmBtn?.textContent).toBe('OK');
    expect(cancelBtn).toBeNull();
  });

  it('resolves when OK is clicked', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    const alertPromise = showAlert({ message: 'Alert' });
    vi.runAllTimers();

    const confirmBtn = document.querySelector('.modal-confirm') as HTMLButtonElement;
    confirmBtn?.click();

    // Animation delay
    vi.advanceTimersByTime(150);

    await expect(alertPromise).resolves.toBeUndefined();
  });

  it('resolves when close button is clicked', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    const alertPromise = showAlert({ message: 'Alert' });
    vi.runAllTimers();

    const closeBtn = document.querySelector('.modal-close') as HTMLButtonElement;
    closeBtn?.click();

    vi.advanceTimersByTime(150);

    await expect(alertPromise).resolves.toBeUndefined();
  });
});

describe('Modal - showConfirm', () => {
  beforeEach(() => {
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows confirm modal with Cancel and OK buttons', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    showConfirm({ message: 'Are you sure?' });
    vi.runAllTimers();

    const container = document.getElementById('modal-container');
    const confirmBtn = container?.querySelector('.modal-confirm');
    const cancelBtn = container?.querySelector('.modal-cancel');

    expect(confirmBtn).not.toBeNull();
    expect(cancelBtn).not.toBeNull();
  });

  it('uses custom button labels', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    showConfirm({
      message: 'Delete?',
      confirmLabel: 'Delete',
      cancelLabel: 'Keep',
    });
    vi.runAllTimers();

    const container = document.getElementById('modal-container');
    const confirmBtn = container?.querySelector('.modal-confirm');
    const cancelBtn = container?.querySelector('.modal-cancel');

    expect(confirmBtn?.textContent).toBe('Delete');
    expect(cancelBtn?.textContent).toBe('Keep');
  });

  it('applies danger class when danger=true', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    showConfirm({ message: 'Delete?', danger: true });
    vi.runAllTimers();

    const confirmBtn = document.querySelector('.modal-confirm');
    expect(confirmBtn?.classList.contains('modal-danger')).toBe(true);
  });

  it('resolves true when confirmed', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    const confirmPromise = showConfirm({ message: 'Confirm?' });
    vi.runAllTimers();

    const confirmBtn = document.querySelector('.modal-confirm') as HTMLButtonElement;
    confirmBtn?.click();

    vi.advanceTimersByTime(150);

    await expect(confirmPromise).resolves.toBe(true);
  });

  it('resolves false when cancelled', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    const confirmPromise = showConfirm({ message: 'Confirm?' });
    vi.runAllTimers();

    const cancelBtn = document.querySelector('.modal-cancel') as HTMLButtonElement;
    cancelBtn?.click();

    vi.advanceTimersByTime(150);

    await expect(confirmPromise).resolves.toBe(false);
  });

  it('resolves false when close button clicked', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    const confirmPromise = showConfirm({ message: 'Confirm?' });
    vi.runAllTimers();

    const closeBtn = document.querySelector('.modal-close') as HTMLButtonElement;
    closeBtn?.click();

    vi.advanceTimersByTime(150);

    await expect(confirmPromise).resolves.toBe(false);
  });

  it('resolves false when overlay clicked', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    const confirmPromise = showConfirm({ message: 'Confirm?' });
    vi.runAllTimers();

    const container = document.getElementById('modal-container') as HTMLElement;
    // Simulate click on overlay (not on modal content)
    container.click();

    vi.advanceTimersByTime(150);

    await expect(confirmPromise).resolves.toBe(false);
  });
});

describe('Modal - showPrompt', () => {
  beforeEach(() => {
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows prompt modal with input field', async () => {
    const { initModal, showPrompt } = await import('@/components/Modal');
    initModal();

    showPrompt({ message: 'Enter name:' });
    vi.runAllTimers();

    const input = document.querySelector('.modal-input') as HTMLInputElement;
    expect(input).not.toBeNull();
  });

  it('sets default value', async () => {
    const { initModal, showPrompt } = await import('@/components/Modal');
    initModal();

    showPrompt({ message: 'Enter name:', defaultValue: 'John' });
    vi.runAllTimers();

    const input = document.querySelector('.modal-input') as HTMLInputElement;
    expect(input?.value).toBe('John');
  });

  it('sets placeholder', async () => {
    const { initModal, showPrompt } = await import('@/components/Modal');
    initModal();

    showPrompt({ message: 'Enter name:', placeholder: 'Your name' });
    vi.runAllTimers();

    const input = document.querySelector('.modal-input') as HTMLInputElement;
    expect(input?.placeholder).toBe('Your name');
  });

  it('resolves with input value when confirmed', async () => {
    const { initModal, showPrompt } = await import('@/components/Modal');
    initModal();

    const promptPromise = showPrompt({ message: 'Name:' });
    vi.runAllTimers();

    const input = document.querySelector('.modal-input') as HTMLInputElement;
    input.value = 'Test Value';

    const confirmBtn = document.querySelector('.modal-confirm') as HTMLButtonElement;
    confirmBtn?.click();

    vi.advanceTimersByTime(150);

    await expect(promptPromise).resolves.toBe('Test Value');
  });

  it('resolves null when cancelled', async () => {
    const { initModal, showPrompt } = await import('@/components/Modal');
    initModal();

    const promptPromise = showPrompt({ message: 'Name:' });
    vi.runAllTimers();

    const cancelBtn = document.querySelector('.modal-cancel') as HTMLButtonElement;
    cancelBtn?.click();

    vi.advanceTimersByTime(150);

    await expect(promptPromise).resolves.toBeNull();
  });

  it('resolves null when close button clicked', async () => {
    const { initModal, showPrompt } = await import('@/components/Modal');
    initModal();

    const promptPromise = showPrompt({ message: 'Name:' });
    vi.runAllTimers();

    const closeBtn = document.querySelector('.modal-close') as HTMLButtonElement;
    closeBtn?.click();

    vi.advanceTimersByTime(150);

    await expect(promptPromise).resolves.toBeNull();
  });

  it('resolves with empty string when confirmed without input', async () => {
    const { initModal, showPrompt } = await import('@/components/Modal');
    initModal();

    const promptPromise = showPrompt({ message: 'Name:' });
    vi.runAllTimers();

    const confirmBtn = document.querySelector('.modal-confirm') as HTMLButtonElement;
    confirmBtn?.click();

    vi.advanceTimersByTime(150);

    await expect(promptPromise).resolves.toBe('');
  });
});

describe('Modal - Keyboard Navigation', () => {
  beforeEach(() => {
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('closes on Escape key for alert', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    const alertPromise = showAlert({ message: 'Alert' });
    vi.runAllTimers();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

    vi.advanceTimersByTime(150);

    await expect(alertPromise).resolves.toBeUndefined();
  });

  it('closes on Escape key for confirm (resolves false)', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    const confirmPromise = showConfirm({ message: 'Confirm?' });
    vi.runAllTimers();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

    vi.advanceTimersByTime(150);

    await expect(confirmPromise).resolves.toBe(false);
  });

  it('closes on Escape key for prompt (resolves null)', async () => {
    const { initModal, showPrompt } = await import('@/components/Modal');
    initModal();

    const promptPromise = showPrompt({ message: 'Name:' });
    vi.runAllTimers();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

    vi.advanceTimersByTime(150);

    await expect(promptPromise).resolves.toBeNull();
  });

  it('confirms on Enter key for confirm modal', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    const confirmPromise = showConfirm({ message: 'Confirm?' });
    vi.runAllTimers();

    // Focus the confirm button (simulates what happens after modal opens)
    const confirmBtn = document.querySelector('.modal-confirm') as HTMLButtonElement;
    confirmBtn?.focus();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

    vi.advanceTimersByTime(150);

    await expect(confirmPromise).resolves.toBe(true);
  });

  it('submits on Enter key in prompt input', async () => {
    const { initModal, showPrompt } = await import('@/components/Modal');
    initModal();

    const promptPromise = showPrompt({ message: 'Name:' });
    vi.runAllTimers();

    const input = document.querySelector('.modal-input') as HTMLInputElement;
    input.value = 'Entered Value';
    input.focus();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

    vi.advanceTimersByTime(150);

    await expect(promptPromise).resolves.toBe('Entered Value');
  });
});

describe('Modal - Focus Trapping', () => {
  beforeEach(() => {
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('has focusable elements within modal', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    showConfirm({ message: 'Confirm?' });
    vi.runAllTimers();

    const container = document.getElementById('modal-container');
    const focusableElements = container?.querySelectorAll('button');

    expect(focusableElements?.length).toBeGreaterThan(1);
  });
});

describe('Modal - closeModal', () => {
  beforeEach(() => {
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('adds exit animation class', async () => {
    const { initModal, showAlert, closeModal } = await import('@/components/Modal');
    initModal();

    showAlert({ message: 'Alert' });
    vi.runAllTimers();

    closeModal();

    const modal = document.querySelector('.modal');
    expect(modal?.classList.contains('modal-exit')).toBe(true);
  });

  it('hides container after animation', async () => {
    const { initModal, showAlert, closeModal } = await import('@/components/Modal');
    initModal();

    showAlert({ message: 'Alert' });
    vi.runAllTimers();

    closeModal();

    // Before animation completes
    const containerBefore = document.getElementById('modal-container');
    expect(containerBefore?.classList.contains('modal-hidden')).toBe(false);

    // After animation (150ms)
    vi.advanceTimersByTime(150);

    const containerAfter = document.getElementById('modal-container');
    expect(containerAfter?.classList.contains('modal-hidden')).toBe(true);
  });
});

describe('Modal - Accessibility', () => {
  beforeEach(() => {
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('is labelled by its title, and unlabelled without one', async () => {
    const { initModal, showAlert, closeModal } = await import('@/components/Modal');
    initModal();

    showAlert({ title: 'Delete chat?', message: 'Gone for good.' });
    const labelId = document.querySelector('.modal')?.getAttribute('aria-labelledby');
    expect(labelId).toBeTruthy();
    expect(document.getElementById(labelId ?? '')?.textContent).toBe('Delete chat?');

    closeModal();
    vi.runAllTimers();
    showAlert({ message: 'No title' });
    expect(document.querySelector('.modal')?.hasAttribute('aria-labelledby')).toBe(false);
  });

  it('has role="dialog" attribute', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    showAlert({ message: 'Alert' });
    vi.runAllTimers();

    const modal = document.querySelector('.modal');
    expect(modal?.getAttribute('role')).toBe('dialog');
  });

  it('has aria-modal="true" attribute', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    showAlert({ message: 'Alert' });
    vi.runAllTimers();

    const modal = document.querySelector('.modal');
    expect(modal?.getAttribute('aria-modal')).toBe('true');
  });

  it('close button has aria-label', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    showAlert({ message: 'Alert' });
    vi.runAllTimers();

    const closeBtn = document.querySelector('.modal-close');
    expect(closeBtn?.getAttribute('aria-label')).toBe('Close');
  });
});

describe('Modal - XSS Prevention', () => {
  beforeEach(() => {
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('escapes HTML in message', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    showAlert({ message: '<script>alert("xss")</script>' });
    vi.runAllTimers();

    const message = document.querySelector('.modal-message');
    expect(message?.innerHTML).not.toContain('<script>');
    expect(message?.textContent).toContain('<script>');
  });

  it('escapes HTML in title', async () => {
    const { initModal, showAlert } = await import('@/components/Modal');
    initModal();

    showAlert({ title: '<img src=x onerror=alert(1)>', message: 'Test' });
    vi.runAllTimers();

    const title = document.querySelector('.modal-title');
    // The < and > should be escaped as &lt; and &gt;
    // so no actual img tag is created
    expect(title?.innerHTML).toContain('&lt;');
    expect(title?.innerHTML).toContain('&gt;');
    expect(title?.querySelector('img')).toBeNull();
  });

  it('escapes HTML in button labels', async () => {
    const { initModal, showConfirm } = await import('@/components/Modal');
    initModal();

    showConfirm({
      message: 'Test',
      confirmLabel: '<b>Bold</b>',
      cancelLabel: '<i>Italic</i>',
    });
    vi.runAllTimers();

    const confirmBtn = document.querySelector('.modal-confirm');
    const cancelBtn = document.querySelector('.modal-cancel');

    expect(confirmBtn?.innerHTML).not.toContain('<b>');
    expect(cancelBtn?.innerHTML).not.toContain('<i>');
  });
});
