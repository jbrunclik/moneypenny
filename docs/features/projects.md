# Projects

A project is a folder of chats about one lasting topic - a client, a renovation, a
bike, a holiday - with its own **instructions**, **memory** and **documents**. A new
chat in the project starts out knowing what earlier chats in it settled. A project can
be **shared** with other family members: they share its instructions, memory and
documents, while each member's chats stay their own (Nov 2026,
[spec](../superpowers/specs/2026-11-24-projects-design.md),
[plan](../superpowers/plans/2026-11-24-projects.md)).

## Design decisions

- **Shared context, private chats** (sharing model A, Jiri's call). A member sees only
  their own chats in a project; what one member's chat settles reaches the others
  through project memory, never by reading the chat. Shared chats (model B) are a TODO.
- **Project memories and documents are ordinary rows** with a `project_id`
  (`user_memories`, `user_documents`); `user_id` stays the author. Every memory and
  document feature (end dates, previous text, search, review, expiry, purge, the UI
  rows) works for projects through a scope.
- **The scope rule.** Personal = `user_id = ? AND project_id IS NULL`; project =
  `project_id = ?` plus membership. Every personal query filters `project_id IS NULL`
  (the no-leak tests in `tests/integration/test_db_project_scope.py` list them). Three
  reaches:
  - *personal* - the Data page, defrag, the instructions review;
  - *in scope* (`get_*_in_scope`) - a chat turn's tools: personal plus the **current
    chat's** project;
  - *visible* (`get_visible_*`) - the app's routes: personal plus every live project the
    user belongs to.
- **Embeddings are fetched by the visible ids** (`get_embeddings_for_refs`), not by
  user: a member's edit rewrites the stored `user_id`, which must not move a vector.
- **The project's text rides in the dynamic context**, after the personal memory and
  document lists (`# Project: <name>` section, `src/agent/prompt_projects.py`). Only
  project chats pay for it; the cached static prefix is the same for every chat.
- **Tools find the project from the conversation row** (`project_scope.chat_project_id`),
  not a contextvar: tools run on the graph's threads.
- **Sharing and deleting are UI-only.** `manage_project` creates, renames, moves chats
  and sets instructions; who may read a project's memory is decided by a person on the
  project page, never by a turn that may have read planted web content.

## Data

Migration `0104_projects`: `projects` (owner, name, instructions, soft delete),
`project_members` (the owner is a member row too), and a nullable `project_id` on
`conversations`, `user_memories` and `user_documents` (no `REFERENCES` clause: foreign
keys are not enforced here, and such a column cannot be dropped on rollback).

- **Which chats can join**: ordinary chats only - not planning, agent, Sports,
  Language, What's new, standing or anonymous (`ELIGIBLE_CHAT_SQL` in
  `src/db/models/projects.py`, mirroring `is_ordinary()`).
- **Main list**: project chats leave it (`project_id IS NULL OR pinned = 1`); a pinned
  one stays under Pinned. The sync listing keeps every chat, and the client files them.
- **Leaving / removal**: the member's chats in the project return to their main list;
  what they wrote stays with the project.
- **Delete**: soft; the project, its memories and documents share one `deleted_at`, so
  a restore brings exactly those back (not the chats). Project memories wait for the
  project's purge (`DOCUMENTS_SOFT_DELETE_RETENTION_DAYS`, 30) rather than the memory
  purge's 7 days; `purge_deleted_projects` runs after the document purge in the nightly
  job.
- **Trash**: a restored chat keeps its project only while its owner is still a member
  of the live project.
- **Bytes** of a project document count toward its author's
  `DOCUMENTS_MAX_TOTAL_BYTES`; the entry cap is the project's.

## Agent side

- `manage_memory`: `scope` on `add` (`"personal"` default, `"project"` only in a project
  chat); patch/delete reach personal memories and the current project's. A batch past
  `PROJECT_MEMORY_MAX_ENTRIES` is rejected. `search_memory` covers both, tagging
  `(project)`.
- `manage_documents`: `scope` on `save`; `open_document` and code access
  (`doc:<id>`) reach personal plus the current project's documents. A member may replace
  another member's project document.
- `search_conversations`: `scope` (`"project"` default) ranks the user's own chats in
  this project first, tagged `(this project)` / `(other)`; `"all"` ranks every chat
  alike. Other members' chats are never searched.
