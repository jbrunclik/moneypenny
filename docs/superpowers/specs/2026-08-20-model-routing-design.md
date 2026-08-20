# Model Routing / Tiering — Design Spec (Aug 2026)

Route everyday turns to a cheaper model tier without degrading quality,
gated by the eval harness. Follow-up to the Aug 2026 agent-improvements
round; replaces the TODO "Model routing / tiering by turn difficulty" entry.

## Sizing (prod data, last 60 days)

| Bucket | Turns | Share | Cost | Note |
|---|---|---|---|---|
| 0 tool rounds | 3,707 | 60% | $156 (33%) | avg 33.5k in (18.6k cached) / 2.0k out |
| 1–2 tool rounds | 1,494 | 24% | $133 (28%) | |
| 3+ tool rounds | 998 | 16% | $188 (39%) | |
| total | 6,199 | | $476 | |

## Tier table (official pricing, ai.google.dev, Aug 2026)

| Model | Input /M | Output /M | Cached /M | Notes |
|---|---|---|---|---|
| gemini-3.7-flash (current default) | $0.75 → **$1.50 on 2027-01-01** | $3.75 → **$7.50** | $0.075 → $0.15 | function calling, caching, thinking |
| **gemini-3.5-flash-lite (new lite tier)** | $0.30 | $2.50 | $0.03 | function calling, thinking; **verify explicit context-caching support at impl** |
| gemini-3.1-pro-preview ("Advanced") | unchanged | unchanged | unchanged | never routed |

A routed average no-tool turn costs ~$0.010 on Lite vs ~$0.020 on Flash today
(≈50% off), and ~$0.010 vs ~$0.040 after the January price change (≈75% off).
Projected total savings: **~15% now, ~25–30% from 2027** if Lite also handles
simple tool turns (design D2 below). No 3.7-generation Lite exists; the lite
tier trails one generation behind.

## Design

### Shape: deterministic heuristic router + sticky escalation (no classifier)

The planning classifier was removed for adding a Flash call + 1.6–2.4s latency
per turn for a 1.9% fire rate — a routing classifier would repeat that
mistake. Route with zero-cost heuristics instead, and rely on **escalation**
to catch misroutes.

Route a turn to Lite only when ALL hold:
- routing enabled (`MODEL_ROUTING_ENABLED`) and the conversation's chosen
  model is the default Flash tier ("Fast"); explicit "Advanced" (Pro) is
  never routed
- not a program/planner/agent conversation (`is_sports`/`is_language`/
  `is_planning`/`is_autonomous` all false) — their system prompts assume the
  stronger model
- no file attachments on the current message and none in the last N history
  messages (Lite multimodal quality unverified)
- `force_tools` not set
- the conversation is not in an escalated cooldown (below)

Otherwise: Flash, as today.

### Tools on Lite (D2): bind the full toolset

Lite officially supports function calling; the eval harness is the gate (see
below). Simple tool turns (weather, one search, memory writes — the 24%
"1–2 rounds" bucket) then also run at Lite rates, which is where the second
half of the savings lives. The alternative (Lite without tools) contradicts
the "ALWAYS use web tools for current facts" prompt and would produce stale
answers — rejected.

### Sticky escalation (misroute recovery)

After a Lite turn, escalate the CONVERSATION to Flash for
`MODEL_ROUTING_ESCALATION_TURNS` (default 5) turns when any of:
- the turn hit the tool-retry give-up path (`check_tool_results` exhausted)
- the turn hit the round cap (`tool_rounds >= AGENT_MAX_TOOL_ROUNDS`)
- the turn produced an empty/whitespace response

Store the escalation marker in `kv_store` (namespace `routing`, key =
conversation_id, value = remaining turns) — NOT module state (4 gunicorn
workers). Decrement per Flash turn; expire naturally.

Explicit user override always wins: switching the conversation to "Advanced"
disables routing for it entirely.

### Cache interplay

