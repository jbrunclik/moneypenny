/**
 * Shared chat header for agent conversations (back + edit actions).
 *
 * Lives outside CommandCenter so conversation.ts can import it statically
 * without dragging the whole Command Center view into the main chunk
 * (CommandCenter is lazy-loaded by core/agents.ts).
 */
import { renderChatHeader } from './ChatHeader';
import { EDIT_ICON, ROBOT_ICON, setIcon } from '../utils/icons';

export function renderAgentConversationHeader(
  agentName: string,
  onBack: () => void,
  onEdit: () => void,
): void {
  const editBtn = document.createElement('button');
  editBtn.className = 'btn-icon agent-conv-edit';
  editBtn.title = 'Edit agent';
  setIcon(editBtn, EDIT_ICON);
  editBtn.addEventListener('click', onEdit);

  renderChatHeader({
    title: agentName,
    iconHtml: ROBOT_ICON,
    extraClass: 'agent-conversation-header',
    onBack,
    actions: [editBtn],
  });
}
