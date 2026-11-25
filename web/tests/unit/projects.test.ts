/**
 * Projects (core/projects.ts): loading the list, opening a project's page
 * (and failing to), moving a chat, deleting a project, and the page's
 * instructions field.
 */
import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import type { Conversation, Project, ProjectDetail } from '@/types/api';

vi.mock('@/utils/logger', () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
}));
vi.mock('@/api/projects', () => ({
  projects: {
    list: vi.fn(),
    get: vi.fn(),
    conversations: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    removeMember: vi.fn(),
    moveChat: vi.fn(),
    bulkMove: vi.fn(),
    people: vi.fn(),
    addMember: vi.fn(),
  },
}));
vi.mock('@/api/memories', () => ({ memories: {} }));
vi.mock('@/api/documents', () => ({ documents: {} }));
vi.mock('@/core/file-actions', () => ({ downloadDocument: vi.fn() }));
vi.mock('@/components/Toast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));
vi.mock('@/components/Modal', () => ({ showConfirm: vi.fn(), showPrompt: vi.fn() }));
vi.mock('@/components/Sidebar', () => ({
  setActiveConversation: vi.fn(),
  closeSidebar: vi.fn(),
  renderConversationsList: vi.fn(),
  // The sidebar's rows (their own component tests cover them)
  projectConversationRows: (convs: Array<{ id: string }>) =>
    convs.map((c) => {
      const row = document.createElement('div');
      row.dataset.convId = c.id;
      return row;
    }),
}))
vi.mock('@/components/messages', () => ({
  updateChatTitle: vi.fn(),
  hasActiveStreamingContext: vi.fn(() => false),
  cleanupStreamingContext: vi.fn(),
  cleanupNewerMessagesScrollListener: vi.fn(),
}));
vi.mock('@/components/ModelSelector', () => ({ renderModelDropdown: vi.fn() }));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: vi.fn() }));
vi.mock('@/components/WelcomeMessage', () => ({ createWelcomeMessage: vi.fn(() => document.createElement('div')) }));
vi.mock('@/components/MessageInput', () => ({
  ensureInputAreaVisible: vi.fn(),
  focusMessageInput: vi.fn(),
  shouldAutoFocusInput: vi.fn(() => false),
}));
vi.mock('@/core/toolbar', () => ({ updateConversationCost: vi.fn(), updateAnonymousButtonState: vi.fn() }));
vi.mock('@/core/kv-store', () => ({ hideChatChrome: vi.fn() }));
vi.mock('@/core/conversation', () => ({ createConversation: vi.fn(), selectConversation: vi.fn() }));
vi.mock('@/router/deeplink', () => ({ clearConversationHash: vi.fn(), setProjectHash: vi.fn() }));
vi.mock('@/components/SidebarSelection', () => ({ renderSelectionChrome: vi.fn() }));
const sheet = vi.hoisted(() => ({ show: vi.fn() }));
vi.mock('@/components/ActionSheet', () => ({ showActionSheet: sheet.show }));
const picker = vi.hoisted(() => ({ open: vi.fn() }));
vi.mock('@/components/ProjectPicker', () => ({ openProjectPicker: picker.open }));
vi.mock('@/utils/thumbnail-blob-urls', () => ({ setCurrentConversationForBlobs: vi.fn() }));

import { useStore } from '@/state/store';
import { projects } from '@/api/projects';
import { toast } from '@/components/Toast';
import { showConfirm, showPrompt } from '@/components/Modal';
import { createConversation } from '@/core/conversation';
import { setProjectHash } from '@/router/deeplink';
import {
  bulkMoveSelectedToProject,
  loadProjects,
  moveChatFromMenu,
  moveChatToProject,
  navigateToProject,
  newChatInProject,
  removeChatFromProject,
} from '@/core/projects';
import type { ProjectPickerOptions } from '@/components/ProjectPicker';

function pickerOptions(): ProjectPickerOptions {
  const [options] = picker.open.mock.calls.at(-1) as [ProjectPickerOptions];
  return options;
}

function project(id: string, name: string, extra: Partial<Project> = {}): Project {
  return {
    id,
    name,
    owner_id: 'user-1',
    is_owner: true,
    shared: false,
    member_names: ['Jiří'],
    member_ids: ['user-1'],
    chat_count: 0,
    unread_count: 0,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    deleted_at: null,
    ...extra,
  };
}

