/**
 * Projects: loading the user's projects, opening a project's page, starting a
 * chat in it, and the page's actions (instructions, memory, documents,
 * rename, delete, leave).
 */
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { projects } from '../api/projects';
import { memories } from '../api/memories';
import { documents } from '../api/documents';
import { downloadDocument } from './file-actions';
import { toast } from '../components/Toast';
import { showConfirm, showPrompt } from '../components/Modal';
import { closeSidebar, renderConversationsList, setActiveConversation } from '../components/Sidebar';
import {
  cleanupNewerMessagesScrollListener,
  cleanupStreamingContext,
  hasActiveStreamingContext,
  updateChatTitle,
} from '../components/messages';
import { renderModelDropdown } from '../components/ModelSelector';
import { renderChatHeader } from '../components/ChatHeader';
import { createWelcomeMessage } from '../components/WelcomeMessage';
import { ensureInputAreaVisible, focusMessageInput, shouldAutoFocusInput } from '../components/MessageInput';
import { getElementById } from '../utils/dom';
import { clearConversationHash, setProjectHash } from '../router/deeplink';
import { setCurrentConversationForBlobs } from '../utils/thumbnail-blob-urls';
import { createConversation } from './conversation';
import { hideChatChrome } from './kv-store';
import { updateAnonymousButtonState, updateConversationCost } from './toolbar';
import { APP_NAME } from '../config';
import type { Conversation, Project, ProjectDetail } from '../types/api';
import type { ProjectChats, ProjectPageCallbacks } from '../components/ProjectPage';

const log = createLogger('projects');

/** The open project page's chats and next-page cursor. */
// UI-local (F2): pagination state of the page on screen
let pageCursor: string | null = null;
let pageChats: Conversation[] = [];

/** Fetch the user's projects into the store and re-render the sidebar. */
export async function loadProjects(): Promise<void> {
  try {
    const data = await projects.list();
    useStore.getState().setProjects(data.projects, data.limit);
    renderConversationsList();
  } catch (error) {
    log.error('Failed to load projects', { error });
  }
}

/** File the store's chats of a gone project back under the main list. */
function releaseChats(projectId: string): void {
  const store = useStore.getState();
  for (const conv of store.conversations.filter((c) => c.project_id === projectId)) {
    store.updateConversation(conv.id, { project_id: null });
  }
}

function getMessagesContainer(): HTMLDivElement | null {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) log.error('Messages container not found');
  return container;
}

/** Leave whatever was on screen for the project page (like the storage view). */
function enterProjectView(projectId: string, title: string): void {
  setCurrentConversationForBlobs('project-loading');
  cleanupNewerMessagesScrollListener();
  if (hasActiveStreamingContext()) {
    cleanupStreamingContext();
  }
  const store = useStore.getState();
  store.setActiveView('project');
  store.setActiveProjectId(projectId);
  setActiveConversation(null);
  setProjectHash(projectId);
  store.setCurrentConversation(null);
  updateChatTitle(title);
  renderModelDropdown();
  void updateConversationCost(null);
  renderChatHeader(null);
  hideChatChrome();
  renderConversationsList();
  closeSidebar();
}

async function loadPage(projectId: string): Promise<{ detail: ProjectDetail; chats: ProjectChats }> {
  const [detail, page] = await Promise.all([projects.get(projectId), projects.conversations(projectId)]);
  pageChats = page.conversations;
  pageCursor = page.pagination.next_cursor ?? null;
  return { detail, chats: { conversations: pageChats, hasMore: page.pagination.has_more } };
}

/** Open a project's page in the main area. */
export async function navigateToProject(projectId: string): Promise<void> {
  log.info('Navigating to project', { projectId });
  const store = useStore.getState();
  const navToken = store.startNavigation();
  const known = store.projects.find((p) => p.id === projectId);
  enterProjectView(projectId, known?.name ?? 'Project');
  const container = getMessagesContainer();
  if (!container) return;
  const { renderProjectPage, renderProjectLoading } = await import('../components/ProjectPage');
  container.replaceChildren(renderProjectLoading());
  let loaded: { detail: ProjectDetail; chats: ProjectChats };
  try {
    loaded = await loadPage(projectId);
  } catch (error) {
    log.error('Failed to load project', { error, projectId });
    if (!useStore.getState().isNavigationValid(navToken)) return;
    toast.error('This project is not available.');
    useStore.getState().removeProject(projectId);
    leaveProjectView();
    return;
  }
  if (!useStore.getState().isNavigationValid(navToken)) return;
  useStore.getState().upsertProject(loaded.detail.project);
  updateChatTitle(loaded.detail.project.name);
  renderConversationsList();
  container.replaceChildren(renderProjectPage(loaded.detail, loaded.chats, pageCallbacks(loaded.detail.project)));
  container.scrollTop = 0;
}

/**
 * Leave the project page for normal chat.
 * @param clearMessages - Whether to show the welcome state (default: true)
 */
export function leaveProjectView(clearMessages: boolean = true): void {
  const store = useStore.getState();
  store.setActiveView('chat');
  store.setActiveProjectId(null);
  ensureInputAreaVisible();
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, store.pendingAnonymousMode);
  }
  renderConversationsList();
  if (!clearMessages) return;
  clearConversationHash();
  store.setCurrentConversation(null);
  updateChatTitle(APP_NAME);
  renderModelDropdown();
  void updateConversationCost(null);
  renderChatHeader(null);
  getElementById<HTMLDivElement>('messages')?.replaceChildren(createWelcomeMessage());
  if (shouldAutoFocusInput()) {
    focusMessageInput();
  }
}

