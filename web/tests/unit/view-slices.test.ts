/**
 * Slices behind the secondary views (agents, sports, language, storage) and
 * search. The views cache their data with a last-fetch timestamp: setting data
 * stamps it, setting null or invalidating clears it (forcing a refetch).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { initialAgentsData } from '@/state/slices/agents';
import { initialLanguageData } from '@/state/slices/language';
import { initialSportsData } from '@/state/slices/sports';
import { initialStorageData } from '@/state/slices/storage';
import { initialSearchData } from '@/state/slices/search';
import type {
  Agent,
  CommandCenterResponse,
  KVNamespacesResponse,
  LanguageProgram,
  SearchResult,
  SportsProgram,
} from '@/types/api';

const NOW = new Date('2026-10-26T10:00:00Z').getTime();

// The payloads are opaque to these slices; only identity and null-ness matter
const opaque = <T>(label: string) => ({ label }) as unknown as T;

interface CacheCase {
  name: string;
  set: (data: unknown) => void;
  invalidate: () => void;
  clear: () => void;
  data: () => unknown;
  lastFetch: () => number | null;
  initial: () => object;
}

const s = () => useStore.getState();

const cases: CacheCase[] = [
  {
    name: 'agents command center',
    set: (d) => s().setCommandCenterData(d as CommandCenterResponse | null),
    invalidate: () => s().invalidateCommandCenterCache(),
    clear: () => s().clearAgentsState(),
    data: () => s().commandCenterData,
    lastFetch: () => s().commandCenterLastFetch,
    initial: initialAgentsData,
  },
  {
    name: 'sports programs',
    set: (d) => s().setSportsPrograms(d as SportsProgram[] | null),
    invalidate: () => s().invalidateSportsCache(),
    clear: () => s().clearSportsState(),
    data: () => s().sportsPrograms,
    lastFetch: () => s().sportsProgramsLastFetch,
    initial: initialSportsData,
  },
  {
    name: 'language programs',
    set: (d) => s().setLanguagePrograms(d as LanguageProgram[] | null),
    invalidate: () => s().invalidateLanguageCache(),
    clear: () => s().clearLanguageState(),
    data: () => s().languagePrograms,
    lastFetch: () => s().languageProgramsLastFetch,
    initial: initialLanguageData,
  },
  {
    name: 'storage namespaces',
    set: (d) => s().setStorageData(d as KVNamespacesResponse | null),
    invalidate: () => s().invalidateStorageCache(),
    clear: () => s().clearStorageState(),
    data: () => s().storageData,
    lastFetch: () => s().storageLastFetch,
    initial: initialStorageData,
  },
];

describe.each(cases)('$name cache', (c) => {
  beforeEach(() => {
    useStore.setState(useStore.getInitialState(), true);
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('setting data stamps the fetch time', () => {
    const payload = opaque<unknown>('x');
    c.set(payload);
    expect(c.data()).toBe(payload);
    expect(c.lastFetch()).toBe(NOW);
  });

  it('setting null clears the fetch time', () => {
    c.set(opaque<unknown>('x'));
    c.set(null);
    expect(c.data()).toBeNull();
    expect(c.lastFetch()).toBeNull();
  });

  it('invalidating keeps the data but forces a refetch', () => {
    const payload = opaque<unknown>('x');
    c.set(payload);
    c.invalidate();
    expect(c.data()).toBe(payload);
    expect(c.lastFetch()).toBeNull();
  });

  it('clearing resets to the initial state', () => {
    c.set(opaque<unknown>('x'));
    c.clear();
    const state = useStore.getState() as unknown as Record<string, unknown>;
    for (const [key, value] of Object.entries(c.initial())) {
      expect(state[key]).toEqual(value);
    }
  });
});

describe('agents list', () => {
  const agent = (id: string, name = id) => ({ id, name }) as unknown as Agent;

  beforeEach(() => {
    useStore.setState(useStore.getInitialState(), true);
  });

  it('addAgent puts the new agent first', () => {
    s().setAgents([agent('a')]);
    s().addAgent(agent('b'));
    expect(s().agents.map((a) => a.id)).toEqual(['b', 'a']);
  });

  it('updateAgent merges into the matching agent only', () => {
    s().setAgents([agent('a'), agent('b')]);
    s().updateAgent('b', { name: 'renamed' });
    expect(s().agents.map((a) => a.name)).toEqual(['a', 'renamed']);
  });

  it('removeAgent drops the agent', () => {
    s().setAgents([agent('a'), agent('b')]);
    s().removeAgent('a');
    expect(s().agents.map((a) => a.id)).toEqual(['b']);
  });
});

describe('search slice', () => {
  const result = (n: number) => ({ conversation_id: `c${n}` }) as unknown as SearchResult;

  beforeEach(() => {
    useStore.setState(useStore.getInitialState(), true);
  });

  function populate(): void {
    s().activateSearch();
    s().setSearchQuery('milk');
    s().setSearchResults([result(1), result(2)], 2);
    s().setIsSearching(true);
    s().setViewedSearchResult(1);
  }

  it('deactivateSearch hides the UI and drops query and results but leaves isSearching alone', () => {
    populate();
    s().deactivateSearch();
    expect(s()).toMatchObject({
      isSearchActive: false,
      searchQuery: '',
      searchResults: [],
      searchTotal: 0,
      viewedSearchResultId: null,
      isSearching: true,
    });
  });

  it('clearSearch resets everything to the initial state', () => {
    populate();
    s().clearSearch();
    expect(s()).toMatchObject(initialSearchData());
  });
});
