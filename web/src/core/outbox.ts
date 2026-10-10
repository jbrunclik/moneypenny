/**
 * Send outbox: tracks user messages that have been rendered optimistically
 * but not yet confirmed by the server.
 *
 * Entries are persisted to localStorage so a send that dies with the page
 * (crash, tab close, lost connection) resurfaces as a failed message with a
 * retry affordance after reload, instead of silently disappearing.
 *
 * Reconciliation on conversation load decides each entry's fate: confirmed
 * by the server → dropped; still being sent in this session → pending;
 * being sent by another live tab (the store is shared by every tab of the
 * browser) → left to that tab; otherwise → failed.
 */
import {
  OUTBOX_PERSIST_MAX_FILE_CHARS,
  OUTBOX_STORAGE_KEY,
  OUTBOX_TAB_HEARTBEAT_MS,
  OUTBOX_TAB_STALE_MS,
  OUTBOX_TABS_STORAGE_KEY,
} from '../config';
import type { DeepResearchStart, FileMetadata, FileUpload, Message, MessageAction } from '../types/api';
import { createLogger } from '../utils/logger';
import { deleteOutboxFiles, loadOutboxFiles, saveOutboxFiles } from './outbox-files';

const log = createLogger('outbox');

export interface OutboxEntry {
  id: string;
  conversationId: string;
  content: string;
  files: FileUpload[];
  /** True when attachments were too large to persist (lost on reload) */
  filesDropped: boolean;
  forceTools: string[];
  anonymousMode: boolean;
  createdAt: string;
  /** Starts a deep-research offer: a retry resends the plan */
  deepResearch?: DeepResearchStart;
  /** What the message is, when the app sent it for the user */
  action?: MessageAction;
  status: 'pending' | 'failed';
  /** The tab sending it (absent on entries persisted before tabs were tracked) */
  ownerTab?: string;
}

export type NewOutboxEntry = Omit<OutboxEntry, 'status' | 'filesDropped' | 'ownerTab'>;

// This page's identity in the shared store
const TAB_ID = crypto.randomUUID();

// Session-only state: full file payloads (which may exceed the persistence
// cap) and the set of sends currently in flight in this page.
const sessionFiles = new Map<string, FileUpload[]>();
const inflightIds = new Set<string>();

/** Test hook: reset session state between tests. */
export function _clearOutboxMemoryCache(): void {
  sessionFiles.clear();
  inflightIds.clear();
  stopHeartbeat();
}

// --- Tab heartbeat: other tabs leave this tab's in-flight sends alone ---

type TabHeartbeats = Record<string, number>;

let heartbeatTimer: ReturnType<typeof setInterval> | null = null;

function readHeartbeats(): TabHeartbeats {
  try {
    return JSON.parse(localStorage.getItem(OUTBOX_TABS_STORAGE_KEY) || '{}') as TabHeartbeats;
  } catch {
    return {};
  }
}

/** Record (or with `alive=false` drop) this tab's heartbeat; prunes dead tabs. */
function writeHeartbeat(alive: boolean): void {
  try {
    const now = Date.now();
    const beats: TabHeartbeats = {};
    for (const [tab, seenAt] of Object.entries(readHeartbeats())) {
      if (tab !== TAB_ID && now - seenAt < OUTBOX_TAB_STALE_MS) beats[tab] = seenAt;
    }
    if (alive) beats[TAB_ID] = now;
    if (Object.keys(beats).length === 0) {
      localStorage.removeItem(OUTBOX_TABS_STORAGE_KEY);
    } else {
      localStorage.setItem(OUTBOX_TABS_STORAGE_KEY, JSON.stringify(beats));
    }
  } catch (error) {
    log.warn('Failed to write the outbox tab heartbeat', { error });
  }
}

function heartbeatTick(): void {
  if (inflightIds.size === 0) {
    stopHeartbeat();
    return;
  }
  writeHeartbeat(true);
}

