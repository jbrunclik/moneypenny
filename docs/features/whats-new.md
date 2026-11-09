# What's new

A product changelog the family actually sees. Each user has a read-only
**What's new** chat ("Novinky" in Czech) that receives an announcement
whenever something visible ships (Nov 2026).

## Writing an announcement

Rule A7: a new feature or behaviour change users can see ships with an
announcement in the same commit, or joins that day's announcement before it
is deployed. Pure visual polish rides along with the next announcement (a
push per restyle would be noise). Once posted,
an announcement is never posted again, but editing its file revises the
posted text in place at the next start - quietly: no push, no unread badge,
and the chat keeps its place in the list (`revise_posted_announcements`;
`announcement_posts.message_id` since migration 0085, which paired earlier
posts with their messages). Log line: "Announcements revised" (revised_count).

`announcements/YYYY-MM-DD-slug.md`, Czech and English, each version starting
with its `# Title`:

```markdown
<!-- lang: cs -->
# Titulek
Text...

<!-- lang: en -->
# Title
Text...
```

- The id is the file name without `.md`; its date prefix is the
  announcement's date.
- Write for the family, not for developers: what they can now do, in their
  words, with an example to try. Leave out internals.
- `test_every_repo_announcement_is_valid` fails on a file missing a language
  or a title (at startup such a file is logged and skipped).
- Shape it for the release card (below): the title, one intro paragraph,
  sections as a **bold-only line** followed by a list, and a closing line.
  A post without sections is fine (title + paragraphs).
- The push title is "Novinky: <title>" / "What's new: <title>".

## How it is posted

`src/services/announcements.py`, called from app startup right after
migrations (`_prepare_process` in `src/app.py`). It runs only in processes
that apply migrations (gunicorn workers, `make run`), never in tests, timers
or the E2E server, and a failure never stops a start.

For every announcement and every user who existed on its date (a user who
signs up later gets no backlog):

1. **Claim** `(user_id, announcement_id)` in `announcement_posts` with
   `INSERT OR IGNORE`. Only the one caller that inserts posts it: both
   workers start at once, and every deploy re-runs this.
2. **Find the chat** (`whats_new_conversation_for_post`): the user's live
   What's new chat, unarchived if archived; a new one when there is none
   (never made, or the user deleted it). A re-created chat holds only the
   new post.
3. **Post** the user's version as an assistant message (`language` cs/en).
   A failure releases the claim, so the next start tries again.
4. **Push** after the post: tag `whats-new-<id>`, linking the chat.

The language is English when the user chose English
(`users.preferred_language`), otherwise Czech.

## The chat

- An ordinary chat in the list (`conversations.is_whats_new = 1`) with a
  sparkles icon before its title; a post brings it to the top with the
  unread badge. It is searchable, can be archived, and deleted to the trash.
- Read-only: the client hides the composer (`refreshChromeAfterSwitch` in
  `web/src/core/conversation-switch.ts`), and the server refuses chat turns,
  interjections and truncation with a validation error
  (`refuse_if_read_only` in `src/api/helpers/chat_turn.py`).
- The API carries `is_whats_new` on the conversation list, sync and detail.
- Posts render as release cards, not chat replies
  ([release-card.ts](../../web/src/components/messages/release-card.ts),
  styles in `release-card.css`): no avatar and no message actions; a card
  with the sparkles mark and the post's date in its own language, the title,
  the intro, each section as a row (title left, bullets right; stacked under
  768px), and the closing line as a quiet footer. The rendered markdown is
  regrouped in place, so a post the parser does not recognise (no `#` title)
  stays plain text. Nov 9 2026: a 2-column tile grid was tried first and
  left holes under short sections.

## Testing

[test_announcements.py](../../tests/unit/test_announcements.py) (parsing,
posting once, unarchive, re-create, the audience, the push, startup),
[test_routes_whats_new.py](../../tests/integration/test_routes_whats_new.py)
(the API field and the read-only guards),
[whats-new.spec.ts](../../web/tests/e2e/whats-new.spec.ts) (desktop and
mobile, the card structure; `POST /test/seed-whats-new` seeds the chat,
optionally with `{"posts": [markdown, ...]}`),
[release-card.test.ts](../../web/tests/unit/release-card.test.ts) (how a post
is split into the card).
