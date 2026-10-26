/**
 * The sandboxed artifact frame's entry (src/templates/artifact-frame.html).
 *
 * Says "ready" to the chat, takes the first init from its parent (the
 * artifact's HTML, theme and saved state), renders it with the design system
 * loaded, and keeps the theme in step. Every other message is ignored.
 */
import '@fontsource-variable/inter';
import '@fontsource-variable/bricolage-grotesque';
import './design-system.css';
import { installBridgeClient } from './bridge-client';
import { loadArtifact } from './loader';
import { isToFrame, type FromFrame } from './protocol';

// The frame is an opaque-origin sandbox and only the app may embed it
// (frame-ancestors 'self'), so the parent is the only possible receiver
const post = (message: FromFrame): void => window.parent.postMessage(message, '*');
const client = installBridgeClient(window, post);
// UI-local (F2): the frame renders its first init only
let initialized = false;

window.addEventListener('message', (event: MessageEvent) => {
  if (event.source !== window.parent || !isToFrame(event.data)) return;
  const message = event.data;
  if (message.type === 'mp:theme') {
    client.applyTheme(message.theme);
    return;
  }
  if (initialized) return;
  initialized = true;
  client.applyInit(message.state, message.theme);
  void loadArtifact(document, message.html).then(() => post({ type: 'mp:rendered' }));
});

post({ type: 'mp:ready' });
