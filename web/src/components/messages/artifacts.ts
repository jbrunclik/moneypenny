/**
 * Artifact cards under a reply: a title row and the sandboxed frame
 * (docs/features/artifacts.md). Decorating is idempotent by `id@version`, so
 * the stream's `artifact` event, the done event and later re-renders keep the
 * same live frame instead of reloading it.
 */
import { fetchArtifactVersion } from '../../api/artifacts';
import { ARTIFACT_PLACEHOLDER_HEIGHT_PX, ARTIFACT_SOURCE_URL_TTL_MS } from '../../config';
import { applyFrameTheme, currentTheme, observeTheme, registerFrame } from './artifact-host';
import { getCachedHeight, heightCacheKey, setCachedHeight } from './artifact-height';
import type { ArtifactRef } from '../../types/api';
import { flashElement } from './action-row';

const LIST_CLASS = 'artifact-list';
const CARD_SELECTOR = '.artifact-card';
const FLASH_CLASS = 'artifact-card--flash';

/** Each card's unregister function, so removed cards stop being served */
const stops = new WeakMap<HTMLElement, () => void>();

const keyOf = (ref: ArtifactRef): string => `${ref.id}@${ref.version}`;

function ensureList(messageEl: HTMLElement): HTMLElement | null {
  const existing = messageEl.querySelector<HTMLElement>(`.${LIST_CLASS}`);
  if (existing) return existing;
  const content = messageEl.querySelector('.message-content');
  if (!content) return null;
  const list = document.createElement('div');
  list.className = LIST_CLASS;
  content.insertAdjacentElement('afterend', list);
  return list;
}

function header(ref: ArtifactRef): HTMLElement {
  const row = document.createElement('div');
  row.className = 'artifact-card__header';
  const title = document.createElement('span');
  title.className = 'artifact-card__title';
  title.textContent = ref.title;
  const badges = document.createElement('span');
  badges.className = 'artifact-card__badges';
  const source = document.createElement('button');
  source.type = 'button';
  source.className = 'artifact-card__source';
  source.textContent = 'View source';
  source.addEventListener('click', () => void viewSource(ref));
  row.append(title, badges, source);
  return row;
}

async function viewSource(ref: ArtifactRef): Promise<void> {
  // Plain text in a new tab: readable at any length, never rendered. The tab
  // opens synchronously (still inside the click, or popup blockers refuse it)
  const tab = window.open('', '_blank');
  let html: string;
  try {
    html = (await fetchArtifactVersion(ref.id, ref.version)).html;
  } catch {
    tab?.close();
    return;
  }
  const url = URL.createObjectURL(new Blob([html], { type: 'text/plain;charset=utf-8' }));
  if (tab) tab.location.href = url;
  window.setTimeout(() => URL.revokeObjectURL(url), ARTIFACT_SOURCE_URL_TTL_MS);
}

function setBadge(card: HTMLElement, kind: string, text: string | null, onClick?: () => void): void {
  const badges = card.querySelector('.artifact-card__badges');
  const existing = card.querySelector(`.artifact-card__${kind}`);
  if (!text) {
    existing?.remove();
    return;
  }
  if (existing) {
    existing.textContent = text;
    return;
  }
  const badge = document.createElement(onClick ? 'button' : 'span');
  badge.className = `artifact-card__${kind}`;
  badge.textContent = text;
  if (onClick) badge.addEventListener('click', onClick);
  badges?.appendChild(badge);
}

function mountFrame(card: HTMLElement, ref: ArtifactRef): void {
  stops.get(card)?.();
  clearFailed(card);
  const frame = document.createElement('iframe');
  frame.className = 'artifact-frame';
  frame.setAttribute('sandbox', 'allow-scripts');
  // The starting theme rides on the URL so the frame matches before init
  const theme = currentTheme();
  frame.setAttribute('src', `/artifact-frame?theme=${theme}`);
  applyFrameTheme(frame, theme);
  frame.setAttribute('title', ref.title);
  const cacheKey = (): string => heightCacheKey(ref, card.clientWidth);
  frame.style.height = `${getCachedHeight(cacheKey()) ?? ARTIFACT_PLACEHOLDER_HEIGHT_PX}px`;
  card.querySelector('.artifact-frame')?.replaceWith(frame);
  if (!frame.isConnected) card.appendChild(frame);
  stops.set(
    card,
    registerFrame(frame, ref, {
      onHeight: (px) => setCachedHeight(cacheKey(), px),
      onFailed: () => showFailed(card, ref),
      // A slow frame (cold start, cellular) that gets ready after the timeout
      onReady: () => clearFailed(card),
      onError: () => setBadge(card, 'error', 'Artifact error'),
    })
  );
}

