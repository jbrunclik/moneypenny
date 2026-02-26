/**
 * Combined Memories & K/V Store management page.
 * Shows memories section first, K/V storage second.
 */

import { escapeHtml, clearElement } from '../utils/dom';
import { DELETE_ICON, DATABASE_ICON, BRAIN_ICON, REFRESH_ICON, CHEVRON_RIGHT_ICON } from '../utils/icons';
import type { KVNamespacesResponse, KVKeysResponse, Memory } from '../types/api';
import { showConfirm } from './Modal';

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
): HTMLDivElement {
  const container = document.createElement('div');
  container.className = 'kv-store';

  // Header
  const header = document.createElement('div');
  header.className = 'kv-store-header';
  header.innerHTML = `
    <div class="kv-store-title">
      <span class="kv-store-icon">${DATABASE_ICON}</span>
      <h2>Data</h2>
    </div>
    <div class="kv-store-header-actions">
      <button class="btn-refresh" title="Refresh">${REFRESH_ICON} Refresh</button>
    </div>
  `;
  header.querySelector('.btn-refresh')?.addEventListener('click', callbacks.onRefresh);
  container.appendChild(header);

  // Memories section
  const memoriesSection = renderMemoriesSection(memories, callbacks);
  container.appendChild(memoriesSection);

  // K/V Storage section
  const kvSection = renderKVSection(kvData, callbacks);
  container.appendChild(kvSection);

  return container;
}

/**
 * Render the memories section.
 */
function renderMemoriesSection(memories: Memory[], callbacks: KVStoreCallbacks): HTMLDivElement {
  const section = document.createElement('div');
  section.className = 'kv-store-section';

  const title = document.createElement('h3');
  title.className = 'kv-store-section-title';
  title.innerHTML = `<span class="section-icon">${BRAIN_ICON}</span> Memories <span class="kv-store-section-count">${memories.length}</span>`;
  section.appendChild(title);

  if (memories.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'kv-store-section-empty';
    empty.innerHTML = '<p>No memories yet. The AI will automatically remember important things from your conversations.</p>';
    section.appendChild(empty);
    return section;
  }

  const list = document.createElement('div');
  list.className = 'kv-memories-list';

  for (const memory of memories) {
    const item = document.createElement('div');
    item.className = 'memory-item';

    const categoryConfig = memory.category ? CATEGORY_CONFIG[memory.category] : null;
    const categoryBadge = categoryConfig
      ? `<span class="memory-category memory-category--${categoryConfig.class}">${categoryConfig.label}</span>`
      : '';

    item.innerHTML = `
      <div class="memory-content-row">
        <span class="memory-text">${escapeHtml(memory.content)}</span>
        <button class="memory-delete" title="Delete memory">${DELETE_ICON}</button>
      </div>
      <div class="memory-meta">
        ${categoryBadge}
        <span class="memory-time">${formatRelativeTime(memory.updated_at)}</span>
      </div>
    `;

    item.querySelector('.memory-delete')?.addEventListener('click', async () => {
      const confirmed = await showConfirm({ message: 'Delete this memory?', confirmLabel: 'Delete', danger: true });
      if (!confirmed) return;
      try {
        await callbacks.onDeleteMemory(memory.id);
        item.remove();
        // Update count
        const countEl = section.querySelector('.kv-store-section-count');
        if (countEl) {
          const remaining = list.children.length;
          countEl.textContent = String(remaining);
        }
        if (list.children.length === 0) {
          list.innerHTML = '<div class="kv-store-section-empty"><p>No memories remaining.</p></div>';
        }
      } catch {
        // Error handled by caller
      }
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

  const title = document.createElement('h3');
  title.className = 'kv-store-section-title';
  title.innerHTML = `<span class="section-icon">${DATABASE_ICON}</span> Key-Value Storage <span class="kv-store-section-count">${data.namespaces.length}</span>`;
  section.appendChild(title);

  if (data.namespaces.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'kv-store-section-empty';
    empty.innerHTML = '<p>No stored data. Data will appear here when agents store key-value pairs.</p>';
    section.appendChild(empty);
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
  header.innerHTML = `
    <div class="kv-namespace-title-row">
      <span class="kv-namespace-chevron">${CHEVRON_RIGHT_ICON}</span>
      <span class="kv-namespace-name">${escapeHtml(namespace)}</span>
      <span class="kv-namespace-count">${keyCount} ${keyCount === 1 ? 'key' : 'keys'}</span>
    </div>
    <div class="kv-namespace-actions">
      <button class="btn-clear-namespace" title="Clear all keys in namespace">${DELETE_ICON}</button>
    </div>
  `;

  const body = document.createElement('div');
  body.className = 'kv-namespace-body collapsed';

  let isExpanded = false;
  let isLoading = false;

  header.querySelector('.kv-namespace-title-row')?.addEventListener('click', async () => {
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
  });

  header.querySelector('.btn-clear-namespace')?.addEventListener('click', async (e) => {
    e.stopPropagation();
    const confirmed = await showConfirm({ message: `Delete all keys in "${namespace}"?`, confirmLabel: 'Clear All', danger: true });
    if (!confirmed) return;

    try {
      await callbacks.onClearNamespace(namespace);
      card.remove();
    } catch {
      // Error handled by caller
    }
  });

  card.appendChild(header);
  card.appendChild(body);
  return card;
}

/**
 * Syntax-highlight a JSON string with colored spans.
 */
function highlightJson(jsonString: string): string {
  try {
    const parsed = JSON.parse(jsonString);
    const formatted = JSON.stringify(parsed, null, 2);
    return formatted
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      // Strings (including keys in "key": patterns)
      .replace(/"([^"\\]*(\\.[^"\\]*)*)"/g, '<span class="json-string">"$1"</span>')
      // Numbers
      .replace(/\b(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b/g, '<span class="json-number">$1</span>')
      // Booleans and null
      .replace(/\b(true|false|null)\b/g, '<span class="json-keyword">$1</span>');
  } catch {
    return escapeHtml(jsonString);
  }
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

    keyRow.innerHTML = `
      <div class="kv-key-info">
        <span class="kv-key-name">${escapeHtml(entry.key)}</span>
        <pre class="kv-key-value">${highlightJson(entry.value)}</pre>
      </div>
      <button class="kv-key-delete" title="Delete key">${DELETE_ICON}</button>
    `;

    keyRow.querySelector('.kv-key-delete')?.addEventListener('click', async () => {
      try {
        await callbacks.onDeleteKey(namespace, entry.key);
        keyRow.remove();
        if (keysList.children.length === 0) {
          body.innerHTML = '<div class="kv-keys-empty">No keys in this namespace</div>';
        }
      } catch {
        // Error handled by caller
      }
    });

    keysList.appendChild(keyRow);
  }

  body.appendChild(keysList);
}
