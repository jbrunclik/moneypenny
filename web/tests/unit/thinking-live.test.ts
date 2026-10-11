/**
 * The live thinking line (Oct 2026 review): while a reply is being worked
 * on, the indicator is ONE line - the current step, and for thinking only
 * its latest heading. The full trace streamed in, filled the screen and
 * pushed the answer out of view. Tap expands it; the answer starting
 * collapses it to the finished summary.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  addThinkingToTrace,
  addToolStartToTrace,
  collapseThinkingIndicator,
  createThinkingIndicator,
  createThinkingState,
  latestThoughtHeading,
  markToolCompletedInTrace,
  updateThinkingIndicator,
} from '../../src/components/ThinkingIndicator';
import type { ThinkingState } from '../../src/types/api';

const THOUGHTS =
  "**Understanding the User's Intent**\n\nI'm now focusing on the Sage.\n\n" +
  '**Reframing the User\'s Needs**\n\nI now suggest single-dosing for the grinder.';

describe('latestThoughtHeading', () => {
  it('is the last bold heading line', () => {
    expect(latestThoughtHeading(THOUGHTS)).toBe("Reframing the User's Needs");
  });

  it('takes a markdown heading too', () => {
    expect(latestThoughtHeading('## Checking the weather\n\nLooking it up')).toBe('Checking the weather');
  });

  it('falls back to the last line, shortened, without markdown', () => {
    const heading = latestThoughtHeading(`First line\n\nThe *latest* line is ${'very '.repeat(30)}long`);
    expect(heading.startsWith('The latest line is very')).toBe(true);
    expect(heading.length).toBeLessThanOrEqual(81);
  });

  it('is empty for no text', () => {
    expect(latestThoughtHeading('')).toBe('');
  });
});

describe('the live line', () => {
  let indicator: HTMLElement;
  let state: ThinkingState;

  beforeEach(() => {
    indicator = createThinkingIndicator();
    document.body.replaceChildren(indicator);
    state = createThinkingState();
  });

  it('marks one current step: the thinking, showing its latest heading', () => {
    addThinkingToTrace(state, THOUGHTS);
    updateThinkingIndicator(indicator, state);

    const current = indicator.querySelectorAll('.thinking-trace-item.current');
    expect(current).toHaveLength(1);
    expect(current[0].querySelector('.thinking-heading')?.textContent).toBe("Reframing the User's Needs");
    // The full text stays in the DOM for the expanded view
    expect(current[0].querySelector('.thinking-markdown')?.textContent).toContain('single-dosing');
  });

  it('marks the running tool current, and the last tool once it is done', () => {
    addThinkingToTrace(state, THOUGHTS);
    addToolStartToTrace(state, 'web_search', 'sage barista touch');
    updateThinkingIndicator(indicator, state);
    expect(indicator.querySelector('.thinking-trace-item.current')?.textContent).toContain('sage barista touch');

    markToolCompletedInTrace(state, 'web_search');
    updateThinkingIndicator(indicator, state);
    expect(indicator.querySelector('.thinking-trace-item.current')?.textContent).toContain('sage barista touch');
  });

  it('is collapsed by default, and a tap expands it across updates', () => {
    addThinkingToTrace(state, THOUGHTS);
    updateThinkingIndicator(indicator, state);
    const toggle = (): HTMLButtonElement => indicator.querySelector<HTMLButtonElement>('.thinking-live-expand')!;
    expect(indicator.classList.contains('live-expanded')).toBe(false);
    expect(toggle().getAttribute('aria-expanded')).toBe('false');

    toggle().click();
    expect(indicator.classList.contains('live-expanded')).toBe(true);
    addThinkingToTrace(state, `${THOUGHTS}\n\nMore.`);
    updateThinkingIndicator(indicator, state);
    expect(indicator.classList.contains('live-expanded')).toBe(true);
    expect(toggle().getAttribute('aria-expanded')).toBe('true');

    toggle().click();
    expect(indicator.classList.contains('live-expanded')).toBe(false);
  });
});

describe('collapseThinkingIndicator (the answer started)', () => {
  let indicator: HTMLElement;
  let state: ThinkingState;

  beforeEach(() => {
    indicator = createThinkingIndicator();
    document.body.replaceChildren(indicator);
    state = createThinkingState();
  });

  it('becomes the finished summary toggle, closed', () => {
    addThinkingToTrace(state, THOUGHTS);
    updateThinkingIndicator(indicator, state);
    collapseThinkingIndicator(indicator, state);

    expect(indicator.querySelector('.thinking-toggle')?.getAttribute('aria-expanded')).toBe('false');
    expect(indicator.querySelector('.thinking-details')?.hasAttribute('hidden')).toBe(true);
    expect(indicator.querySelector('.thinking-indicator-content')).toBeNull();
  });

  it('stays open when the user had expanded the live view', () => {
    addThinkingToTrace(state, THOUGHTS);
    updateThinkingIndicator(indicator, state);
    indicator.querySelector<HTMLButtonElement>('.thinking-live-expand')!.click();
    collapseThinkingIndicator(indicator, state);

    expect(indicator.querySelector('.thinking-toggle')?.getAttribute('aria-expanded')).toBe('true');
    expect(indicator.querySelector('.thinking-details')?.hasAttribute('hidden')).toBe(false);
  });

  it('hides (not removes) an empty trace, so a later round can still show', () => {
    state.isThinking = false;
    collapseThinkingIndicator(indicator, state);
    expect(indicator.isConnected).toBe(true);
    expect(indicator.hidden).toBe(true);

    addToolStartToTrace(state, 'web_search', 'next round');
    updateThinkingIndicator(indicator, state);
    expect(indicator.hidden).toBe(false);
    expect(indicator.querySelector('.thinking-trace-item.current')?.textContent).toContain('next round');
  });

  it('a later round reopens the live line', () => {
    addThinkingToTrace(state, THOUGHTS);
    updateThinkingIndicator(indicator, state);
    collapseThinkingIndicator(indicator, state);

    addToolStartToTrace(state, 'web_search', 'second round');
    updateThinkingIndicator(indicator, state);
    expect(indicator.querySelector('.thinking-toggle')).toBeNull();
    expect(indicator.querySelector('.thinking-trace-item.current')?.textContent).toContain('second round');
  });
});
