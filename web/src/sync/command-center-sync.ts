/**
 * Command center sync: keeps the sidebar's Agents badge current by fetching
 * the job list summary into the store.
 */

import { jobs } from '../api/jobs';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';

const log = createLogger('sync');

/** Fetch the command center summary; the store only changes when a badge count did. */
export async function syncCommandCenter(): Promise<void> {
  try {
    const data = await jobs.overview();
    const store = useStore.getState();

    // Only update if values changed (to avoid unnecessary re-renders)
    const currentData = store.commandCenterData;
    if (
      !currentData ||
      currentData.total_unread !== data.total_unread ||
      currentData.jobs_waiting !== data.jobs_waiting ||
      currentData.jobs_with_errors !== data.jobs_with_errors
    ) {
      store.setCommandCenterData(data);
      log.debug('Command center sync updated', {
        totalUnread: data.total_unread,
        jobsWaiting: data.jobs_waiting,
        jobsWithErrors: data.jobs_with_errors,
      });
    }
  } catch (error) {
    log.warn('Command center sync failed', { error });
    // Don't throw - syncing is best-effort
  }
}
