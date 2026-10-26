/**
 * The sandboxed frame's entry (src/artifact/frame.ts): says ready, renders
 * only the first init from its parent, follows theme changes, and ignores
 * anything from elsewhere or malformed.
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ToFrame } from '../../src/artifact/protocol';

const client = vi.hoisted(() => ({ applyTheme: vi.fn(), applyInit: vi.fn() }));
const loader = vi.hoisted(() => ({ loadArtifact: vi.fn(() => Promise.resolve()) }));
vi.mock('../../src/artifact/bridge-client', () => ({ installBridgeClient: () => client }));
vi.mock('../../src/artifact/loader', () => loader);

let posted: unknown[];

/** A message as the parent (in a test page, the window is its own parent) sends it. */
function fromParent(data: ToFrame | Record<string, unknown>, source: Window | null = window.parent): void {
  window.dispatchEvent(new MessageEvent('message', { data, source }));
}

describe('artifact frame entry', () => {
  beforeAll(async () => {
    posted = [];
    vi.spyOn(window.parent, 'postMessage').mockImplementation((message: unknown) => void posted.push(message));
    await import('../../src/artifact/frame');
  });

  beforeEach(() => {
    client.applyTheme.mockClear();
  });

  it('says ready on load', () => {
    expect(posted).toEqual([{ type: 'mp:ready' }]);
  });

  it('ignores malformed messages and messages from other windows', () => {
    fromParent({ type: 'mp:init', html: 42, theme: 'dark', state: null });
    fromParent({ type: 'mp:init', html: '<p>x</p>', theme: 'dark', state: null }, null);
    expect(client.applyInit).not.toHaveBeenCalled();
    expect(loader.loadArtifact).not.toHaveBeenCalled();
  });

  it('renders the first init and reports it rendered; later inits are ignored', async () => {
    fromParent({ type: 'mp:init', html: '<p>hi</p>', theme: 'dark', state: { n: 1 } });
    fromParent({ type: 'mp:init', html: '<p>again</p>', theme: 'light', state: null });

    expect(client.applyInit).toHaveBeenCalledExactlyOnceWith({ n: 1 }, 'dark');
    expect(loader.loadArtifact).toHaveBeenCalledExactlyOnceWith(document, '<p>hi</p>');
    await vi.waitFor(() => expect(posted).toContainEqual({ type: 'mp:rendered' }));
  });

  it('follows theme changes', () => {
    fromParent({ type: 'mp:theme', theme: 'light' });
    expect(client.applyTheme).toHaveBeenCalledWith('light');
  });
});