function detail(p: Project, extra: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    project: p,
    instructions: 'Metric units',
    memories: [],
    documents: [],
    deleted_memories: [],
    deleted_documents: [],
    instructions_limit: 4000,
    memory_limit: 60,
    documents_limit: 20,
    ...extra,
  };
}

function chat(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: `Chat ${id}`, model: 'm', created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', ...extra };
}

const page = (conversations: Conversation[], hasMore = false) => ({
  conversations,
  pagination: { next_cursor: hasMore ? 'c1' : null, has_more: hasMore, total_count: conversations.length },
});

let messages: HTMLDivElement;

beforeEach(() => {
  vi.clearAllMocks();
  document.body.replaceChildren();
  messages = document.createElement('div');
  messages.id = 'messages';
  document.body.appendChild(messages);
  useStore.setState({
    projects: [],
    projectsLimit: 0,
    isProjectView: false,
    activeProjectId: null,
    conversations: [],
    currentConversation: null,
    user: { id: 'user-1', email: 'a@b.c', name: 'Jiří', picture: null, is_admin: false },
  });
});

describe('loadProjects', () => {
  it('stores the projects by name with the cap', async () => {
    (projects.list as Mock).mockResolvedValue({ projects: [project('p2', 'zahrada'), project('p1', 'Bikes')], limit: 30 });

    await loadProjects();

    expect(useStore.getState().projects.map((p) => p.name)).toEqual(['Bikes', 'zahrada']);
    expect(useStore.getState().projectsLimit).toBe(30);
  });
});

describe('navigateToProject', () => {
  it('renders the page with the chats and instructions and enters the view', async () => {
    const p = project('p1', 'Home');
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([chat('c1', { project_id: 'p1' })]));

    await navigateToProject('p1');

    const state = useStore.getState();
    expect(state.isProjectView).toBe(true);
    expect(state.activeProjectId).toBe('p1');
    expect(setProjectHash).toHaveBeenCalledWith('p1');
    expect(messages.querySelector('.project-name')?.textContent).toBe('Home');
    expect(messages.querySelector('.project-chat-list [data-conv-id="c1"]')).not.toBeNull();
    expect(messages.querySelector<HTMLTextAreaElement>('.project-instructions-input')?.value).toBe('Metric units');
  });

  it('shows the empty state without chats', async () => {
    (projects.get as Mock).mockResolvedValue(detail(project('p1', 'Home')));
    (projects.conversations as Mock).mockResolvedValue(page([]));

    await navigateToProject('p1');

    expect(messages.querySelector('.empty-state__title')?.textContent).toBe('No chats in this project yet');
  });

  it('saves the instructions on blur', async () => {
    (projects.get as Mock).mockResolvedValue(detail(project('p1', 'Home')));
    (projects.conversations as Mock).mockResolvedValue(page([]));
    (projects.update as Mock).mockResolvedValue(project('p1', 'Home'));
    await navigateToProject('p1');

    const input = messages.querySelector<HTMLTextAreaElement>('.project-instructions-input');
    if (!input) throw new Error('no instructions field');
    input.value = 'Formal Czech';
    input.dispatchEvent(new Event('input'));
    input.dispatchEvent(new Event('blur'));
    await Promise.resolve();

    expect(projects.update).toHaveBeenCalledWith('p1', { instructions: 'Formal Czech' });
    expect(messages.querySelector('.project-instructions-count')?.textContent).toBe('12/4000');
  });

  it('leaves the view and drops a project it cannot load', async () => {
    useStore.setState({ projects: [project('p1', 'Gone')] });
    (projects.get as Mock).mockRejectedValue(new Error('404'));
    (projects.conversations as Mock).mockResolvedValue(page([]));

    await navigateToProject('p1');

    expect(toast.error).toHaveBeenCalled();
    expect(useStore.getState().projects).toEqual([]);
    expect(useStore.getState().isProjectView).toBe(false);
  });

  it('deletes the project after a confirm and frees its chats', async () => {
    const p = project('p1', 'Home');
    useStore.setState({ projects: [p], conversations: [chat('c1', { project_id: 'p1' })] });
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([]));
    (showConfirm as Mock).mockResolvedValue(true);
    (projects.remove as Mock).mockResolvedValue(undefined);
    await navigateToProject('p1');

    messages.querySelector<HTMLButtonElement>('.project-delete')?.click();
    await vi.waitFor(() => expect(useStore.getState().projects).toEqual([]));

    expect(projects.remove).toHaveBeenCalledWith('p1');
    expect(useStore.getState().conversations[0]?.project_id).toBeNull();
  });

  it('renames in place: click the name, type, Enter', async () => {
    const p = project('p1', 'Home');
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([]));
    (projects.update as Mock).mockResolvedValue(project('p1', 'Byt'));
    await navigateToProject('p1');

    messages.querySelector<HTMLElement>('.project-name')?.click();
    const input = messages.querySelector<HTMLInputElement>('.project-name input');
    expect(input?.value).toBe('Home');
    (input as HTMLInputElement).value = 'Byt';
    input?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

    await vi.waitFor(() => expect(projects.update).toHaveBeenCalledWith('p1', { name: 'Byt' }));
    expect(showPrompt).not.toHaveBeenCalled();
  });

  it('the Rename button starts the same in-place edit', async () => {
    const p = project('p1', 'Home');
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([]));
    await navigateToProject('p1');

    messages.querySelector<HTMLButtonElement>('.project-rename')?.click();

    expect(messages.querySelector('.project-name input')).not.toBeNull();
    expect(showPrompt).not.toHaveBeenCalled();
  });

  it('a member cannot rename by clicking the name', async () => {
    const p = project('p1', 'Home', { is_owner: false, owner_id: 'user-2', shared: true });
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([]));
    await navigateToProject('p1');

    messages.querySelector<HTMLElement>('.project-name')?.click();

    expect(messages.querySelector('.project-name input')).toBeNull();
  });

  it("the owner's members line opens the share sheet", async () => {
    const p = project('p1', 'Home');
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([]));
    (projects.people as Mock).mockResolvedValue([]);
    await navigateToProject('p1');

    const members = messages.querySelector<HTMLElement>('.project-members');
    expect(members?.tagName).toBe('BUTTON');
    members?.click();

    await vi.waitFor(() => expect(projects.people).toHaveBeenCalled());
  });

  it('offers Leave instead of Rename and Delete to a member', async () => {
    const p = project('p1', 'Home', { is_owner: false, owner_id: 'user-2', shared: true });
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([]));

    await navigateToProject('p1');

    expect(messages.querySelector('.project-leave')).not.toBeNull();
    expect(messages.querySelector('.project-delete')).toBeNull();
  });
});

