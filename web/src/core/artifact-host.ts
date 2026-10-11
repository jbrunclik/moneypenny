/**
 * The chat's side of the artifact bridge: one window listener for every live
 * frame, routing by `event.source` (frames are opaque-origin, so their origin
 * is "null" and says nothing). A frame gets its HTML, theme and saved state
 * when it says ready; what it asks for (send, state, links) is checked here.
 */
import { fetchArtifactVersion, saveArtifactState } from '../api/artifacts';
import { type ArtifactTheme, type FromFrame, isFromFrame, type ToFrame } from '../artifact/protocol';
import {
  ARTIFACT_MAX_HEIGHT_VH,
  ARTIFACT_READY_TIMEOUT_MS,
  ARTIFACT_SEND_MAX_CHARS,
  ARTIFACT_STATE_SAVE_DEBOUNCE_MS,
} from '../config';
import type { ArtifactRef } from '../types/api';
import { createLogger } from '../utils/logger';
import { sendUiMessage } from './messaging';

const log = createLogger('artifacts');

export interface FrameCallbacks {
  /** The frame applied this height (px) */
  onHeight?: (heightPx: number) => void;
  /** The frame never got ready, or its HTML could not be loaded */
  onFailed?: () => void;
  /** The artifact reported a runtime error (it keeps running) */
  onError?: (message: string) => void;
}

interface Entry {
  frame: HTMLIFrameElement;
  ref: ArtifactRef;
  callbacks: FrameCallbacks;
  readyTimer: number | null;
  saveTimer: number | null;
  pendingState: unknown;
}

const entries = new Map<Window, Entry>();
let listening = false;
let themeObserver: MutationObserver | null = null;

export function currentTheme(): ArtifactTheme {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

function post(entry: Entry, message: ToFrame): void {
  // Opaque-origin frame: '*' is the only target origin that reaches it
  entry.frame.contentWindow?.postMessage(message, '*');
}

function fail(entry: Entry): void {
  if (entry.readyTimer !== null) window.clearTimeout(entry.readyTimer);
  entry.readyTimer = null;
  entry.callbacks.onFailed?.();
}

async function initFrame(entry: Entry): Promise<void> {
  if (entry.readyTimer !== null) window.clearTimeout(entry.readyTimer);
  entry.readyTimer = null;
  try {
    const version = await fetchArtifactVersion(entry.ref.id, entry.ref.version);
    post(entry, { type: 'mp:init', html: version.html, theme: currentTheme(), state: version.state });
  } catch (error) {
    log.warn('Artifact version could not be loaded', { artifactId: entry.ref.id, error });
    fail(entry);
  }
}

function applyHeight(entry: Entry, reported: number): void {
  const cap = Math.round((window.innerHeight * ARTIFACT_MAX_HEIGHT_VH) / 100);
  const height = Math.max(0, Math.min(Math.ceil(reported), cap));
  const before = entry.frame.getBoundingClientRect();
  entry.frame.style.height = `${height}px`;
  // A frame above the viewport changing height would shift what the user
  // is reading: move the scroll position by the same amount
  const container = entry.frame.closest<HTMLElement>('#messages');
  if (container && before.bottom <= container.getBoundingClientRect().top) {
    container.scrollTop += height - before.height;
  }
  entry.callbacks.onHeight?.(height);
}

function scheduleStateSave(entry: Entry, state: unknown): void {
  entry.pendingState = state;
  if (entry.saveTimer !== null) window.clearTimeout(entry.saveTimer);
  entry.saveTimer = window.setTimeout(() => {
    entry.saveTimer = null;
    saveArtifactState(entry.ref.id, entry.pendingState).catch((error: unknown) => {
      log.warn('Artifact state not saved', { artifactId: entry.ref.id, error });
    });
  }, ARTIFACT_STATE_SAVE_DEBOUNCE_MS);
}

function openLink(href: string): void {
  try {
    if (new URL(href).protocol === 'https:') window.open(href, '_blank', 'noopener');
  } catch {
    // Not a URL: ignore
  }
}

function handle(entry: Entry, message: FromFrame): void {
  switch (message.type) {
    case 'mp:ready':
      void initFrame(entry);
      break;
    case 'mp:height':
      applyHeight(entry, message.height);
      break;
    case 'mp:send':
      if (message.text.trim()) void sendUiMessage(message.text.slice(0, ARTIFACT_SEND_MAX_CHARS));
      break;
    case 'mp:state':
      scheduleStateSave(entry, message.state);
      break;
    case 'mp:link':
      openLink(message.href);
      break;
    case 'mp:error':
      log.warn('Artifact error', { artifactId: entry.ref.id, message: message.message });
      entry.callbacks.onError?.(message.message);
      break;
    case 'mp:rendered':
      break;
  }
}

function onMessage(event: MessageEvent): void {
  const entry = event.source ? entries.get(event.source as Window) : undefined;
  if (entry && isFromFrame(event.data)) handle(entry, event.data);
}

/**
 * Start serving a frame already in the DOM. Returns a function that stops
 * (call it when the card is removed).
 */
export function registerFrame(
  frame: HTMLIFrameElement,
  ref: ArtifactRef,
  callbacks: FrameCallbacks
): () => void {
  const win = frame.contentWindow;
  if (!win) return () => {};
  if (!listening) {
    window.addEventListener('message', onMessage);
    listening = true;
  }
  const entry: Entry = { frame, ref, callbacks, readyTimer: null, saveTimer: null, pendingState: null };
  entry.readyTimer = window.setTimeout(() => fail(entry), ARTIFACT_READY_TIMEOUT_MS);
  entries.set(win, entry);
  return () => {
    if (entry.readyTimer !== null) window.clearTimeout(entry.readyTimer);
    entries.delete(win);
  };
}

/** Push app theme changes to every live frame (installed once). */
export function observeTheme(): void {
  if (themeObserver) return;
  themeObserver = new MutationObserver(() => {
    const theme = currentTheme();
    for (const entry of entries.values()) post(entry, { type: 'mp:theme', theme });
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

/** Tests: forget every frame and listener. */
export function _resetArtifactHost(): void {
  for (const entry of entries.values()) {
    if (entry.readyTimer !== null) window.clearTimeout(entry.readyTimer);
    if (entry.saveTimer !== null) window.clearTimeout(entry.saveTimer);
  }
  entries.clear();
  window.removeEventListener('message', onMessage);
  listening = false;
  themeObserver?.disconnect();
  themeObserver = null;
}
