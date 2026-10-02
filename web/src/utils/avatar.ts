import { escapeHtml } from './dom';

/**
 * Get initials from a name or email (up to 2 characters)
 */
export function getInitials(nameOrEmail: string): string {
  return nameOrEmail
    .split(' ')
    .map((part) => part.charAt(0).toUpperCase())
    .slice(0, 2)
    .join('');
}

/**
 * Render user avatar - returns HTML string for picture or initials
 */
export function renderUserAvatarHtml(
  picture: string | undefined,
  name: string,
  className = 'user-avatar'
): string {
  if (picture) {
    return `<img src="${escapeHtml(picture)}" alt="${escapeHtml(name)}" class="${className}" data-avatar="${escapeHtml(className)}" referrerpolicy="no-referrer">`;
  }
  const initials = getInitials(name);
  return `<div class="${className} ${className}-initials">${initials}</div>`;
}

/**
 * Create user avatar DOM element
 */
export function createUserAvatarElement(
  picture: string | undefined,
  name: string,
  className = 'user-avatar'
): HTMLElement {
  if (picture) {
    const img = document.createElement('img');
    img.src = picture;
    img.alt = name;
    img.className = className;
    img.dataset.avatar = className;
    // Google's avatar host rate-limits hotlinked images sent with a referrer
    img.referrerPolicy = 'no-referrer';
    return img;
  }

  const div = document.createElement('div');
  div.className = `${className} ${className}-initials`;
  div.textContent = getInitials(name);
  return div;
}

/**
 * Swap avatar images that fail to load (a Google photo URL changed or was
 * retired) for the initials avatar. One capture-phase listener covers every
 * avatar, since image error events don't bubble; call once at startup.
 */
export function installAvatarFallback(): void {
  document.addEventListener(
    'error',
    (event) => {
      const img = event.target;
      if (!(img instanceof HTMLImageElement) || img.dataset.avatar === undefined) return;
      img.replaceWith(createUserAvatarElement(undefined, img.alt, img.dataset.avatar));
    },
    true
  );
}