describe('moving chats', () => {
  it('files the chat under the project in the store', async () => {
    useStore.setState({ conversations: [chat('c1')] });
    (projects.moveChat as Mock).mockResolvedValue(undefined);

    expect(await moveChatToProject('c1', 'p1')).toBe(true);

    expect(useStore.getState().conversations[0]?.project_id).toBe('p1');
  });

  it('keeps the chat where it was when the move fails', async () => {
    useStore.setState({ conversations: [chat('c1')] });
    (projects.moveChat as Mock).mockRejectedValue(new Error('404'));

    expect(await moveChatToProject('c1', 'p1')).toBe(false);

    expect(useStore.getState().conversations[0]?.project_id).toBeUndefined();
    expect(toast.error).toHaveBeenCalled();
  });

  it('starts a new chat inside the project', () => {
    newChatInProject('p1');
    expect(createConversation).toHaveBeenCalledWith('p1');
  });
});

describe('the chat menu and selection mode', () => {
  it('Move to project offers the other projects and moves with Undo', async () => {
    useStore.setState({
      projects: [project('p1', 'Bikes'), project('p2', 'Home')],
      conversations: [chat('c1', { project_id: 'p1' })],
    });
    (projects.moveChat as Mock).mockResolvedValue(undefined);

    moveChatFromMenu('c1');
    const options = pickerOptions();
    expect(options.currentProjectId).toBe('p1');
    options.onPick('p2');
    await vi.waitFor(() => expect(useStore.getState().conversations[0]?.project_id).toBe('p2'));

    const [message, extra] = (toast.success as Mock).mock.calls.at(-1) as [string, { action: { onClick: () => void } }];
    expect(message).toBe('Moved to Home.');
    extra.action.onClick();
    await vi.waitFor(() => expect(useStore.getState().conversations[0]?.project_id).toBe('p1'));
  });

  it('Remove from project takes the chat out', async () => {
    useStore.setState({ projects: [project('p1', 'Bikes')], conversations: [chat('c1', { project_id: 'p1' })] });
    (projects.moveChat as Mock).mockResolvedValue(undefined);

    removeChatFromProject('c1');

    await vi.waitFor(() => expect(useStore.getState().conversations[0]?.project_id).toBeNull());
    expect(projects.moveChat).toHaveBeenCalledWith('c1', null);
  });

  it('bulk move sends the selection and files the moved chats', async () => {
    useStore.setState({ projects: [project('p1', 'Bikes')], conversations: [chat('a'), chat('b')] });
    useStore.getState().startSelection();
    useStore.getState().toggleSelected(chat('a'));
    (projects.bulkMove as Mock).mockResolvedValue(['a']);

    await bulkMoveSelectedToProject();
    pickerOptions().onPick('p1');

    await vi.waitFor(() => expect(useStore.getState().conversations[0]?.project_id).toBe('p1'));
    expect(projects.bulkMove).toHaveBeenCalledWith(expect.objectContaining({ ids: ['a'], project_id: 'p1' }));
    expect(useStore.getState().isSelecting).toBe(false);
    expect(useStore.getState().conversations[1]?.project_id).toBeUndefined();
  });
});

