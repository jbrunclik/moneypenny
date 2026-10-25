/**
 * UI slice: per-conversation flags and active requests (restored after a
 * conversation switch), notifications, the navigation token that cancels
 * stale async work, and the atomic view switch.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import { initialUiSessionData, type ActiveView, type Notification } from '@/state/slices/ui';
import type { ArtifactRef, ThinkingState } from '@/types/api';

function artifact(id: string, version: number): ArtifactRef {
  return { id, version, title: `Artifact ${id}` };
}

const artifactsOf = (convId: string) => useStore.getState().getActiveRequest(convId)?.artifacts;

describe('ui slice', () => {
  beforeEach(() => {
    useStore.setState(useStore.getInitialState(), true);
  });

  it('initial session data starts empty with fresh Maps per call', () => {
    const a = initialUiSessionData();
    const b = initialUiSessionData();
    expect(a.activeRequests.size).toBe(0);
    expect(a.activeRequests).not.toBe(b.activeRequests);
    expect(a.anonymousModeByConversation).not.toBe(b.anonymousModeByConversation);
  });

  describe('anonymous mode', () => {
    it('defaults to off for any conversation', () => {
      expect(useStore.getState().getAnonymousMode('c1')).toBe(false);
    });

    it('is tracked per conversation', () => {
      useStore.getState().setAnonymousMode('c1', true);
      expect(useStore.getState().getAnonymousMode('c1')).toBe(true);
      expect(useStore.getState().getAnonymousMode('c2')).toBe(false);
    });

    it('turning it off removes the entry instead of storing false', () => {
      useStore.getState().setAnonymousMode('c1', true);
      useStore.getState().setAnonymousMode('c1', false);
      expect(useStore.getState().anonymousModeByConversation.has('c1')).toBe(false);
    });

    it('replaces the Map so subscribers see a change', () => {
      const before = useStore.getState().anonymousModeByConversation;
      useStore.getState().setAnonymousMode('c1', true);
      expect(useStore.getState().anonymousModeByConversation).not.toBe(before);
    });
  });

  describe('active requests', () => {
    it('stores, reads and removes a request per conversation', () => {
      useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream' });
      expect(useStore.getState().getActiveRequest('c1')?.type).toBe('stream');
      expect(useStore.getState().getActiveRequest('c2')).toBeUndefined();
      useStore.getState().removeActiveRequest('c1');
      expect(useStore.getState().getActiveRequest('c1')).toBeUndefined();
    });

    it('updateActiveRequestContent replaces the content and keeps the thinking state when none is given', () => {
      const thinkingState: ThinkingState = {
        isThinking: true,
        thinkingText: 'hmm',
        activeTool: null,
        completedTools: [],
        trace: [],
      };
      useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream', thinkingState });
      useStore.getState().updateActiveRequestContent('c1', 'partial reply');
      const req = useStore.getState().getActiveRequest('c1');
      expect(req?.content).toBe('partial reply');
      expect(req?.thinkingState).toEqual(thinkingState);
    });

    it('updateActiveRequestContent ignores a conversation without an active request', () => {
      useStore.getState().updateActiveRequestContent('ghost', 'x');
      expect(useStore.getState().getActiveRequest('ghost')).toBeUndefined();
    });

    it('addActiveRequestArtifact appends new artifacts in order', () => {
      useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream' });
      useStore.getState().addActiveRequestArtifact('c1', artifact('a', 1));
      useStore.getState().addActiveRequestArtifact('c1', artifact('b', 1));
      expect(artifactsOf('c1')).toEqual([artifact('a', 1), artifact('b', 1)]);
    });

    it('a new version of an artifact replaces the old one in its position', () => {
      useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream' });
      useStore.getState().addActiveRequestArtifact('c1', artifact('a', 1));
      useStore.getState().addActiveRequestArtifact('c1', artifact('b', 1));
      useStore.getState().addActiveRequestArtifact('c1', artifact('c', 1));
      useStore.getState().addActiveRequestArtifact('c1', artifact('b', 2));
      expect(artifactsOf('c1')).toEqual([artifact('a', 1), artifact('b', 2), artifact('c', 1)]);
    });

    it('addActiveRequestArtifact ignores a conversation without an active request', () => {
      useStore.getState().addActiveRequestArtifact('ghost', artifact('a', 1));
      expect(useStore.getState().getActiveRequest('ghost')).toBeUndefined();
    });
  });

  describe('force tools and pending files', () => {
    it('toggleForceTool adds then removes a tool', () => {
      useStore.getState().toggleForceTool('search');
      useStore.getState().toggleForceTool('image');
      expect(useStore.getState().forceTools).toEqual(['search', 'image']);
      useStore.getState().toggleForceTool('search');
      expect(useStore.getState().forceTools).toEqual(['image']);
    });

    it('removePendingFile removes by index', () => {
      const file = (name: string) => ({ name, type: 'text/plain', data: '' });
      useStore.getState().addPendingFile(file('a'));
      useStore.getState().addPendingFile(file('b'));
      useStore.getState().addPendingFile(file('c'));
      useStore.getState().removePendingFile(1);
      expect(useStore.getState().pendingFiles.map((f) => f.name)).toEqual(['a', 'c']);
    });
  });

  describe('notifications', () => {
    const note = (id: string): Notification => ({ id, type: 'info', message: id });

    it('adds, dismisses by id and clears', () => {
      useStore.getState().addNotification(note('n1'));
      useStore.getState().addNotification(note('n2'));
      useStore.getState().dismissNotification('n1');
      expect(useStore.getState().notifications.map((n) => n.id)).toEqual(['n2']);
      useStore.getState().clearNotifications();
      expect(useStore.getState().notifications).toEqual([]);
    });
  });

  describe('navigation token', () => {
    it('each navigation invalidates the tokens handed out before it', () => {
      const first = useStore.getState().startNavigation();
      expect(useStore.getState().isNavigationValid(first)).toBe(true);
      const second = useStore.getState().startNavigation();
      expect(second).toBe(first + 1);
      expect(useStore.getState().isNavigationValid(first)).toBe(false);
      expect(useStore.getState().isNavigationValid(second)).toBe(true);
    });
  });

  describe('setActiveView', () => {
    const flags = () => {
      const s = useStore.getState();
      return {
        planner: s.isPlannerView,
        agents: s.isAgentsView,
        storage: s.isStorageView,
        sports: s.isSportsView,
        language: s.isLanguageView,
      };
    };

    it.each<Exclude<ActiveView, 'chat'>>(['planner', 'agents', 'storage', 'sports', 'language'])(
      'switching to %s sets only that view flag',
      (view) => {
        useStore.getState().setActiveView('planner');
        useStore.getState().setActiveView('sports');
        useStore.getState().setActiveView(view);
        const expected = { planner: false, agents: false, storage: false, sports: false, language: false };
        expect(flags()).toEqual({ ...expected, [view]: true });
      }
    );

    it('switching to chat clears every view flag', () => {
      useStore.getState().setActiveView('agents');
      useStore.getState().setActiveView('chat');
      expect(Object.values(flags()).every((f) => !f)).toBe(true);
    });
  });
});
