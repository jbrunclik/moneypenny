/**
 * A project's page: its name and members, a button that starts a chat in it,
 * the user's own chats in it, the project instructions, memory and documents.
 */
import { createElement } from '../utils/dom';
import {
  BRAIN_ICON,
  DELETE_ICON,
  EDIT_ICON,
  FOLDER_ICON,
  HISTORY_ICON,
  LOGOUT_ICON,
  PLUS_ICON,
  USERS_ICON,
  createIconElement,
  iconNodes,
} from '../utils/icons';
import { projectConversationRows } from './Sidebar';
import { startInlineRename } from './inline-rename';
import type { Conversation, DocumentsResponse, ProjectDetail } from '../types/api';
import { createEmptyState } from './EmptyState';
import { renderDocumentsSections, type DocumentCallbacks } from './kv-documents';
import { sectionTitle } from './kv-store-parts';
import { renderDeletedMemoriesSection, renderMemoriesSection, type MemoryCallbacks } from './KVStorePage';

/** What the project page can do (errors are surfaced by the caller). */
export interface ProjectPageCallbacks extends MemoryCallbacks, DocumentCallbacks {
  onNewChat: () => void;
  onLoadMoreChats: () => void;
  onSaveInstructions: (instructions: string) => Promise<void>;
  /** The owner renamed the project in place */
  onRename: (name: string) => void;
  onShare: () => void;
  onDelete: () => void;
  onLeave: () => void;
}

/** The user's chats in the project, a page at a time. */
export interface ProjectChats {
  conversations: Conversation[];
  hasMore: boolean;
}

export function renderProjectLoading(): HTMLDivElement {
  return createElement('div', { class: 'kv-store project-page' }, [
    createElement('div', { class: 'kv-store-loading' }, [
      createElement('div', { class: 'loading-spinner' }),
      createElement('p', {}, ['Loading project...']),
    ]),
  ]);
}

function membersLine(detail: ProjectDetail): string {
  const { project } = detail;
  if (!project.shared) return 'Only you';
  return `Shared: ${project.member_names.join(', ')}`;
}

/** The name: the owner renames it in place (a click, or the Rename button), like a chat title. */
function renderName(detail: ProjectDetail, callbacks: ProjectPageCallbacks): HTMLHeadingElement {
  const name = createElement('h2', { class: 'project-name' }, [detail.project.name]);
  if (detail.project.is_owner) {
    name.classList.add('renameable');
    name.title = 'Rename project';
    name.addEventListener('click', () => startInlineRename(name, callbacks.onRename, 'project-name-input'));
  }
  return name;
}

/** Who has access; for the owner a button that opens the share sheet. */
function renderMembers(detail: ProjectDetail, callbacks: ProjectPageCallbacks): HTMLElement {
  if (!detail.project.is_owner) {
    return createElement('span', { class: 'project-members' }, [membersLine(detail)]);
  }
  const members = createElement('button', { type: 'button', class: 'project-members project-members-btn', title: 'Share' }, [
    membersLine(detail),
  ]);
  members.addEventListener('click', callbacks.onShare);
  return members;
}

function renderHeader(detail: ProjectDetail, callbacks: ProjectPageCallbacks): HTMLDivElement {
  const { project } = detail;
  const actions: HTMLElement[] = [];
  const name = renderName(detail, callbacks);
  if (project.is_owner) {
    const rename = createElement('button', { type: 'button', class: 'btn-refresh project-rename' }, [
      iconNodes(EDIT_ICON),
      'Rename',
    ]);
    rename.addEventListener('click', () => startInlineRename(name, callbacks.onRename, 'project-name-input'));
    const share = createElement('button', { type: 'button', class: 'btn-refresh project-share' }, [
      iconNodes(USERS_ICON),
      'Share',
    ]);
    share.addEventListener('click', callbacks.onShare);
    const remove = createElement('button', { type: 'button', class: 'btn-refresh project-delete' }, [
      iconNodes(DELETE_ICON),
      'Delete',
    ]);
    remove.addEventListener('click', callbacks.onDelete);
    actions.push(share, rename, remove);
  } else {
    const leave = createElement('button', { type: 'button', class: 'btn-refresh project-leave' }, [
      iconNodes(LOGOUT_ICON),
      'Leave',
    ]);
    leave.addEventListener('click', callbacks.onLeave);
    actions.push(leave);
  }
  return createElement('div', { class: 'kv-store-header project-header' }, [
    createElement('div', { class: 'kv-store-title' }, [
      createIconElement('kv-store-icon', FOLDER_ICON),
      createElement('div', { class: 'project-title-block' }, [
        name,
        renderMembers(detail, callbacks),
      ]),
    ]),
    createElement('div', { class: 'kv-store-header-actions' }, actions),
  ]);
}