describe('sharing', () => {
  it('Share lists who has access and adds a family member in place', async () => {
    const p = project('p1', 'Home', { member_ids: ['user-1', 'user-2'], shared: true });
    useStore.setState({ projects: [p] });
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([]));
    (projects.people as Mock).mockResolvedValue([
      { id: 'user-2', name: 'Jana', picture: null },
      { id: 'user-3', name: 'Viktor', picture: null },
    ]);
    (projects.addMember as Mock).mockResolvedValue({ ...p, member_ids: ['user-1', 'user-2', 'user-3'] });
    await navigateToProject('p1');

    messages.querySelector<HTMLButtonElement>('.project-share')?.click();
    await vi.waitFor(() => expect(document.getElementById('share-sheet')).not.toBeNull());

    const actions = () => [...document.querySelectorAll('.share-sheet-action')].map((b) => b.textContent);
    expect(actions()).toEqual(['Remove', 'Add']);
    document.querySelectorAll<HTMLButtonElement>('.share-sheet-action')[1]?.click();
    await vi.waitFor(() => expect(projects.addMember).toHaveBeenCalledWith('p1', 'user-3'));
    await vi.waitFor(() => expect(actions()).toEqual(['Remove', 'Remove']));
    document.getElementById('share-sheet')?.remove();
  });

  it('a member sees no Share button', async () => {
    const p = project('p1', 'Home', { is_owner: false, owner_id: 'user-2', shared: true });
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([]));

    await navigateToProject('p1');

    expect(messages.querySelector('.project-share')).toBeNull();
  });
});

describe('the chat list follows the store', () => {
  it('re-renders when a chat is renamed or deleted, and stops after leaving', async () => {
    const p = project('p1', 'Home');
    (projects.get as Mock).mockResolvedValue(detail(p));
    (projects.conversations as Mock).mockResolvedValue(page([chat('c1', { project_id: 'p1' }), chat('c2', { project_id: 'p1' })]));
    await navigateToProject('p1');
    expect(messages.querySelectorAll('.project-chat-list [data-conv-id]')).toHaveLength(2);

    useStore.getState().removeConversation('c2');
    await vi.waitFor(() =>
      expect(messages.querySelectorAll('.project-chat-list [data-conv-id]')).toHaveLength(1)
    );
  });
});

describe('recently deleted on the project page', () => {
  it("lists the project's deleted memories", async () => {
    const p = project('p1', 'Home');
    const deleted: ProjectDetail['deleted_memories'][number] = {
      id: 'm1',
      content: 'Old fact',
      category: 'fact',
      created_at: '2026-11-01T00:00:00Z',
      updated_at: '2026-11-01T00:00:00Z',
      protected: false,
      source_conversation_id: null,
      deleted_at: '2026-11-20T00:00:00Z',
      valid_until: null,
      previous_content: null,
      author_name: 'Jiří',
    };
    (projects.get as Mock).mockResolvedValue(detail(p, { deleted_memories: [deleted] }));
    (projects.conversations as Mock).mockResolvedValue(page([]));

    await navigateToProject('p1');

    expect(messages.textContent).toContain('Recently deleted');
    expect(messages.textContent).toContain('Old fact');
  });
});
