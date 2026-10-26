/**
 * Navigation wiring: the feature views open conversations and send, so
 * conversation selection and switching sit below them and cannot import
 * them back (F1). They get the views' functions here instead, before
 * anything can navigate.
 */
import { handleAgentEditById, navigateToAgents } from '../agents';
import { setAgentHeaderActions } from '../conversation-switch';

/**
 * Hand the views' navigation functions to the modules below them.
 */
export function initNavigation(): void {
  setAgentHeaderActions({ openAgents: () => navigateToAgents(), editAgent: handleAgentEditById });
}
