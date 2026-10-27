/**
 * `<html data-app-ready>`: startup has settled. Signed in, that is the data
 * loaded, the first sync done and the archive and trash lists loaded after
 * it; signed out, the sign-in button and its handlers in place; or a failed
 * load showing its error. E2E specs wait for it (`appReady` in
 * web/tests/e2e/waits.ts) instead of a shell element that exists from the
 * first paint - acting before startup settled raced its auth check and first
 * sync (Oct 2026).
 */
export function markAppReady(): void {
  document.documentElement.dataset.appReady = '';
}
