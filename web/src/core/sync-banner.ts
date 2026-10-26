/**
 * Sync banner module: the "new messages available" banner.
 */

/**
 * Hide the new messages banner.
 */
export function hideNewMessagesAvailableBanner(): void {
  const banner = document.querySelector('.new-messages-banner');
  banner?.remove();
}
