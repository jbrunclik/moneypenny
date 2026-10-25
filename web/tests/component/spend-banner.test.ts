import { beforeEach, describe, expect, it, vi } from 'vitest';
import { admin } from '@/api/admin';
import { refreshSpendWarning } from '@/components/SpendBanner';

const status = (over: boolean) => ({
  today: { usd: over ? 12.4 : 1, formatted: over ? '285.20 Kč' : '23.00 Kč' },
  threshold_usd: 10,
  over_threshold: over,
});

describe('spend warning banner', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main><div id="messages"></div></main>';
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('appears above the messages when today is past the threshold', async () => {
    vi.spyOn(admin, 'getSpendStatus').mockResolvedValue(status(true));
    await refreshSpendWarning();
    const banner = document.querySelector('.spend-banner');
    expect(banner?.textContent).toContain('285.20 Kč');
    expect(banner?.textContent).toContain('let the admin know');
    expect(banner?.nextElementSibling?.id).toBe('messages');
  });

  it('stays away under the threshold', async () => {
    vi.spyOn(admin, 'getSpendStatus').mockResolvedValue(status(false));
    await refreshSpendWarning();
    expect(document.querySelector('.spend-banner')).toBeNull();
  });

  it('stays dismissed for the rest of the day', async () => {
    vi.spyOn(admin, 'getSpendStatus').mockResolvedValue(status(true));
    await refreshSpendWarning();
    document.querySelector<HTMLButtonElement>('.spend-banner-dismiss')!.click();
    expect(document.querySelector('.spend-banner')).toBeNull();
    await refreshSpendWarning();
    expect(document.querySelector('.spend-banner')).toBeNull();
  });

  it('is not shown twice', async () => {
    vi.spyOn(admin, 'getSpendStatus').mockResolvedValue(status(true));
    await refreshSpendWarning();
    await refreshSpendWarning();
    expect(document.querySelectorAll('.spend-banner')).toHaveLength(1);
  });

  it('never surfaces an error when the status call fails', async () => {
    vi.spyOn(admin, 'getSpendStatus').mockRejectedValue(new Error('offline'));
    await expect(refreshSpendWarning()).resolves.toBeUndefined();
    expect(document.querySelector('.spend-banner')).toBeNull();
  });
});
