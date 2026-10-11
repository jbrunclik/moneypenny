import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/core/artifact-host', () => ({
  registerFrame: vi.fn(() => () => {}),
  observeTheme: vi.fn(),
  currentTheme: vi.fn(() => 'dark'),
  applyFrameTheme: vi.fn((frame: HTMLIFrameElement, theme: string) => {
    frame.style.colorScheme = theme;
  }),
}));
import { registerFrame } from '@/core/artifact-host';
import {
  addLiveArtifact,
  artifactCopyText,
  decorateArtifacts,
  refreshVersionBadges,
} from '@/components/messages/artifacts';
import type { ArtifactRef } from '@/types/api';

const ref = (id: string, version: number, title = 'Tips'): ArtifactRef => ({ id, version, title });

function messageHtml(id: string): string {
  return `<div class="message assistant" data-message-id="${id}"><div class="message-content-wrapper"><div class="message-content"><p>Here.</p></div><div class="message-actions"></div></div></div>`;
}

function setup(...ids: string[]): HTMLElement[] {
  document.body.innerHTML = `<div id="messages">${ids.map(messageHtml).join('')}</div>`;
  return ids.map((id) => document.querySelector<HTMLElement>(`[data-message-id="${id}"]`)!);
}

const cards = (el: ParentNode = document) => [...el.querySelectorAll<HTMLElement>('.artifact-card')];

beforeEach(() => {
  vi.mocked(registerFrame).mockClear();
});

describe('decorateArtifacts', () => {
  it('renders one sandboxed frame per ref between the text and the actions', () => {
    const [m1] = setup('m1');
    decorateArtifacts(m1, { id: 'm1', artifacts: [ref('a', 1), ref('b', 1, 'Recipe')] });

    expect(cards(m1).map((c) => c.dataset.artifactKey)).toEqual(['a@1', 'b@1']);
    const frame = m1.querySelector('iframe')!;
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    // The starting theme rides on the URL so the empty frame matches the app
    expect(frame.getAttribute('src')).toBe('/artifact-frame?theme=dark');
    expect(frame.style.colorScheme).toBe('dark');
    expect(frame.getAttribute('title')).toBe('Tips');
    const list = m1.querySelector('.artifact-list')!;
    expect(list.previousElementSibling?.classList.contains('message-content')).toBe(true);
    expect(list.nextElementSibling?.classList.contains('message-actions')).toBe(true);
    expect(registerFrame).toHaveBeenCalledTimes(2);
  });

  it('keeps live frames when decorated again and drops removed refs', () => {
    const [m1] = setup('m1');
    decorateArtifacts(m1, { id: 'm1', artifacts: [ref('a', 1), ref('b', 1)] });
    const first = m1.querySelector('iframe');

    decorateArtifacts(m1, { id: 'm1', artifacts: [ref('a', 1)] });

    expect(m1.querySelector('iframe')).toBe(first);
    expect(cards(m1).map((c) => c.dataset.artifactKey)).toEqual(['a@1']);
    expect(registerFrame).toHaveBeenCalledTimes(2);
  });

  it('a message without artifacts gets no list', () => {
    const [m1] = setup('m1');
    decorateArtifacts(m1, { id: 'm1' });
    expect(m1.querySelector('.artifact-list')).toBeNull();
  });
});

describe('addLiveArtifact', () => {
  it('adds the card during streaming and the done decoration keeps it', () => {
    const [m1] = setup('m1');
    addLiveArtifact(m1, ref('a', 1));
    const frame = m1.querySelector('iframe');
    decorateArtifacts(m1, { id: 'm1', artifacts: [ref('a', 1)] });
    expect(m1.querySelector('iframe')).toBe(frame);
    expect(registerFrame).toHaveBeenCalledTimes(1);
  });
});

describe('version badges', () => {
  it('an older version points to the newer one below, none when absent', () => {
    const [m1, m2] = setup('m1', 'm2');
    decorateArtifacts(m1, { id: 'm1', artifacts: [ref('a', 1)] });
    expect(m1.querySelector('.artifact-card__newer')).toBeNull();

    decorateArtifacts(m2, { id: 'm2', artifacts: [ref('a', 2)] });

    const badge = m1.querySelector<HTMLButtonElement>('.artifact-card__newer')!;
    expect(badge.textContent).toBe('v1 · newer below');
    expect(m2.querySelector('.artifact-card__newer')).toBeNull();

    m2.remove();
    refreshVersionBadges();
    expect(m1.querySelector('.artifact-card__newer')).toBeNull();
  });
});

describe('artifactCopyText', () => {
  it('names each artifact for the copied text', () => {
    const [m1] = setup('m1');
    decorateArtifacts(m1, { id: 'm1', artifacts: [ref('a', 1, 'Tips'), ref('b', 1, 'Recipe')] });
    expect(artifactCopyText(m1)).toBe('[Artifact: Tips]\n[Artifact: Recipe]');
    expect(artifactCopyText(setup('m3')[0])).toBe('');
  });
});
