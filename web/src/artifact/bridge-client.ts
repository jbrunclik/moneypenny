/**
 * The `mp` API inside an artifact frame, and the reports the frame sends to
 * the chat on its own (height, errors, link clicks). Everything goes out as a
 * postMessage; the chat decides what to do with it (core/artifact-host.ts).
 */
import type { ArtifactTheme, FromFrame } from './protocol';

export interface MpApi {
  /** Send text as the user's next message - only from a click/key handler */
  send(text: string): void;
  state: {
    get(): Promise<unknown>;
    set(state: unknown): void;
  };
  theme: ArtifactTheme;
}

export interface BridgeClient {
  applyInit(state: unknown, theme: ArtifactTheme): void;
  /** Tick the checklist items saved as done (once the artifact's HTML is in) */
  restoreChecklist(): void;
  applyTheme(theme: ArtifactTheme): void;
  /** Remove listeners and `mp` (tests) */
  uninstall(): void;
}

type Post = (message: FromFrame) => void;

const ERROR_MAX_CHARS = 300;
/** Where navigator.userActivation is missing: a gesture this recent counts */
const GESTURE_WINDOW_MS = 1000;
const GESTURE_EVENTS = ['pointerdown', 'keydown', 'click'] as const;

/**
 * The stored state is an envelope: `app` is the artifact's own state (all its
 * code ever sees) and `checklist` the ticks this bridge saves for every
 * .mp-checklist item, keyed by label - so neither can overwrite the other.
 */
interface Envelope {
  app: unknown;
  checklist: Record<string, true>;
}

const CHECKLIST_BOX = '.mp-checklist input[type="checkbox"]';

function toEnvelope(stored: unknown): Envelope {
  if (stored && typeof stored === 'object' && ('app' in stored || 'checklist' in stored)) {
    const { app = null, checklist } = stored as Partial<Envelope>;
    return { app, checklist: checklist && typeof checklist === 'object' ? { ...checklist } : {} };
  }
  return { app: stored ?? null, checklist: {} };
}

/**
 * Every checklist box with its key: the label text, whitespace collapsed, and
 * " #n" on the n-th repeat (src/agent/tools/artifact_checklist.py keys alike).
 */
export function checklistKeys(root: ParentNode): Array<{ input: HTMLInputElement; key: string }> {
  const seen = new Map<string, number>();
  return [...root.querySelectorAll<HTMLInputElement>(CHECKLIST_BOX)].map((input) => {
    const label = (input.closest('label')?.textContent ?? '').replace(/\s+/g, ' ').trim();
    const n = (seen.get(label) ?? 0) + 1;
    seen.set(label, n);
    return { input, key: n === 1 ? label : `${label} #${n}` };
  });
}

function hasActivation(lastGestureAt: number): boolean {
  const activation = (navigator as Navigator & { userActivation?: { isActive: boolean } })
    .userActivation;
  if (activation) return activation.isActive;
  return Date.now() - lastGestureAt < GESTURE_WINDOW_MS;
}

function errorText(parts: unknown[]): string {
  return parts
    .map((p) => (p instanceof Error ? p.message : String(p)))
    .join(' ')
    .slice(0, ERROR_MAX_CHARS);
}

function linkHref(event: Event): string | null {
  const target = event.target instanceof Element ? event.target.closest('a[href]') : null;
  const raw = target?.getAttribute('href') ?? '';
  if (!target || raw.startsWith('#')) return null;
  return (target as HTMLAnchorElement).href;
}

