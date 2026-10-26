/**
 * Message pagination (infinite scroll): scrolling near the top of #messages
 * loads the previous page and prepends it in chronological order, keeping
 * the reading position; scrolling near the bottom of a partial view (after
 * a search jump) loads the next page and appends it. A load is skipped while
 * the conversation streams, while one is running, or when the server said
 * there is nothing more; a failed load clears the loading flag so the next
 * scroll retries. loadAllRemainingNewerMessages pages to the end before a
 * send, sharing one run between concurrent callers.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Message, MessagesPagination, PaginationDirection } from '@/types/api';

type Page = { messages: Message[]; pagination: MessagesPagination };

const api = vi.hoisted(() => ({
  getMessages:
    vi.fn<(id: string, limit?: number, cursor?: string | null, direction?: PaginationDirection) => Promise<Page>>(),
}));
const ui = vi.hoisted(() => ({
  addMessageToUI: vi.fn((msg: { id: string }, container: HTMLElement) => {
    const el = document.createElement('div');
    el.className = 'message';
    el.dataset.id = msg.id;
    container.appendChild(el);
  }),
  lockOlderQuizBlocks: vi.fn(),
  refreshVersionBadges: vi.fn(),
  applyCompactionMarkers: vi.fn(),
  observeThumbnail: vi.fn(),
}));

vi.mock('@/api/conversations', () => ({ conversations: api }));
vi.mock('@/components/messages/render', () => ({
  addMessageToUI: ui.addMessageToUI,
  lockOlderQuizBlocks: ui.lockOlderQuizBlocks,
}));
vi.mock('@/components/messages/artifacts', () => ({ refreshVersionBadges: ui.refreshVersionBadges }));
vi.mock('@/components/CompactionIndicator', () => ({ applyCompactionMarkers: ui.applyCompactionMarkers }));
vi.mock('@/utils/thumbnails', () => ({
  observeThumbnail: ui.observeThumbnail,
  beginProgrammaticScroll: vi.fn(() => 1),
  endProgrammaticScroll: vi.fn(),
}));

import { useStore } from '@/state/store';
import {
  setupOlderMessagesScrollListener,
  cleanupOlderMessagesScrollListener,
  setupNewerMessagesScrollListener,
  cleanupNewerMessagesScrollListener,
  loadAllRemainingNewerMessages,
} from '@/components/messages/pagination';
import { INFINITE_SCROLL_DEBOUNCE_MS } from '@/config';

const ROW_HEIGHT_PX = 200;
const CLIENT_HEIGHT_PX = 600;

function msg(id: string): Message {
  return { id, role: 'user', content: id, created_at: '2026-10-01T00:00:00Z' };
}

function page(overrides: Partial<MessagesPagination> = {}): MessagesPagination {
  return {
    older_cursor: null,
    newer_cursor: null,
    has_older: false,
    has_newer: false,
    total_count: 10,
    ...overrides,
  };
}

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void } {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const domIds = (container: HTMLElement): string[] =>
  Array.from(container.querySelectorAll<HTMLElement>('.message')).map((el) => el.dataset.id ?? '');

const storeIds = (convId: string): string[] => useStore.getState().getMessages(convId).map((m) => m.id);

const pagination = (convId: string) => useStore.getState().getMessagesPagination(convId);

describe('message pagination', () => {
  let container: HTMLDivElement;
  let scrollTop: number;

  /** Open conversation `convId` with messages `ids` rendered and the given pagination. */
  function openConversation(convId: string, ids: string[], pag: Partial<MessagesPagination>): void {
    useStore.getState().setCurrentConversation({
      id: convId,
      title: convId,
      model: 'm',
      created_at: '',
      updated_at: '',
    });
    useStore.getState().setMessages(convId, ids.map(msg), page(pag));
    container.innerHTML = '';
    ids.forEach((id) => ui.addMessageToUI(msg(id), container));
  }

  async function scrollTo(top: number): Promise<void> {
    scrollTop = top;
    container.dispatchEvent(new Event('scroll'));
    await vi.advanceTimersByTimeAsync(INFINITE_SCROLL_DEBOUNCE_MS);
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
    useStore.setState(useStore.getInitialState(), true);
    document.body.innerHTML = '<div id="messages"></div>';
    container = document.getElementById('messages') as HTMLDivElement;
    scrollTop = 0;
    // jsdom has no layout: every rendered message is one row tall
    Object.defineProperty(container, 'scrollTop', {
      configurable: true,
      get: () => scrollTop,
      set: (v: number) => {
        scrollTop = v;
      },
    });
    Object.defineProperty(container, 'scrollHeight', {
      configurable: true,
      get: () => container.querySelectorAll('.message').length * ROW_HEIGHT_PX,
    });
    Object.defineProperty(container, 'clientHeight', { configurable: true, get: () => CLIENT_HEIGHT_PX });
  });

  afterEach(() => {
    cleanupOlderMessagesScrollListener();
    cleanupNewerMessagesScrollListener();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  describe('older messages', () => {
    it('loads the previous page near the top and prepends it in chronological order', async () => {
      openConversation('c1', ['m3', 'm4'], { has_older: true, older_cursor: 'cur-old' });
      api.getMessages.mockResolvedValue({ messages: [msg('m1'), msg('m2')], pagination: page({ has_older: false }) });
      setupOlderMessagesScrollListener('c1');

      await scrollTo(50);

      expect(api.getMessages).toHaveBeenCalledWith('c1', undefined, 'cur-old', 'older');
      await vi.waitFor(() => expect(domIds(container)).toEqual(['m1', 'm2', 'm3', 'm4']));
      expect(storeIds('c1')).toEqual(['m1', 'm2', 'm3', 'm4']);
      expect(pagination('c1')?.hasOlder).toBe(false);
      expect(pagination('c1')?.isLoadingOlder).toBe(false);
      expect(ui.lockOlderQuizBlocks).toHaveBeenCalledWith(container);
      expect(ui.refreshVersionBadges).toHaveBeenCalledWith(container);
      expect(ui.applyCompactionMarkers).toHaveBeenCalledWith(container);
    });

    it('keeps the reading position by the height the prepended page added', async () => {
      openConversation('c1', ['m3', 'm4'], { has_older: true, older_cursor: 'o' });
      api.getMessages.mockResolvedValue({ messages: [msg('m1'), msg('m2')], pagination: page() });
      setupOlderMessagesScrollListener('c1');

      await scrollTo(50);

      await vi.waitFor(() => expect(domIds(container)).toHaveLength(4));
      expect(scrollTop).toBe(50 + 2 * ROW_HEIGHT_PX);
    });

    it('shows a loader at the top while the page loads, and removes it after', async () => {
      openConversation('c1', ['m3'], { has_older: true, older_cursor: 'o' });
      const load = deferred<Page>();
      api.getMessages.mockReturnValue(load.promise);
      setupOlderMessagesScrollListener('c1');

      await scrollTo(0);

      expect(container.firstElementChild?.classList.contains('older-messages-loader')).toBe(true);
      expect(pagination('c1')?.isLoadingOlder).toBe(true);
      load.resolve({ messages: [msg('m1')], pagination: page() });
      await vi.waitFor(() => expect(container.querySelector('.older-messages-loader')).toBeNull());
    });

    it('puts the loader after the planner dashboard so the dashboard stays first', async () => {
      openConversation('c1', ['m3'], { has_older: true, older_cursor: 'o' });
      const dashboard = document.createElement('div');
      dashboard.className = 'planner-dashboard-message';
      container.insertBefore(dashboard, container.firstChild);
      api.getMessages.mockReturnValue(new Promise(() => {}));
      setupOlderMessagesScrollListener('c1');

      await scrollTo(0);

      expect(container.firstElementChild).toBe(dashboard);
      expect(dashboard.nextElementSibling?.classList.contains('older-messages-loader')).toBe(true);
    });

    it('debounces a burst of scroll events into one request', async () => {
      openConversation('c1', ['m3'], { has_older: true, older_cursor: 'o' });
      api.getMessages.mockReturnValue(new Promise(() => {}));
      setupOlderMessagesScrollListener('c1');

      scrollTop = 10;
      container.dispatchEvent(new Event('scroll'));
      container.dispatchEvent(new Event('scroll'));
      container.dispatchEvent(new Event('scroll'));
      await vi.advanceTimersByTimeAsync(INFINITE_SCROLL_DEBOUNCE_MS);

      expect(api.getMessages).toHaveBeenCalledTimes(1);
    });

    it('does not load when the user is not near the top', async () => {
      openConversation('c1', ['m3'], { has_older: true, older_cursor: 'o' });
      setupOlderMessagesScrollListener('c1');

      await scrollTo(500);

      expect(api.getMessages).not.toHaveBeenCalled();
    });

    it('does not load when the server has no older messages', async () => {
      openConversation('c1', ['m3'], { has_older: false });
      setupOlderMessagesScrollListener('c1');

      await scrollTo(0);

      expect(api.getMessages).not.toHaveBeenCalled();
    });

    it('does not load while the conversation is streaming', async () => {
      openConversation('c1', ['m3'], { has_older: true, older_cursor: 'o' });
      useStore.setState({ streamingConversationId: 'c1' });
      setupOlderMessagesScrollListener('c1');

      await scrollTo(0);

      expect(api.getMessages).not.toHaveBeenCalled();
    });

    it('does not start a second load while one is running', async () => {
      openConversation('c1', ['m3'], { has_older: true, older_cursor: 'o' });
      api.getMessages.mockReturnValue(new Promise(() => {}));
      setupOlderMessagesScrollListener('c1');

      await scrollTo(0);
      await scrollTo(0);

      expect(api.getMessages).toHaveBeenCalledTimes(1);
    });

    it('clears the loading state after a failed load so the next scroll retries', async () => {
      openConversation('c1', ['m3'], { has_older: true, older_cursor: 'o' });
      api.getMessages.mockRejectedValueOnce(new Error('offline'));
      setupOlderMessagesScrollListener('c1');

      await scrollTo(0);

      await vi.waitFor(() => expect(pagination('c1')?.isLoadingOlder).toBe(false));
      expect(container.querySelector('.older-messages-loader')).toBeNull();
      expect(domIds(container)).toEqual(['m3']);

      api.getMessages.mockResolvedValueOnce({ messages: [msg('m2')], pagination: page() });
      await scrollTo(0);
      await vi.waitFor(() => expect(domIds(container)).toEqual(['m2', 'm3']));
    });

    it('skips the load when the listener fires for a conversation that is no longer open', async () => {
      openConversation('c1', ['m3'], { has_older: true, older_cursor: 'o' });
      setupOlderMessagesScrollListener('c1');
      useStore.getState().setCurrentConversation(null);

      await scrollTo(0);

      expect(api.getMessages).not.toHaveBeenCalled();
    });

    // The guard reads fresh state after the request: a pre-await snapshot
    // once let A's older messages land in B's list
    it('drops a page that arrives after the user switched to another conversation', async () => {
      openConversation('c1', ['a3'], { has_older: true, older_cursor: 'o' });
      const load = deferred<Page>();
      api.getMessages.mockReturnValue(load.promise);
      setupOlderMessagesScrollListener('c1');
      await scrollTo(0);

      openConversation('c2', ['b1', 'b2'], {});
      load.resolve({ messages: [msg('a1'), msg('a2')], pagination: page() });
      await vi.waitFor(() => expect(container.querySelector('.older-messages-loader')).toBeNull());

      expect(domIds(container)).toEqual(['b1', 'b2']);
    });

    it('stops loading after cleanup', async () => {
      openConversation('c1', ['m3'], { has_older: true, older_cursor: 'o' });
      setupOlderMessagesScrollListener('c1');
      cleanupOlderMessagesScrollListener();

      await scrollTo(0);

      expect(api.getMessages).not.toHaveBeenCalled();
    });
  });

  describe('newer messages', () => {
    it('loads the next page near the bottom and appends it', async () => {
      openConversation('c1', ['m1', 'm2', 'm3', 'm4'], { has_newer: true, newer_cursor: 'cur-new' });
      api.getMessages.mockResolvedValue({ messages: [msg('m5')], pagination: page({ has_newer: false }) });
      setupNewerMessagesScrollListener('c1');

      // 4 rows = 800px tall, 600px visible: 150px from the bottom
      await scrollTo(50);

      expect(api.getMessages).toHaveBeenCalledWith('c1', undefined, 'cur-new', 'newer');
      await vi.waitFor(() => expect(domIds(container)).toEqual(['m1', 'm2', 'm3', 'm4', 'm5']));
      expect(storeIds('c1')).toEqual(['m1', 'm2', 'm3', 'm4', 'm5']);
      expect(pagination('c1')?.hasNewer).toBe(false);
      expect(container.querySelector('.newer-messages-loader')).toBeNull();
    });

    it('does not load when the user is far from the bottom', async () => {
      openConversation('c1', ['m1', 'm2', 'm3', 'm4', 'm5', 'm6'], { has_newer: true, newer_cursor: 'n' });
      setupNewerMessagesScrollListener('c1');

      // 1200px tall, 600px visible: 600px from the bottom
      await scrollTo(0);

      expect(api.getMessages).not.toHaveBeenCalled();
    });

    it('does not load while the conversation is streaming', async () => {
      openConversation('c1', ['m1'], { has_newer: true, newer_cursor: 'n' });
      useStore.setState({ streamingConversationId: 'c1' });
      setupNewerMessagesScrollListener('c1');

      await scrollTo(0);

      expect(api.getMessages).not.toHaveBeenCalled();
    });

    it('clears the loading state after a failed load', async () => {
      openConversation('c1', ['m1'], { has_newer: true, newer_cursor: 'n' });
      api.getMessages.mockRejectedValue(new Error('offline'));
      setupNewerMessagesScrollListener('c1');

      await scrollTo(0);

      await vi.waitFor(() => expect(pagination('c1')?.isLoadingNewer).toBe(false));
      expect(container.querySelector('.newer-messages-loader')).toBeNull();
    });

    // Fresh state after the request (see loadOlderMessages above)
    it('drops a page that arrives after the user switched to another conversation', async () => {
      openConversation('c1', ['a1'], { has_newer: true, newer_cursor: 'n' });
      const load = deferred<Page>();
      api.getMessages.mockReturnValue(load.promise);
      setupNewerMessagesScrollListener('c1');
      await scrollTo(0);

      openConversation('c2', ['b1'], {});
      load.resolve({ messages: [msg('a2')], pagination: page() });
      await vi.waitFor(() => expect(container.querySelector('.newer-messages-loader')).toBeNull());

      expect(domIds(container)).toEqual(['b1']);
    });
  });

  describe('loadAllRemainingNewerMessages', () => {
    it('pages until the server has no newer messages', async () => {
      openConversation('c1', ['m1'], { has_newer: true, newer_cursor: 'n1' });
      api.getMessages
        .mockResolvedValueOnce({ messages: [msg('m2')], pagination: page({ has_newer: true, newer_cursor: 'n2' }) })
        .mockResolvedValueOnce({ messages: [msg('m3')], pagination: page({ has_newer: false }) });

      await loadAllRemainingNewerMessages('c1');

      expect(api.getMessages.mock.calls.map((c) => c[2])).toEqual(['n1', 'n2']);
      expect(domIds(container)).toEqual(['m1', 'm2', 'm3']);
      expect(storeIds('c1')).toEqual(['m1', 'm2', 'm3']);
      expect(container.querySelector('.newer-messages-loader')).toBeNull();
    });

    it('resolves without a request when there is nothing newer', async () => {
      openConversation('c1', ['m1'], { has_newer: false });

      await loadAllRemainingNewerMessages('c1');

      expect(api.getMessages).not.toHaveBeenCalled();
    });

    it('shares one run between concurrent callers (no duplicate pages)', async () => {
      openConversation('c1', ['m1'], { has_newer: true, newer_cursor: 'n1' });
      const load = deferred<Page>();
      api.getMessages.mockReturnValueOnce(load.promise);

      const first = loadAllRemainingNewerMessages('c1');
      const second = loadAllRemainingNewerMessages('c1');
      load.resolve({ messages: [msg('m2')], pagination: page() });
      await Promise.all([first, second]);

      expect(api.getMessages).toHaveBeenCalledTimes(1);
      expect(domIds(container)).toEqual(['m1', 'm2']);
    });

    it('starts a fresh run once the previous one finished', async () => {
      openConversation('c1', ['m1'], { has_newer: true, newer_cursor: 'n1' });
      api.getMessages.mockResolvedValueOnce({ messages: [msg('m2')], pagination: page() });
      await loadAllRemainingNewerMessages('c1');

      useStore.getState().setMessages('c1', [msg('m1'), msg('m2')], page({ has_newer: true, newer_cursor: 'n2' }));
      api.getMessages.mockResolvedValueOnce({ messages: [msg('m3')], pagination: page() });
      await loadAllRemainingNewerMessages('c1');

      expect(api.getMessages).toHaveBeenCalledTimes(2);
    });

    it('rejects when the messages container is missing', async () => {
      openConversation('c1', ['m1'], { has_newer: true, newer_cursor: 'n1' });
      document.body.innerHTML = '';

      await expect(loadAllRemainingNewerMessages('c1')).rejects.toThrow('Messages container not found');
    });

    it('rejects when the conversation is no longer open', async () => {
      openConversation('c1', ['m1'], { has_newer: true, newer_cursor: 'n1' });
      useStore.getState().setCurrentConversation(null);

      await expect(loadAllRemainingNewerMessages('c1')).rejects.toThrow('Conversation changed');
      expect(api.getMessages).not.toHaveBeenCalled();
      expect(container.querySelector('.newer-messages-loader')).toBeNull();
    });

    // Fresh state after each page (see loadOlderMessages above)
    it('stops with "Conversation changed" when the user switches away mid-run', async () => {
      openConversation('c1', ['a1'], { has_newer: true, newer_cursor: 'n1' });
      const load = deferred<Page>();
      api.getMessages.mockReturnValueOnce(load.promise);

      const run = loadAllRemainingNewerMessages('c1');
      openConversation('c2', ['b1'], {});
      load.resolve({ messages: [msg('a2')], pagination: page() });

      await expect(run).rejects.toThrow('Conversation changed');
    });

    it('propagates a failed request and removes the loader', async () => {
      openConversation('c1', ['m1'], { has_newer: true, newer_cursor: 'n1' });
      api.getMessages.mockRejectedValue(new Error('offline'));

      await expect(loadAllRemainingNewerMessages('c1')).rejects.toThrow('offline');
      expect(container.querySelector('.newer-messages-loader')).toBeNull();
    });
  });
});
