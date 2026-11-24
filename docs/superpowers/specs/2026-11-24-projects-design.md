# Projects - design

Nov 24 2026. Part (2) of the TODO item "Knowledge base, then Projects" (part 1, document
memory, shipped the same day).

## Intent

A project is a folder of chats about one lasting topic. It has its own instructions,
memory and documents, and it can be shared with other family members. A new chat in the
project starts out knowing what earlier chats in it settled, so nobody has to paste
background in again or say "move this to the other thread". The Sep 30 2026
conversation sweep flagged that habit as the main continuity gap.

Production chat titles (last 120 days, read Nov 24 2026) show projects that already
exist, just without the folder:

- **Jana's copywriting clients**: about 10 chats each for Hanák/Zeleko LinkedIn posts,
  Zdeněk Zajíček's LinkedIn, and the whisky shop's "postupka". She comes back to each
  every week or two, some chats run to 60 messages, and only 3 of her 27 memories mention
  any of them. Each client's voice and background are re-explained every time.
- **Jiri's bikes** (the Canyon road bike choice, selling the Topstone, the GT Grade
  stripdown, the Canyon Enduro setup), **home** (the wallbox hookup, circadian lighting)
  and **car** (the Toyota loan, the G31 service).
- **The kids' schoolwork** (Viktor's maths test and Scio prep; Brigita's Animal Farm
  chapters and Australia presentation). Shared with a parent, this is the family case.

Prior art (research, Nov 24 2026): ChatGPT Projects, Claude.ai Projects, Claude Code
(CLAUDE.md layers, per-repo auto memory), Hermes Agent (profiles, context files, frozen
memory snapshot), Gemini notebooks, Perplexity Projects. All of them share instructions,
files and the project's chat history. Memory is layered: personal, then project, then the
chat. The common complaints are project instructions ignored as a chat grows, files never
opened unless the model is told to look, memory leaking between projects, and isolation
that only comes by switching memory off altogether.

## Goals

1. Users create projects, and move their existing chats in and out (one at a time or in
   bulk). A new chat can be started inside a project.
2. A project has **instructions** (free text, editable by members) that every chat in it
   follows.
3. A project has its own **memory**. Facts about the project's topic go there, written by
   the agent in a turn (`manage_memory`) or by the background memory review. Personal
   facts stay personal. Inside a project the agent sees the user's personal memory plus
   that project's memory. It never sees another project's memory.
4. A project has its own **documents**: saved-document library entries scoped to it.
5. **Sharing (model A, decided with Jiri):** the owner adds other family members.
   Members share the project's instructions, memory and documents. Each member's chats
   stay private: in the project, a member sees only their own chats.
6. Past-chat search inside a project searches that project's chats first.

## Non-goals (v1)

- **Shared chats (model B)**: every member sees and continues every chat in the project.
  This goes to TODO.md as a follow-up, likely as an explicit "share this chat" action.
- Standing chats, agents, Sports/Language coaches and What's new inside projects. They
  have their own standing context. Anonymous chats can't join a project either.
- A per-project "ignore my personal memory" switch.
- Defragmenting project memory. The per-project cap bounds it; add defrag if projects
  approach the cap.
- RAG over project documents. It inherits the library's "one list, open on demand".
- Invitations, roles beyond owner and member, and leaving notifications. The family is
  the deployment's user list, so there is no invite flow.

## Anti-goals

- **Personal memory leaking to family.** In a shared project, a member's personal facts
  (health, a crush, money) must never be written into project memory, where the others
  read it in every turn. This is the failure that would make the feature harmful even
  though it works.
- **One project's memory showing up in another project or in a plain chat.**
- **Instructions that fade.** Project instructions are re-sent on every turn as part of
  the dynamic context, never just once in the history where compaction can drop them.
- **Unbounded per-turn cost.** Each project's lists are capped like the personal ones.

## Approaches considered

