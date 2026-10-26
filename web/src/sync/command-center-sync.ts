/**
 * Command center sync: keeps the sidebar's agent badges current by fetching
 * the latest command center summary into the store.
 */

import { agents as agentsApi } from '../api/agents';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';

const log = createLogger('sync');

/** Fetch the command center summary; the store only changes when a badge count did. */
export async function syncCommandCenter(): Promise<void> {
  try {
    const data = await agentsApi.getCommandCenter();
    const store = useStore.getState();

    // Only update if values changed (to avoid unnecessary re-renders)
    const currentData = store.commandCenterData;
    if (
      !currentData ||
      currentData.total_unread !== data.total_unread ||
      currentData.agents_waiting !== data.agents_waiting ||
      currentData.agents_with_errors !== data.agents_with_errors
    ) {
      store.setCommandCenterData(data);
      log.debug('Command center sync updated', {
        totalUnread: data.total_unread,
        agentsWaiting: data.agents_waiting,
        agentsWithErrors: data.agents_with_errors,
      });
    }
  } catch (error) {
    log.warn('Command center sync failed', { error });
    // Don't throw - syncing is best-effort
  }
}
