/**
 * Combined Memories & K/V Store management page.
 * Shows memories section first, K/V storage second.
 */

import { clearElement, createElement } from '../utils/dom';
import { createEmptyState } from './EmptyState';
import {
  DELETE_ICON,
  DATABASE_ICON,
  BRAIN_ICON,
  REFRESH_ICON,
  CHEVRON_RIGHT_ICON,
  LOCK_ICON,
  UNLOCK_ICON,
  RESTORE_ICON,
  createIconButton,
  createIconElement,
  setIcon,
  type IconHtml,
} from '../utils/icons';
import type { KVNamespacesResponse, KVKeysResponse, Memory } from '../types/api';
import { showConfirm } from './Modal';

/** A section heading: icon, title and its count. */
function sectionTitle(icon: IconHtml, title: string, count: string): HTMLHeadingElement {
  return createElement('h3', { class: 'kv-store-section-title' }, [
    createIconElement('section-icon', icon),
    ` ${title} `,
    createElement('span', { class: 'kv-store-section-count' }, [count]),
  ]);
}

/**
 * Render loading skeleton for the storage page.
 */
export function renderKVStoreLoading(): HTMLDivElement {
  const container = document.createElement('div');
  container.className = 'kv-store kv-store--loading';
  container.innerHTML = `
    <div class="kv-store-loading">
      <div class="loading-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <p>Loading data...</p>
    </div>
  `;
  return container;
}

/** Callbacks for the storage page */
export interface KVStoreCallbacks {
  onRefresh: () => void;
  onNamespaceExpand: (namespace: string) => Promise<KVKeysResponse>;
  onDeleteKey: (namespace: string, key: string) => Promise<void>;
  onClearNamespace: (namespace: string) => Promise<void>;
  onDeleteMemory: (memoryId: string) => Promise<void>;
  onSetMemoryProtected: (memoryId: string, isProtected: boolean) => Promise<void>;
  onRestoreMemory: (memoryId: string) => Promise<void>;
}

/** Category labels */
const CATEGORY_CONFIG: Record<string, { label: string; class: string }> = {
  preference: { label: 'Preference', class: 'preference' },
  fact: { label: 'Fact', class: 'fact' },
  context: { label: 'Context', class: 'context' },
  goal: { label: 'Goal', class: 'goal' },
};

/**
 * Format relative time (e.g., "2 days ago")
 */
function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);
  const diffWeeks = Math.floor(diffDays / 7);
  const diffMonths = Math.floor(diffDays / 30);

  if (diffMinutes < 1) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffWeeks < 4) return `${diffWeeks}w ago`;
  return `${diffMonths}mo ago`;
}

/**
 * Render the combined data management page.
 */
export function renderKVStorePage(
  kvData: KVNamespacesResponse,
  memories: Memory[],
  callbacks: KVStoreCallbacks,
  options?: { limit?: number; deletedMemories?: Memory[] },
): HTMLDivElement {
  const container = document.createElement('div');
  container.className = 'kv-store';

  // Header
  const header = document.createElement('div');
  header.className = 'kv-store-header';
  const refreshBtn = createElement('button', { class: 'btn-refresh', title: 'Refresh' });
  setIcon(refreshBtn, REFRESH_ICON);
  refreshBtn.append(' Refresh');
  refreshBtn.addEventListener('click', callbacks.onRefresh);
  header.append(
    createElement('div', { class: 'kv-store-title' }, [
      createIconElement('kv-store-icon', DATABASE_ICON),
      createElement('h2', {}, ['Data']),
    ]),
    createElement('div', { class: 'kv-store-header-actions' }, [refreshBtn])
  );
  container.appendChild(header);

  // Memories section
  const memoriesSection = renderMemoriesSection(memories, callbacks, options);
  container.appendChild(memoriesSection);

  // Recently deleted memories, restorable until the nightly purge
  const deleted = options?.deletedMemories ?? [];
  if (deleted.length > 0) {
    container.appendChild(renderDeletedMemoriesSection(deleted, callbacks));
  }

  // K/V Storage section
  const kvSection = renderKVSection(kvData, callbacks);
  container.appendChild(kvSection);

  return container;
}

/**
 * Render the memories section.
 */
