/**
 * Word documents and voice memos can be attached (Nov 16 2026: both were
 * refused as "File type not allowed"). The server reads the document as text
 * and hands the audio to the model; here, the composer takes them and the
 * sent message shows them as attachments.
 */
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { test, expect } from './fixtures';
import { appReady } from '../waits';

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'fixtures');
const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

const files = [
  { name: 'Trip plan.docx', mimeType: DOCX, buffer: readFileSync(join(FIXTURES, 'tiny.docx')) },
  { name: 'Memo 12.m4a', mimeType: 'audio/x-m4a', buffer: readFileSync(join(FIXTURES, 'tiny.m4a')) },
];

for (const viewport of [
  { label: 'desktop', size: null },
  { label: 'phone', size: { width: 390, height: 844 } },
]) {
  test(`a Word document and a voice memo attach and send (${viewport.label})`, async ({ page }) => {
    await page.goto('/');
    await appReady(page);
    await page.click('#new-chat-btn');
    // After setup: on a phone New Chat sits in the hidden sidebar
    if (viewport.size) await page.setViewportSize(viewport.size);

    await page.locator('#file-input').setInputFiles(files);
    await expect(page.locator('.file-preview-item')).toHaveCount(2);

    await page.fill('#message-input', 'What is in these?');
    await page.click('#send-btn');

    const sent = page.locator('.message.user').last();
    await expect(sent.locator('.document-name')).toHaveText(['Trip plan.docx', 'Memo 12.m4a']);
    await expect(page.locator('.message.assistant:not(.streaming)').last()).toBeVisible({ timeout: 20000 });
  });
}