- **Explicit context cache**: keyed per (profile, model) — Lite adds one
  cache entry per profile (standard/anonymous only; programs aren't routed).
  Cache storage cost is negligible (existing docs note). If Lite turns out
  not to support explicit caching, fall back to uncached Lite: at Lite rates
  an uncached system prompt still beats a cached Flash one for r0 turns —
  compute both at impl time and pick.
- **Implicit prefix caching**: per-model, so a conversation alternating
  models re-warms per side. Mitigation is stickiness: route by CONVERSATION
  state, not per-message randomness — the heuristics are stable within a
  conversation, so switches happen at escalation boundaries, not every turn.
- `_usage_tokens` / cost rows already record per-message `model` — but see
  Accounting below for the one required change.

### Accounting (required pre-work)

`calculate_and_save_message_cost` prices the turn with the CONVERSATION's
model today. With routing, the executed model can differ per turn — the
routed model must be threaded from `ChatAgent` into the cost call and stored
in `message_costs.model`. (Column exists; only the value source changes.
This also fixes the latent inaccuracy where a conversation switched between
Fast/Advanced mid-history prices old rows correctly but only by luck.)

### Config

```python
MODEL_ROUTING_ENABLED: bool = env("MODEL_ROUTING_ENABLED", "false")  # off by default
MODEL_ROUTING_LITE_MODEL: str = env("MODEL_ROUTING_LITE_MODEL") or "gemini-3.5-flash-lite"
MODEL_ROUTING_ESCALATION_TURNS: int = env("MODEL_ROUTING_ESCALATION_TURNS", "5")
MODEL_ROUTING_MAX_HISTORY_FILES: int = env("MODEL_ROUTING_MAX_HISTORY_FILES", "6")  # lookback window
```

`MODEL_PRICING` gains the Lite entry. `MODELS` (user-facing picker) does NOT
gain Lite — routing is invisible; the picker keeps Fast/Advanced semantics
("Fast" = auto Flash/Lite when routing is on).

### Telemetry

- Log per turn: `model_routed` {chosen, reason} (grep-able, mirrors the old
  `planning_classifier` telemetry pattern).
- `scripts/analyze_costs.py` already groups by model — before/after blended
  cost per message is measurable with zero new code.
- Frontend: no change (the cost popup reads stored rows).

## Suitability check (Aug 20, 2026) — PRELIMINARY PASS

The eval suite was first extended from 8 synthetic cases to 30 cases grounded
in real usage analysis (94% Czech traffic; terse/elliptical/typo-heavy query
styles; clusters: household advice, Czech copywriting, trips, purchases,
current events, health/longevity, sports-program coaching incl. kv_store
persistence, ZWO generation, multi-turn follow-ups). Then both tiers ran the
full suite:

- **Flash: 27/30** (standing targets: ghost-writing emits variant menus,
  teen-register too clinical, longevity answer lacks evidence nuance)
- **Lite: 26/30** — the SAME cases fail (model-family behavior, not tier);
  longevity actually scored higher on Lite; the 4th miss is the known
  research round-variance case. All Czech-quality and tool-calling cases
  (kv_store persistence, memory writes, code exec, web+cite) pass on Lite.

Quality verdict: no per-case regression vs Flash → design D2 (full toolset on
Lite) stands. Known eval gap: Garmin-dependent flows ("mrkni na data") can't
run in the harness (no Garmin token for the eval user).

## Latency verdict (Aug 20, 2026) — FAIL, routing PARKED

Requirement (explicit): the agent must get FASTER with a less complex model,
not slower. Timed head-to-head (8 representative cases × 2 passes each,
agent-turn wall clock): Flash mean ~10.8 s vs Lite mean ~13.1 s (~20–30%
slower), with a worse tail (18–25 s outliers; one 32 s with thinking_level
"low", which did not help — the gap looks like serving-tier latency variance,
not reasoning overhead).

**Decision: do NOT implement routing now.** Cheaper-but-slower fails the
requirement. Revisit when a lite tier of the current generation ships
(3.7-flash-lite or successor) — re-run this suite's quality gate plus the
timed comparison; both must pass. The eval suite, timing capture, and this
spec make that re-check a one-command exercise.

## Quality gate (before any prod enablement)

1. Run the full eval suite with `DEFAULT_MODEL=gemini-3.5-flash-lite`:
   `DEFAULT_MODEL=gemini-3.5-flash-lite make eval` — require 8/8, three runs
   (tool-calling correctness on Lite is the make-or-break; the suite covers
   web+cite, research, memory writes, code exec, Czech fluency).
2. Add two Lite-sensitive cases first: a multi-turn-context answer and a
   nuance-sensitive Czech reply (Lite's likely weak spots).
3. If Lite fails tool cases: fall back to design D1' (route to Lite only
   when heuristics predict no tools AND bind tools anyway, accept the rare
   misroute cost) — decide on eval evidence, not vibes.

## Rollout

1. Land code with `MODEL_ROUTING_ENABLED=false` (no behavior change).
2. Local: enable, live-test a dozen turns incl. Czech, memory, weather.
3. Prod: enable; watch `model_routed` logs + `analyze_costs.py` deltas and
   family feedback for a week.
4. Success = blended cost/message down ≥15% with no eval regression and no
   family complaints; otherwise flip the flag off (single env var).

## Non-goals

- Routing Pro ("Advanced") turns — user intent is explicit there.
- An LLM routing classifier (latency + cost per turn; the removed planning
  classifier is the cautionary tale).
- Auto-upgrading the lite tier across generations (pin the model id; revisit
  when a 3.7-lite ships).
- Per-user rollout flags (global env flag is enough at 4 users).

## Impl sketch (for the future plan)

1. `src/agent/routing.py`: `resolve_model(conversation, message, history) ->
   (model_name, reason)` + escalation read/write via kv_store. Pure logic,
   unit-testable.
2. Chat routes call it where `conv.model` is read today (batch + streaming
   paths); pass the resolved model into `ChatAgent` and into cost accounting.
3. Escalation markers written in the same place `check_tool_results`
   outcomes/usage land server-side (chat_save / routes layer, post-turn).
4. Config + pricing entries; telemetry log line; eval gate run; docs.