export function installBridgeClient(win: Window, post: Post): BridgeClient {
  let envelope: Envelope = { app: null, checklist: {} };
  let initialized = false;
  let lastGestureAt = 0;
  const waiting: Array<(value: unknown) => void> = [];
  const doc = win.document;

  const mp: MpApi = {
    send(text: string) {
      if (hasActivation(lastGestureAt)) post({ type: 'mp:send', text: String(text) });
    },
    state: {
      get: () =>
        initialized ? Promise.resolve(envelope.app) : new Promise((r) => waiting.push(r)),
      set(next: unknown) {
        envelope = { ...envelope, app: next };
        post({ type: 'mp:state', state: envelope });
      },
    },
    theme: 'dark',
  };
  (win as Window & { mp?: MpApi }).mp = mp;

  const onGesture = (): void => {
    lastGestureAt = Date.now();
  };
  for (const name of GESTURE_EVENTS) win.addEventListener(name, onGesture, true);
  const stopLinks = interceptLinks(doc, post);
  const stopErrors = forwardErrors(win, post);
  const stopHeight = observeHeight(win, post);
  const onTick = (event: Event): void => {
    if (!(event.target instanceof Element) || !event.target.matches(CHECKLIST_BOX)) return;
    const checklist: Record<string, true> = {};
    for (const { input, key } of checklistKeys(doc)) if (input.checked) checklist[key] = true;
    envelope = { ...envelope, checklist };
    post({ type: 'mp:state', state: envelope });
  };
  doc.addEventListener('change', onTick, true);

  const applyTheme = (theme: ArtifactTheme): void => {
    doc.documentElement.dataset.theme = theme;
    mp.theme = theme;
    win.dispatchEvent(new Event('mp:theme'));
  };

  return {
    applyInit(initState, theme) {
      envelope = toEnvelope(initState);
      initialized = true;
      waiting.splice(0).forEach((resolve) => resolve(envelope.app));
      applyTheme(theme);
    },
    restoreChecklist() {
      for (const { input, key } of checklistKeys(doc)) {
        if (envelope.checklist[key]) input.checked = true;
      }
    },
    applyTheme,
    uninstall() {
      for (const name of GESTURE_EVENTS) win.removeEventListener(name, onGesture, true);
      stopLinks();
      stopErrors();
      stopHeight();
      doc.removeEventListener('change', onTick, true);
      delete (win as Window & { mp?: MpApi }).mp;
    },
  };
}

/** Hold back link clicks and let the chat open them (the sandbox cannot). */
function interceptLinks(doc: Document, post: Post): () => void {
  const onClick = (event: Event): void => {
    const href = linkHref(event);
    if (href === null) return;
    event.preventDefault();
    post({ type: 'mp:link', href });
  };
  doc.addEventListener('click', onClick, true);
  return () => doc.removeEventListener('click', onClick, true);
}

/** Uncaught errors, rejections and console.error go to the chat's error badge. */
function forwardErrors(win: Window, post: Post): () => void {
  const onError = (event: ErrorEvent): void =>
    post({ type: 'mp:error', message: errorText([event.message]) });
  const onRejection = (event: PromiseRejectionEvent): void =>
    post({ type: 'mp:error', message: errorText([event.reason]) });
  const originalConsoleError = console.error;
  console.error = (...args: unknown[]) => {
    post({ type: 'mp:error', message: errorText(args) });
    originalConsoleError.apply(console, args);
  };
  win.addEventListener('error', onError);
  win.addEventListener('unhandledrejection', onRejection);
  return () => {
    win.removeEventListener('error', onError);
    win.removeEventListener('unhandledrejection', onRejection);
    console.error = originalConsoleError;
  };
}

/** Report the document's height whenever it changes (rounded, deduped). */
function observeHeight(win: Window, post: Post): () => void {
  const ResizeObserverCtor = (win as Window & { ResizeObserver?: typeof ResizeObserver })
    .ResizeObserver;
  if (!ResizeObserverCtor) return () => {};
  const root = win.document.documentElement;
  let last = -1;
  const observer = new ResizeObserverCtor(() => {
    const height = Math.ceil(root.getBoundingClientRect().height);
    if (height === last) return;
    last = height;
    post({ type: 'mp:height', height });
  });
  observer.observe(root);
  return () => observer.disconnect();
}
