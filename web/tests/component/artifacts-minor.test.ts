/**
 * Follow-ups from the artifacts review: live cards during a turn, badges after
 * a revision turn is regenerated away, View source cleanup.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/core/artifact-host', () => ({
  registerFrame: vi.fn(() => () => {}),
  observeTheme: vi.fn(),
  currentTheme: vi.fn(() => 'dark'),
  applyFrameTheme: vi.fn(),
}));
vi.mock('@/api/artifacts', () => ({
  fetchArtifactVersion: vi.fn(),
  saveArtifactState: vi.fn(),
}));
import { fetchArtifactVersion } from '@/api/artifacts';
import { addLiveArtifact, decorateArtifacts } from '@/components/messages/artifacts';

function setup(...ids: string[]): HTMLElement[] {
  document.body.innerHTML = `<div id="messages">${ids
    .map(
      (id) =>
        `<div class="message assistant" data-message-id="${id}"><div class="message-content-wrapper"><div class="message-content"><p>x</p></div></div></div>`
    )
    .join('')}</div>`;
  return ids.map((id) => document.querySelector<HTMLElement>(`[data-message-id="${id}"]`)!);
}

const keys = (el: ParentNode) =>
  [...el.querySelectorAll<HTMLElement>('.artifact-card')].map((c) => c.dataset.artifactKey);

describe('live cards during a turn', () => {
  it('an update in the same turn replaces the card it revises', () => {
    const [m1] = setup('m1');
    addLiveArtifact(m1, { id: 'a', version: 1, title: 'T' });
    addLiveArtifact(m1, { id: 'a', version: 2, title: 'T' });
    expect(keys(m1)).toEqual(['a@2']);
  });

  it('keeps an earlier message’s card of the same artifact', () => {
    const [m1, m2] = setup('m1', 'm2');
    decorateArtifacts(m1, { id: 'm1', artifacts: [{ id: 'a', version: 1, title: 'T' }] });
    addLiveArtifact(m2, { id: 'a', version: 2, title: 'T' });
    expect(keys(m1)).toEqual(['a@1']);
  });
});

describe('badges after a revision turn is regenerated', () => {
  it('a text-only reply in place of the revision clears "newer below"', () => {
    const [m1, m2] = setup('m1', 'm2');
    decorateArtifacts(m1, { id: 'm1', artifacts: [{ id: 'a', version: 1, title: 'T' }] });
    decorateArtifacts(m2, { id: 'm2', artifacts: [{ id: 'a', version: 2, title: 'T' }] });
    expect(m1.querySelector('.artifact-card__newer')).not.toBeNull();

    decorateArtifacts(m2, { id: 'm2' });

    expect(m1.querySelector('.artifact-card__newer')).toBeNull();
  });
});

describe('View source', () => {
  let open: ReturnType<typeof vi.spyOn>;
  const tab = { close: vi.fn(), location: { href: '' } };

  beforeEach(() => {
    open = vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    open.mockRestore();
    tab.close.mockClear();
    vi.useRealTimers();
  });

  const clickSource = (el: HTMLElement) =>
    el.querySelector<HTMLButtonElement>('.artifact-card__source')!.click();

  it('closes the opened tab when the source cannot be loaded', async () => {
    vi.mocked(fetchArtifactVersion).mockRejectedValueOnce(new Error('offline'));
    const [m1] = setup('m1');
    decorateArtifacts(m1, { id: 'm1', artifacts: [{ id: 'a', version: 1, title: 'T' }] });
    clickSource(m1);
    await vi.waitFor(() => expect(tab.close).toHaveBeenCalled());
  });

  it('frees the blob URL once the tab has it', async () => {
    vi.useFakeTimers();
    vi.mocked(fetchArtifactVersion).mockResolvedValueOnce({
      id: 'a',
      version: 1,
      title: 'T',
      html: '<p>x</p>',
      state: null,
    });
    const [m1] = setup('m1');
    decorateArtifacts(m1, { id: 'm1', artifacts: [{ id: 'a', version: 1, title: 'T' }] });
    clickSource(m1);
    await vi.waitFor(() => expect(tab.location.href).toBe('blob:x'));
    vi.advanceTimersByTime(60_000);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:x');
  });
});
