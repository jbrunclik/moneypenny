import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderAgentConversationHeader } from '@/components/AgentConversationHeader';

const header = () => document.getElementById('chat-header')!;

describe('AgentConversationHeader', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="chat-header" class="chat-header hidden"></div>';
  });

  it('shows the agent name with back and edit actions', () => {
    const onBack = vi.fn();
    const onEdit = vi.fn();
    renderAgentConversationHeader('Daily digest', onBack, onEdit);

    expect(header().classList.contains('agent-conversation-header')).toBe(true);
    expect(header().classList.contains('hidden')).toBe(false);
    expect(header().querySelector('.chat-header-title')!.textContent).toBe('Daily digest');
    expect(header().querySelector('.chat-header-icon svg')).not.toBeNull();

    header().querySelector<HTMLElement>('.chat-header-back')!.click();
    expect(onBack).toHaveBeenCalledOnce();
    header().querySelector<HTMLElement>('.agent-conv-edit')!.click();
    expect(onEdit).toHaveBeenCalledOnce();
  });

  it('renders the name as text, never markup', () => {
    renderAgentConversationHeader('<img src=x onerror=alert(1)>', vi.fn(), vi.fn());
    expect(header().querySelector('img')).toBeNull();
    expect(header().querySelector('.chat-header-title')!.textContent).toBe('<img src=x onerror=alert(1)>');
  });
});
