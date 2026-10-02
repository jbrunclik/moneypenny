/**
 * The message Copy button's plain text must keep line breaks: user bubbles
 * render newlines as <br>, and textContent drops them, so a copied message
 * pasted back (users do this to resend) arrived as one run-on line.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('@/api/files', () => ({ files: {} }));
vi.mock('@/components/Toast', () => ({ toast: { error: vi.fn() } }));
vi.mock('@/utils/haptics', () => ({ hapticTick: vi.fn() }));

import { copyMessageContent } from '@/core/file-actions';

describe('copyMessageContent', () => {
  let writeText: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    writeText = vi.fn(async () => undefined);
    // No ClipboardItem in jsdom: the plain-text fallback is what we observe
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  });

  it('keeps <br> line breaks in the plain text', async () => {
    document.body.innerHTML = `
      <div class="message user">
        <div class="message-content">first line<br>second line<br><br>after a blank line</div>
        <button class="copy-btn"></button>
      </div>`;
    const button = document.querySelector<HTMLButtonElement>('.copy-btn')!;

    await copyMessageContent(button);

    expect(writeText).toHaveBeenCalledWith('first line\nsecond line\n\nafter a blank line');
  });
});
