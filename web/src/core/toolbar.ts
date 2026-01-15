/**
 * Toolbar module.
 * Handles toolbar buttons initialization and state management.
 */

import { useStore } from '../state/store';
import { costs } from '../api/client';
import { updateMonthlyCost } from '../components/Sidebar';
import { getElementById } from '../utils/dom';
import { STREAM_ICON, STREAM_OFF_ICON } from '../utils/icons';

import { isTempConversation } from './conversation';
import { openMostRecentCanvas } from './canvas';

/**
 * Update conversation cost display and monthly cost in sidebar.
 */
export async function updateConversationCost(convId: string | null): Promise<void> {
  const costEl = getElementById<HTMLDivElement>('conversation-cost');
  if (!costEl) return;

  if (!convId || isTempConversation(convId)) {
    costEl.textContent = '';
    return;
  }

  try {
    const costData = await costs.getConversationCost(convId);
    // Only show cost if it's greater than 0
    if (costData.cost_usd > 0) {
      costEl.textContent = costData.formatted;
    } else {
      costEl.textContent = '';
    }
    // Also update the monthly cost in the sidebar
    updateMonthlyCost();
  } catch {
    // Ignore errors - cost display is optional
    costEl.textContent = '';
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
    });
  }

  // Initialize canvas button
  initCanvasButton();
}

/**
 * Update stream button visual state.
 */
function updateStreamButtonState(btn: HTMLButtonElement, enabled: boolean): void {
  btn.classList.toggle('active', enabled);
  btn.setAttribute('aria-pressed', String(enabled));
  btn.innerHTML = enabled ? STREAM_ICON : STREAM_OFF_ICON;
  btn.title = enabled ? 'Streaming enabled (click to disable)' : 'Streaming disabled (click to enable)';
}

/**
 * Update search button visual state.
 */
function updateSearchButtonState(btn: HTMLButtonElement, active: boolean): void {
  btn.classList.toggle('active', active);
  btn.title = active ? 'Web search will be used for next message' : 'Force web search for next message';
}

/**
 * Update image generation button visual state.
 */
function updateImagegenButtonState(btn: HTMLButtonElement, active: boolean): void {
  btn.classList.toggle('active', active);
  btn.title = active ? 'Image generation will be used for next message' : 'Force image generation for next message';
}

/**
 * Update anonymous mode button visual state.
 */
export function updateAnonymousButtonState(btn: HTMLButtonElement, active: boolean): void {
  btn.classList.toggle('active', active);
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

/**
 * Initialize canvas button - toggle canvas panel.
 */
function initCanvasButton(): void {
  const btn = getElementById<HTMLButtonElement>('canvas-btn');
  if (!btn) return;

  // Subscribe to canvas state
  useStore.subscribe(
    (state) => state.isCanvasOpen,
    (isOpen) => {
      btn.classList.toggle('active', isOpen);
      btn.title = isOpen ? 'Hide Canvas (Esc)' : 'Show Canvas';
    }
  );

  // Toggle canvas on click
  btn.addEventListener('click', () => {
    const state = useStore.getState();
    if (state.isCanvasOpen) {
      state.closeCanvas();
    } else {
      openMostRecentCanvas();
    }
  });
}
