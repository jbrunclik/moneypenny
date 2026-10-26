/**
 * New Program modals: the language one offers the languages not taken yet
 * and creates with the picked one; the sports one creates with the typed
 * name and the picked icon.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createSportsProgramsElement } from '@/components/SportsDashboard';
import { createLanguageProgramsElement } from '@/components/LanguageDashboard';
import type { LanguageProgram } from '@/types/api';

describe('New Program modals', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('language: lists free languages and creates the picked one', () => {
    const onAdd = vi.fn();
    const taken = { id: 'p', name: 'Czech', emoji: '🇨🇿', created_at: '', updated_at: '' } as unknown as LanguageProgram;
    const page = createLanguageProgramsElement([taken], onAdd, vi.fn(), vi.fn());
    document.body.appendChild(page);
    page.querySelector<HTMLButtonElement>('.language-add-btn')!.click();

    const select = document.querySelector<HTMLSelectElement>('.language-select')!;
    const submit = document.querySelector<HTMLButtonElement>('.language-add-submit')!;
    expect(select.value).toBe('');
    expect(submit.disabled).toBe(true);
    expect([...select.options].some((o) => o.value === 'Czech')).toBe(false);

    select.value = 'German';
    select.dispatchEvent(new Event('change'));
    expect(submit.disabled).toBe(false);
    submit.click();
    expect(onAdd).toHaveBeenCalledWith({ name: 'German', emoji: select.selectedOptions[0]?.dataset.emoji });
  });

  it('sports: creates with the typed name and the picked icon', () => {
    const onAdd = vi.fn();
    const page = createSportsProgramsElement([], onAdd, vi.fn(), vi.fn());
    document.body.appendChild(page);
    page.querySelector<HTMLButtonElement>('.sports-add-btn')!.click();

    document.querySelector<HTMLButtonElement>('.sports-emoji-trigger')!.click();
    const option = document.querySelectorAll<HTMLButtonElement>('.sports-emoji-option')[2]!;
    option.click();
    expect(document.querySelector('.sports-emoji-trigger')?.textContent).toBe(option.dataset.emoji);
    document.querySelector<HTMLInputElement>('.sports-add-name')!.value = 'Climbing';
    document.querySelector<HTMLButtonElement>('.sports-add-submit')!.click();
    expect(onAdd).toHaveBeenCalledWith({ name: 'Climbing', emoji: option.dataset.emoji });
  });
});
