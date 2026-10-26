/**
 * Startup routing: the URL hash becomes the initial route (one view flag,
 * or a conversation id - never a temp one), and openInitialRoute opens that
 * view: a sports or language program deep link opens the program, a
 * conversation id that is not a valid id opens nothing, and so does home.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const nav = vi.hoisted(() => ({
  navigateToAgents: vi.fn(() => Promise.resolve()),
  navigateToArchive: vi.fn(),
  loadDeepLinkedConversation: vi.fn(() => Promise.resolve()),
  navigateToStorage: vi.fn(() => Promise.resolve()),
  navigateToLanguage: vi.fn(() => Promise.resolve()),
  navigateToLanguageProgram: vi.fn(() => Promise.resolve()),
  navigateToPlanner: vi.fn(() => Promise.resolve()),
  navigateToSports: vi.fn(() => Promise.resolve()),
  navigateToSportsProgram: vi.fn(() => Promise.resolve()),
  navigateToTrash: vi.fn(),
}));

vi.mock('@/core/agents', () => ({ navigateToAgents: nav.navigateToAgents }));
vi.mock('@/core/archive', () => ({ navigateToArchive: nav.navigateToArchive }));
vi.mock('@/core/conversation-deeplink', () => ({ loadDeepLinkedConversation: nav.loadDeepLinkedConversation }));
vi.mock('@/core/kv-store', () => ({ navigateToStorage: nav.navigateToStorage }));
vi.mock('@/core/language', () => ({
  navigateToLanguage: nav.navigateToLanguage,
  navigateToLanguageProgram: nav.navigateToLanguageProgram,
}));
vi.mock('@/core/planner', () => ({ navigateToPlanner: nav.navigateToPlanner }));
vi.mock('@/core/sports', () => ({
  navigateToSports: nav.navigateToSports,
  navigateToSportsProgram: nav.navigateToSportsProgram,
}));
vi.mock('@/core/trash', () => ({ navigateToTrash: nav.navigateToTrash }));

import { initialRouteFromHash, openInitialRoute } from '@/core/startup/initial-route';
import type { InitialRoute } from '@/router/deeplink';

const HOME: InitialRoute = {
  conversationId: null,
  isPlanner: false,
  isAgents: false,
  isStorage: false,
  isSports: false,
  isLanguage: false,
  isArchive: false,
  isTrash: false,
};

function setHash(hash: string): void {
  window.history.replaceState(null, '', `/${hash}`);
}

const calledNavigations = (): string[] =>
  Object.entries(nav)
    .filter(([, fn]) => fn.mock.calls.length > 0)
    .map(([name]) => name);

describe('initialRouteFromHash', () => {
  it('reads home from an empty hash', () => {
    setHash('');
    expect(initialRouteFromHash()).toEqual(HOME);
  });

  it('reads a conversation id', () => {
    setHash('#/conversations/abc-123');
    expect(initialRouteFromHash()).toEqual({ ...HOME, conversationId: 'abc-123' });
  });

  it('ignores a temp conversation id in the URL', () => {
    setHash('#/conversations/temp-1');
    expect(initialRouteFromHash()).toEqual(HOME);
  });

  it.each([
    ['#/planner', 'isPlanner'],
    ['#/agents', 'isAgents'],
    ['#/storage', 'isStorage'],
    ['#/sports', 'isSports'],
    ['#/sports/strength', 'isSports'],
    ['#/language/czech', 'isLanguage'],
    ['#/archive', 'isArchive'],
    ['#/trash', 'isTrash'],
  ])('reads %s as the %s view', (hash, flag) => {
    setHash(hash);
    expect(initialRouteFromHash()).toEqual({ ...HOME, [flag]: true });
  });

  it('treats an unknown route as home', () => {
    setHash('#/nowhere/at/all');
    expect(initialRouteFromHash()).toEqual(HOME);
  });
});

describe('openInitialRoute', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setHash('');
  });

  it('opens nothing without a route or for home', async () => {
    await openInitialRoute(null);
    await openInitialRoute(undefined);
    await openInitialRoute(HOME);
    expect(calledNavigations()).toEqual([]);
  });

  it.each([
    ['isPlanner', 'navigateToPlanner'],
    ['isAgents', 'navigateToAgents'],
    ['isStorage', 'navigateToStorage'],
    ['isSports', 'navigateToSports'],
    ['isLanguage', 'navigateToLanguage'],
    ['isArchive', 'navigateToArchive'],
    ['isTrash', 'navigateToTrash'],
  ])('opens the %s view with %s only', async (flag, navigation) => {
    await openInitialRoute({ ...HOME, [flag]: true });
    expect(calledNavigations()).toEqual([navigation]);
  });

  it('opens the sports program named in the hash', async () => {
    setHash('#/sports/strength');
    await openInitialRoute({ ...HOME, isSports: true });
    expect(nav.navigateToSportsProgram).toHaveBeenCalledWith('strength');
    expect(nav.navigateToSports).not.toHaveBeenCalled();
  });

  it('opens the language program named in the hash', async () => {
    setHash('#/language/czech');
    await openInitialRoute({ ...HOME, isLanguage: true });
    expect(nav.navigateToLanguageProgram).toHaveBeenCalledWith('czech');
    expect(nav.navigateToLanguage).not.toHaveBeenCalled();
  });

  it('loads a deep-linked conversation', async () => {
    await openInitialRoute({ ...HOME, conversationId: 'abc-123' });
    expect(nav.loadDeepLinkedConversation).toHaveBeenCalledWith('abc-123');
  });

  it('ignores a conversation id with invalid characters', async () => {
    await openInitialRoute({ ...HOME, conversationId: 'abc<script>' });
    expect(calledNavigations()).toEqual([]);
  });

  it('waits for the view to open', async () => {
    let finish!: () => void;
    nav.navigateToPlanner.mockReturnValueOnce(new Promise<void>((resolve) => (finish = resolve)));
    let opened = false;
    const run = openInitialRoute({ ...HOME, isPlanner: true }).then(() => {
      opened = true;
    });
    await Promise.resolve();
    expect(opened).toBe(false);
    finish();
    await run;
    expect(opened).toBe(true);
  });
});