function renderMemoriesSection(
  memories: Memory[],
  callbacks: KVStoreCallbacks,
  options?: { limit?: number },
): HTMLDivElement {
  const section = document.createElement('div');
  section.className = 'kv-store-section';

  // The cap comes from the API so the UI never keeps its own copy of it
  const countLabel = options?.limit ? `${memories.length}/${options.limit}` : String(memories.length);

  section.appendChild(sectionTitle(BRAIN_ICON, 'Memories', countLabel));

  if (memories.length === 0) {
    section.appendChild(createEmptyState({
      icon: BRAIN_ICON,
      title: 'No memories yet',
      hint: 'Important things from your conversations are remembered here automatically.',
      compact: true,
    }));
    return section;
  }

  const list = document.createElement('div');
  list.className = 'kv-memories-list';

  for (const memory of memories) {
    list.appendChild(renderMemoryItem(memory, section, list, callbacks));
  }

  section.appendChild(list);
  return section;
}

/**
 * Render one memory row with its protect and delete actions.
 */
function renderMemoryItem(
  memory: Memory,
  section: HTMLDivElement,
  list: HTMLDivElement,
  callbacks: KVStoreCallbacks,
): HTMLDivElement {
  const item = document.createElement('div');
  item.className = 'memory-item';

  const categoryConfig = memory.category ? CATEGORY_CONFIG[memory.category] : null;
  const categoryBadge = (): HTMLElement | null =>
    categoryConfig
      ? createElement('span', { class: `memory-category memory-category--${categoryConfig.class}` }, [
          categoryConfig.label,
        ])
      : null;

  let isProtected = memory.protected === true;

  const renderRow = (): void => {
    const protectTitle = isProtected
      ? 'Protected - the assistant cannot delete this. Click to unprotect.'
      : 'Protect from automatic deletion';
    item.classList.toggle('memory-item--protected', isProtected);
    item.replaceChildren(
      createElement('div', { class: 'memory-content-row' }, [
        createElement('span', { class: 'memory-text' }, [memory.content]),
        createIconButton(
          { class: 'memory-protect', 'aria-pressed': String(isProtected), title: protectTitle },
          isProtected ? LOCK_ICON : UNLOCK_ICON
        ),
        createIconButton({ class: 'memory-delete', title: 'Delete memory' }, DELETE_ICON),
      ]),
      createElement('div', { class: 'memory-meta' }, [
        categoryBadge(),
        isProtected && createElement('span', { class: 'memory-protected-badge' }, ['Protected']),
        createElement('span', { class: 'memory-time' }, [formatRelativeTime(memory.updated_at)]),
      ])
    );
    attachHandlers();
  };

  const updateCount = (): void => {
    const countEl = section.querySelector('.kv-store-section-count');
    if (!countEl) return;
    // Keep the "N/limit" shape when a limit is being shown
    const [, limit] = (countEl.textContent ?? '').split('/');
    countEl.textContent = limit ? `${list.children.length}/${limit}` : String(list.children.length);
  };

  const attachHandlers = (): void => {
    const toggleProtected = async (): Promise<void> => {
      const next = !isProtected;
      try {
        await callbacks.onSetMemoryProtected(memory.id, next);
        isProtected = next;
        renderRow();
      } catch {
        // Error surfaced by the caller
      }
    };
    item.querySelector('.memory-protect')?.addEventListener('click', () => {
      void toggleProtected();
    });

    const deleteMemory = async (): Promise<void> => {
      const confirmed = await showConfirm({
        message: 'Delete this memory?',
        confirmLabel: 'Delete',
        danger: true,
      });
      if (!confirmed) return;
      try {
        await callbacks.onDeleteMemory(memory.id);
        item.remove();
        updateCount();
        if (list.children.length === 0) {
          list.replaceChildren(createEmptyState({ icon: BRAIN_ICON, title: 'No memories remaining', compact: true }));
        }
      } catch {
        // Error handled by caller
      }
    };
    item.querySelector('.memory-delete')?.addEventListener('click', () => {
      void deleteMemory();
    });
  };

  renderRow();
  return item;
}

/**
 * Render recently deleted memories with a restore action.
 *
 * Deletes are soft, and can be made by the assistant as well as the user, so the
 * recovery window needs to be visible somewhere.
 */