1. **Projects as their own records, reusing memories and documents (chosen).** New
   `projects` and `project_members` tables, plus `conversations.project_id`. A project
   memory is a `user_memories` row with a `project_id`, and a project document is a
   `user_documents` row with a `project_id`. Every existing memory and document feature
   then works for projects once a scope is threaded through: `manage_memory`, end dates,
   previous text, search, embeddings, the review, the nightly expiry and purge, and the
   UI rows. The cost is scoping every memory and document query, plus caps per project.
2. **A project notebook**: one shared Markdown page per project holding instructions and
   running notes, which the agent edits (like CLAUDE.md or Hermes's MEMORY.md) and the
   family can edit by hand. It's simpler and transparent. But it's a second memory system
   with no end dates, search or review. A single page tends to grow until instructions
   get ignored, which is the research's top complaint. And two members' chats editing
   one page collide.
3. **Copy project settings into each chat** through the standing-chat columns. Cheapest,
   but the copies drift apart and there is no shared memory, so it fails goal 3.

Jiri picked approach 1 and sharing model A, with B left for TODO.

## Design

### Data (migration `0104_projects`; re-check the highest number on `main` before committing)

`projects`:

| column | notes |
|---|---|
| `id` | UUID |
| `owner_id` | FK users, cascade |
| `name` | <= `PROJECT_NAME_MAX_CHARS` (60). The UI may prefix an emoji, like chat titles |
| `instructions` | text, <= `PROJECT_INSTRUCTIONS_MAX_CHARS` (4000), may be empty |
| `created_at`, `updated_at`, `deleted_at` | soft delete, see Deleting |

`project_members`: `(project_id, user_id)` primary key, `added_at`. The owner is a member
row too, so every scope check is one membership lookup. Cascade from both sides.

`conversations.project_id` is a nullable FK to projects. Only that chat's owner sets it,
and only for a plain chat (not an agent, Sports, Language, What's new or anonymous chat).

`user_memories.project_id` and `user_documents.project_id`: nullable. `user_id` keeps
meaning **author** (the member whose turn wrote it). Partial indexes on
`(project_id, updated_at)` where `deleted_at IS NULL`.

**Scope rule (the core invariant):** personal = `user_id = ? AND project_id IS NULL`;
project = `project_id = ?` plus a membership check for the caller. Every existing personal
memory and document query gains `project_id IS NULL`. Without it, a member's personal
list would include what they wrote into a shared project, and their search would reach
other projects. A test per query enumerates them: list, count, search, embeddings recall,
the review's list, defrag's input, the Data page, the caps and the usage totals, plus `instructions_review` and the
admin memory counts.

**Authorization rewrite, not just a filter.** Today every memory and document lookup
matches `user_id = ?`: short-id resolution (`matching_memory_ids`), patch, delete,
protect, restore, `restore_previous`, `get_document`, `_retire_replaced` and
`/documents/<id>/file`. Each one becomes "personal row of the caller, or a row of a
project the caller belongs to (the current project, for agent tools)". Short ids resolve
over personal + current-project ids, and a collision is reported naming both, as today.

**Embeddings get a `project_id` column too.** The `embeddings` table is keyed by
`user_id`, and `upsert_embedding` overwrites `user_id` on conflict. Without this, a member
patching another member's project memory would move its vector into *their* personal
recall, which is a leak path. Project vectors carry `project_id`, the upsert never
rewrites ownership, personal recall filters `project_id IS NULL`, and project recall
filters by project.

**Author accounts.** `user_id` on memories and documents cascades on user delete
(0009, 0103), so a deleted account's project memories and documents go with it. My
call: accept that. Deleting a family account is rare and done by hand, and changing the
FK means rebuilding both tables.

### Bounds (all in `src/config.py`, `.env.example`, docs)

- `PROJECTS_MAX_PER_USER` (30, owned): plenty for the observed topics.
- `PROJECT_MEMORY_MAX_ENTRIES` (60): all injected, with no tiering (it equals
  `MEMORY_INJECT_FULL_MAX`). A write past the cap is rejected with a message telling the
  agent to merge or delete.
- `PROJECT_DOCUMENTS_MAX_ENTRIES` (20). Bytes count toward the **author's**
  `DOCUMENTS_MAX_TOTAL_BYTES`, since the author's upload is what's stored.
- `PROJECT_INSTRUCTIONS_MAX_CHARS` (4000): half the personal instructions cap. Long
  blocks are what gets ignored.

### Agent context in a project chat

The dynamic context (`prompts.py`, next to the memory and document lists) gains a
`# Project: <name>` section **after** the personal lists, so project text sits closer to
the conversation:

```
# Project: Hanák / Zeleko (shared with Jiří)
Instructions:
<project instructions>

Project memory (facts about this project, visible to every member):
- <short id> | <category> | <created>[, upd ...] | by Jana | <text>
...
Project documents:
- <short id> | <title> | ... | Use for: ...
```

- The author's first name is shown only in a shared project, so the agent can tell whose
  note a fact is.
- If the project has no instructions, the line is left out; empty lists are left out
  too. The section is omitted entirely outside a project.
- Static guidance (cached prefix, only when the memory tool is bound) explains the two
  scopes:
  - Facts about the project's topic go to `scope: "project"`.
  - Facts about the user go to `scope: "personal"`.
  - In a **shared** project, health, relationships, money and anything private stays
    personal, or is not saved at all, because family members read project memory.
  - Project instructions win over personal custom instructions where they conflict.
  - Open a project document when the chat matches its use.
- Prompt snapshot cases: a chat in a solo project, a chat in a shared project, and a chat
  with no project (unchanged).

**Prefix cache:** the section is dynamic, like the memory list, so the static prefix
stays shared across all chats. Check `_static_prefix_profile` is unchanged.

### Tools

- **`manage_memory`**: each `add` op takes an optional `scope` (`"personal"` |
  `"project"`), default `"personal"`. A safe default, since the prompt pushes topic
  facts to the project. `"project"` outside a project chat is `REJECTED` with a reason.
  `patch`, `delete` and the rest find the scope from the memory's id. They may touch
  personal memories and the **current** project's. Another project's id gets "not
  found", the same as a foreign user's today. Members may patch or delete each other's
  project memories, since the project is shared. Each write logs its author.
- **`search_memory`**: personal + the current project, each hit tagged `(project)` or
  `(personal)`.
- **`manage_documents` `save`**: optional `scope` the same way. `open_document` reaches
  personal documents + the current project's. A member may replace another member's
  project document. The new copy is the replacer's upload and counts against their
  bytes; the old one is soft-deleted and counts against its author until purged.
- **`search_conversations`**: in a project chat, a new `scope` argument, default
  `"project"`. It searches the user's **own** chats in this project, then fills the
  remaining slots from their other chats, each hit tagged `(this project)` or `(other)`.
  `scope="all"` ignores the project. It never reaches another member's chats (model A).
  `read_conversation` stays owner-only.
- **`propose_instruction_change`** (decided with Jiri, 1A): in a project chat, the
  proposal takes a `scope` (`"personal"` | `"project"`), and the agent picks it. A
  client- or topic-specific rule goes to the project. The card names the target ("Add to
  Hanák / Zeleko instructions"). Accepting a project-scoped card edits
  `projects.instructions` (any member may accept, as they may edit them by hand), within
  `PROJECT_INSTRUCTIONS_MAX_CHARS`. Outside a project only `"personal"` exists. The
  instructions self-tuning review (`instructions_review.py`) follows the same rule for
  project chats. Eval: in a project chat, "no emoji for this client from now on" proposes
  a project-scoped change.
- **`manage_project(operations)`** (Jiri, Nov 24 2026: in the initial scope). It writes
  inline and reports per-op results like `manage_memory`. Ops:
  - `list`: the user's projects (short id, name, shared, chat count);
  - `create`: `name`, optional `instructions`, optional `move_current_chat` (default
    true). "Turn this chat into a project" is one call; the agent drafts the
    instructions from the chat;
  - `move_chat`: the current chat, or one of the user's chats by id (from
    `search_conversations`), into a project the user belongs to;
  - `remove_chat`: take a chat out of its project;
  - `rename` (owner only) and `set_instructions`, a full replacement within the cap, for
    when the user explicitly asks. Lasting corrections still go through the
    `propose_instruction_change` card.

  The rules for when it acts:
  - It acts when the user asks. When a chat clearly belongs to an existing project, or
    a topic recurs, it may **offer** to move the chat or create a project, and acts only
    after a yes (the same as saving documents).
  - **Sharing and deleting stay UI-only.** Who can read a project's memory is decided by
    a person on the project page, never by a turn that may have read planted web
    content.
  - A move takes effect from the **next** turn. The current turn's prompt is already
    built, so the result says so.
  - The same chat-kind rules as the UI apply (no agent, coach, What's new or anonymous
    chats).
  - Guards: not bound in anonymous mode or in autonomous runs, an injection scan on
    `name` and `instructions`, and never in `EXTRACT_ONLY_TOOL_NAMES`.
  - Logs "Project tool" (op, project id, ok/rejected reason).
  - Evals: "make this a project" creates the project and moves the chat; "move this to
    my Bikes project" moves it; a chat about a client with an existing project gets an
    offer and no move without a yes.
- Autonomous runs and anonymous mode: unchanged. Agent chats can't be in a project, so
  no run ever has a project scope.

### Background memory review (`memory_review.py`)

For a project chat, the review prompt also lists the project's memories (with ids) and
explains the two scopes and the shared-project privacy rule. Each op it returns carries
`scope`. The reply label ("Saved to memory: ...") names the project for project writes.
An eval case pins the privacy rule (below).

### Moving chats

- **The chat's ⋯ menu / action sheet**: **Move to project…** opens a picker with the
  user's projects, then **New project…**, then **Remove from project** when the chat is in
  one. The same action is available in bulk select mode.
- A moved chat's earlier turns stay as they are. From its next turn, it gets the
  project's context. Memories the chat wrote earlier stay personal; nothing is
  re-filed. (A possible later "file this chat's facts under the project" action goes to
  TODO.)
- Removing a chat from a project leaves the project memories it wrote in the project.
- **Starting a chat from the project page** sets `project_id` when the conversation is
  created, on both the stream and batch paths (and the E2E fake), so the first turn
  already has the project context.
- **Pinned, archived and unread (my calls):**
  - A pinned project chat stays under Pinned in the main list, because pinning is an
    explicit wish to see it there. It shows the project name.
  - The Archived list shows archived project chats with the project label.
  - A project row in the sidebar shows an unread dot when any of the user's chats in it
    has unread messages (background replies, other devices). The sync delta still
    carries project chats; the client files them under their project.
  - The project page lists chats by recency with the same Today / Yesterday groups.
- Trash and archive keep `project_id`. A restored chat goes back into its project if the
  project still exists and the user is still a member, and into the main list otherwise.

### Sharing

- The owner adds or removes members from the project page. The picker lists the
  deployment's other users (the family).
- A member sees the project in their sidebar with a shared marker. They can edit the
  instructions, add, delete or protect project memories, save documents, and move their
  own chats in.
- Only the owner renames or deletes the project and manages members. A member can
  **leave**.
- When a member is removed or leaves, their chats in the project go back to their main
  list (`project_id = NULL`). The project memories and documents they wrote stay with
  the project. Documents keep their blob and stay counted against the author's bytes
  until deleted. (Builder call; revisit if it matters.)
- Sync: members' clients learn about project changes (new project, rename, membership,
  instructions) through the existing sync poll. One option is a project change counter
  next to the conversation change log, returned with the sync response. The builder
  picks the mechanism; it must not add a second polling loop.

### Deleting a project

Owner only, with a confirm. The project is soft-deleted. Every member's chats go back to
their main lists. The project's memories and documents are soft-deleted (restorable from
the project's entry in **Recently deleted projects** on the Data page for
`DOCUMENTS_SOFT_DELETE_RETENTION_DAYS`). The nightly purge then removes them with their
blobs. Restoring a project restores those memories and documents but not chat
membership, because the chats may have moved elsewhere. (Builder call.)

