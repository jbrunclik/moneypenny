/**
 * Version banner: the running version comes from the page (#app's
 * data-version); the app polls /api/version right away and then on an
 * interval, and shows "A new version is available" when the server reports
 * a different one. Dismissing hides it for that version only - the same
 * version stays quiet on later polls, a newer one shows again. Polling
 * pauses while the tab is hidden and checks at once on return when the
 * last check is older than the interval. A failed check is silent.
 *
 * The module keeps its banner and timers in module state, so every test
 * loads a fresh copy (vi.resetModules) and removes the document listeners
 * the previous copy added.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { VERSION_CHECK_INTERVAL_MS, STORAGE_KEY_VERSION_DISMISSED } from '@/config';

const api = vi.hoisted(() => ({ get: vi.fn<() => Promise<{ version: string }>>() }));
vi.mock('@/api/app', () => ({ version: api }));

type Store = (typeof import('@/state/store'))['useStore'];

let useStore: Store;
let hidden = false;
let docListenerSpy: ReturnType<typeof vi.spyOn>;

async function boot(pageVersion: string | null): Promise<void> {
  document.body.innerHTML = pageVersion === null ? '<div id="app"></div>' : `<div id="app" data-version="${pageVersion}"></div>`;
  ({ useStore } = await import('@/state/store'));
  const { initVersionBanner } = await import('@/components/VersionBanner');
  initVersionBanner();
  await vi.advanceTimersByTimeAsync(0);
}

const banner = (): HTMLElement => document.querySelector('.version-banner') as HTMLElement;
const bannerVisible = (): boolean => banner().classList.contains('visible');

async function poll(): Promise<void> {
  await vi.advanceTimersByTimeAsync(VERSION_CHECK_INTERVAL_MS);
}

function setHidden(value: boolean): void {
  hidden = value;
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('VersionBanner', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    vi.useFakeTimers();
    localStorage.clear();
    hidden = false;
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
    docListenerSpy = vi.spyOn(document, 'addEventListener');
    api.get.mockResolvedValue({ version: '1.0' });
  });

  afterEach(() => {
    for (const [type, listener] of docListenerSpy.mock.calls as [string, EventListener][]) {
      document.removeEventListener(type, listener);
    }
    docListenerSpy.mockRestore();
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it('takes the running version from the page and checks the server at once', async () => {
    await boot('1.0');
    expect(useStore.getState().appVersion).toBe('1.0');
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(bannerVisible()).toBe(false);
    expect(document.body.firstElementChild).toBe(banner());
  });

  it('adopts the server version when the page carried none, without a banner', async () => {
    api.get.mockResolvedValue({ version: '2.0' });
    await boot(null);
    expect(useStore.getState().appVersion).toBe('2.0');
    expect(bannerVisible()).toBe(false);
  });

  it('shows the banner when the server reports a different version', async () => {
    api.get.mockResolvedValue({ version: '1.1' });
    await boot('1.0');
    expect(bannerVisible()).toBe(true);
    expect(useStore.getState().newVersionAvailable).toBe(true);
    expect(banner().textContent).toContain('A new version is available');
  });

  it('notices a deploy on a later poll', async () => {
    await boot('1.0');
    expect(bannerVisible()).toBe(false);

    api.get.mockResolvedValue({ version: '1.1' });
    await poll();
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(bannerVisible()).toBe(true);
  });

  it('stays dismissed for the dismissed version, and shows again for a newer one', async () => {
    api.get.mockResolvedValue({ version: '1.1' });
    await boot('1.0');
    (banner().querySelector('.version-banner-dismiss') as HTMLElement).click();
    expect(bannerVisible()).toBe(false);
    expect(useStore.getState().versionBannerDismissed).toBe(true);
    expect(localStorage.getItem(STORAGE_KEY_VERSION_DISMISSED)).toBe('1.1');

    await poll();
    expect(bannerVisible()).toBe(false);

    api.get.mockResolvedValue({ version: '1.2' });
    await poll();
    expect(bannerVisible()).toBe(true);
  });

  it('shows a version dismissed in an earlier session until it is dismissed in this one', async () => {
    localStorage.setItem(STORAGE_KEY_VERSION_DISMISSED, '1.1');
    api.get.mockResolvedValue({ version: '1.1' });
    await boot('1.0');
    expect(bannerVisible()).toBe(true);
  });

  it('stays quiet when the check fails', async () => {
    api.get.mockRejectedValue(new Error('offline'));
    await boot('1.0');
    expect(bannerVisible()).toBe(false);
    expect(useStore.getState().newVersionAvailable).toBe(false);
  });

  it('pauses polling while the tab is hidden', async () => {
    await boot('1.0');
    setHidden(true);
    await poll();
    await poll();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('checks at once on return after a long absence, then polls again', async () => {
    await boot('1.0');
    setHidden(true);
    await vi.advanceTimersByTimeAsync(VERSION_CHECK_INTERVAL_MS + 1000);

    api.get.mockResolvedValue({ version: '1.1' });
    setHidden(false);
    await vi.advanceTimersByTimeAsync(0);
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(bannerVisible()).toBe(true);

    await poll();
    expect(api.get).toHaveBeenCalledTimes(3);
  });

  it('does not re-check on a quick return', async () => {
    await boot('1.0');
    setHidden(true);
    await vi.advanceTimersByTimeAsync(1000);
    setHidden(false);
    await vi.advanceTimersByTimeAsync(0);
    expect(api.get).toHaveBeenCalledTimes(1);
  });
});
