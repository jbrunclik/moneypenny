/**
 * F2: the local ESLint rule that flags store state read from a
 * `useStore.getState()` snapshot after an await. Cases come from the Oct 2026
 * bugs (archiveConversation, the pagination guards).
 */
import { RuleTester } from 'eslint';
import tseslint from 'typescript-eslint';
import rule from '../../eslint-rules/no-stale-store-snapshot.js';

const tester = new RuleTester({
  languageOptions: { parser: tseslint.parser, ecmaVersion: 2022, sourceType: 'module' },
});

const stale = (name: string) => ({ messageId: 'stale', data: { name } });

tester.run('no-stale-store-snapshot', rule, {
  valid: [
    // Fields read before the await, actions called after it
    `async function archive(id: string) {
      const store = useStore.getState();
      const conv = store.conversations.find((c) => c.id === id);
      await api.archive(id);
      store.removeConversation(id);
      store.addArchivedConversation({ ...conv });
    }`,
    // The fix: re-read after the request
    `async function archive(id: string) {
      const store = useStore.getState();
      await api.archive(id);
      if (useStore.getState().currentConversation?.id === id) store.setCurrentConversation(null);
    }`,
    // Reassigned from getState() after the await
    `async function f() {
      let state = useStore.getState();
      await g();
      state = useStore.getState();
      return state.conversations;
    }`,
    // A getter action called after the await
    `async function f(id: string) {
      const store = useStore.getState();
      await g();
      return store.getMessagesPagination(id);
    }`,
    // Optional-call action
    `async function f() {
      const store = useStore.getState();
      await g();
      store.onDone?.();
    }`,
    // Destructured action called after the await
    `async function f() {
      const { setLoading, isLoading } = useStore.getState();
      if (isLoading) return;
      await g();
      setLoading(false);
    }`,
    // The snapshot is taken inside the loop: fresh each iteration
    `async function f() {
      while (more) {
        const store = useStore.getState();
        if (store.currentConversation) break;
        await g();
      }
    }`,
    // An await in a nested function that is not on the read's path
    `async function f() {
      const store = useStore.getState();
      const later = async () => { await g(); };
      return store.isLoading;
    }`,
    // No await at all
    `function f() {
      const store = useStore.getState();
      return store.currentConversation;
    }`,
    // Not the app store
    `async function f() {
      const s = otherStore.getState();
      await g();
      return s.value;
    }`,
  ],
  invalid: [
    // archiveConversation before 64c5e993
    {
      code: `async function archive(id: string) {
        const store = useStore.getState();
        await api.archive(id);
        store.removeConversation(id);
        if (store.currentConversation?.id === id) store.setCurrentConversation(null);
      }`,
      errors: [stale('store.currentConversation')],
    },
    // loadOlderMessages before 7d057edf (guard and log both stale)
    {
      code: `async function loadOlder(conversationId: string) {
        const store = useStore.getState();
        if (store.currentConversation?.id !== conversationId) return;
        try {
          const result = await api.getMessages(conversationId);
          if (store.currentConversation?.id !== conversationId) {
            log.debug('changed', { currentId: store.currentConversation?.id });
            return;
          }
          store.prependMessages(conversationId, result.messages);
        } finally {
          store.setLoadingOlderMessages(conversationId, false);
        }
      }`,
      errors: [stale('store.currentConversation'), stale('store.currentConversation')],
    },
    // The load-all loop: the top-of-loop guard runs after the previous batch's await
    {
      code: `async function loadAll(conversationId: string) {
        const store = useStore.getState();
        let pagination = store.getMessagesPagination(conversationId);
        while (pagination?.hasNewer) {
          if (store.currentConversation?.id !== conversationId) throw new Error('changed');
          const result = await api.getMessages(conversationId);
          store.appendMessages(conversationId, result.messages);
          pagination = result.pagination;
        }
      }`,
      errors: [stale('store.currentConversation')],
    },
    // Destructured field read after the await
    {
      code: `async function send() {
        const { pendingFiles, isLoading } = useStore.getState();
        if (isLoading) return;
        await upload();
        return pendingFiles.length;
      }`,
      errors: [stale('pendingFiles')],
    },
    // Read in a .then callback
    {
      code: `function f() {
        const state = useStore.getState();
        api.load().then(() => render(state.conversations));
      }`,
      errors: [stale('state.conversations')],
    },
    // Read in a nested callback after the await
    {
      code: `async function f() {
        const store = useStore.getState();
        await g();
        return items.map((i) => store.conversations[i]);
      }`,
      errors: [stale('store.conversations')],
    },
    // for await
    {
      code: `async function f(stream: AsyncIterable<string>) {
        const store = useStore.getState();
        for await (const chunk of stream) {
          if (store.streamingConversationId) handle(chunk);
        }
      }`,
      errors: [stale('store.streamingConversationId')],
    },
  ],
});
