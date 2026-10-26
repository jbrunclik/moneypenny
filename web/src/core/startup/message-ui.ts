/**
 * The interactive parts of rendered messages and the popups they open:
 * lightbox, sources, claims, artifact sends, research offers and progress, action rows,
 * image-generation details, costs and compaction, and the quizzes in markdown.
 */
import { initClaimCard } from '../../components/ClaimCard';
import { initClaimsSheet } from '../../components/ClaimsSheet';
import { initCompactionIndicator } from '../../components/CompactionIndicator';
import { costHistoryPopup } from '../../components/CostHistoryPopup';
import { initImageGenPopup } from '../../components/ImageGenPopup';
import { initLightbox } from '../../components/Lightbox';
import { initMessageCostPopup } from '../../components/MessageCostPopup';
import { renderQuizBlock } from '../../components/QuizBlock';
import { initSourcesPopup } from '../../components/SourcesPopup';
import { initActionRows } from '../../components/messages/action-row';
import { initResearchOffers } from '../../components/messages/research-offer';
import { initResearchProgress } from '../../components/messages/research-progress';
import { setArtifactSender } from '../../components/messages/artifact-host';
import { setQuizRenderer } from '../../utils/markdown';
import { declineDeepResearch, startDeepResearch } from '../deep-research';
import { sendUiMessage } from '../messaging';

/**
 * Wire up message popups and widgets.
 */
export function initMessageUi(): void {
  // Before any message renders: quiz blocks in markdown become quizzes
  setQuizRenderer(renderQuizBlock);
  initLightbox();
  initSourcesPopup();
  initClaimCard({ send: sendUiMessage });
  initClaimsSheet();
  setArtifactSender(sendUiMessage);
  initResearchOffers({ start: startDeepResearch, decline: declineDeepResearch });
  initResearchProgress();
  initActionRows();
  initImageGenPopup();
  initMessageCostPopup();
  costHistoryPopup.init();
  initCompactionIndicator();
}
