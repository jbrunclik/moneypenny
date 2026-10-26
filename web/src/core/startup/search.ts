/**
 * Conversation search: the sidebar input and opening a picked result.
 */
import { initSearchInput } from '../../components/SearchInput';
import { renderConversationsList } from '../../components/Sidebar';
import { subscribeToSearchChanges } from '../../components/SearchResults';
import { createLogger } from '../../utils/logger';
import { handleSearchResultClick } from '../search';

const log = createLogger('init');

/**
 * Wire up the search input and its results.
 */
export function initSearch(): void {
  initSearchInput();
  subscribeToSearchChanges((convId, messageId, resultIndex) => {
    void handleSearchResultClick(convId, messageId, resultIndex).catch((error: unknown) =>
      log.error('Failed to open search result', { error }),
    );
  }, renderConversationsList);
}