/** Beat while this tab has sends in flight (idempotent). */
function startHeartbeat(): void {
  writeHeartbeat(true);
  if (heartbeatTimer !== null) return;
  heartbeatTimer = setInterval(heartbeatTick, OUTBOX_TAB_HEARTBEAT_MS);
  // A closed tab's sends are failed for the others right away
  window.addEventListener('pagehide', stopHeartbeat);
}

function stopHeartbeat(): void {
  if (heartbeatTimer === null) return;
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
  window.removeEventListener('pagehide', stopHeartbeat);
  writeHeartbeat(false);
}

/** Another tab is still sending this entry: not ours to fail or render. */
function isOwnedByLiveTab(entry: OutboxEntry): boolean {
  if (!entry.ownerTab || entry.ownerTab === TAB_ID) return false;
  const seenAt = readHeartbeats()[entry.ownerTab];
  return seenAt !== undefined && Date.now() - seenAt < OUTBOX_TAB_STALE_MS;
}

type OutboxStore = Record<string, OutboxEntry[]>;

function readStore(): OutboxStore {
  try {
    return JSON.parse(localStorage.getItem(OUTBOX_STORAGE_KEY) || '{}') as OutboxStore;
  } catch {
    return {};
  }
}

function writeStore(store: OutboxStore): void {
  try {
    if (Object.keys(store).length === 0) {
      localStorage.removeItem(OUTBOX_STORAGE_KEY);
      return;
    }
    localStorage.setItem(OUTBOX_STORAGE_KEY, JSON.stringify(store));
  } catch (error) {
    // Quota exceeded: retry without any file payloads rather than losing text
    log.warn('Failed to persist outbox, retrying without files', { error });
    try {
      const stripped: OutboxStore = {};
      for (const [convId, entries] of Object.entries(store)) {
        stripped[convId] = entries.map((e) =>
          e.files.length ? { ...e, files: [], filesDropped: true } : e
        );
      }
      localStorage.setItem(OUTBOX_STORAGE_KEY, JSON.stringify(stripped));
    } catch (retryError) {
      log.error('Failed to persist outbox', { error: retryError });
    }
  }
}

function mutateEntries(convId: string, fn: (entries: OutboxEntry[]) => OutboxEntry[]): void {
  const store = readStore();
  const updated = fn(store[convId] ?? []);
  if (updated.length === 0) {
    delete store[convId];
  } else {
    store[convId] = updated;
  }
  writeStore(store);
}

/** Strip blob preview URLs (dead after reload) and drop oversized payloads. */
function persistableFiles(files: FileUpload[]): { files: FileUpload[]; filesDropped: boolean } {
  const totalChars = files.reduce((sum, f) => sum + f.data.length, 0);
  if (totalChars > OUTBOX_PERSIST_MAX_FILE_CHARS) {
    return { files: [], filesDropped: true };
  }
  return {
    files: files.map(({ name, type, data }) => ({ name, type, data })),
    filesDropped: false,
  };
}

/** Record a new outgoing message before its network request starts. */
export function addOutboxEntry(entry: NewOutboxEntry): void {
  if (entry.files.length) {
    sessionFiles.set(entry.id, entry.files);
    // localStorage holds small files only; IndexedDB keeps the rest for a
    // retry after a reload
    void saveOutboxFiles(entry.id, entry.files);
  }
  const persisted: OutboxEntry = {
    ...entry,
    ...persistableFiles(entry.files),
    status: 'pending',
    ownerTab: TAB_ID,
  };
  mutateEntries(entry.conversationId, (entries) => [
    ...entries.filter((e) => e.id !== entry.id),
    persisted,
  ]);
}

/**
 * Entry for a manual retry: like getOutboxEntry, plus attachments that only
 * survived a reload in IndexedDB.
 */
export async function restoreOutboxEntry(convId: string, id: string): Promise<OutboxEntry | undefined> {
  const entry = getOutboxEntry(convId, id);
  if (!entry?.filesDropped) return entry;
  const stored = await loadOutboxFiles(id);
  if (!stored) return entry;
  sessionFiles.set(id, stored);
  return { ...entry, files: stored, filesDropped: false };
}

