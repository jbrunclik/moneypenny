/**
 * Toolbar module.
 * Handles toolbar buttons initialization and state management.
 */

import { useStore } from '../state/store';
import { conversations, costs } from '../api/client';
import { updateMonthlyCost } from '../components/Sidebar';
import { getElementById } from '../utils/dom';
import { STREAM_ICON, STREAM_OFF_ICON } from '../utils/icons';
import { logger } from '../utils/logger';

import { isTempConversation } from './conversation';

/**
 * Update conversation cost display and monthly cost in sidebar.
 */
export async function updateConversationCost(convId: string | null): Promise<void> {
  // Desktop chip lives in the chat header (only when rendered); mobile chip
  // lives in the mobile header and always exists.
  const costEls = [
    getElementById<HTMLElement>('conversation-cost'),
    getElementById<HTMLElement>('conversation-cost-mobile'),
  ].filter((el): el is HTMLElement => el !== null);
  if (costEls.length === 0) return;

  const setCost = (text: string): void => {
    for (const el of costEls) {
      el.textContent = text;
      if (text) el.title = 'Total cost of this conversation';
    }
  };

  if (!convId || isTempConversation(convId)) {
    setCost('');
    return;
  }

  try {
    const costData = await costs.getConversationCost(convId);
    // Only show cost if it's greater than 0
    setCost(costData.cost_usd > 0 ? costData.formatted : '');
    // Also update the monthly cost in the sidebar
    updateMonthlyCost();
  } catch {
    // Ignore errors - cost display is optional
    setCost('');
  }
}

/**
 * Initialize toolbar buttons (stream toggle, search toggle, imagegen toggle).
 */
export function initToolbarButtons(): void {
  const store = useStore.getState();
  const streamBtn = getElementById<HTMLButtonElement>('stream-btn');
  const searchBtn = getElementById<HTMLButtonElement>('search-btn');
  const imagegenBtn = getElementById<HTMLButtonElement>('imagegen-btn');

  // Mobile: the four toggles live in a popover behind the options button
  const optionsBtn = getElementById<HTMLButtonElement>('toolbar-options-btn');
  const togglesPanel = document.querySelector<HTMLDivElement>('.toolbar-toggles');
  if (optionsBtn && togglesPanel) {
    optionsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = togglesPanel.classList.toggle('open');
      optionsBtn.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', (e) => {
      if (
        togglesPanel.classList.contains('open') &&
        !togglesPanel.contains(e.target as Node) &&
        !optionsBtn.contains(e.target as Node)
      ) {
        togglesPanel.classList.remove('open');
        optionsBtn.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // Initialize stream button state from store
  if (streamBtn) {
    updateStreamButtonState(streamBtn, store.streamingEnabled);
    streamBtn.addEventListener('click', () => {
      const currentState = useStore.getState().streamingEnabled;
      const newState = !currentState;
      useStore.getState().setStreamingEnabled(newState);
      updateStreamButtonState(streamBtn, newState);
    });
  }

  // Initialize search button (one-shot toggle for web_search tool)
  if (searchBtn) {
    updateSearchButtonState(searchBtn, store.forceTools.includes('web_search'));
    searchBtn.addEventListener('click', () => {
      useStore.getState().toggleForceTool('web_search');
      const isActive = useStore.getState().forceTools.includes('web_search');
      updateSearchButtonState(searchBtn, isActive);
    });
  }

  // Initialize image generation button (one-shot toggle for generate_image tool)
  if (imagegenBtn) {
    updateImagegenButtonState(imagegenBtn, store.forceTools.includes('generate_image'));
    imagegenBtn.addEventListener('click', () => {
      useStore.getState().toggleForceTool('generate_image');
      const isActive = useStore.getState().forceTools.includes('generate_image');
      updateImagegenButtonState(imagegenBtn, isActive);
    });
  }

  // Initialize anonymous mode button (per-conversation toggle)
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    const currentConvId = store.currentConversation?.id;
    const isAnonymous = currentConvId
      ? store.getAnonymousMode(currentConvId)
      : store.pendingAnonymousMode;
    updateAnonymousButtonState(anonymousBtn, isAnonymous);
    anonymousBtn.addEventListener('click', () => {
      const state = useStore.getState();
      const convId = state.currentConversation?.id;
      if (!convId) {
        // No conversation exists, store as pending anonymous mode
        const newState = !state.pendingAnonymousMode;
        state.setPendingAnonymousMode(newState);
        updateAnonymousButtonState(anonymousBtn, newState);
        return;
      }
      const currentState = state.getAnonymousMode(convId);
      const newState = !currentState;
      state.setAnonymousMode(convId, newState);
      updateAnonymousButtonState(anonymousBtn, newState);
      // Persist so the setting survives a reload. Optimistic: the local toggle
      // already applied, and the server ORs its stored flag with the per-request
      // one, so a failed write cannot silently un-anonymise the conversation.
      void conversations.setAnonymousMode(convId, newState).catch((error: unknown) => {
        logger.error('Failed to persist anonymous mode', { error });
      });
    });
  }
}

/**
 * Update stream button visual state.
 */
function updateStreamButtonState(btn: HTMLButtonElement, enabled: boolean): void {
  btn.classList.toggle('active', enabled);
  btn.setAttribute('aria-pressed', String(enabled));
  btn.setAttribute('aria-pressed', String(enabled));
  btn.innerHTML = enabled ? STREAM_ICON : STREAM_OFF_ICON;
  btn.title = enabled ? 'Streaming enabled (click to disable)' : 'Streaming disabled (click to enable)';
}

/**
 * Update search button visual state.
 */
function updateSearchButtonState(btn: HTMLButtonElement, active: boolean): void {
  btn.classList.toggle('active', active);
  btn.setAttribute('aria-pressed', String(active));
  btn.title = active ? 'Web search will be used for next message' : 'Force web search for next message';
}

/**
 * Update image generation button visual state.
 */
function updateImagegenButtonState(btn: HTMLButtonElement, active: boolean): void {
  btn.classList.toggle('active', active);
  btn.setAttribute('aria-pressed', String(active));
  btn.title = active ? 'Image generation will be used for next message' : 'Force image generation for next message';
}

/**
 * Update anonymous mode button visual state.
 */
export function updateAnonymousButtonState(btn: HTMLButtonElement, active: boolean): void {
  btn.classList.toggle('active', active);
  btn.setAttribute('aria-pressed', String(active));
  btn.title = active ? 'Anonymous mode enabled - memory and integrations disabled' : 'Anonymous mode - disable memory and integrations';
}

/**
 * Reset force tools and update UI after message is sent.
 */
export function resetForceTools(): void {
  const searchBtn = getElementById<HTMLButtonElement>('search-btn');
  const imagegenBtn = getElementById<HTMLButtonElement>('imagegen-btn');
  useStore.getState().clearForceTools();
  if (searchBtn) {
    updateSearchButtonState(searchBtn, false);
  }
  if (imagegenBtn) {
    updateImagegenButtonState(imagegenBtn, false);
  }
}
