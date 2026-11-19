# Todoist: add_tasks and list_completed - design (short)

**Intent.** "Add milk, eggs, bread and butter" takes one `add_task` call per
item: each is a model call that re-sends ~20k tokens of prompt and tools.
And the tool cannot read completed tasks, so "what did I get done this week"
has no answer.

**Goals.**
- `add_tasks` action: `tasks` = up to 25 entries (`content` required;
  `description`, `due_string`/`due_date`, `priority`, `labels`, `project_id`,
  `section_id`, `assignee_id` optional). A top-level `project_id`/`section_id`
  is the default for entries without one. One REST create per entry (the
  existing `todoist_add_task`), all in one tool call; the result lists
  `added` (id, content) and `failed` (content, error). It fails as a whole only
  if every entry failed.
- `list_completed` action: optional `since`/`until` (YYYY-MM-DD, local
  dates, `until` inclusive; default the last 7 days) and `project_id`.
  `GET /tasks/completed/by_completion_date` (range at most 3 months, the API's
  limit; paged by `items`/`next_cursor`). Items: content, local completion
  time, project name; capped at `TODOIST_MAX_TASK_RESULTS`.
- The autonomous gate already treats `add_tasks` as a write and
  `list_completed` as a read (`_READ_PREFIXES`).
- A8: the existing "todoist called" log line carries `action` and the count;
  a re-measure in TODO.md: `add_tasks` calls vs turns with 3+ `add_task`
  calls (`message_costs.tools_used`).
- A7: What's-new announcement.

**Approaches.** (1) REST loop inside one tool call (chosen): reuses
`todoist_add_task` and its field mapping; per-entry errors come for free.
(2) Sync API `item_add` batch: one HTTP request, but a different arg shape
(`due` objects, `responsible_uid`) to map and test, for no user-visible gain
at 25 items. (3) Leave it to the model to call `add_task` in parallel: the
measured pattern is one call per round (tool-round-economics, Sep 2026).
