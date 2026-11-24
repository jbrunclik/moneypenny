/**
 * E2E: saved documents (document memory) on the Data page - a saved document
 * shows what it holds and when it is used, delete moves it to Recently
 * deleted, restore brings it back. Desktop and mobile.
 */
import { test, expect } from '../global-setup';

for (const [name, viewport] of [
  ['desktop', { width: 1280, height: 800 }],
  ['mobile', { width: 375, height: 812 }],
] as const) {
  test(`a saved document can be deleted and restored on the Data page (${name})`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const seeded = await page.request.post('/test/seed-document', {
      data: { title: 'Flat lease', valid_until: '2099-06-30' },
    });
    expect(seeded.ok()).toBeTruthy();

    await page.goto('/#/storage');
    const section = page.locator('.kv-doc-section');
    const row = section.locator('.kv-doc-item', { hasText: 'Flat lease' });
    await expect(row).toBeVisible();
    await expect(row.locator('.kv-doc-use-for')).toHaveText('Use for: Rent and notice questions');
    await expect(row.locator('.memory-until-badge')).toContainText('Until');

    await row.locator('.kv-doc-delete').click();
    await page.locator('.modal-confirm').click();
    await expect(section.locator('.kv-doc-item')).toHaveCount(0);
    await expect(section).toContainText('No documents yet');

    // The deleted list is rendered on load: reopen the page to see it
    await page.locator('.btn-refresh').click();
    const deleted = page.locator('.kv-doc-deleted', { hasText: 'Flat lease' });
    await expect(deleted).toBeVisible();
    await deleted.locator('.kv-doc-restore').click();
    await expect(deleted).toHaveCount(0);

    await page.locator('.btn-refresh').click();
    await expect(page.locator('.kv-doc-section .kv-doc-item', { hasText: 'Flat lease' })).toBeVisible();
  });
}
