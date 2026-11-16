# Past-chat search that works in Czech - design

Nov 16 2026. Small project; one pass, approved scope ("let's do it all in one pass").

## Why

The family asks Moneypenny about earlier chats daily, mostly in Czech. In the
production journal (Nov 13-16), 11 of 12 agent searches found nothing by
keyword ("Rybníček Regál", "Endurace příslušenství nářadí Sloperoad RearVue")
and lived on the meaning-based pass alone; "Matematická olympiáda" found
nothing at all. Cause: `_fts_query` ANDs every word as a prefix, so one wrong
or inflected word ("olympiáda" vs a stored "olympiády") empties the result.
The meaning pass is appended after keyword hits instead of ranked with them,
and there is no way to ask "what did we talk about yesterday".

Embeddings: 26.1k of 44.0k message embeddings belong to deleted messages
(18.4k of one user's 19.8k), and the similarity loop is pure Python
(~0.5 s for 11k vectors on a laptop, slower on the production host).

## Goals

1. A query with one unmatched or inflected word still finds the chat.
2. Keyword and meaning hits come back as one ranked list.
3. The agent can list or filter chats by date ("yesterday", "last week").
4. Embeddings of deleted messages are gone and stay gone; scoring is faster.
5. The app's search box gets the same fallback.

Non-goals: a Czech stemmer or a new FTS tokenizer (a re-index of every
message); a new tool (the fixed prompt is the biggest cost lever, so this
extends `search_conversations`). Anti-goal: the strict search getting worse -
a query whose words all match ranks exactly as today.

## Approaches

- **Fallback + fusion in the existing FTS index (chosen).** Keep the AND query;
  when it finds fewer than `CONVERSATION_SEARCH_FALLBACK_MIN_RESULTS` (3),
  run an OR query with Czech endings trimmed and append its hits after the
  AND hits. Merge keyword and meaning lists by reciprocal rank fusion.
- New tokenizer / Czech stemming in FTS: better recall in theory, but a full
  re-index, a migration on the busiest table and no stemmer in SQLite's box.
- Meaning-only search: drops exact matches (amounts, names, codes), which
  keyword search is best at.

## Design

- **OR fallback** (`src/db/models/search.py`): `_fts_query(query, mode)`;
  the `"any"` mode ORs the words, and each word of 6+ letters becomes a prefix
  without its last 2 letters ("olympiáda" -> "olympiá*", "matematická" ->
  "matematic*") - a crude Czech ending trim, my call, pinned by tests on real
  forms. bm25 ranks rows matching more words first. Used by the tool and the
  app (`db.search`); the result says nothing new to the app's UI.
- **Fusion** (`src/agent/tools/conversation_search.py`): reciprocal rank
  fusion, `1/(60 + rank)` per list, one hit per conversation (its best message),
  agents' runs still sorted last. Each hit says how it matched (`words`,
  `meaning`, `both`). The result line counts stay.
- **Dates**: `search_conversations(query="", limit=10, after=None, before=None)`;
  `after`/`before` are ISO dates (inclusive, the user's timezone) applied to
  message time in both passes. An empty query with a date lists the chats
  active in the range, newest first: date, title, the first user message
  excerpt. An empty query without dates lists the most recent chats. A bad
  date is a retriable tool error.
- **Orphans**: migration `0095` deletes message embeddings whose message no
  longer exists and adds an `AFTER DELETE ON messages` trigger deleting the
  message's embedding (every delete path, including the trash purge). Embeddings
  of trashed but restorable conversations stay (1.5k; restore keeps recall).
- **Scoring**: `top_k_similar` uses `array('f').frombytes` and `math.sumprod`
  (stdlib; measured 0.18 s vs 0.50 s for 11k vectors) - my call over numpy,
  which is not a dependency today and would cost RAM in each worker.
- **Instrument**: the "Conversation search via tool" line gains `mode`
  (`all`/`any`), `fused`, `after`, `before`, `ms`. Re-measure ~Nov 30 2026:
  share of searches with zero keyword hits (today 11 of 12) and median `ms`.
- **Prompt/tool text**: the docstring and the `core.py` example mention dates
  and the listing; `make prompt-snapshots`.

## Left to the builder

Exact rendering of the listing; whether the `any` pass needs its own bm25
weights for titles; test fixtures.

## Verification

Unit and integration tests (Czech inflection, one wrong word, fusion order,
dates, empty query, trigger on every delete path, orphan purge); evals
`cz_episodic_recall`, `cz_compaction_recall`, `cz_compaction_user_details`,
`facts_retention_mixed_topics` before/after (cost reported).
