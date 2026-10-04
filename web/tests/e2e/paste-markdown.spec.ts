import { test, expect } from '../global-setup';

/** Dispatch a paste carrying HTML (and its plain-text form) into the composer. */
async function pasteHtml(page: import('@playwright/test').Page, html: string, text: string): Promise<boolean> {
  return page.locator('#message-input').evaluate(
    (el, { html, text }) => {
      const data = new DataTransfer();
      data.setData('text/html', html);
      data.setData('text/plain', text);
      const event = new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true });
      el.dispatchEvent(event);
      return event.defaultPrevented;
    },
    { html, text }
  );
}

test.describe('Paste rich text', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#message-input');
  });

  test('a formatted page lands as markdown at the cursor, and undo removes it', async ({ page }) => {
    const input = page.locator('#message-input');
    await input.fill('Před  po');
    await input.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(5, 5));

    const handled = await pasteHtml(
      page,
      '<h2>Ceny</h2><ul><li><b>RoS 3</b>: 6 990 Kč</li><li><a href="https://a.cz">obchod</a></li></ul>',
      'Ceny RoS 3: 6 990 Kč obchod'
    );

    expect(handled).toBe(true);
    await expect(input).toHaveValue('Před ## Ceny\n\n- **RoS 3**: 6 990 Kč\n- [obchod](https://a.cz) po');

    // Undo takes the paste back out (WebKit may merge it with the preceding
    // fill into one undo step, so the earlier text can go too)
    await page.keyboard.press('ControlOrMeta+z');
    await expect(input).not.toHaveValue(/Ceny|RoS 3|obchod/);
  });

  test('unformatted HTML pastes as the browser would', async ({ page }) => {
    const handled = await pasteHtml(page, '<span style="color:#ccc">const x = 1;</span>', 'const x = 1;');
    expect(handled).toBe(false);
  });
});