### UI

**Sidebar.** A **Projects** group above the chat list. Each row shows the name, a shared
marker and a ⋯ menu. A tap opens the project page. **New project** sits at the end of the
group. Project chats **leave the main chat list** and live in their project. This is what
declutters Jana's 1,400 chats; the sidebar search still finds them, labelled with the
project name.

```
┌ Sidebar ───────────────────┐   ┌ Project page ───────────────────────────┐
│ [+ New chat]   [search]    │   │ 🐟 Hanák / Zeleko        👥 Jana, Jiří ⋯ │
│ PINNED                     │   │ ┌ composer: New chat in this project ┐  │
│  ...                       │   │ └────────────────────────────────────┘  │
│ PROJECTS                   │   │ Chats (yours)                            │
│  🐟 Hanák / Zeleko  👥      │   │  LinkedIn posty pro Hanáka   · Nov 9     │
│  🥃 Whisky postupka        │   │  Říjnové příspěvky ...       · Oct 1     │
│  🚴 Bikes                  │   │ Instructions            [Edit]           │
│  + New project             │   │  Tone: friendly expert, no emoji ...     │
│ TODAY                      │   │ Memory (12)             (rows, delete)   │
│  ...                       │   │ Documents (2)           (rows)           │
└────────────────────────────┘   └──────────────────────────────────────────┘
```

