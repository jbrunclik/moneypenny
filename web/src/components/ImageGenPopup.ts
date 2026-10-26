import type { GeneratedImage } from '../types/api';
import { escapeHtml } from '../utils/dom';
import { SPARKLES_ICON } from '../utils/icons';
import { createPopup, type PopupInstance } from './InfoPopup';
import { costs } from '../api/costs';
import { createLogger } from '../utils/logger';

const log = createLogger('imagegen');

/**
 * Render generated images info HTML
 */
function renderImageGenInfo(images: GeneratedImage[]): string {
  const imagesHtml = images
    .map(
      (img, index) => `
      <div class="imagegen-item">
        <span class="imagegen-number">${index + 1}</span>
        <span class="imagegen-prompt">${escapeHtml(img.prompt)}</span>
      </div>
    `
    )
    .join('');

  return `
    <div class="imagegen-list">
      ${imagesHtml}
    </div>
    <div id="imagegen-cost-placeholder" class="imagegen-cost-loading">Loading cost...</div>
  `;
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
  renderImageGenInfo
);

/**
 * Initialize image generation popup event handlers
 */
export function initImageGenPopup(): void {
  imageGenPopup.init();

  // Listen for popup open to fetch and display cost
  const showImageGenCost = async (e: Event): Promise<void> => {
    const event = e as CustomEvent<GeneratedImage[]>;
    const messageId = event.detail?.[0]?.message_id;
    if (messageId) {
      const costPlaceholder = document.getElementById('imagegen-cost-placeholder');
      if (costPlaceholder) {
        try {
          const costData = await costs.getMessageCost(messageId);
          // Show image generation cost if available, otherwise show nothing
          if (costData.image_generation_cost_formatted) {
            costPlaceholder.outerHTML = `
              <div class="imagegen-cost">
                <div class="imagegen-label">Image generation cost:</div>
                <div class="imagegen-cost-value">${escapeHtml(costData.image_generation_cost_formatted)}</div>
              </div>
            `;
          } else {
            costPlaceholder.remove();
          }
        } catch (error) {
          // Silently fail - cost display is optional
          log.warn('Failed to fetch message cost for image gen popup', { error });
          costPlaceholder.remove();
        }
      }
    } else {
      // Remove placeholder if no message_id
      const costPlaceholder = document.getElementById('imagegen-cost-placeholder');
      if (costPlaceholder) {
        costPlaceholder.remove();
      }
    }
  };
  window.addEventListener('imagegen:open', (e: Event) => {
    void showImageGenCost(e);
  });
}

/**
 * Open image generation popup with the given images
 */
export function openImageGenPopup(images: GeneratedImage[]): void {
  if (images && images.length > 0) {
    imageGenPopup.open(images);
  }
}

/**
 * Close image generation popup
 */
export function closeImageGenPopup(): void {
  imageGenPopup.close();
}