/** Full entry for retry: prefers the in-memory file payloads when available. */
export function getOutboxEntry(convId: string, id: string): OutboxEntry | undefined {
  const entry = readStore()[convId]?.find((e) => e.id === id);
  if (!entry) return undefined;
  const files = sessionFiles.get(id);
  return files ? { ...entry, files } : entry;
}

/** Whether a send carried attachments (stored in IndexedDB until it settles). */
function hadFiles(convId: string, id: string): boolean {
  const entry = readStore()[convId]?.find((e) => e.id === id);
  return sessionFiles.has(id) || Boolean(entry && (entry.files.length || entry.filesDropped));
}

/** The server confirmed receipt: the entry is no longer our responsibility. */
export function confirmOutboxEntry(convId: string, id: string): void {
  if (hadFiles(convId, id)) void deleteOutboxFiles(id);
  inflightIds.delete(id);
  sessionFiles.delete(id);
  mutateEntries(convId, (entries) => entries.filter((e) => e.id !== id));
}

/** Mark a send as in flight in this page (survives reconciliation as pending). */
export function markOutboxPending(convId: string, id: string): void {
  inflightIds.add(id);
  startHeartbeat();
  // (a retry here takes over a send another, dead, tab left behind)
  mutateEntries(convId, (entries) =>
    entries.map((e) => (e.id === id ? { ...e, status: 'pending' as const, ownerTab: TAB_ID } : e))
  );
}

/** The send failed and is awaiting a manual retry or discard. */
export function markOutboxFailed(convId: string, id: string): void {
  inflightIds.delete(id);
  mutateEntries(convId, (entries) =>
    entries.map((e) => (e.id === id ? { ...e, status: 'failed' as const } : e))
  );
}

/** User discarded the failed message. */
export function removeOutboxEntry(convId: string, id: string): void {
  if (hadFiles(convId, id)) void deleteOutboxFiles(id);
  inflightIds.delete(id);
  sessionFiles.delete(id);
  mutateEntries(convId, (entries) => entries.filter((e) => e.id !== id));
}

/** Render an outbox entry as a client-side message. */
export function outboxEntryToMessage(entry: OutboxEntry): Message {
  const files: FileMetadata[] = entry.files.map((f, i) => ({
    name: f.name,
    type: f.type,
    fileIndex: i,
    previewUrl: f.previewUrl,
  }));
  return {
    id: entry.id,
    role: 'user',
    content: entry.content,
    files: files.length ? files : undefined,
    created_at: entry.createdAt,
    status: entry.status,
    action: entry.action,
  };
}

/**
 * Merge server messages with outstanding outbox entries for this conversation.
 *
 * Entries the server knows about are confirmed and dropped; entries still in
 * flight in this session stay pending; everything else becomes failed. The
 * unconfirmed entries are appended (oldest first) as renderable messages.
 */
export function reconcileOutboxWithServer(convId: string, serverMessages: Message[]): Message[] {
  const entries = readStore()[convId] ?? [];
  if (entries.length === 0) return serverMessages;

  const serverIds = new Set(serverMessages.map((m) => m.id));
  const extras: Message[] = [];

  for (const entry of [...entries].sort((a, b) => a.createdAt.localeCompare(b.createdAt))) {
    if (serverIds.has(entry.id)) {
      confirmOutboxEntry(convId, entry.id);
      continue;
    }
    // Another tab's send in flight: it confirms or fails it itself (marking
    // it failed here showed Retry on a send that was about to land)
    if (isOwnedByLiveTab(entry)) continue;
    if (!inflightIds.has(entry.id) && entry.status !== 'failed') {
      markOutboxFailed(convId, entry.id);
    }
    const current = getOutboxEntry(convId, entry.id);
    if (current) {
      extras.push(outboxEntryToMessage(current));
    }
  }

  if (extras.length) {
    log.info('Reconciled unconfirmed sends', {
      conversationId: convId,
      count: extras.length,
    });
  }
  return [...serverMessages, ...extras];
}