**Project page** (main pane, like the Command Center or Data page). From the top:
- the name and members;
- a composer that starts a chat in the project;
- the user's chats in the project, newest first, paginated like the main list;
- the instructions (inline edit, save on blur, the same as the custom instructions
  field);
- the memory rows (the Data page's memory row component: delete, protect, previous
  text);
- the document rows (Data page component).

A chat inside a project shows the project name in its header as a link back to the
project page.

**Mobile.** The project page is a full view, opened from the drawer. Test at 768 px and
on desktop. Follow the existing patterns: `EmptyState` for "no chats yet", `btn btn-*-sm`
buttons, raised surfaces, icon + label headers, component-prefixed CSS (`project-*`).

**Data page.** It stays the personal library: memories and documents with
`project_id IS NULL`. Add a Recently deleted projects list.

### API

`src/api/routes/projects.py` and Pydantic schemas, then `make openapi`, `make types`, and
`web/src/api/projects.ts`:

- `GET /api/projects`: projects the user belongs to (owner or member), with member names
  and the user's chat count in each.
- `POST /api/projects` with `{name, instructions?}`.
- `GET /api/projects/<id>`: details, instructions, memories, documents (members only).
- `PATCH /api/projects/<id>` with `{name?, instructions?}` (name: owner only).
- `DELETE /api/projects/<id>` (owner) and `POST /api/projects/<id>/restore`.
- `PUT /api/projects/<id>/members/<user_id>` and `DELETE .../members/<user_id>` (owner;
  a member may remove only themself).
