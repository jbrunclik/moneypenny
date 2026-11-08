# Standing Chats - Design

Discussed in chat with Jiri on Nov 8 2026. Builds on
[lightweight agents from chat](2026-11-07-lightweight-agents-design.md) (scheduled items,
shipped Nov 7-8 2026). Jiri: "the agent design is very old - we can both improve and
simplify"; "keep language for now and just simplify/consolidate".

## Why

There are four special kinds of chat - **agent**, **sports program**, **language program**
(and the planner, out of scope here) - and each is a special case in the tools, the prompt,
the context cache, compaction, the turn setup and the UI. When the user writes in one of
them, it behaves unlike a regular chat:

| | Regular chat | Agent chat | Sports / language chat |
|---|---|---|---|
| "Remind me...", conversation facts, deep research | yes | no | no |
| Freshness check before answering | yes | no | no |
| Todoist, Calendar, WhatsApp, places, code, images, artifacts | yes | only if granted | removed (token trim) |
| Prompt | chat prompt | autonomous-agent prompt | program prompt |
| Long history | chat compaction (full text kept, searchable) | **destructive**: all but the last 10 replaced after 50 | chat compaction |
| Context cache | yes | no | per-program profile |
| Tools while the user is present | full | the agent's unattended restrictions | trimmed |

Production, Nov 8 2026 (counts only):

- **Agents:** Daily Briefing (158 runs) and VWCE Watcher (29) - nobody replies; a cycle coach
  on Garmin data (122 runs) - the user chats with it, but only 5 typed messages survive
  (the rest were compacted away), and "remember..." / "remind me..." fail there because the
  agent's run restrictions apply while the user is present.
- **Sports programs:** 3 users, 9 programs, ~110 user messages in the last 30 days - all
  coaching (cycling, strength, indoor trainer). "Put tomorrow's workout in my calendar"
  fails (Calendar is trimmed).
- **Language programs:** dormant since August; kept and consolidated (Jiri).

Meanwhile chat items (`scheduled_items`) already give ordinary chats reminders, check-ins,
watchers and recurring checks - a recurring item is basically a lightweight agent.

## The model: standing chats with jobs

A **standing chat** is a long-lived chat with:

- **standing instructions** (an agent's goals, a program's coaching prompt),
- optional **state** (a program's kv data: goals, progress, vocabulary) and **dashboard**,
- optional **jobs** that post into it (scheduled items: check-in, watcher, recurring...).

Agents, sports programs and language programs are all standing chats.

- **Writing in a standing chat is an ordinary chat turn**: the normal chat prompt and the
  user's full chat tools (memory, schedule, conversation facts, deep research, calendar,
  Todoist...), freshness check, context cache, normal (non-destructive) compaction - with
  the chat's standing instructions and domain context (program state, dashboard data)
  added. The user is present, so no unattended restrictions apply (Jiri: full chat tools).
- **Jobs run unattended** and keep what makes that safe: their grants (not the user's full
  tools), approvals for write actions, fresh-context option, silent runs (`[SILENT]`).
