/**
 * Messages between the chat and an artifact frame (postMessage). Shared by the
 * frame (src/artifact/) and the host (core/artifact-host.ts) so both sides
 * agree on the shapes. Frames are opaque-origin sandboxes: the host trusts a
 * message only by its `source` (a frame it created), never by its contents.
 */

export type ArtifactTheme = 'light' | 'dark';

/** Chat -> frame */
export type ToFrame =
  | { type: 'mp:init'; html: string; theme: ArtifactTheme; state: unknown }
  | { type: 'mp:theme'; theme: ArtifactTheme };

/** Frame -> chat */
export type FromFrame =
  | { type: 'mp:ready' }
  | { type: 'mp:rendered' }
  | { type: 'mp:height'; height: number }
  | { type: 'mp:send'; text: string }
  | { type: 'mp:state'; state: unknown }
  | { type: 'mp:link'; href: string }
  | { type: 'mp:error'; message: string };

function isRecord(data: unknown): data is Record<string, unknown> {
  return typeof data === 'object' && data !== null;
}

function isTheme(value: unknown): value is ArtifactTheme {
  return value === 'light' || value === 'dark';
}

/** A well-formed frame -> chat message (anything else is ignored). */
export function isFromFrame(data: unknown): data is FromFrame {
  if (!isRecord(data)) return false;
  switch (data.type) {
    case 'mp:ready':
    case 'mp:rendered':
    case 'mp:state':
      return true;
    case 'mp:height':
      return typeof data.height === 'number' && Number.isFinite(data.height);
    case 'mp:send':
      return typeof data.text === 'string';
    case 'mp:link':
      return typeof data.href === 'string';
    case 'mp:error':
      return typeof data.message === 'string';
    default:
      return false;
  }
}

/** A well-formed chat -> frame message. */
export function isToFrame(data: unknown): data is ToFrame {
  if (!isRecord(data)) return false;
  if (data.type === 'mp:init') return typeof data.html === 'string' && isTheme(data.theme);
  if (data.type === 'mp:theme') return isTheme(data.theme);
  return false;
}