function clearFailed(card: HTMLElement): void {
  card.classList.remove('artifact-card--failed');
  card.querySelector('.artifact-card__failed')?.remove();
}

function showFailed(card: HTMLElement, ref: ArtifactRef): void {
  card.classList.add('artifact-card--failed');
  if (card.querySelector('.artifact-card__failed')) return;
  const note = document.createElement('div');
  note.className = 'artifact-card__failed';
  const text = document.createElement('span');
  text.textContent = "Couldn't display";
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.textContent = 'Retry';
  retry.addEventListener('click', () => mountFrame(card, ref));
  note.append(text, retry);
  card.insertBefore(note, card.querySelector('.artifact-frame'));
}

function createCard(ref: ArtifactRef): HTMLElement {
  const card = document.createElement('div');
  card.className = 'artifact-card';
  card.dataset.artifactKey = keyOf(ref);
  card.dataset.artifactId = ref.id;
  card.dataset.artifactVersion = String(ref.version);
  card.dataset.artifactTitle = ref.title;
  card.appendChild(header(ref));
  return card;
}

function addCard(list: HTMLElement, ref: ArtifactRef): void {
  if (list.querySelector(`${CARD_SELECTOR}[data-artifact-key="${CSS.escape(keyOf(ref))}"]`)) return;
  const card = createCard(ref);
  list.appendChild(card);
  observeTheme();
  mountFrame(card, ref);
}

function removeCard(card: HTMLElement): void {
  stops.get(card)?.();
  card.remove();
}

/** Cards for a message's artifacts (idempotent; drops cards no longer listed). */
export function decorateArtifacts(
  messageEl: HTMLElement,
  message: { id: string; artifacts?: ArtifactRef[] }
): void {
  const refs = message.artifacts ?? [];
  const existing = messageEl.querySelector<HTMLElement>(`.${LIST_CLASS}`);
  if (!refs.length && !existing) return;
  const list = existing ?? ensureList(messageEl);
  if (!list) return;
  const keep = new Set(refs.map(keyOf));
  for (const card of Array.from(list.querySelectorAll<HTMLElement>(CARD_SELECTOR))) {
    if (!keep.has(card.dataset.artifactKey ?? '')) removeCard(card);
  }
  for (const ref of refs) addCard(list, ref);
  if (!refs.length) list.remove();
  refreshVersionBadges();
}

/** The stream's `artifact` event: show the card while the reply streams. */
export function addLiveArtifact(messageEl: HTMLElement, ref: ArtifactRef): void {
  const list = ensureList(messageEl);
  if (!list) return;
  // An update later in the same turn replaces the card it revises (done
  // lists only the turn's last version of each artifact)
  for (const card of Array.from(list.querySelectorAll<HTMLElement>(CARD_SELECTOR))) {
    const older = Number(card.dataset.artifactVersion) < ref.version;
    if (card.dataset.artifactId === ref.id && older) removeCard(card);
  }
  addCard(list, ref);
  refreshVersionBadges();
}

/** The next card further down showing a later version of the same artifact. */
function newerCard(card: HTMLElement): HTMLElement | null {
  const cards = Array.from(document.querySelectorAll<HTMLElement>(CARD_SELECTOR));
  const version = Number(card.dataset.artifactVersion);
  return (
    cards
      .slice(cards.indexOf(card) + 1)
      .find(
        (c) =>
          c.dataset.artifactId === card.dataset.artifactId &&
          Number(c.dataset.artifactVersion) > version
      ) ?? null
  );
}

/** "v1 · newer below" on a card whose artifact has a later version further down. */
export function refreshVersionBadges(container: ParentNode = document): void {
  for (const card of Array.from(container.querySelectorAll<HTMLElement>(CARD_SELECTOR))) {
    const text = newerCard(card) ? `v${card.dataset.artifactVersion} · newer below` : null;
    setBadge(card, 'newer', text, () => {
      const target = newerCard(card);
      if (target) flashElement(target, FLASH_CLASS);
    });
  }
}

/** Lines naming the message's artifacts, for the copied text. */
export function artifactCopyText(messageEl: Element): string {
  return Array.from(messageEl.querySelectorAll<HTMLElement>(CARD_SELECTOR))
    .map((card) => `[Artifact: ${card.dataset.artifactTitle ?? ''}]`)
    .join('\n');
}
