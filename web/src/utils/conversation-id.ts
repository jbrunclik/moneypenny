/**
 * Conversation ids. A conversation created in this tab has a client-side
 * `temp-` id until the server saves it and assigns the real one.
 */

/** Whether a conversation ID is temporary (not yet saved to the DB). */
export function isTempConversation(convId: string | undefined): boolean {
  return convId?.startsWith('temp-') ?? false;
}