- `GET /api/projects/<id>/conversations?cursor=`: the user's own chats in the project.
- `PATCH /api/conversations/<id>` gains `project_id` (null to remove), or a bulk move in
  select mode: reuse the bulk endpoint's resolution of "select all".
- Project memory and document delete, protect and restore reuse the existing memory and
  document endpoints, which now authorize by scope: author, or a member of the row's
  project.
- `GET /api/users` (or the existing equivalent) for the member picker: id and name only.

### Instrumentation (A8)

- Log lines (ids and counts only, no names, instructions or memory text):
  - "Project created", "Project deleted", "Project member added/removed";
  - "Chat moved to project" (`from`, `to`, bulk count);
  - "Project memory write" (`project_id`, `author`, op, source tool/review);
  - "Project context" per turn (`project_id`, `shared`, `chars` of the section).
- `docs/regular-review.md` check:
  - projects per user, how many are shared, chats per project;
  - share of a user's new chats started inside a project;
  - project memories written per project, and by whom;
  - the project section's chars per turn;
  - a manual sample of shared-project memories for personal facts that leaked (the
    anti-goal).
- TODO.md: re-measure ~Dec 22 2026.
  - Are projects created and kept used?
  - Does project memory fill, or stay empty?
  - Does Jana's re-explaining drop? Compare the length of the first user message in her
    client chats before and after.
  - What does the section cost per turn?