function renderDeletedMemoriesSection(
  deletedMemories: Memory[],
  callbacks: KVStoreCallbacks,
): HTMLDivElement {
  const section = document.createElement('div');
  section.className = 'kv-store-section';

  section.appendChild(sectionTitle(RESTORE_ICON, 'Recently deleted', String(deletedMemories.length)));

  const list = document.createElement('div');
  list.className = 'kv-memories-list';

  for (const memory of deletedMemories) {
    const item = document.createElement('div');
    item.className = 'memory-item memory-item--deleted';
    item.append(
      createElement('div', { class: 'memory-content-row' }, [
        createElement('span', { class: 'memory-text' }, [memory.content]),
        createIconButton({ class: 'memory-restore', title: 'Restore this memory' }, RESTORE_ICON),
      ]),
      createElement('div', { class: 'memory-meta' }, [
        createElement('span', { class: 'memory-time' }, [
          `deleted ${memory.deleted_at ? formatRelativeTime(memory.deleted_at) : ''}`,
        ]),
      ])
    );

    const restoreMemory = async (): Promise<void> => {
      try {
        await callbacks.onRestoreMemory(memory.id);
        item.remove();
        const countEl = section.querySelector('.kv-store-section-count');
        if (countEl) countEl.textContent = String(list.children.length);
        if (list.children.length === 0) section.remove();
      } catch {
        // Error handled by caller
      }
    };
    item.querySelector('.memory-restore')?.addEventListener('click', () => {
      void restoreMemory();
    });

    list.appendChild(item);
  }

  section.appendChild(list);
  return section;
}

/**
 * Render the K/V storage section.
 */
function renderKVSection(data: KVNamespacesResponse, callbacks: KVStoreCallbacks): HTMLDivElement {
  const section = document.createElement('div');
  section.className = 'kv-store-section';

  section.appendChild(sectionTitle(DATABASE_ICON, 'Key-Value Storage', String(data.namespaces.length)));

  if (data.namespaces.length === 0) {
    section.appendChild(createEmptyState({
      icon: DATABASE_ICON,
      title: 'No stored data',
      hint: 'Data appears here when agents store key-value pairs.',
      compact: true,
    }));
    return section;
  }

  const list = document.createElement('div');
  list.className = 'kv-store-namespaces';

  for (const ns of data.namespaces) {
    const card = createNamespaceCard(ns.namespace, ns.key_count, callbacks);
    list.appendChild(card);
  }

  section.appendChild(list);
  return section;
}

/**
 * Create a namespace card with expand/collapse functionality.
 */
function createNamespaceCard(
  namespace: string,
  keyCount: number,
  callbacks: KVStoreCallbacks,
): HTMLDivElement {
  const card = document.createElement('div');
  card.className = 'kv-namespace-card';

  const header = document.createElement('div');
  header.className = 'kv-namespace-header';
  const clearBtn = createElement('button', { class: 'btn-clear-namespace', title: 'Clear all keys in namespace' });
  setIcon(clearBtn, DELETE_ICON);
  header.append(
    createElement('div', { class: 'kv-namespace-title-row' }, [
      createIconElement('kv-namespace-chevron', CHEVRON_RIGHT_ICON),
      createElement('span', { class: 'kv-namespace-name' }, [namespace]),
      createElement('span', { class: 'kv-namespace-count' }, [`${keyCount} ${keyCount === 1 ? 'key' : 'keys'}`]),
    ]),
    createElement('div', { class: 'kv-namespace-actions' }, [clearBtn])
  );

  const body = document.createElement('div');
  body.className = 'kv-namespace-body collapsed';

  let isExpanded = false;
  let isLoading = false;

  const toggleExpanded = async (): Promise<void> => {
    if (isLoading) return;

    isExpanded = !isExpanded;
    card.classList.toggle('expanded', isExpanded);

    if (isExpanded) {
      body.classList.remove('collapsed');
      isLoading = true;
      body.innerHTML = `
        <div class="kv-keys-loading">
          <div class="loading-dots"><span></span><span></span><span></span></div>
        </div>
      `;

      try {
        const keysData = await callbacks.onNamespaceExpand(namespace);
        clearElement(body);
        renderKeysInBody(body, namespace, keysData, callbacks);
      } catch {
        body.innerHTML = '<div class="kv-keys-error">Failed to load keys</div>';
      } finally {
        isLoading = false;
      }
    } else {
      body.classList.add('collapsed');
      clearElement(body);
    }
  };
  header.querySelector('.kv-namespace-title-row')?.addEventListener('click', () => {
    void toggleExpanded();
  });

  const clearNamespace = async (): Promise<void> => {
    const confirmed = await showConfirm({ message: `Delete all keys in "${namespace}"?`, confirmLabel: 'Clear All', danger: true });
    if (!confirmed) return;

    try {
      await callbacks.onClearNamespace(namespace);
      card.remove();
    } catch {
      // Error handled by caller
    }
  };
  header.querySelector('.btn-clear-namespace')?.addEventListener('click', (e) => {
    e.stopPropagation();
    void clearNamespace();
  });

  card.appendChild(header);
  card.appendChild(body);
  return card;
}

