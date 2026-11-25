/**
 * The project's share sheet: who has access (the owner first), with Add and
 * Remove on each family member's row, updated in place.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { openShareSheet, type ShareSheetOptions } from '@/components/ShareSheet';
import type { Person } from '@/types/api';

const jana: Person = { id: 'u2', name: 'Jana', picture: null };
const viktor: Person = { id: 'u3', name: 'Viktor', picture: 'https://example.com/v.jpg' };

function options(extra: Partial<ShareSheetOptions> = {}): ShareSheetOptions {
  return {
    projectName: 'Bikes',
    owner: { name: 'Jiří', picture: null },
    people: [jana, viktor],
    memberIds: new Set(['u1', 'u2']),
    onAdd: vi.fn(() => Promise.resolve(true)),
    onRemove: vi.fn(() => Promise.resolve(true)),
    ...extra,
  };
}

function row(name: string): HTMLElement {
  const rows = [...document.querySelectorAll<HTMLElement>('.share-sheet-row')];
  const found = rows.find((r) => r.querySelector('.share-sheet-name')?.textContent === name);
  if (!found) throw new Error(`no row for ${name}`);
  return found;
}

describe('openShareSheet', () => {
  beforeEach(() => {
    document.body.replaceChildren();
  });

  it('lists the owner first, then each person with their access and action', () => {
    openShareSheet(options());

    const sheet = document.getElementById('share-sheet') as HTMLElement;
    expect(sheet.querySelector('.share-sheet-title')?.textContent).toBe('Share “Bikes”');
    const names = [...sheet.querySelectorAll('.share-sheet-name')].map((n) => n.textContent);
    expect(names).toEqual(['Jiří (you)', 'Jana', 'Viktor']);
    expect(row('Jiří (you)').querySelector('.share-sheet-status')?.textContent).toBe('Owner');
    expect(row('Jiří (you)').querySelector('button')).toBeNull();
    expect(row('Jana').querySelector('.share-sheet-status')?.textContent).toBe('Has access');
    expect(row('Jana').querySelector('button')?.textContent).toBe('Remove');
    expect(row('Viktor').querySelector('.share-sheet-status')).toBeNull();
    expect(row('Viktor').querySelector('button')?.textContent).toBe('Add');
    expect(row('Viktor').querySelector('img')?.getAttribute('src')).toBe('https://example.com/v.jpg');
  });

  it('adds a person and flips their row to Remove, keeping the sheet open', async () => {
    const opts = options();
    openShareSheet(opts);

    row('Viktor').querySelector<HTMLButtonElement>('button')?.click();

    expect(opts.onAdd).toHaveBeenCalledWith(viktor);
    await vi.waitFor(() => expect(row('Viktor').querySelector('button')?.textContent).toBe('Remove'));
    expect(row('Viktor').querySelector('.share-sheet-status')?.textContent).toBe('Has access');
    expect(document.getElementById('share-sheet')).not.toBeNull();
  });

  it('removes a person and flips their row to Add; a declined or failed change leaves it', async () => {
    const onRemove = vi.fn<(p: Person) => Promise<boolean>>().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    openShareSheet(options({ onRemove }));

    row('Jana').querySelector<HTMLButtonElement>('button')?.click();
    await vi.waitFor(() => expect(onRemove).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(row('Jana').querySelector('button')?.hasAttribute('disabled')).toBe(false));
    expect(row('Jana').querySelector('button')?.textContent).toBe('Remove');

    row('Jana').querySelector<HTMLButtonElement>('button')?.click();
    await vi.waitFor(() => expect(row('Jana').querySelector('button')?.textContent).toBe('Add'));
  });

  it('closes on Done and on the backdrop', () => {
    openShareSheet(options());
    document.querySelector<HTMLButtonElement>('.share-sheet-done')?.click();
    expect(document.getElementById('share-sheet')).toBeNull();

    openShareSheet(options());
    document.getElementById('share-sheet')?.click();
    expect(document.getElementById('share-sheet')).toBeNull();
  });
});
