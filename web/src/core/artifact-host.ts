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
  ARTIFACT_SEND_MIN_INTERVAL_MS,
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
  /** The frame said ready (also after a timeout already reported failure) */
  onReady?: () => void;
}

interface Entry {
  frame: HTMLIFrameElement;
  ref: ArtifactRef;
  callbacks: FrameCallbacks;
  readyTimer: number | null;
  saveTimer: number | null;
  pendingState: unknown;
  /** When this frame last sent a message (one send per click burst) */
  lastSendAt: number;
}

// Keyed by the element, matched to `event.source` per message: a frame can be
// registered before it is in the DOM (history renders a message, then appends
// it), when it has no contentWindow yet
const entries = new Map<HTMLIFrameElement, Entry>();
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

/**
 * Whether the user just clicked or typed IN THIS FRAME. Checked here, never
 * trusted from the frame: artifact code runs in the frame's realm and can post
 * mp:send / mp:link itself. A click inside a frame activates its ancestors
 * (so the chat sees isActive) and focuses the iframe element. Focus is what
 * ties the activation to this frame: a click on the chat's own Send button
 * stays "active" for seconds, long enough for a fresh artifact to fire.
 */
function userJustActed(entry: Entry): boolean {
  if (document.activeElement !== entry.frame) return false;
  const activation = (navigator as Navigator & { userActivation?: { isActive: boolean } })
    .userActivation;
  // Without the API (older Safari) focus alone has to do
  return activation ? activation.isActive : true;
}

function send(entry: Entry, text: string): void {
  const now = Date.now();
  if (!text.trim() || !userJustActed(entry) || now - entry.lastSendAt < ARTIFACT_SEND_MIN_INTERVAL_MS) {
    log.warn('Artifact send refused', { artifactId: entry.ref.id });
    return;
  }
  entry.lastSendAt = now;
  void sendUiMessage(text.slice(0, ARTIFACT_SEND_MAX_CHARS));
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
      entry.callbacks.onReady?.();
      void initFrame(entry);
      break;
    case 'mp:height':
      applyHeight(entry, message.height);
      break;
    case 'mp:send':
      send(entry, message.text);
      break;
    case 'mp:state':
      scheduleStateSave(entry, message.state);
      break;
    case 'mp:link':
      if (userJustActed(entry)) openLink(message.href);
      break;
    case 'mp:error':
      log.warn('Artifact error', { artifactId: entry.ref.id, message: message.message });
      entry.callbacks.onError?.(message.message);
      break;
    case 'mp:rendered':
      break;
  }
}

function entryFor(source: MessageEventSource | null): Entry | undefined {
  if (!source) return undefined;
  for (const entry of entries.values()) {
    if (entry.frame.contentWindow === source) return entry;
  }
  return undefined;
}

function onMessage(event: MessageEvent): void {
  const entry = entryFor(event.source);
  if (entry && isFromFrame(event.data)) handle(entry, event.data);
}

/** The iframe's colour scheme must match its page's, or Chrome paints an
 * opaque backdrop behind the (transparent) artifact. */
export function applyFrameTheme(frame: HTMLIFrameElement, theme: ArtifactTheme): void {
  frame.style.colorScheme = theme;
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
  if (!listening) {
    window.addEventListener('message', onMessage);
    listening = true;
  }
  const entry: Entry = {
    frame,
    ref,
    callbacks,
    readyTimer: null,
    saveTimer: null,
    pendingState: null,
    lastSendAt: 0,
  };
  entry.readyTimer = window.setTimeout(() => fail(entry), ARTIFACT_READY_TIMEOUT_MS);
  entries.set(frame, entry);
  return () => {
    if (entry.readyTimer !== null) window.clearTimeout(entry.readyTimer);
    entries.delete(frame);
  };
}

/** Push app theme changes to every live frame (installed once). */
export function observeTheme(): void {
  if (themeObserver) return;
  themeObserver = new MutationObserver(() => {
    const theme = currentTheme();
    for (const [frame, entry] of entries) {
      // Cards dropped by a re-render without unregistering
      if (!frame.isConnected) {
        entries.delete(frame);
        continue;
      }
      applyFrameTheme(frame, theme);
      post(entry, { type: 'mp:theme', theme });
    }
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
