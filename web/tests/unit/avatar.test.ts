/**
 * A Google avatar URL can stop working (photo changed, URL retired); the
 * avatar must fall back to initials instead of a broken-image icon.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { createUserAvatarElement, installAvatarFallback, renderUserAvatarHtml } from '@/utils/avatar';

describe('avatar fallback', () => {
  beforeAll(() => installAvatarFallback());

  it('replaces a failed avatar image (HTML string) with initials', () => {
    document.body.innerHTML = `<div id="host">${renderUserAvatarHtml('https://lh3.example/dead.jpg', 'Jana Nováková')}</div>`;

    document.querySelector('img')!.dispatchEvent(new Event('error'));

    const fallback = document.querySelector('#host > div')!;
    expect(fallback.className).toBe('user-avatar user-avatar-initials');
    expect(fallback.textContent).toBe('JN');
    expect(document.querySelector('img')).toBeNull();
  });

  it('replaces a failed avatar element with initials, keeping a custom class', () => {
    document.body.innerHTML = '<div id="host"></div>';
    document.querySelector('#host')!.appendChild(createUserAvatarElement('https://x/dead.jpg', 'Petr', 'message-avatar'));

    document.querySelector('img')!.dispatchEvent(new Event('error'));

    expect(document.querySelector('#host > div')!.className).toBe('message-avatar message-avatar-initials');
  });

  it('leaves other failing images alone', () => {
    document.body.innerHTML = '<img src="https://x/a.png" alt="chart" class="message-image">';

    document.querySelector('img')!.dispatchEvent(new Event('error'));

    expect(document.querySelector('img.message-image')).not.toBeNull();
  });

  it('asks the avatar host without a referrer', () => {
    expect(renderUserAvatarHtml('https://x/p.jpg', 'A')).toContain('referrerpolicy="no-referrer"');
    expect((createUserAvatarElement('https://x/p.jpg', 'A') as HTMLImageElement).referrerPolicy).toBe('no-referrer');
  });
});