// JSON token classes, applied in this order to the text (a later pass also
// splits the text inside earlier tokens: a number inside a string is colored)
const JSON_TOKENS: [RegExp, string][] = [
  // Strings (including keys in "key": patterns)
  [/"([^"\\]*(\\.[^"\\]*)*)"/g, 'json-string'],
  [/\b(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b/g, 'json-number'],
  // Booleans and null
  [/\b(true|false|null)\b/g, 'json-keyword'],
];

/** Wrap each match of `pattern` in the text nodes under `root` in a span of `className`. */
function wrapMatches(root: Node, pattern: RegExp, className: string): void {
  for (const child of [...root.childNodes]) {
    if (child.nodeType !== Node.TEXT_NODE) {
      wrapMatches(child, pattern, className);
      continue;
    }
    const text = child.textContent ?? '';
    const parts: (Node | string)[] = [];
    let last = 0;
    for (const match of text.matchAll(pattern)) {
      parts.push(text.slice(last, match.index), createElement('span', { class: className }, [match[0]]));
      last = match.index + match[0].length;
    }
    if (last === 0) continue;
    parts.push(text.slice(last));
    (child as Text).replaceWith(...parts.filter((part) => part !== ''));
  }
}

/**
 * Syntax-highlight a JSON string with colored spans (pretty-printed); text
 * that isn't JSON stays as it is.
 */
function highlightJson(jsonString: string): HTMLPreElement {
  const pre = createElement('pre', { class: 'kv-key-value' });
  try {
    pre.textContent = JSON.stringify(JSON.parse(jsonString), null, 2);
  } catch {
    pre.textContent = jsonString;
    return pre;
  }
  for (const [pattern, className] of JSON_TOKENS) wrapMatches(pre, pattern, className);
  return pre;
}

/**
 * Render keys inside a namespace body.
 */
function renderKeysInBody(
  body: HTMLDivElement,
  namespace: string,
  keysData: KVKeysResponse,
  callbacks: KVStoreCallbacks,
): void {
  if (keysData.keys.length === 0) {
    body.innerHTML = '<div class="kv-keys-empty">No keys in this namespace</div>';
    return;
  }

  const keysList = document.createElement('div');
  keysList.className = 'kv-keys-list';

  for (const entry of keysData.keys) {
    const keyRow = document.createElement('div');
    keyRow.className = 'kv-key-row';

    const highlighted = highlightJson(entry.value);
    const lineCount = (highlighted.textContent ?? '').split('\n').length;
    const isLong = lineCount > 6;

    keyRow.append(
      createElement('div', { class: 'kv-key-info' }, [
        createElement('div', { class: 'kv-key-header' }, [
          createElement('span', { class: 'kv-key-name' }, [entry.key]),
          createIconButton({ class: 'kv-key-delete', title: 'Delete key' }, DELETE_ICON),
        ]),
        createElement('div', { class: `kv-key-value-wrapper${isLong ? ' collapsed' : ''}` }, [
          highlighted,
          isLong && createElement('div', { class: 'kv-key-value-fade' }),
        ]),
        isLong && createElement('button', { class: 'kv-key-expand' }, [`Show all ${lineCount} lines`]),
      ])
    );

    const deleteKey = async (): Promise<void> => {
      try {
        await callbacks.onDeleteKey(namespace, entry.key);
        keyRow.remove();
        if (keysList.children.length === 0) {
          body.innerHTML = '<div class="kv-keys-empty">No keys in this namespace</div>';
        }
      } catch {
        // Error handled by caller
      }
    };
    keyRow.querySelector('.kv-key-delete')?.addEventListener('click', () => {
      void deleteKey();
    });

    const expandBtn = keyRow.querySelector('.kv-key-expand');
    if (expandBtn) {
      expandBtn.addEventListener('click', () => {
        const wrapper = keyRow.querySelector('.kv-key-value-wrapper');
        if (!wrapper) return;
        const isCollapsed = wrapper.classList.contains('collapsed');
        wrapper.classList.toggle('collapsed', !isCollapsed);
        expandBtn.textContent = isCollapsed ? 'Show less' : `Show all ${lineCount} lines`;
      });
    }

    keysList.appendChild(keyRow);
  }

  body.appendChild(keysList);
}
