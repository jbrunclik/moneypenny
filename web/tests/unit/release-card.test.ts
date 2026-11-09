import { describe, expect, it } from 'vitest';
import { asReleaseCard } from '../../src/components/messages/release-card';

function rendered(html: string): HTMLElement {
  const el = document.createElement('div');
  el.className = 'message-content';
  el.innerHTML = html;
  return el;
}

const SECTIONED = `
<h1>Reminders, agents and more</h1>
<p>This chat is where you'll hear what's new.</p>
<p><strong>Reminders</strong></p>
<ul><li>Say "remind me"</li></ul>
<p><strong>Agents</strong></p>
<ul><li>Set one up by talking</li><li>One list</li></ul>
<p>This chat is read-only.</p>`;

describe('asReleaseCard', () => {
  it('splits a post into header, intro, section tiles and a footer', () => {
    const el = rendered(SECTIONED);
    asReleaseCard(el, '2026-11-09T08:00:00Z', 'en');

    expect(el.classList.contains('release-card')).toBe(true);
    expect(el.querySelector('.release-card-date')?.textContent).toBe('November 9, 2026');
    expect(el.querySelector('.release-card-date')?.getAttribute('datetime')).toBe('2026-11-09T08:00:00Z');
    expect(el.querySelector('.release-card-title')?.textContent).toBe('Reminders, agents and more');
    expect(el.querySelector('.release-card-intro')?.textContent).toBe("This chat is where you'll hear what's new.");
    const tiles = [...el.querySelectorAll('.release-card-grid > .release-card-section')];
    expect(tiles.map((t) => t.querySelector('.release-card-section-title')?.textContent)).toEqual([
      'Reminders',
      'Agents',
    ]);
    expect(tiles[1]?.querySelectorAll('li')).toHaveLength(2);
    expect(el.querySelector('.release-card-footer')?.textContent).toBe('This chat is read-only.');
  });

  it('keeps a paragraph between sections with the section above it', () => {
    const el = rendered(
      '<h1>T</h1><p>Intro.</p><p><strong>A</strong></p><ul><li>a</li></ul><p>More on A.</p>' +
        '<p><strong>B</strong></p><ul><li>b</li></ul>',
    );
    asReleaseCard(el, '2026-11-09T08:00:00Z', 'en');
    const [first] = el.querySelectorAll('.release-card-section');
    expect(first?.textContent).toContain('More on A.');
    expect(el.querySelector('.release-card-footer')).toBeNull();
  });

  it('takes the stored form, whose title is a level-2 heading', () => {
    // announcements.py stores "# Title" as "## Title"
    const el = rendered('<h2>Stored title</h2><p>Intro.</p><p><strong>A</strong></p><ul><li>a</li></ul>');
    asReleaseCard(el, '2026-11-09T08:00:00Z', 'en');
    expect(el.classList.contains('release-card')).toBe(true);
    expect(el.querySelector('.release-card-title')?.textContent).toBe('Stored title');
    expect(el.querySelectorAll('.release-card-section')).toHaveLength(1);
  });

  it('dates the post in its own language', () => {
    const el = rendered('<h1>Novinky</h1><p>Text.</p>');
    asReleaseCard(el, '2026-11-09T08:00:00Z', 'cs');
    expect(el.querySelector('.release-card-date')?.textContent).toBe('9. listopadu 2026');
  });

  it('keeps a post without sections as body text, with no footer', () => {
    const el = rendered('<h1>More thorough answers</h1><p>First.</p><p>Second.</p>');
    asReleaseCard(el, '2026-11-09T08:00:00Z', 'en');
    expect(el.querySelector('.release-card-intro')?.textContent).toBe('First.');
    expect(el.querySelector('.release-card-grid')).toBeNull();
    expect(el.querySelector('.release-card-footer')).toBeNull();
    expect(el.querySelector('.release-card-body')?.textContent).toBe('Second.');
  });

  it('leaves a post without a title untouched', () => {
    const el = rendered('<p>Just text.</p>');
    asReleaseCard(el, '2026-11-09T08:00:00Z', 'en');
    expect(el.classList.contains('release-card')).toBe(false);
    expect(el.innerHTML).toBe('<p>Just text.</p>');
  });
});
