import { beforeEach, describe, expect, it } from 'vitest';
import { useStore } from '@/state/store';

describe('live artifacts of a running turn', () => {
  beforeEach(() => {
    useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream', content: '' });
  });

  it('keeps the latest version of each artifact, for restoring after a switch', () => {
    const store = useStore.getState();
    store.addActiveRequestArtifact('c1', { id: 'a', version: 1, title: 'T' });
    store.addActiveRequestArtifact('c1', { id: 'b', version: 1, title: 'U' });
    store.addActiveRequestArtifact('c1', { id: 'a', version: 2, title: 'T' });
    expect(useStore.getState().getActiveRequest('c1')?.artifacts).toEqual([
      { id: 'a', version: 2, title: 'T' },
      { id: 'b', version: 1, title: 'U' },
    ]);
  });

  it('ignores a conversation with no running turn', () => {
    useStore.getState().addActiveRequestArtifact('nope', { id: 'a', version: 1, title: 'T' });
    expect(useStore.getState().getActiveRequest('nope')).toBeUndefined();
  });
});
