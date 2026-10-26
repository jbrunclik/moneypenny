/**
 * Navigation wiring: the feature views open conversations and send, so
 * conversation selection and switching sit below them and cannot import
 * them back (F1). They get the views' functions here instead, before
 * anything can navigate.
 */
import { handleAgentEditById, leaveAgentsView, navigateToAgents } from '../agents';
import { setViewLeavers } from '../conversation';
import { setAgentHeaderActions } from '../conversation-switch';
import { leaveSportsView } from '../sports';

/**
 * Hand the views' navigation functions to the modules below them.
 */
export function initNavigation(): void {
  // The agents view leaves the main area to the conversation being opened
  setViewLeavers({ agents: () => leaveAgentsView(false), sports: leaveSportsView });
  setAgentHeaderActions({ openAgents: () => navigateToAgents(), editAgent: handleAgentEditById });
}