/** Start a chat that is saved into the project with its first message. */
export function newChatInProject(projectId: string): void {
  createConversation(projectId);
}

/** Ask for a name and create a project; returns it, or null when cancelled or refused. */
async function promptNewProject(): Promise<Project | null> {
  const name = (await showPrompt({ title: 'New project', message: 'Name the project', placeholder: 'e.g. Home, Bikes, a client' }))?.trim();
  if (!name) return null;
  try {
    const project = await projects.create({ name });
    useStore.getState().upsertProject(project);
    renderConversationsList();
    return project;
  } catch (error) {
    toast.error(error instanceof Error ? error.message : 'Failed to create the project.');
    return null;
  }
}

/** The sidebar's New project: create it and open its page. */
export async function createProjectAndOpen(): Promise<void> {
  const project = await promptNewProject();
  if (project) await navigateToProject(project.id);
}

async function renameProject(project: Project): Promise<void> {
  const name = (await showPrompt({ title: 'Rename project', message: 'New name', defaultValue: project.name }))?.trim();
  if (!name || name === project.name) return;
  try {
    useStore.getState().upsertProject(await projects.update(project.id, { name }));
    await navigateToProject(project.id);
  } catch {
    toast.error('Failed to rename the project.');
  }
}

async function deleteProject(project: Project): Promise<void> {
  const confirmed = await showConfirm({
    title: 'Delete project?',
    message: 'Its chats go back to your chat list (and the other members\'), and its memory and documents can be restored for 30 days.',
    confirmLabel: 'Delete',
    danger: true,
  });
  if (!confirmed) return;
  try {
    await projects.remove(project.id);
  } catch {
    toast.error('Failed to delete the project.');
    return;
  }
  useStore.getState().removeProject(project.id);
  releaseChats(project.id);
  leaveProjectView();
  toast.success('Project deleted.');
}

async function leaveProject(project: Project): Promise<void> {
  const userId = useStore.getState().user?.id;
  if (!userId) return;
  const confirmed = await showConfirm({
    title: 'Leave project?',
    message: 'Your chats in it go back to your chat list. What you added to its memory stays with the project.',
    confirmLabel: 'Leave',
    danger: true,
  });
  if (!confirmed) return;
  try {
    await projects.removeMember(project.id, userId);
  } catch {
    toast.error('Failed to leave the project.');
    return;
  }
  useStore.getState().removeProject(project.id);
  releaseChats(project.id);
  leaveProjectView();
}

async function loadMoreChats(project: Project): Promise<void> {
  if (!pageCursor) return;
  try {
    const page = await projects.conversations(project.id, pageCursor);
    pageChats = [...pageChats, ...page.conversations];
    pageCursor = page.pagination.next_cursor ?? null;
    const container = getMessagesContainer();
    const detail = await projects.get(project.id);
    const { renderProjectPage } = await import('../components/ProjectPage');
    container?.replaceChildren(
      renderProjectPage(detail, { conversations: pageChats, hasMore: page.pagination.has_more }, pageCallbacks(project))
    );
  } catch (error) {
    log.error('Failed to load more project chats', { error });
  }
}

async function openChat(conversationId: string): Promise<void> {
  const { selectConversation } = await import('./conversation');
  const store = useStore.getState();
  // The chat may not be in the store: project chats are not in the main list pages
  if (!store.conversations.some((c) => c.id === conversationId)) {
    const conv = pageChats.find((c) => c.id === conversationId);
    if (conv) store.addConversation(conv);
  }
  await selectConversation(conversationId);
}

function pageCallbacks(project: Project): ProjectPageCallbacks {
  return {
    onNewChat: () => newChatInProject(project.id),
    onOpenChat: (conversationId) => void openChat(conversationId),
    onLoadMoreChats: () => void loadMoreChats(project),
    onSaveInstructions: async (instructions) => {
      try {
        await projects.update(project.id, { instructions });
      } catch (error) {
        toast.error('Failed to save the instructions.');
        throw error;
      }
    },
    onRename: () => void renameProject(project),
    onDelete: () => void deleteProject(project),
    onLeave: () => void leaveProject(project),
    onDeleteMemory: async (memoryId) => {
      await memories.delete(memoryId);
      toast.success('Memory deleted.');
    },
    onSetMemoryProtected: async (memoryId, isProtected) => {
      await memories.setProtected(memoryId, isProtected);
    },
    onRestoreMemory: async (memoryId) => {
      await memories.restore(memoryId);
    },
    onRestorePreviousMemory: async (memoryId) => memories.restorePrevious(memoryId),
    onDeleteDocument: async (documentId) => {
      await documents.delete(documentId);
      toast.success('Document deleted.');
    },
    onRestoreDocument: async (documentId) => {
      await documents.restore(documentId);
    },
    onDownloadDocument: (documentId, fileName) => void downloadDocument(documentId, fileName),
  };
}

/** Move a chat into a project (or out, with null); the store and sidebar follow. */
export async function moveChatToProject(conversationId: string, projectId: string | null): Promise<boolean> {
  try {
    await projects.moveChat(conversationId, projectId);
  } catch {
    toast.error(projectId ? 'Could not move the chat into the project.' : 'Could not take the chat out of the project.');
    return false;
  }
  useStore.getState().updateConversation(conversationId, { project_id: projectId });
  renderConversationsList();
  return true;
}