### Evals

Run `make eval-smoke` plus these cases, and report the cost:

- **Topic facts:** in a solo project chat, the user states a topic fact (the client
  prefers no emoji). It is saved with `scope: "project"`.
- **Personal facts:** in a **shared** project chat, the user mentions a personal health
  fact. It is not saved to the project (saved personal, or not at all). Run the review
  path on the same transcript too.
- **Instructions in long chats:** a seeded project with an instructions rule (formal
  address). A long `chat_*`-style history still follows it at the end.
- **Documents:** a seeded project document whose use matches the question gets
  `open_document` before the answer.
- **Search:** "what did we decide last time" in a project chat calls
  `search_conversations` and gets this project's chat first.
- **No leaks:** a plain chat (no project) with a project's fact asked about. The agent
  does not know it and does not claim to, and `search_memory` doesn't return it.

The E2E fake (`tests/e2e_server/`) needs the new tool arguments if it mirrors tool
signatures.

### Announcement

`announcements/<ship date>-projects.md` (Czech + English, for the family):
- chats can be gathered into projects, each with its own instructions and memory;
- projects can be shared with family members, and each person's chats stay their own;
- existing chats move in from the chat menu.

## Suggested build order (for the plan)

Each slice is deployable alone, with the UI hidden until slice 2:

1. Schema, scope rule and queries (with the no-leak tests), the projects API, moving
   chats.
2. Sidebar group, project page, chat header link, instructions in the prompt,
   `manage_project`, the announcement.
3. Project memory: the `manage_memory` and `search_memory` scope, the prompt list, the
   review, the evals.
4. Project documents, scoped conversation search.
5. Sharing: members, the picker, sync, leave and remove. It ships last, behind the
   privacy gate below.

### Privacy gate for sharing (decided with Jiri, 2A)

- **Evals:** a privacy set (a health fact, a crush, money) in a shared project chat.
  Each case passes **3 of 3 runs** on both write paths: inline `manage_memory` and the
  background review. Sharing does not ship until it does.
- **Visible writes:** every write to a *shared* project's memory, inline or from the
  review, adds a "Saved to <project> memory: ..." note under the reply. Reuse the
  review's reply label, so the author sees it at once and can delete it from the project
  page. There is no confirmation step (approval friction was declined for memory edits
  before).

## TODO.md entries this adds

- Shared chats (model B): every member sees and continues every chat in a project.
- "File this chat's facts under the project" (re-file a moved chat's personal memories).
- Project memory defrag, once a project nears `PROJECT_MEMORY_MAX_ENTRIES`.
- The re-measure above (~Dec 22 2026).

## Left to the builder

- Exact prompt wording and the section's layout (measure it in the snapshot).
- The sync mechanism for project changes (within the existing poll).
- Visual details of the project page and the picker within the existing patterns.
- Whether bulk move reuses the bulk-delete endpoint or gets its own.
