/**
 * Planner conversation sync: detects external updates, resets and deletion.
 * The planner is excluded from the regular conversation sync (it has the
 * is_planning=1 flag), so it is polled on its own.
 */

import { planner as plannerApi } from '../api/planner';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import type { SyncManagerCallbacks } from './sync-state';

const log = createLogger('sync');

export class PlannerSync {
  /** Tracks planner conversation message count for sync. */
  private messageCount: number | null = null;

  /** Tracks planner last reset timestamp for reset detection. */
  private lastReset: string | null = null;

  constructor(private readonly callbacks: SyncManagerCallbacks) {}

  /** Poll the planner's state and report what changed while it is shown. */
  async sync(): Promise<void> {
    try {
      const response = await plannerApi.sync();
      if (!response.conversation) {
        this.handleMissing();
        return;
      }
      const { message_count, last_reset } = response.conversation;
      this.detectReset(last_reset);
      this.detectNewMessages(message_count);
      this.messageCount = message_count;
      this.lastReset = last_reset;
    } catch (error) {
      log.warn('Planner sync failed', { error });
      // Don't throw - syncing is best-effort
    }
  }

  /** Planner doesn't exist yet, or was deleted (it existed before). */
  private handleMissing(): void {
    if (this.messageCount === null) return;
    if (useStore.getState().isPlannerView) {
      log.info('Planner conversation was deleted externally');
      this.callbacks.onPlannerDeleted?.();
    }
    this.messageCount = null;
    this.lastReset = null;
  }

  /** The last_reset timestamp changed: reset in another tab. */
  private detectReset(lastReset: string | null): void {
    if (!this.lastReset || lastReset === this.lastReset) return;
    if (useStore.getState().isPlannerView) {
      log.info('Planner conversation was reset externally');
      this.callbacks.onPlannerReset?.();
    }
  }

  /** The message count rose: messages added in another tab/device. */
  private detectNewMessages(messageCount: number): void {
    if (this.messageCount === null || messageCount <= this.messageCount) return;
    if (useStore.getState().isPlannerView) {
      log.info('Planner conversation has new messages', {
        previousCount: this.messageCount,
        newCount: messageCount,
      });
      this.callbacks.onPlannerExternalUpdate?.(messageCount);
    }
  }

  /**
   * Baseline for the planner view's new-message check, set when it loads.
   * Left to the first poll, a change made in the minute after opening the
   * planner set the baseline instead of being noticed. (A baseline that is
   * off by a filtered placeholder only causes a no-op merge.)
   */
  setBaseline(messageCount: number): void {
    this.messageCount = messageCount;
    // Re-baseline the reset marker too: this device just loaded (possibly
    // auto-reset) or reset the planner itself - the next poll's new
    // last_reset is ours, not "reset in another tab" (whose reload would
    // re-render over the running analysis)
    this.lastReset = null;
  }

  /** This device's own turn in the open planner: its count is no news. */
  noteOwnCount(count: number): void {
    if (this.messageCount !== null) this.messageCount = count;
  }

  clear(): void {
    this.messageCount = null;
    this.lastReset = null;
  }
}