/** The "Your chats" section (re-rendered alone when the store's chats change). */
export function renderProjectChats(chats: ProjectChats, callbacks: ProjectPageCallbacks): HTMLDivElement {
  const newChat = createElement('button', { type: 'button', class: 'btn btn-primary btn-sm project-new-chat' }, [
    iconNodes(PLUS_ICON),
    'New chat in this project',
  ]);
  newChat.addEventListener('click', callbacks.onNewChat);
  const section = createElement('div', { class: 'kv-store-section project-chats' }, [
    sectionTitle(HISTORY_ICON, 'Your chats', String(chats.conversations.length)),
    newChat,
  ]);
  if (chats.conversations.length === 0) {
    section.appendChild(
      createEmptyState({
        icon: FOLDER_ICON,
        title: 'No chats in this project yet',
        hint: 'Start one here, or move a chat in from its menu.',
        compact: true,
      })
    );
    return section;
  }
  // The sidebar's own rows: same look, actions, swipe (core/events, gestures)
  const list = createElement('div', { class: 'project-chat-list' }, projectConversationRows(chats.conversations));
  section.appendChild(list);
  if (chats.hasMore) {
    const more = createElement('button', { type: 'button', class: 'btn btn-secondary btn-sm project-more-chats' }, [
      'Show more',
    ]);
    more.addEventListener('click', callbacks.onLoadMoreChats);
    section.appendChild(more);
  }
  return section;
}

function countClass(count: number, limit: number): string {
  if (count > limit) return 'error';
  return count > limit * 0.9 ? 'warning' : '';
}

function renderInstructionsSection(detail: ProjectDetail, callbacks: ProjectPageCallbacks): HTMLDivElement {
  const limit = detail.instructions_limit;
  const textarea = createElement('textarea', {
    class: 'settings-textarea project-instructions-input',
    placeholder: 'How the assistant should work in this project (tone, units, what to keep in mind)...',
    maxlength: String(limit),
    'aria-label': 'Project instructions',
  });
  textarea.value = detail.instructions;
  const count = createElement('span', { class: 'settings-char-count project-instructions-count' }, [
    `${detail.instructions.length}/${limit}`,
  ]);
  const saved = createElement('span', { class: 'project-instructions-saved' }, ['']);
  let lastSaved = detail.instructions;
  textarea.addEventListener('input', () => {
    count.textContent = `${textarea.value.length}/${limit}`;
    count.className = `settings-char-count project-instructions-count ${countClass(textarea.value.length, limit)}`;
  });
  textarea.addEventListener('blur', () => {
    const text = textarea.value;
    if (text === lastSaved) return;
    void callbacks
      .onSaveInstructions(text)
      .then(() => {
        lastSaved = text;
        saved.textContent = 'Saved';
      })
      .catch(() => {
        saved.textContent = '';
      });
  });
  return createElement('div', { class: 'kv-store-section project-instructions' }, [
    sectionTitle(EDIT_ICON, 'Instructions', ''),
    textarea,
    createElement('div', { class: 'project-instructions-footer' }, [saved, count]),
  ]);
}

function documentsData(detail: ProjectDetail): DocumentsResponse {
  return {
    documents: detail.documents,
    deleted: detail.deleted_documents,
    limit: detail.documents_limit,
    bytes_used: 0,
    bytes_limit: 0,
  };
}

/** The whole project page. */
export function renderProjectPage(
  detail: ProjectDetail,
  chats: ProjectChats,
  callbacks: ProjectPageCallbacks
): HTMLDivElement {
  const authors = detail.project.shared
    ? new Map(detail.memories.map((m) => [m.id, m.author_name ?? '']))
    : undefined;
  const memories = renderMemoriesSection(detail.memories, callbacks, {
    limit: detail.memory_limit,
    emptyHint: "What the assistant learns in this project's chats is kept here, for every chat in it.",
    authors,
  });
  memories.classList.add('project-memory');
  memories.querySelector('.kv-store-section-title')?.replaceWith(
    sectionTitle(BRAIN_ICON, 'Project memory', `${detail.memories.length}/${detail.memory_limit}`)
  );
  const deletedMemories = detail.deleted_memories.length
    ? [renderDeletedMemoriesSection(detail.deleted_memories, callbacks)]
    : [];
  return createElement('div', { class: 'kv-store project-page', 'data-project-id': detail.project.id }, [
    renderHeader(detail, callbacks),
    renderProjectChats(chats, callbacks),
    renderInstructionsSection(detail, callbacks),
    memories,
    ...deletedMemories,
    ...renderDocumentsSections(documentsData(detail), callbacks),
  ]);
}
