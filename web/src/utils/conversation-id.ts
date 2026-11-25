/**
 * Conversation ids. A conversation created in this tab has a client-side
 * `temp-` id until the server saves it and assigns the real one.
 */

/** Whether a conversation ID is temporary (not yet saved to the DB). */
export function isTempConversation(convId: string | undefined): boolean {
  return convId?.startsWith('temp-') ?? false;
}

/**
 * Whether a saved chat can be filed under a project: an ordinary chat, not
 * What's new, an agent's or an anonymous one (the server's ELIGIBLE_CHAT_SQL;
 * Sports, Language and planning chats never reach the chat list).
 */
export function canJoinProject(
  conv: { id: string; is_whats_new?: boolean | null; is_agent?: boolean },
  anonymous: boolean,
): boolean {
  return !isTempConversation(conv.id) && !conv.is_whats_new && !conv.is_agent && !anonymous;
}