- `propose_instruction_change`: `scope` - in a project chat, a client- or topic-specific
  rule is proposed for the project's instructions (decided with Jiri, 1A). The card says
  "Every chat in the <name> project"; accepting it edits `projects.instructions` while
  they still hold the text the change was computed from. A project card has no memory
  part.
- `manage_project` (ordinary non-anonymous chats only, never a grant): `list`,
  `create` (moves the current chat by default), `move_chat`, `remove_chat`, `rename`
  (owner), `set_instructions`. A move takes effect from the next turn.
- **Background memory review**: in a project chat the prompt lists the project's
  memories and the two scopes; in a shared project, the privacy rule. The nightly
  instructions review learns personal style only from chats outside projects.

## Privacy gate for sharing (decided with Jiri, 2A)

- **Visible writes**: every write to a *shared* project's memory - inline
  (`src/api/helpers/project_notes.py`) or from the review - labels the reply: "Memory
  updated: <items> (in the <name> project - its members see it)".
- **Evals**: `project_shared_*` cases (health, a crush, money, and the review path) must
  pass 3/3 runs before sharing ships.

## UI

- **Sidebar**: a Projects group (only once the user has a project) with a shared marker
  and an unread dot; **New project** is in the user menu.
- **Project page** (`#/projects/<id>`, `ProjectPage.ts`): name and members, Share
  (owner) / Rename / Delete or Leave, New chat in this project, the user's chats,
  instructions (save on blur), project memory (author names when shared), documents.
- **Moving chats**: the chat's menu (Move to project… / Remove from project, with Undo)
  and bulk select (Move to project).
- **Chat header**: a link to the chat's project (desktop; the mobile header is hidden).
- **Sync**: the sync response carries `projects_version` (count, deleted count, latest
  `updated_at` of the user's projects); when it moves, the client reloads the projects.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PROJECTS_MAX_PER_USER` | 30 | Live projects a user may own |
| `PROJECT_NAME_MAX_CHARS` | 60 | Name length |
| `PROJECT_INSTRUCTIONS_MAX_CHARS` | 4000 | Instructions length (half the personal cap) |
| `PROJECT_MEMORY_MAX_ENTRIES` | 60 | Project memories, all listed every turn |
| `PROJECT_DOCUMENTS_MAX_ENTRIES` | 20 | Project documents |
| `PROJECT_MAX_OPS_PER_CALL` | 5 | `manage_project` operations per call |

## Instrumentation

Log lines (ids and counts only): "Project created", "Project deleted", "Project member
added" / "removed", "Chat moved to project", "Project memory write", "Project context"
(`chars` of the section per turn), "Project tool", "Shared project memory noted". The
regular-review check is in [regular-review.md](../regular-review.md).

## Key files

- `src/db/models/projects.py`, `src/db/models/memory.py`, `src/db/models/documents.py`
- `src/api/routes/projects.py`, `src/api/schemas/projects.py`
- `src/agent/project_context.py`, `src/agent/prompt_projects.py`,
  `src/agent/prompt_texts/projects.py`, `src/agent/tools/projects.py`,
  `src/agent/tools/project_scope.py`, `src/api/helpers/project_notes.py`
- `web/src/core/projects.ts`, `web/src/components/ProjectPage.ts`,
  `web/src/components/ProjectPicker.ts`, `web/src/state/slices/projects.ts`,
  `web/src/api/projects.ts`

## Testing

Backend: `tests/integration/test_db_projects.py`, `test_db_project_scope.py`,
`test_db_project_conversations.py`, `test_routes_projects.py`,
`test_memory_note_projects.py`; `tests/unit/test_projects_tool.py`,
`test_memory_tool_projects.py`, `test_memory_review_projects.py`,
`test_instructions_tool_projects.py`, `test_documents_tool_projects.py`,
`test_conversation_search_projects.py`, `test_prompt_projects.py`. Frontend:
`web/tests/unit/projects.test.ts`, `project-picker.test.ts`, the Sidebar component
tests, `web/tests/e2e/projects.spec.ts`, `web/tests/visual/projects.visual.ts`. Evals:
`evals/cases/project_*.yaml`.
