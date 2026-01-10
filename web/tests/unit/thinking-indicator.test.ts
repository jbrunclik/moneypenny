/**
 * Unit tests for ThinkingIndicator component
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  createThinkingIndicator,
  updateThinkingIndicator,
  finalizeThinkingIndicator,
  createThinkingState,
  addThinkingToTrace,
  addToolStartToTrace,
  markToolCompletedInTrace,
  updateToolDetailInTrace,
} from '../../src/components/ThinkingIndicator';
import type { ThinkingState, ToolMetadata } from '../../src/types/api';

// Test metadata matching backend TOOL_METADATA
const TOOL_METADATA: Record<string, ToolMetadata> = {
  web_search: { label: 'Searching the web', label_past: 'Searched', icon: 'search' },
  fetch_url: { label: 'Fetching page', label_past: 'Fetched', icon: 'link' },
  generate_image: { label: 'Generating image', label_past: 'Generated image', icon: 'sparkles' },
  execute_code: { label: 'Running code', label_past: 'Ran code', icon: 'code' },
  todoist: { label: 'Managing tasks', label_past: 'Managed tasks', icon: 'checklist' },
};

describe('ThinkingIndicator', () => {
  describe('createThinkingIndicator', () => {
    it('should create a thinking indicator element', () => {
      const indicator = createThinkingIndicator();

      expect(indicator).toBeInstanceOf(HTMLElement);
      expect(indicator.className).toBe('thinking-indicator');
      expect(indicator.getAttribute('aria-live')).toBe('polite');
    });

    it('should contain initial thinking trace item', () => {
      const indicator = createThinkingIndicator();

      const traceItem = indicator.querySelector('.thinking-trace-item');
      expect(traceItem).toBeTruthy();

      const label = indicator.querySelector('.thinking-label');
      expect(label?.textContent).toBe('Thinking');

      const dots = indicator.querySelector('.thinking-dots');
      expect(dots).toBeTruthy();
    });
  });

  describe('createThinkingState', () => {
    it('should create initial thinking state with empty trace', () => {
      const state = createThinkingState();

      expect(state.isThinking).toBe(true);
      expect(state.thinkingText).toBe('');
      expect(state.activeTool).toBeNull();
      expect(state.completedTools).toEqual([]);
      // Trace starts empty - thinking is added at the END when it arrives
      // This ensures thinking stays at bottom during streaming for auto-scroll
      expect(state.trace).toEqual([]);
    });
  });

  describe('trace helper functions', () => {
    let state: ThinkingState;

    beforeEach(() => {
      state = createThinkingState();
    });

    it('addThinkingToTrace should add thinking item at the end', () => {
      addThinkingToTrace(state, 'Analyzing the question');

      expect(state.trace.length).toBe(1);
      expect(state.trace[0].type).toBe('thinking');
      expect(state.trace[0].detail).toBe('Analyzing the question');
      expect(state.trace[0].completed).toBe(false);
      expect(state.thinkingText).toBe('Analyzing the question');
    });

    it('addThinkingToTrace should update existing thinking item', () => {
      addThinkingToTrace(state, 'First thought');
      addThinkingToTrace(state, 'Updated thought');

      expect(state.trace.length).toBe(1);
      expect(state.trace[0].detail).toBe('Updated thought');
    });

    it('addToolStartToTrace should add tool BEFORE thinking and mark thinking as completed', () => {
      addThinkingToTrace(state, 'Thinking...');
      addToolStartToTrace(state, 'web_search', 'best restaurants');

      expect(state.trace.length).toBe(2);
      // Tool is inserted BEFORE thinking to keep thinking at the end for auto-scroll
      expect(state.trace[0].type).toBe('tool');
      expect(state.trace[0].label).toBe('web_search');
      expect(state.trace[0].detail).toBe('best restaurants');
      // Thinking is now at the end and marked completed
      expect(state.trace[1].type).toBe('thinking');
      expect(state.trace[1].completed).toBe(true);
      expect(state.activeTool).toBe('web_search');
    });

    it('markToolCompletedInTrace should mark tool as completed', () => {
      addThinkingToTrace(state, 'Thinking...');
      addToolStartToTrace(state, 'web_search', 'query');
      markToolCompletedInTrace(state, 'web_search');

      // trace[0] is the tool (marked completed by markToolCompletedInTrace)
      // trace[1] is thinking (at the end for auto-scroll)
      expect(state.trace[0].type).toBe('tool');
      expect(state.trace[0].completed).toBe(true);
      expect(state.completedTools).toContain('web_search');
      expect(state.activeTool).toBeNull();
    });

    it('thinking should remain singleton when updated after tool completes', () => {
      addThinkingToTrace(state, 'Initial thinking');
      addToolStartToTrace(state, 'web_search', 'query');
      markToolCompletedInTrace(state, 'web_search');
      // More thinking after tool completes
      addThinkingToTrace(state, 'More thinking after tool');

      // Should still be only 2 items: tool + thinking (thinking at end for auto-scroll)
      expect(state.trace.length).toBe(2);
      expect(state.trace[0].type).toBe('tool');
      expect(state.trace[1].type).toBe('thinking');
      expect(state.trace[1].detail).toBe('More thinking after tool');
      expect(state.trace[1].completed).toBe(false); // Now active again
    });

    describe('updateToolDetailInTrace', () => {
      it('should update detail for active tool', () => {
        addToolStartToTrace(state, 'todoist');
        updateToolDetailInTrace(state, 'todoist', 'list_tasks: today');

        expect(state.trace[0].detail).toBe('list_tasks: today');
        expect(state.activeToolDetail).toBe('list_tasks: today');
      });

      it('should not update completed tool', () => {
        addToolStartToTrace(state, 'web_search', 'initial query');
        markToolCompletedInTrace(state, 'web_search');

        updateToolDetailInTrace(state, 'web_search', 'new query');

        // Detail unchanged because tool is completed
        expect(state.trace[0].detail).toBe('initial query');
      });

      it('should update correct tool when multiple tools in trace', () => {
        addThinkingToTrace(state, 'Thinking...');
        addToolStartToTrace(state, 'web_search', 'query 1');
        markToolCompletedInTrace(state, 'web_search');
        addToolStartToTrace(state, 'todoist');

        updateToolDetailInTrace(state, 'todoist', 'add_task: Buy milk');

        // Second tool (todoist) at index 1 should be updated
        expect(state.trace[1].label).toBe('todoist');
        expect(state.trace[1].detail).toBe('add_task: Buy milk');
        expect(state.activeToolDetail).toBe('add_task: Buy milk');
      });

      it('should not update detail for wrong tool name', () => {
        addToolStartToTrace(state, 'web_search', 'initial query');

        updateToolDetailInTrace(state, 'fetch_url', 'https://example.com');

        // web_search unchanged - detail stays as 'initial query'
        expect(state.trace[0].detail).toBe('initial query');
        // activeToolDetail set by addToolStartToTrace, not changed by updateToolDetailInTrace for wrong tool
        expect(state.activeToolDetail).toBe('initial query');
      });
    });
  });

  describe('updateThinkingIndicator', () => {
    let indicator: HTMLElement;
    let state: ThinkingState;

    beforeEach(() => {
      indicator = createThinkingIndicator();
      state = createThinkingState();
    });

    it('should show thinking trace item when isThinking is true', () => {
      state.isThinking = true;
      updateThinkingIndicator(indicator, state);

      const traceItem = indicator.querySelector('.thinking-trace-item');
      expect(traceItem).toBeTruthy();
    });

    it('should show active tool when activeTool is set via trace', () => {
      addToolStartToTrace(state, 'web_search', 'test query', TOOL_METADATA.web_search);
      updateThinkingIndicator(indicator, state);

      const tool = indicator.querySelector('.thinking-trace-item.active');
      expect(tool).toBeTruthy();

      const label = tool?.querySelector('.thinking-label');
      expect(label?.textContent).toBe('Searching the web');
    });

    it('should show completed tools in trace', () => {
      addThinkingToTrace(state, 'Initial thinking');
      addToolStartToTrace(state, 'web_search');
      markToolCompletedInTrace(state, 'web_search');
      addToolStartToTrace(state, 'fetch_url', 'https://example.com');
      markToolCompletedInTrace(state, 'fetch_url');
      updateThinkingIndicator(indicator, state);

      // 3 items: 2 tools + thinking (thinking at end, marked completed when tools start)
      const completedTools = indicator.querySelectorAll('.thinking-trace-item.completed');
      expect(completedTools.length).toBe(3);
    });

    it('should use correct label for generate_image tool', () => {
      addToolStartToTrace(state, 'generate_image', 'a blue circle', TOOL_METADATA.generate_image);
      updateThinkingIndicator(indicator, state);

      const label = indicator.querySelector('.thinking-trace-item.active .thinking-label');
      expect(label?.textContent).toBe('Generating image');
    });

    it('should use correct label for fetch_url tool', () => {
      addToolStartToTrace(state, 'fetch_url', 'https://example.com', TOOL_METADATA.fetch_url);
      updateThinkingIndicator(indicator, state);

      const label = indicator.querySelector('.thinking-trace-item.active .thinking-label');
      expect(label?.textContent).toBe('Fetching page');
    });

    it('should show fallback label for unknown tool', () => {
      addToolStartToTrace(state, 'unknown_tool');
      updateThinkingIndicator(indicator, state);

      const label = indicator.querySelector('.thinking-trace-item.active .thinking-label');
      expect(label?.textContent).toBe('Running unknown_tool');
    });

    it('should use correct label for todoist tool', () => {
      addToolStartToTrace(state, 'todoist', 'list_tasks: today', TOOL_METADATA.todoist);
      updateThinkingIndicator(indicator, state);

      const label = indicator.querySelector('.thinking-trace-item.active .thinking-label');
      expect(label?.textContent).toBe('Managing tasks');
    });

    it('should show tool detail when provided', () => {
      addToolStartToTrace(state, 'web_search', 'best pizza in town');
      updateThinkingIndicator(indicator, state);

      const detail = indicator.querySelector('.thinking-detail');
      expect(detail?.textContent).toContain('best pizza in town');
    });
  });

  describe('finalizeThinkingIndicator', () => {
    let indicator: HTMLElement;
    let state: ThinkingState;

    beforeEach(() => {
      indicator = createThinkingIndicator();
      state = createThinkingState();
    });

    it('should remove indicator if no meaningful content', () => {
      state.thinkingText = '';
      state.completedTools = [];
      state.trace = [];

      // Add to DOM so we can check removal
      document.body.appendChild(indicator);
      finalizeThinkingIndicator(indicator, state);

      expect(document.body.contains(indicator)).toBe(false);
    });

    it('should add finalized class when there is trace content', () => {
      addThinkingToTrace(state, 'Some thinking');
      finalizeThinkingIndicator(indicator, state);

      expect(indicator.classList.contains('finalized')).toBe(true);
    });

    it('should create collapsible toggle', () => {
      addToolStartToTrace(state, 'web_search');
      markToolCompletedInTrace(state, 'web_search');
      finalizeThinkingIndicator(indicator, state);

      const toggle = indicator.querySelector('.thinking-toggle');
      expect(toggle).toBeTruthy();
      expect(toggle?.getAttribute('aria-expanded')).toBe('false');
    });

    it('should show "Show details" as summary', () => {
      addToolStartToTrace(state, 'web_search');
      markToolCompletedInTrace(state, 'web_search');
      finalizeThinkingIndicator(indicator, state);

      const summary = indicator.querySelector('.thinking-toggle-summary');
      expect(summary?.textContent).toBe('Show details');
    });

    it('should create expandable details section', () => {
      addToolStartToTrace(state, 'web_search');
      markToolCompletedInTrace(state, 'web_search');
      finalizeThinkingIndicator(indicator, state);

      const details = indicator.querySelector('.thinking-details');
      expect(details).toBeTruthy();
      expect(details?.hasAttribute('hidden')).toBe(true);
    });

    it('should toggle details when button is clicked', () => {
      addToolStartToTrace(state, 'web_search');
      markToolCompletedInTrace(state, 'web_search');
      finalizeThinkingIndicator(indicator, state);

      const toggle = indicator.querySelector('.thinking-toggle') as HTMLButtonElement;
      const details = indicator.querySelector('.thinking-details');

      // Initially hidden
      expect(details?.hasAttribute('hidden')).toBe(true);
      expect(toggle.getAttribute('aria-expanded')).toBe('false');

      // Click to expand
      toggle.click();
      expect(details?.hasAttribute('hidden')).toBe(false);
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      expect(indicator.classList.contains('expanded')).toBe(true);

      // Click to collapse - should show "Show details" again
      toggle.click();
      expect(details?.hasAttribute('hidden')).toBe(true);
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect(indicator.classList.contains('expanded')).toBe(false);
    });

    it('should show thinking detail in details trace', () => {
      addThinkingToTrace(state, 'My detailed thinking process');
      finalizeThinkingIndicator(indicator, state);

      const trace = indicator.querySelector('.thinking-details .thinking-trace');
      expect(trace).toBeTruthy();

      const detail = trace?.querySelector('.thinking-detail');
      expect(detail?.textContent).toContain('My detailed thinking process');
    });

    it('should list completed tools in details trace', () => {
      addThinkingToTrace(state, 'Initial thinking');
      addToolStartToTrace(state, 'web_search', 'query 1');
      markToolCompletedInTrace(state, 'web_search');
      addToolStartToTrace(state, 'fetch_url', 'https://example.com');
      markToolCompletedInTrace(state, 'fetch_url');
      finalizeThinkingIndicator(indicator, state);

      // 3 items: thinking (reordered to first in finalized view) + 2 tools
      const trace = indicator.querySelector('.thinking-details .thinking-trace');
      const tools = trace?.querySelectorAll('.thinking-trace-item');
      expect(tools?.length).toBe(3);
    });

    it('should update toggle summary when expanded/collapsed', () => {
      addToolStartToTrace(state, 'web_search');
      markToolCompletedInTrace(state, 'web_search');
      finalizeThinkingIndicator(indicator, state);

      const toggle = indicator.querySelector('.thinking-toggle') as HTMLButtonElement;
      const summary = indicator.querySelector('.thinking-toggle-summary');

      expect(summary?.textContent).toBe('Show details');

      toggle.click();
      expect(summary?.textContent).toBe('Hide details');

      toggle.click();
      expect(summary?.textContent).toBe('Show details');
    });
  });
});
