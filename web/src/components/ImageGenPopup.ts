import type { GeneratedImage } from '../types/api';
import { createElement } from '../utils/dom';
import { SPARKLES_ICON } from '../utils/icons';
import { createPopup, type PopupInstance } from './InfoPopup';
import { costs } from '../api/costs';
import { createLogger } from '../utils/logger';

const log = createLogger('imagegen');

/**
 * The generated images' prompts, then their cost (filled in once fetched)
 */
function imageGenInfo(images: GeneratedImage[]): HTMLElement[] {
  return [
    createElement(
      'div',
      { class: 'imagegen-list' },
      images.map((img, index) =>
        createElement('div', { class: 'imagegen-item' }, [
          createElement('span', { class: 'imagegen-number' }, [String(index + 1)]),
          createElement('span', { class: 'imagegen-prompt' }, [img.prompt]),
        ])
      )
    ),
    createElement('div', { id: 'imagegen-cost-placeholder', class: 'imagegen-cost-loading' }, ['Loading cost...']),
  ];
}

// Create the image generation popup instance
const imageGenPopup: PopupInstance<GeneratedImage[]> = createPopup<GeneratedImage[]>(
  {
    id: 'imagegen-popup',
    eventName: 'imagegen:open',
    icon: SPARKLES_ICON,
    title: 'Image Generation',
    styleClass: 'imagegen',
  },
  imageGenInfo
);

/** Replace the cost placeholder with the message's image generation cost, or drop it. */
async function fillImageGenCost(costPlaceholder: HTMLElement, messageId: string): Promise<void> {
  try {
    const costData = await costs.getMessageCost(messageId);
    // Show image generation cost if available, otherwise show nothing
    if (costData.image_generation_cost_formatted) {
      costPlaceholder.replaceWith(
        createElement('div', { class: 'imagegen-cost' }, [
          createElement('div', { class: 'imagegen-label' }, ['Image generation cost:']),
          createElement('div', { class: 'imagegen-cost-value' }, [costData.image_generation_cost_formatted]),
        ])
      );
    } else {
      costPlaceholder.remove();
    }
  } catch (error) {
    // Silently fail - cost display is optional
    log.warn('Failed to fetch message cost for image gen popup', { error });
    costPlaceholder.remove();
  }
}

/**
 * Initialize image generation popup event handlers
 */
export function initImageGenPopup(): void {
  imageGenPopup.init();

  // Listen for popup open to fetch and display cost
  const showImageGenCost = async (e: Event): Promise<void> => {
    const event = e as CustomEvent<GeneratedImage[]>;
    const messageId = event.detail?.[0]?.message_id;
    const costPlaceholder = document.getElementById('imagegen-cost-placeholder');
    if (!costPlaceholder) return;
    if (messageId) {
      await fillImageGenCost(costPlaceholder, messageId);
    } else {
      // Remove placeholder if no message_id
      costPlaceholder.remove();
    }
  };
  window.addEventListener('imagegen:open', (e: Event) => {
    void showImageGenCost(e);
  });
}
