/**
 * Shared chat header for agent conversations (back, run now and edit actions).
 *
 * Lives outside CommandCenter so conversation.ts can import it statically
 * without dragging the whole Command Center view into the main chunk
 * (CommandCenter is lazy-loaded by core/agents.ts).
 */
import { renderChatHeader } from './ChatHeader';
import { EDIT_ICON, PLAY_ICON, ROBOT_ICON, setIcon } from '../utils/icons';

export function renderAgentConversationHeader(
  agentName: string,
  onBack: () => void,
  onEdit: () => void,
  onRun?: () => void,
): void {
  const editBtn = document.createElement('button');
  editBtn.className = 'btn-icon agent-conv-edit';
  editBtn.title = 'Edit agent';
  setIcon(editBtn, EDIT_ICON);
  editBtn.addEventListener('click', onEdit);

  const actions = [editBtn];
  if (onRun) {
    const runBtn = document.createElement('button');
    runBtn.className = 'btn-icon agent-conv-run';
    runBtn.title = 'Run now';
    setIcon(runBtn, PLAY_ICON);
    runBtn.addEventListener('click', onRun);
    actions.unshift(runBtn);
  }

  renderChatHeader({
    title: agentName,
    iconHtml: ROBOT_ICON,
    extraClass: 'agent-conversation-header',
    onBack,
    actions,
  });
}