- **A standing agent** = a standing chat whose job has grants. The Daily Briefing becomes
  "Daily Briefing chat + a daily 07:15 job". A sports coach can get jobs too ("how did
  today's ride go?" check-ins, a Sunday weekly plan, a reminder before a session).

## Limits: light items vs standing jobs

A job is **standing** when it has grants (the user made it a proper agent); quick items
created from an ordinary chat are **light** and keep today's limits. Jiri: standing agents
need looser limits.

| Limit | Light item | Standing job |
|---|---|---|
| Expiry | watcher 30 days by default; recurring none | none |
| After repeated failures | stops after 3, with a note | **pauses** with one alert ("paused after 3 failures" + Resume); the job and its setup stay |
| Frequency | watcher >= 6 h; recurring one time per day | any cron (e.g. hourly), as agents have today |
| Tools while unattended | web only | its grants (Garmin, Todoist...), approvals for writes |
| Memory while unattended | none | if granted |
| Count limit | 20 per user | separate - standing jobs do not use up the 20 |
| Budget | none | per-job daily budget, as agents have today |
| Slow-down when quiet | watchers only | none (a digest keeps its schedule) |

"Make this a proper agent" promotes a light item by adding grants - and **moves its chat out
of the inbox into Agents** (Jiri). "Standing" is a property of the chat: every job with grants
lives in a standing chat, so archiving an inbox chat can only ever pause light items, never an
agent.

- **Budget** (my call): a standing job's daily budget covers its unattended runs only; the
  user's own turns in that chat are ordinary chat spend, so a long talk with the coach cannot
  block its next run. Runs are attributed to the job, not the conversation.
- **Run history and stats** (my call): standing jobs keep their run history and cost stats
  (today's executions and Command Center observability); the jobs list shows recent runs.
- **Context** (my call): jobs in a standing chat see that chat's standing instructions and
  state (a coach's Sunday plan knows the program); light items in ordinary chats stay
  context-free (web tools only), as shipped.

## Agents that work together

Agent-to-agent triggering stays (Jiri): a standing job can trigger another standing chat's
job (today's `trigger_agent`, with its chain/cycle protection), and the agent prompt tells
the model it can in principle build a small multi-agent setup - e.g. propose a helper agent
and have one trigger the other - always through the same approval gates.

## The Daily Briefing

Stays **system-provided** (Jiri): the Settings toggle creates it for any user as a standing
chat + daily job; it keeps the stock prompt from code (improvements arrive with deploys)
until the user edits it - the first edit ("add the weather") freezes that user's own copy,
and the agent says so when proposing the change. "All tools" remains a valid grant.

## Where things live

- **Standing chats never appear in the conversation list** (Jiri works inbox zero:
  archives and deletes chats often; open-ended things like the VWCE Watcher must not sit
  there). Agents live under Agents (the Command Center), programs under Sports / Language,
  as today; deliveries push and bump the area's unread badge. The scheduled-items chip also
  shows in standing chat headers (items created there with `schedule` are visible in place).
- **Chats the user started stay in the conversation list.** Archiving or trashing such a
  chat stops its light items; unarchiving or restoring brings them back (as shipped Nov 7).

## Agents edit their own settings, with approval

- In conversation ("from now on add the weather", "move it to 06:30"): the agent proposes
  the change and it applies after the user's yes - the same preview-then-confirm-in-a-later-
  turn gate as the `schedule` tool.
- In an unattended run ("prices move slowly, check weekly"): the run files an approval
  request (the existing approval workflow); nothing changes until approved.
- **Grants** (more tools, more budget) always need explicit approval, in both cases. An
  agent never widens its own permissions silently.
- Editable: standing instructions, schedule, model, budget, fresh-context, grants.

## Simplify and consolidate

The point is fewer special cases, not more: one conversation kind with optional standing
instructions / state / dashboard / jobs instead of `is_agent` / `is_sports` /
`is_language` branches across tools, prompts, cache profiles, compaction and turn setup.
Dead and duplicate code goes (agent compaction, the interactive-agent turn path, per-mode
tool exclusion lists, and whatever else the consolidation makes unused) - removed with its
tests and docs, after checking it is truly unused.

## Phases (each shipped and deployed on its own)

1. **One turn path.** Writing in an agent, sports or language chat runs the ordinary chat
   turn (full tools, facts, freshness, cache, normal compaction) with the chat's standing
   instructions and domain context added; mode-specific tool trims and turn branches go.
   Agent runs unchanged except destructive agent compaction is replaced by the regular
   chat compaction. UI unchanged (agent header with Run / Edit, approvals, trigger rows,
   program dashboards).
2. **Jobs carry grants; agents become standing chats + jobs.** Scheduled items gain grants,
   approvals, budget, model and the standing-job limits; the three production agents
   migrate (chat + standing instructions + standing job; histories kept); program chats can
   have jobs; one scheduler pass, one run path; `autonomous_agents` and the agent-only code
   are removed. Agents edit their own settings with approval.
3. **Created by talking; the Command Center lists jobs.** "Be my cycle coach, check my
   Garmin every evening and ask how I feel" creates a standing chat with a job (preview +
   confirm, grants approved); the Command Center becomes one list of all jobs (light and
   standing) with run now, pause, edit, approvals; the form editor stays for fine-tuning
   grants. One alert per failure for standing jobs.

## Learnings from current personal agents (Nov 8 2026)

OpenAI's Dots (Sep 29 2026) and Meta's Muse (Sep 8 2026) are always-on personal agents.
What they do that shapes phases 2-3 (phase 1 unchanged):

- **Goals, not just schedules** (Muse: "builds a personalized plan for a shared goal, then
  advances the work"): a standing chat can carry a *goal* - the agent drafts a plan, works it
  through jobs, and checks in on progress (phase 3; the TODO's "goal mode").
- **Proactive notices** (Muse suggests unprompted from memory): a *notice* job type that scans
  memory, calendar and Todoist and speaks only when something is worth flagging (phase 3).
- **Audit trail of done and planned** (Muse; Dots' launch reopened "what did my assistant
  do?"): the Command Center shows each job's recent actions and its upcoming runs (phase 3).
- **Per-connector access levels** (Muse: read email vs also send): grants are per
  integration *and* level, e.g. Todoist read vs write (phase 2).
- **Read-only when the user is absent, never send to others unasked** (Dots): already our
  rule - unattended writes need approval; state it in the agent prompt (phase 2).
- **Later:** an egress check on unattended `fetch_url` (Muse's Sentinel), inbound channels
  and an agent email address (event triggers).

Family use cases these enable: a household logistics chat, a trip planner with a goal and
price watchers, recipe to Todoist shopping list, bill and subscription watchers (Gmail), and
the training coach adjusting its plan.

## Non-goals

- The planner (its own dashboard and refresh flow) - unchanged.
- Event triggers (on email, on calendar change) - later.
- Sharing standing chats between family members.
- Removing language learning (kept, consolidated).

## Anti-goals

- An agent changing its own grants without the user's approval.
- Standing chats cluttering the inbox.
- Losing a companion chat's history (no destructive compaction).
- Unattended runs gaining the user's full tools.
- More noise: silent by default, one alert per failure.
- A consolidation that adds branches instead of removing them.

## Constraints

- Production daily driver (4 users); repo is public (no infra in docs/commits).
- The three production agents, the program chats, their state and histories survive every
  phase.
- Migrations: check the highest number on main right before committing.
- New env vars: `src/config.py` default, `.env.example`, `docs/features/` page.
- Evals for changed agent and program behavior (report cost); UI on desktop and mobile.

## Left to the builder

- How the standing instructions and domain context join the ordinary chat prompt, and what
  that means for the context-cache profiles.
- The data shape for standing instructions, grants and standing jobs (columns on
  conversations / scheduled items vs a settings table).
- The settings-edit tool's name and fields; how approvals render.
- Migration mechanics for the existing agents and their conversations.

## How we'll know it worked

- In the cycle coach's chat and in a sports program, "remember...", "remind me..." and "put
  it in my calendar" work, and history is kept.
- Nothing about a standing chat feels different from a regular chat when you write in it.
- After phase 2, one conversation kind, one turn path, one run path - and less code than
  before (count the removed branches).
