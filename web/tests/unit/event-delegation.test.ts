/**
 * setupEventListeners: delegated clicks in the sidebar list, the messages
 * list and the user menu reach the right action (a failed menu action
 * surfaces as a toast), the touch action sheet offers the actions that fit
 * the conversation, and the conversation list's roving tabindex moves
 * without wrapping.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const m = vi.hoisted(() => ({
  createConversation: vi.fn(),
  selectConversation: vi.fn(),
  deleteConversation: vi.fn(),
  renameConversation: vi.fn(),
  togglePinConversation: vi.fn(),
  archiveConversation: vi.fn(),
  unarchiveConversation: vi.fn(),
  navigateToArchive: vi.fn(),
  leaveArchiveView: vi.fn(),
  restoreConversation: vi.fn(),
  deleteConversationForever: vi.fn(),
  emptyTrash: vi.fn(),
  navigateToTrash: vi.fn(),
  leaveTrashView: vi.fn(),
  enterSelectionMode: vi.fn(),
  navigateToPlanner: vi.fn(),
  navigateToAgents: vi.fn(() => Promise.resolve()),
  navigateToSports: vi.fn(),
  navigateToLanguage: vi.fn(),
  navigateToStorage: vi.fn(() => Promise.resolve()),
  openFileInNewTab: vi.fn(),
  downloadFile: vi.fn(),
  copyMessageContent: vi.fn(),
  copyInlineContent: vi.fn(),
  handleQuizOptionClick: vi.fn(),
  handleQuizContinue: vi.fn(),
  handleQuizInputChange: vi.fn(),
  resetSwipeStates: vi.fn(),
  showActionSheet: vi.fn(),
  logout: vi.fn(),
  getCostHistory: vi.fn(),
  openCostHistory: vi.fn(),
  toggleSidebar: vi.fn(),
  toastError: vi.fn(),
  openAdminPage: vi.fn<() => Promise<void>>(),
  openSettingsPopup: vi.fn(),
  openPdfViewer: vi.fn(),
}));

vi.mock('@/api/costs', () => ({ costs: { getCostHistory: m.getCostHistory } }));
vi.mock('@/components/Toast', () => ({ toast: { error: m.toastError } }));
vi.mock('@/components/CostHistoryPopup', () => ({ openCostHistory: m.openCostHistory }));
vi.mock('@/auth/google', () => ({ logout: m.logout }));
vi.mock('@/components/Sidebar', () => ({ toggleSidebar: m.toggleSidebar }));
vi.mock('@/gestures/swipe', () => ({ resetSwipeStates: m.resetSwipeStates }));
vi.mock('@/components/ActionSheet', () => ({ showActionSheet: m.showActionSheet }));
vi.mock('@/core/conversation', () => ({
  createConversation: m.createConversation,
  selectConversation: m.selectConversation,
}));
vi.mock('@/core/conversation-actions', () => ({
  deleteConversation: m.deleteConversation,
  renameConversation: m.renameConversation,
  togglePinConversation: m.togglePinConversation,
}));
vi.mock('@/core/archive', () => ({
  archiveConversation: m.archiveConversation,
  unarchiveConversation: m.unarchiveConversation,
  navigateToArchive: m.navigateToArchive,
  leaveArchiveView: m.leaveArchiveView,
}));
vi.mock('@/core/trash', () => ({
  restoreConversation: m.restoreConversation,
  deleteConversationForever: m.deleteConversationForever,
  emptyTrash: m.emptyTrash,
  navigateToTrash: m.navigateToTrash,
  leaveTrashView: m.leaveTrashView,
}));
vi.mock('@/components/SidebarSelection', () => ({ enterSelectionMode: m.enterSelectionMode }));
vi.mock('@/core/planner', () => ({ navigateToPlanner: m.navigateToPlanner }));
vi.mock('@/core/agents', () => ({ navigateToAgents: m.navigateToAgents }));
vi.mock('@/core/sports', () => ({ navigateToSports: m.navigateToSports }));
vi.mock('@/core/language', () => ({ navigateToLanguage: m.navigateToLanguage }));
vi.mock('@/core/kv-store', () => ({ navigateToStorage: m.navigateToStorage }));
vi.mock('@/core/file-actions', () => ({
  openFileInNewTab: m.openFileInNewTab,
  downloadFile: m.downloadFile,
  copyMessageContent: m.copyMessageContent,
  copyInlineContent: m.copyInlineContent,
}));
vi.mock('@/components/AdminPage', () => ({ openAdminPage: m.openAdminPage }));
vi.mock('@/components/SettingsPopup', () => ({ openSettingsPopup: m.openSettingsPopup }));
vi.mock('@/components/PdfViewer', () => ({ openPdfViewer: m.openPdfViewer }));
vi.mock('@/components/QuizBlock', () => ({
  handleQuizOptionClick: m.handleQuizOptionClick,
  handleQuizContinue: m.handleQuizContinue,
  handleQuizInputChange: m.handleQuizInputChange,
}));

import { useStore } from '@/state/store';
import { nextRovingIndex, setupEventListeners } from '@/core/events';

function click(el: Element): MouseEvent {
  const event = new MouseEvent('click', { bubbles: true, cancelable: true });
  el.dispatchEvent(event);
  return event;
}

function el(html: string): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host.firstElementChild as HTMLElement;
}

describe('setupEventListeners', () => {
  let list: HTMLElement;
  let messages: HTMLElement;
  let userInfo: HTMLElement;
  let rowClicks: number;

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `<main id="root">
      <button id="new-chat-btn"></button>
      <button id="menu-btn"></button>
      <div id="conversations-list"></div>
      <div id="messages"></div>
      <div id="user-info">
        <button id="user-menu-btn" aria-expanded="false"></button>
        <div class="user-menu hidden"></div>
      </div></main>`;
    list = document.getElementById('conversations-list') as HTMLElement;
    messages = document.getElementById('messages') as HTMLElement;
    userInfo = document.getElementById('user-info') as HTMLElement;
    rowClicks = 0;
    document.getElementById('root')?.addEventListener('click', () => rowClicks++);
    setupEventListeners();
  });

  describe('conversation list clicks', () => {
    it.each([
      ['data-rename-id', m.renameConversation],
      ['data-archive-id', m.archiveConversation],
      ['data-unarchive-id', m.unarchiveConversation],
      ['data-restore-id', m.restoreConversation],
      ['data-delete-forever-id', m.deleteConversationForever],
      ['data-delete-id', m.deleteConversation],
    ])('%s closes swipes, acts on the id and stops the click', (attr, action) => {
      const btn = list.appendChild(el(`<button ${attr}="c1"></button>`));
      click(btn);
      expect(m.resetSwipeStates).toHaveBeenCalled();
      expect(action).toHaveBeenCalledWith('c1');
      expect(rowClicks).toBe(0);
    });

    it('pins without closing swipes', () => {
      click(list.appendChild(el('<button data-pin-id="c1"></button>')));
      expect(m.togglePinConversation).toHaveBeenCalledWith('c1');
      expect(m.resetSwipeStates).not.toHaveBeenCalled();
    });

    it('opens the action sheet for a conversation and an archived one', () => {
      useStore.setState({
        conversations: [{ id: 'c1', title: 'Chat', model: 'm', created_at: '', updated_at: '' }],
        archivedConversations: [],
      });
      click(list.appendChild(el('<button data-more-id="c1"></button>')));
      expect(m.showActionSheet).toHaveBeenLastCalledWith('Chat', expect.any(Array));
      const labels = (m.showActionSheet.mock.lastCall?.[1] as { label: string }[]).map((a) => a.label);
      expect(labels).toEqual(['Pin', 'Rename', 'Archive', 'Delete']);

      click(list.appendChild(el('<button data-more-archived-id="z1"></button>')));
      const archived = (m.showActionSheet.mock.lastCall?.[1] as { label: string }[]).map((a) => a.label);
      expect(m.showActionSheet).toHaveBeenLastCalledWith('Conversation', expect.any(Array));
      expect(archived).toEqual(['Rename', 'Unarchive', 'Delete']);
    });

    it('runs the trash and archive view controls', () => {
      click(list.appendChild(el('<button data-empty-trash></button>')));
      click(list.appendChild(el('<button data-trash-back></button>')));
      click(list.appendChild(el('<button data-archive-back></button>')));
      expect(m.emptyTrash).toHaveBeenCalled();
      expect(m.leaveTrashView).toHaveBeenCalled();
      expect(m.leaveArchiveView).toHaveBeenCalled();
      expect(rowClicks).toBe(0);
    });

    it.each([
      ['planner-entry', m.navigateToPlanner],
      ['agents-entry', m.navigateToAgents],
      ['sports-entry', m.navigateToSports],
      ['language-entry', m.navigateToLanguage],
    ])('the %s opens its view and lets the click through', (cls, open) => {
      click(list.appendChild(el(`<div class="${cls}"><span>x</span></div>`)).firstElementChild as Element);
      expect(m.resetSwipeStates).toHaveBeenCalled();
      expect(open).toHaveBeenCalled();
      expect(rowClicks).toBe(1);
    });

    it('selects a conversation row, with a row button taking precedence', () => {
      const row = list.appendChild(
        el('<div data-conv-id="c7"><div class="conversation-item"><button data-delete-id="c7"></button></div></div>')
      );
      click(row.querySelector('.conversation-item') as Element);
      expect(m.selectConversation).toHaveBeenCalledWith('c7');

      m.selectConversation.mockClear();
      click(row.querySelector('[data-delete-id]') as Element);
      expect(m.deleteConversation).toHaveBeenCalledWith('c7');
      expect(m.selectConversation).not.toHaveBeenCalled();
    });
  });

  describe('messages list clicks', () => {
    it('opens a PDF in the viewer path and other documents in a new tab', async () => {
      const doc = messages.appendChild(
        el('<a class="document-preview" data-message-id="m1" data-file-index="2" data-file-name="a.txt" data-file-type="text/plain"></a>')
      );
      const event = click(doc);
      expect(event.defaultPrevented).toBe(true);
      expect(m.openFileInNewTab).toHaveBeenCalledWith('m1', 2, 'a.txt', 'text/plain');

      m.openFileInNewTab.mockClear();
      click(messages.appendChild(el('<a class="document-preview" data-message-id="m1" data-file-index="0" data-file-type="application/pdf"></a>')));
      expect(m.openFileInNewTab).not.toHaveBeenCalled();
      await vi.waitFor(() => expect(m.openPdfViewer).toHaveBeenCalledWith('m1', 0, 'file.pdf'));
    });

    it('downloads with a fallback file name', () => {
      click(messages.appendChild(el('<button class="document-download" data-message-id="m1" data-file-index="3"></button>')));
      expect(m.downloadFile).toHaveBeenCalledWith('m1', 3, 'file-3');
    });

    it('routes copy, overflow and quiz buttons', () => {
      const copy = messages.appendChild(el('<button class="message-copy-btn"></button>'));
      click(copy);
      expect(m.copyMessageContent).toHaveBeenCalledWith(copy);

      const inline = messages.appendChild(el('<button class="inline-copy-btn"></button>'));
      click(inline);
      expect(m.copyInlineContent).toHaveBeenCalledWith(inline);

      const actions = messages.appendChild(
        el('<div class="message-actions"><button class="message-actions-overflow"></button></div>')
      );
      const overflow = actions.querySelector('.message-actions-overflow') as HTMLElement;
      click(overflow);
      expect(actions.classList.contains('expanded')).toBe(true);
      expect(overflow.getAttribute('aria-expanded')).toBe('true');

      const option = messages.appendChild(el('<button class="quiz-option"></button>'));
      click(option);
      expect(m.handleQuizOptionClick).toHaveBeenCalledWith(option);

      const cont = messages.appendChild(el('<button class="quiz-continue"></button>'));
      click(cont);
      expect(m.handleQuizContinue).toHaveBeenCalledWith(cont);
    });
  });

  describe('user menu', () => {
    it('toggles the menu and closes it on an outside click', () => {
      const menu = userInfo.querySelector('.user-menu') as HTMLElement;
      click(userInfo.querySelector('#user-menu-btn') as Element);
      expect(menu.classList.contains('hidden')).toBe(false);
      expect(document.getElementById('user-menu-btn')?.getAttribute('aria-expanded')).toBe('true');

      click(list);
      expect(menu.classList.contains('hidden')).toBe(true);
      expect(document.getElementById('user-menu-btn')?.getAttribute('aria-expanded')).toBe('false');
    });

    it.each([
      ['logout-btn', m.logout],
      ['memories-btn', m.navigateToStorage],
      ['select-chats-btn', m.enterSelectionMode],
    ])('#%s closes the menu and runs its action', (id, action) => {
      const menu = userInfo.querySelector('.user-menu') as HTMLElement;
      menu.classList.remove('hidden');
      click(menu.appendChild(el(`<button id="${id}"></button>`)));
      expect(menu.classList.contains('hidden')).toBe(true);
      expect(action).toHaveBeenCalled();
    });

    it('opens archive and trash from their menu items', () => {
      const menu = userInfo.querySelector('.user-menu') as HTMLElement;
      click(menu.appendChild(el('<button class="user-menu-archive"></button>')));
      click(menu.appendChild(el('<button class="user-menu-trash"></button>')));
      expect(m.navigateToArchive).toHaveBeenCalled();
      expect(m.navigateToTrash).toHaveBeenCalled();
    });

    it('loads the cost history, and reports a failure', async () => {
      const menu = userInfo.querySelector('.user-menu') as HTMLElement;
      const btn = menu.appendChild(el('<button id="cost-history-btn"></button>'));
      m.getCostHistory.mockResolvedValue({ months: [] });
      click(btn);
      await vi.waitFor(() => expect(m.openCostHistory).toHaveBeenCalledWith({ months: [] }));

      m.getCostHistory.mockRejectedValue(new Error('down'));
      click(btn);
      await vi.waitFor(() => expect(m.toastError).toHaveBeenCalledWith('Failed to load cost history.'));
    });

    it('opens the admin page, and reports a failure instead of failing silently', async () => {
      const menu = userInfo.querySelector('.user-menu') as HTMLElement;
      const btn = menu.appendChild(el('<button id="admin-btn"></button>'));
      m.openAdminPage.mockResolvedValue(undefined);
      click(btn);
      await vi.waitFor(() => expect(m.openAdminPage).toHaveBeenCalled());
      expect(m.toastError).not.toHaveBeenCalled();

      m.openAdminPage.mockRejectedValue(new Error('chunk gone'));
      click(btn);
      await vi.waitFor(() => expect(m.toastError).toHaveBeenCalledWith('Failed to open the admin page.'));
    });

    it('opens the settings popup from its menu item', async () => {
      const menu = userInfo.querySelector('.user-menu') as HTMLElement;
      menu.classList.remove('hidden');
      click(menu.appendChild(el('<button id="settings-btn"></button>')));
      expect(menu.classList.contains('hidden')).toBe(true);
      await vi.waitFor(() => expect(m.openSettingsPopup).toHaveBeenCalled());
    });
  });

  describe('header buttons and inputs', () => {
    it('starts a new chat and toggles the sidebar', () => {
      click(document.getElementById('new-chat-btn') as Element);
      click(document.getElementById('menu-btn') as Element);
      expect(m.createConversation).toHaveBeenCalled();
      expect(m.toggleSidebar).toHaveBeenCalled();
    });

    it('routes typing in a quiz text input to the quiz', () => {
      const input = messages.appendChild(el('<input class="quiz-text-input">')) as HTMLInputElement;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      expect(m.handleQuizInputChange).toHaveBeenCalledWith(input);
    });

    it('ignores typing in other inputs in the messages list', () => {
      const input = messages.appendChild(el('<input class="other">'));
      input.dispatchEvent(new Event('input', { bubbles: true }));
      expect(m.handleQuizInputChange).not.toHaveBeenCalled();
    });
  });

  describe('conversation action sheet', () => {
    type SheetAction = { label: string; danger?: boolean; onSelect: () => void };
    const sheetActions = (): SheetAction[] => m.showActionSheet.mock.lastCall?.[1] as SheetAction[];
    const select = (label: string): void => sheetActions().find((a) => a.label === label)?.onSelect();

    it('offers Unpin for a pinned conversation and runs each action on its id', () => {
      useStore.setState({
        conversations: [{ id: 'c1', title: 'Chat', model: 'm', created_at: '', updated_at: '', pinned: true }],
      });
      click(list.appendChild(el('<button data-more-id="c1"></button>')));

      expect(sheetActions().map((a) => a.label)).toEqual(['Unpin', 'Rename', 'Archive', 'Delete']);
      expect(sheetActions().find((a) => a.label === 'Delete')?.danger).toBe(true);
      select('Unpin');
      select('Rename');
      select('Archive');
      select('Delete');
      expect(m.togglePinConversation).toHaveBeenCalledWith('c1');
      expect(m.renameConversation).toHaveBeenCalledWith('c1');
      expect(m.archiveConversation).toHaveBeenCalledWith('c1');
      expect(m.deleteConversation).toHaveBeenCalledWith('c1');
    });

    it('titles an archived conversation from the archive list and unarchives it', () => {
      useStore.setState({
        archivedConversations: [{ id: 'z1', title: 'Old chat', model: 'm', created_at: '', updated_at: '' }],
      });
      click(list.appendChild(el('<button data-more-archived-id="z1"></button>')));

      expect(m.showActionSheet).toHaveBeenLastCalledWith('Old chat', expect.any(Array));
      select('Unarchive');
      expect(m.unarchiveConversation).toHaveBeenCalledWith('z1');
      expect(rowClicks).toBe(0);
    });
  });

  describe('conversation list keyboard', () => {
    function rows(): HTMLElement[] {
      list.innerHTML = [0, 1, 2]
        .map((i) => `<div class="conversation-item" tabindex="${i === 0 ? 0 : -1}">${i}</div>`)
        .join('');
      return Array.from(list.querySelectorAll<HTMLElement>('.conversation-item'));
    }
    const key = (target: HTMLElement, k: string): KeyboardEvent => {
      const event = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true });
      target.dispatchEvent(event);
      return event;
    };

    it('moves the roving tabindex with the arrows, Home and End', () => {
      const items = rows();
      key(items[0] as HTMLElement, 'ArrowDown');
      expect(document.activeElement).toBe(items[1]);
      expect(items.map((i) => i.getAttribute('tabindex'))).toEqual(['-1', '0', '-1']);

      key(items[1] as HTMLElement, 'End');
      expect(document.activeElement).toBe(items[2]);
      key(items[2] as HTMLElement, 'Home');
      expect(document.activeElement).toBe(items[0]);
    });

    it('does not wrap past the ends', () => {
      const items = rows();
      const event = key(items[0] as HTMLElement, 'ArrowUp');
      expect(event.defaultPrevented).toBe(false);
      expect(items[0]?.getAttribute('tabindex')).toBe('0');
    });

    it('activates the focused row on Enter', () => {
      const items = rows();
      const clicked = vi.fn();
      items[1]?.addEventListener('click', clicked);
      const event = key(items[1] as HTMLElement, 'Enter');
      expect(event.defaultPrevented).toBe(true);
      expect(clicked).toHaveBeenCalled();
    });

    it('activates a sidebar entry on Space', () => {
      const entry = list.appendChild(el('<div class="planner-entry" tabindex="0"></div>'));
      const event = key(entry, ' ');
      expect(event.defaultPrevented).toBe(true);
      expect(m.navigateToPlanner).toHaveBeenCalled();
    });

    it('leaves other keys alone', () => {
      const items = rows();
      const event = key(items[0] as HTMLElement, 'a');
      expect(event.defaultPrevented).toBe(false);
      expect(items.map((i) => i.getAttribute('tabindex'))).toEqual(['0', '-1', '-1']);
    });
  });
});

describe('nextRovingIndex', () => {
  it('jumps to the ends with Home and End', () => {
    expect(nextRovingIndex('Home', 2, 5)).toBe(0);
    expect(nextRovingIndex('End', 0, 5)).toBe(4);
  });

  it('enters the list from outside at the near end', () => {
    expect(nextRovingIndex('ArrowDown', -1, 5)).toBe(0);
    expect(nextRovingIndex('ArrowUp', -1, 5)).toBe(4);
  });

  it('steps without wrapping', () => {
    expect(nextRovingIndex('ArrowDown', 1, 5)).toBe(2);
    expect(nextRovingIndex('ArrowUp', 1, 5)).toBe(0);
    expect(nextRovingIndex('ArrowUp', 0, 5)).toBeNull();
    expect(nextRovingIndex('ArrowDown', 4, 5)).toBeNull();
  });
});
