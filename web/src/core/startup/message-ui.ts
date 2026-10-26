/**
 * The interactive parts of rendered messages and the popups they open:
 * lightbox, sources, claims, research offers and progress, action rows,
 * image-generation details, costs and compaction.
 */
import { initClaimCard } from '../../components/ClaimCard';
import { initClaimsSheet } from '../../components/ClaimsSheet';
import { initCompactionIndicator } from '../../components/CompactionIndicator';
import { costHistoryPopup } from '../../components/CostHistoryPopup';
import { initImageGenPopup } from '../../components/ImageGenPopup';
import { initLightbox } from '../../components/Lightbox';
import { initMessageCostPopup } from '../../components/MessageCostPopup';
import { initSourcesPopup } from '../../components/SourcesPopup';
import { initActionRows } from '../../components/messages/action-row';
import { initResearchOffers } from '../../components/messages/research-offer';
import { initResearchProgress } from '../../components/messages/research-progress';

/**
 * Wire up message popups and widgets.
 */
export function initMessageUi(): void {
  initLightbox();
  initSourcesPopup();
  initClaimCard();
  initClaimsSheet();
  initResearchOffers();
  initResearchProgress();
  initActionRows();
  initImageGenPopup();
  initMessageCostPopup();
  costHistoryPopup.init();
  initCompactionIndicator();
}
