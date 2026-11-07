# Scheduling From Chat + Silent Runs - Design

Approved in chat with Jiri on Nov 7 2026.

## Why

Nobody can say "remind me Friday at 8 to call the plumber" or "every Monday check the
school menu and tell me": scheduled agents are created only in the Command Center form.
And every scheduled run pushes, whether or not it found anything - more scheduling
without a way to stay quiet would mean more noise.

## Goals

1. From any ordinary chat, create a **one-off reminder** (a push at a time, no model call)
   or a **recurring task** (a scheduled prompt-only agent), and list / pause / resume /
   delete them.
2. Scheduled agents can say "nothing new" and **not push**.

## Non-goals (stay in TODO)

Self-stopping watchers, once-per-failure alerts, results delivered into the originating
chat, goal mode, a tap-to-confirm card.

## Decisions

- **Confirmation in chat** (Jiri's choice): `create` without `confirm=true` only returns a
  preview ("Every Monday 9:00 - check the school menu. Ask the user to confirm, then call
  again with confirm=true."). Nothing is stored until the confirmed call. Works the same in
  streaming and batch.
- **Reminders are not agents.** A `reminders` table (user, conversation, text, due_at,
  status) and the existing every-minute scheduler send them as a push with no model call -
  cheap and certain to fire. The push opens the conversation it was set in.
- **Recurring tasks are ordinary agents** (`db.create_agent`, prompt-only, visible and
  editable in the Command Center). Their prompt is the task, run through the injection
  scan (`find_injection`).
- **Schedules are built by code, not the model** (my call): the model passes structured
  fields - one-off `date` (YYYY-MM-DD) + `time` (HH:MM); recurring `days` (mon..sun, or
  "daily"/"weekdays") + `time` - in the household timezone (`Config.APP_TIMEZONE`). Code
  validates and builds the datetime / cron string. Language-independent (Czech works).
  Refused: a one-off in the past; recurring more often than once a day per time given
  (one time per day; minutes 0-59).
- **Limits** (my call): at most `SCHEDULE_MAX_ACTIVE_PER_USER` (default 20) active
  reminders + chat-created agents per user; a scheduled run cannot schedule (the tool is
  not bound for agents); anonymous chats get no tool.
- **Silent runs:** scheduled agents' prompt says: when the check finds nothing worth
  telling, reply exactly `[SILENT]`. The executor then stores "Nothing new." as the reply
  and sends no push. Manual runs are unaffected (they never push).

## Constraints

- Production daily driver; repo is public (no infra in docs/commits).
- New env vars: `src/config.py` default, `.env.example`, `docs/features/` page.
- New tool: the `/new-tool` checklist (`TOOL_METADATA`, `extract_tool_detail`,
  `lost_actions.SIDE_EFFECT_TOOLS`, agent-editor lists as applicable) and
  `make prompt-snapshots`.
- New migration: check the highest number on main right before committing.
- Report eval cost.

## How we'll know it worked

- Evals: "remind me tomorrow at 8 to call the plumber" -> preview, then on "yes" a stored
  reminder at the right local time; "every Monday at 9 check the school menu" -> preview,
  confirmed -> an agent with cron `0 9 * * 1` in the household timezone; a check with
  nothing new -> `[SILENT]`.
- A due reminder pushes exactly once within a minute (scheduler test).
