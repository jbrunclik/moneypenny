/**
 * Agent conversation sync: detects messages added from another tab/device
 * while an autonomous agent's conversation is viewed. Agent conversations
 * are excluded from the regular conversation sync (they have the is_agent=1
 * flag), so the viewed one is polled on its own.
 */

import { agents as agentsApi } from '../api/agents';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import type { SyncState } from './sync-state';

const log = createLogger('sync');

export class AgentConversationSync {
  /** Tracks the agent ID being viewed (for agent conversation sync). */
  private viewedAgentId: string | null = null;

  /** Tracks agent conversation message count for sync. */
  private messageCount: number | null = null;

  constructor(private readonly state: SyncState) {}

  /** Poll the viewed agent's conversation (none viewed, or streaming: skipped). */
  async sync(): Promise<void> {
    const agentId = this.viewedAgentId;
    if (!agentId) return;

    const currentConv = useStore.getState().currentConversation;
    if (currentConv && this.state.streamingConversations.has(currentConv.id)) {
      log.debug('Skipping agent sync - conversation is streaming');
      return;
    }

    try {
      const response = await agentsApi.syncConversation(agentId);
      if (!response.conversation) {
        log.debug('Agent conversation not found', { agentId });
        return;
      }
      this.detectNewMessages(agentId, response.conversation.message_count);
      this.messageCount = response.conversation.message_count;
    } catch (error) {
      log.warn('Agent conversation sync failed', { error, agentId });
      // Don't throw - syncing is best-effort
    }
  }

  /** The message count rose: messages added in another tab/device. */
  private detectNewMessages(agentId: string, messageCount: number): void {
    if (this.messageCount === null || messageCount <= this.messageCount) return;
    log.info('Agent conversation has new messages', {
      agentId,
      previousCount: this.messageCount,
      newCount: messageCount,
    });
    this.state.callbacks.onAgentConversationExternalUpdate?.(messageCount);
  }

  /**
   * Set the agent being viewed for sync tracking.
   *
   * @param agentId The agent ID being viewed, or null when leaving
   * @param messageCount The current message count (to establish baseline)
   */
  setViewedAgent(agentId: string | null, messageCount?: number): void {
    if (agentId) {
      this.viewedAgentId = agentId;
      this.messageCount = messageCount ?? null;
      log.debug('Set viewed agent', { agentId, messageCount });
    } else {
      this.clear();
      log.debug('Cleared viewed agent');
    }
  }

  /** This device's own turn in the viewed agent conversation: no news. */
  noteOwnCount(count: number): void {
    if (this.viewedAgentId && this.messageCount !== null) this.messageCount = count;
  }

  clear(): void {
    this.viewedAgentId = null;
    this.messageCount = null;
  }
}
