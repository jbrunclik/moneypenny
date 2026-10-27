# Moneypenny

[![CI](https://github.com/jbrunclik/moneypenny/actions/workflows/test.yml/badge.svg)](https://github.com/jbrunclik/moneypenny/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A self-hosted AI assistant for a household, built on Google Gemini. It chats,
researches, plans your week from your tasks and calendar, coaches training
programs, teaches languages, and runs agents on a schedule - on a single box,
for a few people who trust it with their data.

**[What makes it different](#what-makes-it-different)** · **[Features](#features)** ·
**[Quick start](#quick-start)** · **[Documentation](docs/README.md)**

<p align="center">
  <img src="web/tests/visual/chat.visual.ts-snapshots/conversation-with-messages-chromium-darwin.png" alt="Desktop chat interface" width="840">
  <br><em>Streaming chat with live syntax highlighting and an expandable trace of the model's thinking and tool calls</em>
</p>

<p align="center"><sub>Every screenshot here is a visual-regression baseline from the test suite, so none of them can drift from the real UI.</sub></p>

## What makes it different

- **It shows its evidence.** After a web-backed answer, a second model checks
  each specific claim against the pages the turn actually read: supported
  claims carry their source, and unsourced or contradicted ones are marked
  in the text, with a one-tap "look it up".
- **Agents act only within limits you set.** Destructive tool calls by
  scheduled agents wait for your approval, enforced in code rather than asked
  for in a prompt. Each agent gets an explicit tool allowlist and a daily budget.
- **Its memory is yours to read.** Everything it remembers about you is on one
  page, with where it learned it; delete anything, or protect it from cleanup.
- **It doesn't lose your work.** Replies survive dropped connections and
  resume where they left off, unsent messages survive reloads, and every
  device stays in sync.
- **Built to be relied on daily.** Every project rule is enforced by a test,
  not just a review, and about 7,900 backend, frontend, E2E and visual tests
  run on every change.

## Features

**Chat and research**
- Two Gemini models per conversation: **Gemini 3.8 Flash** ("Fast", the default) and **Gemini 3.1 Pro** ("Advanced")
- Streaming with a live thinking trace; stop, regenerate, continue, edit and resend; **steer a reply while it is still being written**
- **Deep research**: for questions that need several options compared, it offers a plan you can edit; parallel sub-agents research it and a Pro model writes a report whose claims are checked against the pages behind them
- **Current facts**: looks things up before answering when the question is about now, with quota-aware web search across several providers and a free fallback
- **Inline artifacts**: answers can be small working pages (a recipe with a checklist, a tracker, a chart, a game) rendered safely under the reply
- Files and images in (photos, PDFs, video, text), images out (generate or edit), sandboxed Python for analysis and charts, and a headless browser for pages that need one
- Recall of your past conversations ("what did we decide about X?") and non-destructive compaction for very long chats

<p align="center">
  <img src="web/tests/visual/deep-research.visual.ts-snapshots/deep-research-offer-chromium-darwin.png" alt="Deep research offer" width="560">
  <br><em>A deep research plan to adjust before it runs, with its time and cost</em>
</p>

**Your day**
- **Planner**: Todoist tasks and Google Calendar events in one schedule, with weather, analyzed proactively
- **Training coach** per program, with Garmin Connect health data and Rouvy workouts
- **Language tutor** per language, with inline quizzes graded by the model
- **Places and routes** near you, with your location shared per message when you opt in

**Agents**
- Cron-scheduled agents with their own conversations, a Command Center for runs and approvals, agent-to-agent triggers, and push or WhatsApp notifications

<p align="center">
  <img src="web/tests/visual/agents.visual.ts-snapshots/command-center-with-approvals-chromium-darwin.png" alt="Agent command center with pending approvals" width="620">
  <br><em>Destructive actions wait for approval, showing the exact tool and arguments</em>
</p>

**Everyday comfort**
- An installable PWA, built for iOS with the keyboard and safe areas handled properly, plus touch gestures, an offline shell, and push notifications
- Full-text search, pinning, archive, and a 14-day trash; light and dark themes; voice input
- Anonymous mode per conversation (no memory, recall or integrations); per-conversation and monthly cost tracking, with a spend warning

<p align="center">
  <img src="web/tests/visual/planner.visual.ts-snapshots/dashboard-full-chromium-darwin.png" alt="Planner dashboard" width="560">
  &nbsp;
  <img src="web/tests/visual/mobile.visual.ts-snapshots/mobile-conversation-chromium-darwin.png" alt="Mobile layout" width="220">
  <br><em>The planner, and the app on a phone</em>
</p>

**Security**
- Google Sign In with an email allowlist, per-user and per-IP rate limits, and integration tokens encrypted at rest
- Web and browser output is fenced as data, never instructions; fetched URLs are checked against private networks, including after DNS resolution

The full list, with how each piece works, is in **[docs/features](docs/README.md#features-features)**.

## Who it is for

A household or a small team that wants one assistant with real integrations
and is happy to run it: one Linux box, one SQLite database, Google Gemini.
It is not a hosted multi-tenant service, and it does not switch between LLM
providers.

## Quick start

You need Python 3.14+ ([uv](https://docs.astral.sh/uv/) recommended), Node.js 24+,
Git LFS (for the test screenshots), and a
[Gemini API key](https://aistudio.google.com/apikey).

```bash
git clone https://github.com/jbrunclik/moneypenny.git
cd moneypenny
make setup                 # virtualenv + Python and Node dependencies
cp .env.example .env       # then set GEMINI_API_KEY
make dev                   # Flask + Vite with hot reload: http://localhost:5173
```

Local development needs only `GEMINI_API_KEY` (it runs without sign-in).
[`.env.example`](.env.example) lists every setting with a comment; every
integration is optional and stays hidden until it is configured.

## Going further

| | |
|---|---|
| Integrations and production sign-in | [docs/setup.md](docs/setup.md) |
| Running it in production (systemd, updates, backups, nginx) | [docs/deployment.md](docs/deployment.md) |
| How it works: agents, streaming, memory, sync | [docs/README.md](docs/README.md) |
| Tests, the E2E mock server, visual baselines | [docs/testing.md](docs/testing.md) |
| Contributing: conventions and the rules the tests enforce | [docs/conventions.md](docs/conventions.md) |

`make` on its own lists every command.

**Stack:** Python 3.14, Flask (APIFlask), LangGraph, SQLite (WAL, FTS5,
yoyo migrations) · TypeScript (strict), Vite, Zustand, no UI framework ·
pytest, Vitest, Playwright · frontend API types generated from the backend's
OpenAPI spec.

## License

MIT
