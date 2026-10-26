/**
 * Spend warning banner (S12): when the signed-in user's spend today passes the
 * threshold, a neutral note above the messages suggests telling the admin.
 * Never blocks anything; dismissed, it stays away for the rest of the day.
 */
import { admin } from '../api/admin';
import { createElement } from '../utils/dom';
import { CLOSE_ICON, setIcon } from '../utils/icons';
import { createLogger } from '../utils/logger';

const log = createLogger('components/SpendBanner');

// One key holding the day it was dismissed on (a key per day would pile up)
const DISMISSED_KEY = 'spend-banner-dismissed';

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
}

function dismissedToday(): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) === today();
  } catch {
    return false; // storage unavailable: show the banner, harmlessly
  }
}

function dismiss(banner: HTMLElement): void {
  try {
    localStorage.setItem(DISMISSED_KEY, today());
  } catch {
    // storage unavailable: the banner just comes back on the next check
  }
  banner.remove();
}

function show(formattedToday: string): void {
  const messages = document.getElementById('messages');
  if (!messages?.parentElement || document.querySelector('.spend-banner')) return;
  const banner = document.createElement('div');
  banner.className = 'spend-banner';
  banner.setAttribute('role', 'status');
  const dismissBtn = createElement('button', { type: 'button', class: 'spend-banner-dismiss', 'aria-label': 'Dismiss for today' });
  setIcon(dismissBtn, CLOSE_ICON);
  dismissBtn.addEventListener('click', () => dismiss(banner));
  banner.append(
    createElement('span', {}, [
      `Unusually high usage today (${formattedToday}). If this is unexpected, let the admin know.`,
    ]),
    dismissBtn
  );
  messages.parentElement.insertBefore(banner, messages);
}

/** Check today's spend and show the banner when it's past the threshold. */
export async function refreshSpendWarning(): Promise<void> {
  if (dismissedToday()) return;
  try {
    const status = await admin.getSpendStatus();
    if (status.over_threshold) show(status.today.formatted);
  } catch (error) {
    log.warn('Spend status unavailable', { error });
  }
}
