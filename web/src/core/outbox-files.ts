/**
 * Attachments of unsent messages, kept in IndexedDB so a retry after a reload
 * resends them. localStorage (the outbox itself) holds a few MB at most, so
 * photos, PDFs and videos only ever lived in memory and were lost when the
 * page reloaded mid-send (iPhone app suspended or killed).
 *
 * Best effort: any IndexedDB failure (private mode, quota, no support) just
 * means the files are not restorable - the retry then warns and sends text.
 */
import type { FileUpload } from '../types/api';
import { createLogger } from '../utils/logger';

const log = createLogger('outbox');

const DB_NAME = 'ai-chatbot-outbox-files';
const STORE = 'files';

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function run<T>(mode: IDBTransactionMode, op: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = op(db.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

/** Keep a message's attachments (blob preview URLs dropped - dead after reload). */
export async function saveOutboxFiles(messageId: string, files: FileUpload[]): Promise<void> {
  try {
    const plain = files.map(({ name, type, data }) => ({ name, type, data }));
    await run('readwrite', (store) => store.put(plain, messageId));
  } catch (error) {
    log.warn('Could not store outbox attachments', { error, messageId });
  }
}

export async function loadOutboxFiles(messageId: string): Promise<FileUpload[] | null> {
  try {
    const files = await run<FileUpload[] | undefined>('readonly', (store) => store.get(messageId));
    return files?.length ? files : null;
  } catch (error) {
    log.warn('Could not read outbox attachments', { error, messageId });
    return null;
  }
}

export async function deleteOutboxFiles(messageId: string): Promise<void> {
  try {
    await run('readwrite', (store) => store.delete(messageId));
  } catch (error) {
    log.warn('Could not delete outbox attachments', { error, messageId });
  }
}
